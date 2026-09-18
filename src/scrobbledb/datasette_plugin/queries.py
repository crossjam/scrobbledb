"""
The stored-query catalog: scrobbledb's analytics as named, linkable URLs.

Every entry is one shared builder from `domain_queries` plus the human-facing
text that makes it discoverable on the database index page. The SQL is never
written here -- a second SQL catalog is exactly what design D4 rejected -- so
an entry is a *data* addition: a `QueryEntry(...)` line in `CATALOG`.

Registration surface, confirmed against the installed Datasette 1.0a39
-----------------------------------------------------------------------

There is no `canned_queries` hook in 1.0a39. The 0.x hook is gone: the term is
now "stored queries", they live as rows in the internal database's `queries`
table, and a plugin contributes them by calling
`await datasette.add_query(database, name, sql, title=..., description=...)`.
Nothing in the installed package mentions "canned" at all, and pluggy rejects a
hookimpl whose name matches no hookspec, so defining one would be a startup
error rather than a no-op.

`stored_query_definitions()` therefore returns the classic canned-query dict
shape (`{name: {"sql", "title", "description"}}`), which is both what
`add_query` consumes and what a future re-introduction of a per-database hook
would want. Projecting it onto a running Datasette is the next commit.

Resolving `parse_when` once per statement (design D5)
-----------------------------------------------------

A builder's named form binds an already-converted UTC string and emits no
`parse_when` at all:

    WHERE (:since = '' OR plays.timestamp >= :since)

A stored query cannot do that. Its `:since` arrives from a URL or a form field
as human text -- `last march`, `30 days ago` -- so it has to pass through
`parse_when` before it is compared against a stored timestamp. The naive edit
is to wrap each comparison:

    WHERE (:since = '' OR plays.timestamp >= parse_when(:since))

which is wrong in a way that only shows up under load. `parse_when` is not
registered `deterministic=True` -- it reads the wall clock, and claiming
otherwise would be a false assertion to SQLite (see `functions.py`). So every
call site resolves independently, and its cache is keyed by a one-second
generation. `build_top_artists_sql` alone has *four* bound call sites, because
the period total is a scalar subquery carrying the same predicates as the outer
query. A statement that straddles a generation boundary can therefore compare
the ranked rows against one instant and the total against another, and the
result depends on scan order.

So the bound is resolved once, in SQL, in a materialized CTE, and every
comparison site reads that one value:

    WITH scrobbledb_bounds AS MATERIALIZED (
        SELECT parse_when(:since) AS since_utc
    )
    SELECT ... WHERE (:since = '' OR plays.timestamp >= (SELECT since_utc
                                                         FROM scrobbledb_bounds))

`resolve_time_bounds_once()` performs that rewrite on the builder's own output,
which is what keeps the SELECT body, joins, grouping and ordering written
exactly once, in `domain_queries`. It rewrites only the comparison operand; the
`:since = ''` guard keeps comparing the *raw* parameter, so "the user left it
blank" stays distinguishable from "the text did not parse" (both make
`parse_when` return NULL, but only the first should match everything). It
refuses to return SQL in which a bound reaches a comparison unparsed, so a
future builder that renders its bounds differently fails loudly here rather
than silently filtering on the literal text `last march`.
"""

import dataclasses
import re
import types
from typing import Any, Callable, Mapping

from scrobbledb import domain_queries

# Name of the CTE that holds one resolution of each time bound per statement.
BOUNDS_CTE = "scrobbledb_bounds"

# The SQL function the CTE resolves bounds with. It is registered by
# `functions.prepare_connection`, not by this module; the pairing is asserted in
# the tests rather than imported, so the catalog stays free of that dependency.
PARSE_WHEN = "parse_when"

# The optional time bounds every time-ranged builder renders, in the guarded
# named form of design D5.
BOUND_PARAMETERS = ("since", "until")

_NO_KWARGS: Mapping[str, Any] = types.MappingProxyType({})


def _guard_pattern(name: str) -> re.Pattern:
    """
    Match one rendered optional bound, e.g. ``(:since = '' OR t.ts >= :since)``.

    Written against `_time_bound_conditions`'s named form. The column and the
    operator are captured so the rewrite can put them back untouched; only the
    right-hand operand changes.
    """
    placeholder = re.escape(f":{name}")
    return re.compile(
        r"\("
        + placeholder
        + r" = '' OR (?P<column>[A-Za-z_][\w.]*) (?P<op><=|>=) "
        + placeholder
        + r"\)"
    )


def _unparsed_bound_pattern(name: str) -> re.Pattern:
    """Match a ``:since`` that is not the left side of its own empty guard."""
    return re.compile(re.escape(f":{name}") + r"\b(?! = '')")


