"""
The packaged metadata and config Datasette is constructed with (design D9).

Two files, because 1.0 loads two things from a config directory and reads
different keys from each. `metadata.yaml` carries what a reader sees --
descriptions of the tables and their columns. `datasette.yaml` carries what the
server does -- hidden tables, default sort, the SQL time limit.

The split is not cosmetic and not interchangeable. `Datasette.__init__` calls
`move_table_config(metadata, config)`, which relocates `hidden`, `sort`,
`sort_desc`, `size`, `sortable_columns`, `label_column`, `facets`, `fts_table`,
`fts_pk` and `searchmode` out of metadata for you -- so a single combined file
passed as `metadata=` happens to work today. It is a 0.x compatibility shim
inside an alpha and is not relied on here. The reverse direction has no shim at
all: a description passed through `config=` renders nothing, with no warning and
no error.

Both files name the database they configure, because Datasette keys both
structures by database name and a scrobbledb database is whatever the user
named their file. `$DATABASE` stands in for that name until load time.
"""

import importlib.resources
from typing import Any, Mapping

import yaml

#: The packaged file names, which are also the names Datasette itself would
#: look for in a `--config-dir`. Kept identical so the files can be read by
#: anyone who already knows Datasette's conventions.
METADATA_FILE = "metadata.yaml"
CONFIG_FILE = "datasette.yaml"

#: The stand-in for the served database's name inside both packaged files.
#: A literal, not a format specifier: the files are full of prose containing
#: braces and percent signs, and neither `str.format` nor `%` can be let near
#: them.
DATABASE_PLACEHOLDER = "$DATABASE"


def _load(filename: str) -> dict[str, Any]:
    """Parse one packaged YAML file out of this package."""
    source = importlib.resources.files("scrobbledb.datasette_plugin").joinpath(
        filename
    )
    return yaml.safe_load(source.read_text(encoding="utf-8")) or {}


def _rename_database(document: Mapping[str, Any], database_name: str) -> dict:
    """
    Return `document` with its placeholder database key renamed.

    Only the one key is rewritten, rather than a substitution over the file's
    text: the descriptions are prose, and prose is entitled to contain a dollar
    sign without becoming configuration.
    """
    result = dict(document)
    databases = result.get("databases")
    if not databases or DATABASE_PLACEHOLDER not in databases:
        return result
    renamed = dict(databases)
    renamed[database_name] = renamed.pop(DATABASE_PLACEHOLDER)
    result["databases"] = renamed
    return result


def load_metadata(database_name: str) -> dict[str, Any]:
    """Descriptions for `database_name`, for `Datasette(metadata=...)`."""
    return _rename_database(_load(METADATA_FILE), database_name)


def load_config(database_name: str) -> dict[str, Any]:
    """Server behaviour for `database_name`, for `Datasette(config=...)`."""
    return _rename_database(_load(CONFIG_FILE), database_name)
