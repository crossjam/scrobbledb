"""
The analytics indexes: the secondary indexes scrobbledb's rollups need.

A scrobbledb database carries no non-PK indexes by default. These three cover
the foreign-key columns that join plays to tracks to albums to artists, so a
query that starts from the parent side -- the plays of a track, the tracks of an
album -- can look rows up instead of scanning. A full-history rollup reads every
play whatever indexes exist: measured against a 56k-play database, top artists
and the monthly rollup take the same time with or without them, while top tracks,
which looks plays up by track, gets faster. There is deliberately no index on
the month of a play: the rollup groups by `%Y` and
`%m` separately, so an expression on `%Y-%m` is never used, and regrouping to
match it was measured to save nothing (design D10).

They are created only on request, by `scrobbledb index --analytics`, and never
as a side effect of anything else -- `serve` in particular detects their absence
and says so, because its read-only guarantee is worth more than a faster first
query.

This module holds the one definition both sides read: the command that creates
the indexes and the server that checks for them.
"""

import sqlite3
from typing import NamedTuple

#: Index name -> the `(table, column)` it exists to serve.
INDEX_TARGETS = {
    "idx_plays_track_id": ("plays", "track_id"),
    "idx_tracks_album_id": ("tracks", "album_id"),
    "idx_albums_artist_id": ("albums", "artist_id"),
}

#: Index name -> the statement that creates it. Every statement is
#: `IF NOT EXISTS`, so creation is idempotent by construction.
ANALYTICS_INDEXES = {
    name: f"CREATE INDEX IF NOT EXISTS {name} ON {table}({column})"
    for name, (table, column) in INDEX_TARGETS.items()
}

#: The tables a scrobbledb database has. All four have to exist before any
#: index can be created, and a database lacking them has nothing to index yet.
SCROBBLE_TABLES = ("artists", "albums", "tracks", "plays")

#: The columns the indexes above sit on, per table. Table names alone do not
#: make a scrobbledb database -- four tables with the right names and the wrong
#: columns would pass a names-only check and then fail with "no such column"
#: part way through creation. This mirrors the schema check the Datasette
#: plugin makes, trimmed to what indexing needs, rather than importing it: that
#: package needs the optional `serve` extra and this command must not.
REQUIRED_COLUMNS = {
    "plays": frozenset({"track_id"}),
    "tracks": frozenset({"album_id"}),
    "albums": frozenset({"artist_id"}),
}


class IndexingResult(NamedTuple):
    """What `create_analytics_indexes` did, name by name."""

    #: Indexes this call created.
    created: list[str]
    #: Indexes whose purpose was already served, under this name or another.
    existing: list[str]
    #: Indexes this call could not create because the name is taken by an index
    #: on something else.
    conflicts: list[str]


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _indexed_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """
    The columns that lead a usable index on `table`, lower-cased.

    A column counts when an index starts with it, whatever the index is called
    and whatever follows it: a lookup on that column can use the index either
    way. Three kinds do not count. Partial indexes cover only some of the rows.
    Expression indexes lead with an expression, not a column. And an index whose
    leading term is not compared as BINARY cannot serve a join or lookup on the
    column, which is: scrobbledb never declares a collation, and SQLite will not
    use a NOCASE index for a binary comparison (it scans instead).
    """
    leading = set()
    for _seq, name, _unique, _origin, partial in conn.execute(
        f"PRAGMA index_list({_quote(table)})"
    ).fetchall():
        if partial:
            continue
        first = conn.execute(f"PRAGMA index_xinfo({_quote(name)})").fetchone()
        # (seqno, cid, name, desc, collation, key); the first row is the lead term.
        if first and first[2] and (first[4] or "").upper() == "BINARY":
            leading.add(first[2].lower())
    return leading


def missing_analytics_indexes(conn: sqlite3.Connection) -> list[str]:
    """
    The analytics indexes whose purpose `conn`'s database does not yet serve.

    Decided by what each index covers, not by what it is called: an index of
    that name on some other column leaves the column unindexed, and an
    equivalent index under another name leaves nothing to create.
    """
    return [
        name
        for name, (table, column) in INDEX_TARGETS.items()
        if column.lower() not in _indexed_columns(conn, table)
    ]


def unindexable_reasons(conn: sqlite3.Connection) -> list[str]:
    """
    Why `conn`'s database has nothing to index yet; empty when it can be indexed.

    Missing tables, and tables present without the columns the indexes need.
    """
    present = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    reasons: list[str] = [f"no {t} table" for t in SCROBBLE_TABLES if t not in present]
    for table, columns in REQUIRED_COLUMNS.items():
        if table not in present:
            continue
        have = {
            row[1].lower()
            for row in conn.execute(f"PRAGMA table_info({_quote(table)})")
        }
        for column in sorted(columns - have):
            reasons.append(f"{table} has no {column} column")
    return reasons


def create_analytics_indexes(conn: sqlite3.Connection) -> IndexingResult:
    """
    Create whichever analytics indexes the database does not already serve.

    Only indexes are written -- no row is touched -- and an index that is
    already there is left alone, so a second call creates nothing. If a needed
    index's name is already taken by an index on something else it is reported
    as a conflict rather than silently skipped, since creating it under that
    name is exactly what `IF NOT EXISTS` would pretend had worked.
    """
    missing = missing_analytics_indexes(conn)
    # SQLite compares identifiers without regard to case, so IDX_PLAYS_TRACK_ID
    # on another column takes the name just as idx_plays_track_id would.
    taken = {
        row[0].lower()
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    created, conflicts = [], []
    for name in missing:
        if name.lower() in taken:
            conflicts.append(name)
        else:
            conn.execute(ANALYTICS_INDEXES[name])
            created.append(name)
    conn.commit()
    existing = [name for name in INDEX_TARGETS if name not in missing]
    return IndexingResult(created, existing, conflicts)