_LEADING_WITH = re.compile(r"(?is)^\s*WITH\s+(RECURSIVE\s+)?")


def _prepend_cte(sql: str, cte: str) -> str:
    """
    Put `cte` first in the statement's WITH clause, creating one if needed.

    A builder with CTEs of its own -- the streaks query will have them -- keeps
    them, and ours going first means they may reference it.
    """
    match = _LEADING_WITH.match(sql)
    if match is None:
        return f"WITH {cte}\n{sql}"
    recursive = "RECURSIVE " if match.group(1) else ""
    return f"WITH {recursive}{cte},\n{sql[match.end() :]}"


def resolve_time_bounds_once(sql: str) -> str:
    """
    Rewrite a builder's optional bounds to resolve `parse_when` once per
    statement, in a materialized CTE. See the module docstring for why.

    SQL with no optional bounds is returned unchanged, so a query without a
    time range does not grow `:since`/`:until` form fields it ignores.

    Raises ValueError if a bound would still reach a comparison without going
    through `parse_when`.
    """
    resolved: list[str] = []
    for name in BOUND_PARAMETERS:

        def substitute(match: re.Match, name: str = name) -> str:
            return (
                f"(:{name} = '' OR {match['column']} {match['op']} "
                f"(SELECT {name}_utc FROM {BOUNDS_CTE}))"
            )

        sql, count = _guard_pattern(name).subn(substitute, sql)
        if count:
            resolved.append(name)

    if not resolved:
        return sql

    for name in BOUND_PARAMETERS:
        stray = _unparsed_bound_pattern(name).search(sql)
        if stray:
            raise ValueError(
                f"bound :{name} reaches SQL without parse_when() at offset "
                f"{stray.start()}; the builder's rendering of its optional "
                "bounds no longer matches what the catalog can rewrite"
            )

    selects = ", ".join(f"{PARSE_WHEN}(:{name}) AS {name}_utc" for name in resolved)
    return _prepend_cte(sql, f"{BOUNDS_CTE} AS MATERIALIZED (\n    SELECT {selects}\n)")


@dataclasses.dataclass(frozen=True)
class QueryEntry:
    """
    One stored query: a shared builder plus the text that describes it.

    `builder_kwargs` pins arguments that are SQL *text* rather than bound
    parameters -- a sort column, say -- since those cannot come from a URL.
    Everything else the builder binds stays a parameter of the stored query.
    """

    name: str
    title: str
    description: str
    builder: Callable[..., tuple[str, Any]]
    builder_kwargs: Mapping[str, Any] = _NO_KWARGS

    @property
    def sql(self) -> str:
        """The stored query's SQL: the builder's named form, bounds rewritten."""
        sql, _params = self.builder(
            form=domain_queries.SQL_FORM_NAMED, **self.builder_kwargs
        )
        return resolve_time_bounds_once(sql)


