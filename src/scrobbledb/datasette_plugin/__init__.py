"""
The first-party Datasette plugin shipped with scrobbledb.

Registered programmatically from `scrobbledb serve` via `datasette.plugins.pm`
rather than through a `datasette.plugins` entry point, so it never loads into
unrelated Datasette processes that happen to share the environment (design D3).

Pluggy discovers hookimpls as attributes of the registered module, so every
hook the plugin implements has to be named here -- it lives in a submodule for
readability, but only what this module re-exports is actually wired up.

`prepare_connection` is the exception: it is *defined* here rather than
re-exported, because two submodules have something to put on every connection
and pluggy accepts only one implementation per module per hook.
"""

from datasette import hookimpl

from scrobbledb.datasette_plugin.functions import register_sql_functions
from scrobbledb.datasette_plugin.queries import startup
from scrobbledb.datasette_plugin.readonly import (
    add_read_only_database,
    apply_read_only,
)


@hookimpl
def prepare_connection(conn):
    """
    Everything a served connection needs, in the one order that works.

    The SQL functions are registered first: `apply_read_only` installs an
    authorizer, and while `create_function` itself never consults one, keeping
    the write-side setup last means nothing added later can be refused by a
    policy this plugin installed on itself.
    """
    register_sql_functions(conn)
    apply_read_only(conn)


__all__ = [
    "add_read_only_database",
    "apply_read_only",
    "prepare_connection",
    "register_sql_functions",
    "startup",
]
