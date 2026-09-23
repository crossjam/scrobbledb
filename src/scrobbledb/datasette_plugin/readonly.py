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

#: The pragmas a served connection may run, each mapped to whether SQLite may
#: be handed an argument alongside it. Everything else is refused, which is the
#: point -- an allowlist is the only form that answers "read-only cannot be
#: switched off", because a denylist silently permits whatever pragma it has
#: not heard of yet.
#:
#: The name alone is not enough, because `arg2` carries two different things.
#: SQLite reports `PRAGMA journal_mode=WAL` and `PRAGMA table_xinfo(artists)`
#: identically -- `SQLITE_PRAGMA`, the pragma in `arg1`, the assigned value or
#: the call argument equally in `arg2` -- so "refuse any pragma carrying an
#: argument" reads plausibly and takes Datasette's schema introspection down
#: with it. Deciding per name *and* per argument is what separates them.
#: (A schema qualifier is not an argument: `PRAGMA main.schema_version` puts
#: `main` in `arg3` and leaves `arg2` empty.)
#:
#: `True` is therefore reserved for two kinds of entry, and adding a third is
#: how a write gets in:
#:
#: - introspection over a named object -- `table_info`, `index_list` and the
#:   rest -- which have no assignment form at all;
#: - `cache_size` and `recursive_triggers`, which *are* set but cannot touch
#:   the file. `cache_size` allocates memory, and Datasette issues it on every
#:   connection. `recursive_triggers` governs whether a trigger may fire
#:   another trigger, and no trigger can run when every statement that would
#:   fire one is denied; `sqlite_utils.Database(conn)` sets it in its
#:   constructor, and Datasette builds one of those around the served
#:   connection to resolve foreign-key label columns.
#:
#: Everything else is `False` and readable only in its bare form.
#: `schema_version` is the entry that makes the distinction load-bearing rather
#: than tidy: Datasette reads it on every request to detect schema changes, but
#: `PRAGMA schema_version = N` rewrites the database header -- verified, on a
#: writable connection carrying this authorizer and nothing else, by comparing
#: the file's bytes. `page_size` is the same shape, and `max_page_count` is
#: absent for it (Datasette allows that one, but only through the
#: `pragma_*()` table-valued form, which has no assignment syntax to abuse).
#:
#: The rest of the list is Datasette's own `utils.allowed_pragmas` plus
#: `compile_options`, which Datasette executes in statement form, and
#: `data_version`, which FTS5 reads internally on every `MATCH` -- omitting it
#: turns every search into an "authorization denied" rather than a result set.
ALLOWED_PRAGMAS = {
    "cache_size": True,
    "compile_options": False,
    "data_version": False,
    "database_list": False,
    "foreign_key_list": True,
    "function_list": False,
    "index_info": True,
    "index_list": True,
    "index_xinfo": True,
    "page_count": False,
    "page_size": False,
    "recursive_triggers": True,
    "schema_version": False,
    "table_info": True,
    "table_list": True,
    "table_xinfo": True,
}

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
        argument_allowed = ALLOWED_PRAGMAS.get((arg1 or "").lower())
        if argument_allowed is None:
            return sqlite3.SQLITE_DENY
        if arg2 is not None and not argument_allowed:
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