#: Every stored query scrobbledb serves, in the order they are registered.
#:
#: Adding one is a single data addition: a `QueryEntry` naming the builder.
#: The SQL, its parameters and its rewritten time bounds all follow from that.
#:
#: Pending (task 3.5/3.6, owned elsewhere): the daily rollup, the hour-of-day
#: and day-of-week distributions, consecutive-day streaks, per-artist discovery
#: dates, and the FTS search entry. Each becomes one more line here once its
#: builder lands in `domain_queries`.
#:
#: Deliberately absent: `build_artist_albums_sql` groups by `albums.id`, so it
#: does not satisfy the album-aggregate requirement (an alias group would be
#: several rows). The `album_list` entry's `artist`/`artist_id` filters cover
#: the same ground with the corrected grouping. The `*_lookup` builders are
#: LIMIT-2 ambiguity probes, not analytics, and the search builders re-rank in
#: Python, so neither belongs in a single-statement stored query.
CATALOG: tuple[QueryEntry, ...] = (
    QueryEntry(
        name="overview",
        title="Collection overview",
        description=(
            "Totals for the whole collection: plays, distinct artists, albums "
            "and tracks, and the timestamps of the first and last play."
        ),
        builder=domain_queries.build_overview_stats_sql,
    ),
    QueryEntry(
        name="plays_feed",
        title="Play feed",
        description=(
            "Most recent plays, denormalized: each row carries the timestamp "
            "alongside the track, album and artist names, so no joining is "
            "needed. Optional artist, album and track substring filters."
        ),
        builder=domain_queries.build_plays_with_filters_sql,
    ),
    QueryEntry(
        name="monthly_rollup",
        title="Plays by month",
        description=(
            "One row per calendar month with plays, carrying that month's play "
            "count and its distinct artist, album and track counts."
        ),
        builder=domain_queries.build_monthly_rollup_sql,
    ),
    QueryEntry(
        name="yearly_rollup",
        title="Plays by year",
        description=(
            "One row per calendar year with plays, carrying that year's play "
            "count and its distinct artist, album and track counts."
        ),
        builder=domain_queries.build_yearly_rollup_sql,
    ),
    QueryEntry(
        name="top_artists",
        title="Top artists",
        description=(
            "Most played artists in range, each with its play count and its "
            "share of all plays in the same range, highest first."
        ),
        builder=domain_queries.build_top_artists_sql,
    ),
    QueryEntry(
        name="top_albums",
        title="Top albums",
        description=(
            "Most played albums in range, each with its play count and its "
            "share of all plays in the same range. One row per album title: a "
            "compilation stays a single album rather than one row per "
            "contributor, and `album_ids` carries every identifier the counts "
            "cover."
        ),
        builder=domain_queries.build_top_albums_sql,
    ),
    QueryEntry(
        name="top_tracks",
        title="Top tracks",
        description=(
            "Most played tracks in range, each with its artist, album, play "
            "count and share of all plays in the same range."
        ),
        builder=domain_queries.build_top_tracks_sql,
    ),
    QueryEntry(
        name="artist_list",
        title="Artists with statistics",
        description=(
            "Every artist with plays in range, with play, track and album "
            "counts and the timestamp of its most recent play."
        ),
        builder=domain_queries.build_artists_with_stats_sql,
    ),
    QueryEntry(
        name="album_list",
        title="Albums with statistics",
        description=(
            "Every album, one row per title, with track and play counts and "
            "its most recent play. An album held under several identifiers is "
            "a single row whose counts cover all of them (`album_ids`); an "
            "album whose tracks span several artists is credited to "
            f"'{domain_queries.VARIOUS_ARTISTS}' rather than to one "
            "contributor. Optional artist name or artist id filter."
        ),
        builder=domain_queries.build_albums_list_sql,
    ),
    QueryEntry(
        name="track_list",
        title="Tracks with statistics",
        description=(
            "Every track with its artist, album, play count and most recent "
            "play. Optional artist, album, artist id and album id filters."
        ),
        builder=domain_queries.build_tracks_list_sql,
    ),
    QueryEntry(
        name="artist_detail",
        title="Artist detail",
        description=(
            "One artist's totals, given its `artist_id`: play, track and album "
            "counts with the timestamps of its first and last play."
        ),
        builder=domain_queries.build_artist_stats_sql,
    ),
    QueryEntry(
        name="artist_top_tracks",
        title="An artist's top tracks",
        description=(
            "One artist's most played tracks, given its `artist_id`, each with "
            "its album, play count and most recent play."
        ),
        builder=domain_queries.build_artist_top_tracks_sql,
    ),
    QueryEntry(
        name="album_detail",
        title="Album detail",
        description=(
            "One album identifier's totals, given its `album_id`: track and "
            "play counts with the timestamps of its first and last play. An "
            "album held under several identifiers is covered one identifier at "
            "a time here; pass the album list's `album_ids` to `album_tracks` "
            "for the whole group."
        ),
        builder=domain_queries.build_album_stats_sql,
    ),
    QueryEntry(
        name="album_tracks",
        title="An album's tracks",
        description=(
            "The tracks of one album, with play counts. `album_ids` is a JSON "
            'array of album identifiers, e.g. ["md5:abc","md5:def"], so an '
            "album held under several identifiers resolves to all of its "
            "tracks in one query."
        ),
        builder=domain_queries.build_album_tracks_sql,
    ),
    QueryEntry(
        name="track_detail",
        title="Track detail",
        description=(
            "One track's totals, given its `track_id`: play count and the "
            "timestamps of its first and last play."
        ),
        builder=domain_queries.build_track_stats_sql,
    ),
    QueryEntry(
        name="track_plays",
        title="A track's play history",
        description=(
            "Every recorded play of one track, given its `track_id`, most "
            "recent first."
        ),
        builder=domain_queries.build_track_plays_sql,
    ),
)


def stored_query_definitions() -> dict[str, dict[str, str]]:
    """
    The catalog as `{name: {"sql", "title", "description"}}`.

    The classic canned-query dict shape, which is also exactly what
    `datasette.add_query()` consumes.
    """
    return {
        entry.name: {
            "sql": entry.sql,
            "title": entry.title,
            "description": entry.description,
        }
        for entry in CATALOG
    }
