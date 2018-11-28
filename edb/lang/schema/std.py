#
# This source file is part of the EdgeDB open source project.
#
# Copyright 2016-present MagicStack Inc. and the EdgeDB authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import hashlib
import os
import pathlib
import pickle
import tempfile
import typing

from edb import lib as stdlib
from edb.lang import edgeql
from edb.lang import schema
from edb.lang.edgeql import ast as qlast
from edb.lang.edgeql import compiler as qlcompiler

from . import ddl as s_ddl
from . import error as s_err
from . import schema as s_schema


SCHEMA_ROOT = pathlib.Path(schema.__path__[0])
LIB_ROOT = pathlib.Path(stdlib.__path__[0])
QL_COMPILER_ROOT = pathlib.Path(qlcompiler.__path__[0])

STD_LIB = ['std', 'schema']
STD_MODULES = {'std', 'schema', 'stdattrs', 'stdgraphql'}
CACHED_SCHEMA = LIB_ROOT / '.schema.pickle'


def std_module_to_ddl(
        schema: s_schema.Schema,
        modname: str) -> typing.List[qlast.DDL]:

    module_eql = ''

    module_path = LIB_ROOT / modname
    module_files = []

    if module_path.is_dir():
        for entry in module_path.iterdir():
            if entry.is_file() and entry.suffix == '.eql':
                module_files.append(entry)
    else:
        module_path = module_path.with_suffix('.eql')
        if not module_path.exists():
            raise s_err.SchemaError(f'std module not found: {modname}')
        module_files.append(module_path)

    module_files.sort(key=lambda p: p.name)

    for module_file in module_files:
        with open(module_file) as f:
            module_eql += '\n' + f.read()

    return edgeql.parse_block(module_eql)


def load_std_module(
        schema: s_schema.Schema, modname: str) -> s_schema.Schema:

    modaliases = {}
    if modname == 'std':
        modaliases[None] = 'std'

    for statement in std_module_to_ddl(schema, modname):
        cmd = s_ddl.delta_from_ddl(
            statement, schema=schema, modaliases=modaliases, stdmode=True)
        schema, _ = cmd.apply(schema)

    return schema


def load_std_schema() -> s_schema.Schema:
    std_dirs_hash = hash_std_dirs()
    if CACHED_SCHEMA.exists():
        with open(CACHED_SCHEMA, 'rb') as f:
            src_hash = f.read(16)
            if src_hash == std_dirs_hash:
                schema = pickle.loads(f.read())
                return schema

    schema = s_schema.Schema()
    for modname in STD_LIB:
        schema = load_std_module(schema, modname)

    pickled_schema = pickle.dumps(schema)
    try:
        with tempfile.NamedTemporaryFile(
                mode='wb', dir=CACHED_SCHEMA.parent, delete=False) as f:
            f.write(std_dirs_hash)
            f.write(pickled_schema)
    except Exception:
        try:
            os.unlink(f.name)
        except OSError:
            pass
        finally:
            raise
    else:
        os.rename(f.name, CACHED_SCHEMA)

    return schema


def load_graphql_schema(
        schema: typing.Optional[s_schema.Schema]=None) -> s_schema.Schema:
    if schema is None:
        schema = s_schema.Schema()

    return load_std_module(schema, 'stdgraphql')


def hash_std_dirs():
    return _hash_dirs(
        (SCHEMA_ROOT, '.py'),
        (QL_COMPILER_ROOT, '.py'),
        (LIB_ROOT, '.eql'),
    )


def _hash_dirs(*dirs: typing.Tuple[str, str]) -> bytes:
    def hash_dir(dirname, ext, paths):
        with os.scandir(dirname) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith(ext):
                    paths.append(entry.path)
                elif entry.is_dir():
                    hash_dir(entry.path, ext, paths)

    paths = []
    for dirname, ext in dirs:
        hash_dir(dirname, ext, paths)

    h = hashlib.md5()
    for path in sorted(paths):
        with open(path, 'rb') as f:
            h.update(f.read())

    return h.digest()
