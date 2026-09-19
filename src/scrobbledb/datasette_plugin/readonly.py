"""
Read-only enforcement for every served connection (design D7).

Three layers, none of them a restatement of the others:

1. **Open mode.** The database is registered with an explicit `mode="ro"`,
   which takes final precedence in `Database.connect()` over both the
   mutable/immutable branch and the `write=True` branch that otherwise clears
   the URI query string entirely.
2. **`PRAGMA query_only=ON`**, issued on every connection. It stops temp-object
   creation that `mode=ro` allows, but it is resettable via
   `PRAGMA query_only=OFF`, so it cannot be the last word.
3. **A `sqlite3` authorizer**, which is the only durable layer: `ATTACH`,
   `DETACH` and `REINDEX` are reachable without it, and it is what survives an
   attempt to switch layer 2 off.

The authorizer denies a named set of actions and allows everything else.
A default-deny policy is not usable here: `SQLITE_READ`, `SQLITE_SELECT` and
`SQLITE_FUNCTION` fire constantly on ordinary queries, and the custom SQL
functions of `functions.py` arrive through `SQLITE_FUNCTION` too.
"""

import sqlite3
from typing import Optional

#: Authorizer actions that are refused outright, by name so a test can be
#: table-driven over exactly this set rather than a hand-written copy of it.
#:
#: The `_TEMP_` and `_VTABLE` variants are present deliberately. Temp objects
#: are the case `query_only` covers during normal operation, which is precisely
#: why the authorizer must cover them too -- `query_only` is resettable, and a
#: guarantee that depends on a layer above it is not a guarantee.
#:
#: `SQLITE_ATTACH` also carries `VACUUM INTO`: measured, the first action SQLite
#: reports for `VACUUM INTO '<path>'` is `SQLITE_ATTACH` naming the output file,
#: so denying it stops a statement that would otherwise produce a file on disk
#: without writing a single row to this database.
DENIED_ACTIONS = {
    name: getattr(sqlite3, name)
    for name in (
        "SQLITE_INSERT",
        "SQLITE_UPDATE",
        "SQLITE_DELETE",
        "SQLITE_ALTER_TABLE",
        "SQLITE_CREATE_INDEX",
        "SQLITE_CREATE_TABLE",
        "SQLITE_CREATE_TEMP_INDEX",
        "SQLITE_CREATE_TEMP_TABLE",
        "SQLITE_CREATE_TEMP_TRIGGER",
        "SQLITE_CREATE_TEMP_VIEW",
        "SQLITE_CREATE_TRIGGER",
        "SQLITE_CREATE_VIEW",
        "SQLITE_CREATE_VTABLE",
        "SQLITE_DROP_INDEX",
        "SQLITE_DROP_TABLE",
        "SQLITE_DROP_TEMP_INDEX",
        "SQLITE_DROP_TEMP_TABLE",
        "SQLITE_DROP_TEMP_TRIGGER",
        "SQLITE_DROP_TEMP_VIEW",
        "SQLITE_DROP_TRIGGER",
        "SQLITE_DROP_VIEW",
        "SQLITE_DROP_VTABLE",
        "SQLITE_REINDEX",
        "SQLITE_ANALYZE",
        "SQLITE_ATTACH",
        "SQLITE_DETACH",
    )
}

#: The only pragmas a served connection may run: introspection, all of it
#: read-only. Everything else is refused, which is the point -- an allowlist is
#: the only form that answers "read-only cannot be switched off", because a
#: denylist silently permits whatever pragma it has not heard of yet.
#:
#: The authorizer cannot distinguish `PRAGMA journal_mode=WAL` from
#: `PRAGMA table_xinfo(artists)`: SQLite reports both as `SQLITE_PRAGMA` with
#: the pragma in `arg1` and the assigned value or the call argument, equally,
#: in `arg2`. So a rule of the form "refuse any pragma carrying a value" reads
#: plausibly and breaks Datasette's schema introspection outright. The name is
#: the only thing worth deciding on.
#:
#: This is Datasette's own `utils.allowed_pragmas` (which it enforces only over
#: the `pragma_*()` table-valued form, in a layer above the connection), minus
#: `max_page_count`, which is settable, plus `compile_options` and
#: `cache_size`, which Datasette itself executes in statement form, and
#: `data_version`, which FTS5 reads internally on every `MATCH` -- omitting it
#: turns every search into an "authorization denied" rather than a result set.
#:
#: `recursive_triggers` is the one entry here that is *set* rather than read:
#: `sqlite_utils.Database(conn)` turns it on in its constructor, and Datasette
#: builds one of those around the served connection to resolve foreign-key
#: label columns. It is safe to allow because it cannot make the connection
#: writable -- it governs whether a trigger may fire another trigger, and no
#: trigger can run at all when every statement that would fire one is denied.
ALLOWED_PRAGMAS = frozenset(
    {
        "cache_size",
        "compile_options",
        "data_version",
        "database_list",
        "foreign_key_list",
        "function_list",
        "index_info",
        "index_list",
        "index_xinfo",
        "page_count",
        "page_size",
        "recursive_triggers",
        "schema_version",
        "table_info",
        "table_list",
        "table_xinfo",
    }
)

#: The function whose denial is the whole point of the `SQLITE_FUNCTION` case.
#: Python refuses extension loading by default, but that default is a
#: connection flag Datasette itself flips when `--load-extension` is used, so
#: the authorizer has to deny it on its own terms.
_EXTENSION_LOADER = "load_extension"


def authorize(action, arg1, arg2, db_name, trigger_or_view):
    """
    `sqlite3` authorizer callback: `SQLITE_DENY` for writes, `SQLITE_OK` else.

    `SQLITE_DENY` rather than `SQLITE_IGNORE`: ignoring turns a denied action
    into a silent no-op, and a client that asked to write should be told it was
    refused rather than left to believe it succeeded.
    """
    if action in DENIED_ACTIONS.values():
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA:
        if (arg1 or "").lower() not in ALLOWED_PRAGMAS:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() == _EXTENSION_LOADER:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def apply_read_only(conn) -> None:
    """
    Put layers 2 and 3 on one connection.

    Order is load-bearing: `query_only` is not in `ALLOWED_PRAGMAS` -- turning
    it off is exactly what the authorizer exists to refuse -- so turning it on
    has to happen before the authorizer is installed.
    """
    conn.execute("PRAGMA query_only=ON")
    conn.set_authorizer(authorize)


def add_read_only_database(ds, path, name: Optional[str] = None):
    """
    Register `path` with `ds` as a read-only but *mutable* database.

    `mode="ro"` states the read-only property rather than inheriting it from
    Datasette's default, and takes precedence over the `write=True` branch of
    `Database.connect()`, so `execute_write()` gets a read-only handle instead
    of a read-write one.

    `is_mutable` stays true on purpose. It is not a claim that the server may
    write -- `mode=ro` settles that -- but a statement that the *file* may
    change underneath us. Running `scrobbledb ingest` in another terminal
    during a serve session is ordinary usage here, and that is exactly the
    promise `immutables=[path]` makes and would break (design D7).
    """
    from datasette.database import Database

    db = Database(ds, path=str(path), is_mutable=True, mode="ro")
    return ds.add_database(db, name=name)
