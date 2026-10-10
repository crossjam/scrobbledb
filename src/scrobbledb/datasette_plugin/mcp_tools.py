"""
scrobbledb's own MCP tools: listening-history questions answered without SQL.

`datasette-mcp` owns the `/-/mcp` endpoint and three generic tools. This module
contributes the domain ones through the hook it documents, `register_mcp_tools`
(design D8). It lives apart from the rest of the plugin because a hookimpl with
no matching hookspec sits unmatched in the plugin manager and `pm.check_pending()`
raises on it: `scrobbledb serve` therefore registers this module only after
confirming `datasette_mcp` imports, and without it the server still starts and
says the endpoint is unavailable.

Every tool is a thin wrapper. The SQL comes from the builders in
`domain_queries` and the rows are shaped by its shapers, which are the same ones
the CLI and the stored queries use, so the three surfaces cannot drift. What is
different is how the SQL runs. `domain_queries.get_*` open their own
`sqlite_utils` connection, which from inside a request would bypass Datasette's
thread pool, time limit and the connection `prepare_connection` has made
read-only; these tools run it through `Database.execute()` instead.

That call performs no permission check of its own, so the check is explicit and
comes first in every tool (design D11): the caller must be able to view the
database and to execute SQL against it, and nothing reads the database before
both are settled.

Authorization API, confirmed against the installed Datasette 1.0a39
--------------------------------------------------------------------

    await datasette.allowed(action="execute-sql",
                            resource=DatabaseResource(name),
                            actor=actor)

with `DatabaseResource` from `datasette.resources`, keyword-only, returning a
bool. `datasette-mcp` 0.2 uses the same call; this module makes its own rather
than importing that package's private helpers.
"""

import sqlite3
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, TypedDict, cast

from datasette import hookimpl
from datasette.database import QueryInterrupted
from datasette.resources import DatabaseResource
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from scrobbledb import domain_queries as dq
from scrobbledb.datasette_plugin.queries import is_scrobbledb

#: Most rows any one tool returns. A result cut by it says so (`truncated`), so
#: an agent never mistakes a capped list for the whole history. Kept well under
#: Datasette's own `max_returned_rows`, and small enough to sit in a model's
#: context without crowding out the question.
ROW_CAP = 100

#: Every tool reads and nothing else, and none reaches beyond the database.
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)

_TIME_EXAMPLES = "'2024-01-31', '7 days ago', '6 months ago' or 'last march'"

Since = Annotated[
    str,
    Field(
        description=(
            "Start of the range, inclusive: an ISO date or a relative expression "
            f"such as {_TIME_EXAMPLES}. Empty means from the beginning."
        )
    ),
]
Until = Annotated[
    str,
    Field(
        description=(
            "End of the range, inclusive, in the same forms as `since`. Empty "
            "means up to now."
        )
    ),
]
DatabaseName = Annotated[
    str,
    Field(
        description=(
            "Which database to query. Only needed when the server has more than one."
        )
    ),
]


def _limit_field(default: int):
    return Field(
        ge=1,
        description=(
            f"Most rows to return (default {default}). Values above {ROW_CAP} "
            "are capped and the result is marked truncated."
        ),
    )


TopLimit = Annotated[int, _limit_field(10)]
ListLimit = Annotated[int, _limit_field(20)]


class Page(TypedDict):
    """A list result: the rows, how many, and whether the cap cut it short."""

    items: list[dict[str, Any]]
    count: int
    truncated: bool


class Overview(TypedDict):
    total_scrobbles: int
    unique_artists: int
    unique_albums: int
    unique_tracks: int
    first_scrobble: Optional[str]
    last_scrobble: Optional[str]


class Detail(TypedDict):
    """A single-entity lookup: found with the details, or not found with why."""

    found: bool
    match: Optional[dict[str, Any]]
    message: Optional[str]


class SearchResults(TypedDict):
    artists: Page
    albums: Page
    tracks: Page


# --------------------------------------------------------------------------
# Authorization and database resolution
# --------------------------------------------------------------------------


def _actor_from_context(ctx: Context) -> Optional[dict[str, Any]]:
    """The calling actor, as Datasette's authentication put it on the request."""
    request = ctx.request_context.request
    scope = getattr(request, "scope", None)
    if not isinstance(scope, dict):
        return None
    actor = scope.get("actor")
    return actor if isinstance(actor, dict) else None


def _unavailable(name: str) -> ToolError:
    # One wording for "no such database" and "not allowed to see it", so the
    # answer does not reveal which databases exist.
    return ToolError(f"Database {name!r} does not exist or is not available.")


async def _authorized_database(datasette, ctx: Context, database: str):
    """
    The scrobbledb `Database` to query, once the caller is allowed to query it.

    Every tool calls this before it builds a statement. Both permissions are
    settled for every candidate before any database is read; the schema check
    that picks the scrobbledb one among the permitted databases is the first
    read, and it never touches a database the caller may not query.

    A server can carry more than the scrobbledb database (Datasette adds an
    empty `_memory` one when it is started without files), so with no
    `database` named the choice is the one permitted database that has the
    scrobbledb schema.
    """
    actor = _actor_from_context(ctx)
    await datasette.invoke_startup()

    visible = [name for name in datasette.databases if name != "_internal"]
    if database and database not in visible:
        raise _unavailable(database)

    permitted, denied = [], []
    for name in [database] if database else visible:
        resource = DatabaseResource(name)
        if not await datasette.allowed(
            action="view-database", resource=resource, actor=actor
        ):
            if database:
                raise _unavailable(name)
            continue
        if await datasette.allowed(
            action="execute-sql", resource=resource, actor=actor
        ):
            permitted.append(name)
        else:
            denied.append(name)

    if not permitted:
        if denied:
            raise ToolError(
                "You do not have permission to execute SQL against database "
                f"{denied[0]!r}."
            )
        raise ToolError("This server has no database to query.")

    scrobbledbs = [
        name for name in permitted if await is_scrobbledb(datasette.get_database(name))
    ]
    if not scrobbledbs:
        if denied:
            # Whether a database the caller may not query is the scrobbledb one
            # cannot be learned without reading it, so say what is known: they
            # were refused, and nothing else qualified.
            raise ToolError(
                "You do not have permission to execute SQL against database "
                f"{denied[0]!r}."
            )
        raise ToolError(
            "No scrobbledb database is available: it needs the artists, albums, "
            f"tracks and plays tables. Checked: {', '.join(sorted(permitted))}."
        )
    if len(scrobbledbs) > 1:
        raise ToolError(
            "This server has several scrobbledb databases; say which with the "
            f"`database` argument. Available: {', '.join(sorted(scrobbledbs))}."
        )
    return datasette.get_database(scrobbledbs[0])


# --------------------------------------------------------------------------
# Execution and shaping
# --------------------------------------------------------------------------


async def _fetch(db, built, *, tolerate_sql_errors: bool = False):
    """
    Run one built statement through Datasette, with the caller's errors tidy.

    `tolerate_sql_errors` returns None for a SQLite error instead of raising it,
    for the one stage that is allowed to fail. The time limit is never tolerated.
    """
    sql, params = built
    try:
        return await db.execute(sql, params, truncate=True, log_sql_errors=False)
    except QueryInterrupted:
        raise ToolError(
            "The query exceeded the server's SQL time limit. Narrow the range "
            "with `since`/`until` or lower `limit`."
        ) from None
    except (sqlite3.DatabaseError, sqlite3.Warning) as ex:
        if tolerate_sql_errors:
            return None
        raise ToolError(f"SQL error: {ex}") from None


async def _rows(db, built) -> tuple[list, bool]:
    """The statement's rows, cut at `ROW_CAP`, and whether anything was cut."""
    results = await _fetch(db, built)
    rows = list(results.rows)
    truncated = bool(results.truncated)
    if len(rows) > ROW_CAP:
        rows = rows[:ROW_CAP]
        truncated = True
    return rows, truncated


async def _one(db, built):
    rows, _ = await _rows(db, built)
    return rows[0] if rows else None


def _sql_limit(limit: Optional[int]) -> int:
    """
    The LIMIT to ask SQL for: one past the cap at most.

    The extra row is what lets `_rows` tell "exactly the cap" from "more than
    the cap", and it stops a request for a million rows from making the
    database aggregate a million.
    """
    return ROW_CAP + 1 if limit is None else min(limit, ROW_CAP + 1)


def _page(items: list[dict], truncated: bool) -> Page:
    return {"items": items, "count": len(items), "truncated": truncated}


def _bound(name: str, text: str) -> Optional[datetime]:
    """
    One time bound, read exactly as the CLI reads `--since` and `--until`.

    It uses `parse_relative_time`, the parser `parse_when` is built on, so a
    value means the same thing on every surface. Where `parse_when` answers an
    unreadable value with NULL, a tool names it and shows a form that works.
    """
    if text is None or not text.strip():
        return None
    parsed = dq.parse_relative_time(text)
    if parsed is None:
        raise ToolError(
            f"Cannot interpret {name} value {text!r}. Use an ISO date or a "
            f"relative time such as {_TIME_EXAMPLES}."
        )
    return parsed


def _range(since: str, until: str) -> tuple[Optional[datetime], Optional[datetime]]:
    return _bound("since", since), _bound("until", until)


def _call(build, **kwargs):
    """Build a statement in positional form, turning a bad argument into a tool error."""
    try:
        return build(form=dq.SQL_FORM_POSITIONAL, **kwargs)
    except ValueError as ex:
        raise ToolError(str(ex)) from None


def _candidates(rows, label) -> str:
    return "; ".join(label(row) for row in rows)


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


@hookimpl
def register_mcp_tools(datasette, mcp):
    """Register scrobbledb's domain tools on this Datasette's MCP server."""

    tool = mcp.tool(annotations=READ_ONLY)

    @tool
    async def collection_overview(ctx: Context, database: DatabaseName = "") -> Overview:
        """Totals for the whole listening history: scrobbles, distinct artists,
        albums and tracks, and the first and last scrobble. A good first call."""
        db = await _authorized_database(datasette, ctx, database)
        row = await _one(db, _call(dq.build_overview_stats_sql))
        return cast(Overview, dq.shape_overview_stats(row))

    @tool
    async def top_artists(
        ctx: Context,
        since: Since = "",
        until: Until = "",
        limit: TopLimit = 10,
        database: DatabaseName = "",
    ) -> Page:
        """Most-played artists, ranked, with each one's share of the plays and
        average plays per day, optionally within a time range."""
        db = await _authorized_database(datasette, ctx, database)
        since_dt, until_dt = _range(since, until)
        rows, truncated = await _rows(
            db,
            _call(
                dq.build_top_artists_sql,
                limit=_sql_limit(limit),
                since=since_dt,
                until=until_dt,
            ),
        )
        date_range = None
        if dq.needs_date_range(since_dt, until_dt):
            date_range = await _one(db, (dq.DATE_RANGE_SQL, []))
        days = dq.days_in_period(since_dt, until_dt, date_range)
        return _page(dq.shape_top_artists(rows, days=days), truncated)

    @tool
    async def top_albums(
        ctx: Context,
        since: Since = "",
        until: Until = "",
        artist: Annotated[
            str, Field(description="Only albums whose artist name contains this.")
        ] = "",
        limit: TopLimit = 10,
        database: DatabaseName = "",
    ) -> Page:
        """Most-played albums, ranked, optionally within a time range or for one
        artist. Albums sharing a title are merged; a merged album with several
        contributing artists is credited to "Various Artists"."""
        db = await _authorized_database(datasette, ctx, database)
        since_dt, until_dt = _range(since, until)
        rows, truncated = await _rows(
            db,
            _call(
                dq.build_top_albums_sql,
                limit=_sql_limit(limit),
                since=since_dt,
                until=until_dt,
                artist=artist or None,
            ),
        )
        return _page(dq.shape_top_albums(rows), truncated)

    @tool
    async def top_tracks(
        ctx: Context,
        since: Since = "",
        until: Until = "",
        artist: Annotated[
            str, Field(description="Only tracks whose artist name contains this.")
        ] = "",
        limit: TopLimit = 10,
        database: DatabaseName = "",
    ) -> Page:
        """Most-played tracks, ranked, optionally within a time range or for one
        artist."""
        db = await _authorized_database(datasette, ctx, database)
        since_dt, until_dt = _range(since, until)
        rows, truncated = await _rows(
            db,
            _call(
                dq.build_top_tracks_sql,
                limit=_sql_limit(limit),
                since=since_dt,
                until=until_dt,
                artist=artist or None,
            ),
        )
        return _page(dq.shape_top_tracks(rows), truncated)

    @tool
    async def recent_plays(
        ctx: Context,
        since: Since = "",
        until: Until = "",
        artist: Annotated[
            str, Field(description="Only plays whose artist name contains this.")
        ] = "",
        album: Annotated[
            str, Field(description="Only plays whose album title contains this.")
        ] = "",
        track: Annotated[
            str, Field(description="Only plays whose track title contains this.")
        ] = "",
        limit: ListLimit = 20,
        database: DatabaseName = "",
    ) -> Page:
        """The listening log, newest first: when each track was played, optionally
        within a time range or filtered by artist, album or track name."""
        db = await _authorized_database(datasette, ctx, database)
        since_dt, until_dt = _range(since, until)
        rows, truncated = await _rows(
            db,
            _call(
                dq.build_plays_with_filters_sql,
                limit=_sql_limit(limit),
                since=since_dt,
                until=until_dt,
                artist=artist or None,
                album=album or None,
                track=track or None,
            ),
        )
        return _page(dq.shape_plays_with_filters(rows), truncated)

    @tool
    async def listening_rollup(
        ctx: Context,
        period: Annotated[
            Literal["day", "month", "year"],
            Field(description="How to group the plays: by day, month or year."),
        ] = "month",
        since: Since = "",
        until: Until = "",
        limit: Annotated[
            Optional[int],
            Field(
                ge=1,
                description=(
                    "Most periods to return, newest first. Omit for as many as "
                    f"the cap allows ({ROW_CAP})."
                ),
            ),
        ] = None,
        database: DatabaseName = "",
    ) -> Page:
        """Scrobbles and distinct artists, albums and tracks per day, month or
        year, newest first, optionally within a time range."""
        db = await _authorized_database(datasette, ctx, database)
        since_dt, until_dt = _range(since, until)
        build, shape = {
            "day": (dq.build_daily_rollup_sql, dq.shape_daily_rollup),
            "month": (dq.build_monthly_rollup_sql, dq.shape_monthly_rollup),
            "year": (dq.build_yearly_rollup_sql, dq.shape_yearly_rollup),
        }[period]
        rows, truncated = await _rows(
            db,
            _call(
                build, since=since_dt, until=until_dt, limit=_sql_limit(limit)
            ),
        )
        return _page(shape(rows), truncated)

    @tool
    async def artist_details(
        ctx: Context,
        name: Annotated[
            str, Field(description="Artist name; a partial name is fine if it is unique.")
        ] = "",
        artist_id: Annotated[
            str, Field(description="Exact artist id, as returned by search_music.")
        ] = "",
        database: DatabaseName = "",
    ) -> Detail:
        """One artist's play count, track count, album count and first and last
        play. Give a name or an exact id. An ambiguous name is an error listing
        the candidates; an unknown one is a result with found=false."""
        if not name.strip() and not artist_id.strip():
            raise ToolError("Give an artist `name` or an `artist_id`.")
        db = await _authorized_database(datasette, ctx, database)
        matches, _ = await _rows(
            db,
            _call(
                dq.build_artist_lookup_sql,
                artist_id=artist_id or None,
                artist_name=None if artist_id else name,
            ),
        )
        if not matches:
            return _no_match("artist", artist_id or name)
        if len(matches) > 1:
            raise _ambiguous("artist", name, matches, lambda r: f"{r[1]} (id {r[0]})")
        stats = await _one(
            db, _call(dq.build_artist_stats_sql, artist_id=matches[0][0])
        )
        return _found(dq.shape_artist_details(matches[0], stats))

    @tool
    async def album_details(
        ctx: Context,
        title: Annotated[
            str, Field(description="Album title; a partial title is fine if unique.")
        ] = "",
        artist: Annotated[
            str, Field(description="Artist name, to tell apart albums sharing a title.")
        ] = "",
        album_id: Annotated[
            str, Field(description="Exact album id, as returned by search_music.")
        ] = "",
        database: DatabaseName = "",
    ) -> Detail:
        """One album's track count, play count and first and last play. Give a
        title (and an artist if the title is shared) or an exact id. An ambiguous
        title is an error listing the candidates; an unknown one is a result with
        found=false."""
        if not title.strip() and not album_id.strip():
            raise ToolError("Give an album `title` or an `album_id`.")
        db = await _authorized_database(datasette, ctx, database)
        matches, _ = await _rows(
            db,
            _call(
                dq.build_album_lookup_sql,
                album_id=album_id or None,
                album_title=None if album_id else title,
                artist_name=None if album_id else (artist or None),
            ),
        )
        if not matches:
            return _no_match("album", album_id or title)
        if len(matches) > 1:
            raise _ambiguous(
                "album", title, matches, lambda r: f"{r[1]} by {r[2]} (id {r[0]})"
            )
        stats = await _one(db, _call(dq.build_album_stats_sql, album_id=matches[0][0]))
        return _found(dq.shape_album_details(matches[0], stats))

    @tool
    async def track_details(
        ctx: Context,
        title: Annotated[
            str, Field(description="Track title; a partial title is fine if unique.")
        ] = "",
        artist: Annotated[
            str, Field(description="Artist name, to tell apart tracks sharing a title.")
        ] = "",
        album: Annotated[
            str, Field(description="Album title, to tell apart tracks sharing a title.")
        ] = "",
        track_id: Annotated[
            str, Field(description="Exact track id, as returned by search_music.")
        ] = "",
        database: DatabaseName = "",
    ) -> Detail:
        """One track's play count and first and last play. Give a title (with an
        artist or album if the title is shared) or an exact id. An ambiguous title
        is an error listing the candidates; an unknown one is a result with
        found=false."""
        if not title.strip() and not track_id.strip():
            raise ToolError("Give a track `title` or a `track_id`.")
        db = await _authorized_database(datasette, ctx, database)
        matches, _ = await _rows(
            db,
            _call(
                dq.build_track_lookup_sql,
                track_id=track_id or None,
                track_title=None if track_id else title,
                artist_name=None if track_id else (artist or None),
                album_title=None if track_id else (album or None),
            ),
        )
        if not matches:
            return _no_match("track", track_id or title)
        if len(matches) > 1:
            raise _ambiguous(
                "track",
                title,
                matches,
                lambda r: f"{r[1]} by {r[2]} on {r[3]} (id {r[0]})",
            )
        stats = await _one(db, _call(dq.build_track_stats_sql, track_id=matches[0][0]))
        return _found(dq.shape_track_details(matches[0], stats))

    @tool
    async def search_music(
        ctx: Context,
        query: Annotated[
            str, Field(min_length=1, description="Part of an artist, album or track name.")
        ],
        limit: TopLimit = 10,
        database: DatabaseName = "",
    ) -> SearchResults:
        """Find artists, albums and tracks by part of a name. Each hit carries the
        id to pass to artist_details, album_details or track_details."""
        db = await _authorized_database(datasette, ctx, database)
        n = _sql_limit(limit)

        artists, artists_cut = await _search_artists(db, query, n)
        album_rows, albums_cut = await _rows(
            db, _call(dq.build_albums_by_search_sql, query=query, limit=n)
        )
        track_rows, tracks_cut = await _rows(
            db, _call(dq.build_tracks_by_search_sql, query=query, limit=n)
        )
        return {
            "artists": _page(artists, artists_cut),
            "albums": _page(dq.shape_albums_by_search(album_rows), albums_cut),
            "tracks": _page(dq.shape_tracks_by_search(track_rows), tracks_cut),
        }


async def _search_artists(db, query: str, limit: int) -> tuple[list[dict], bool]:
    """
    Artist search, the same candidate pipeline `get_artists_by_search` runs.

    The FTS5 stage is allowed to fail. Its query is built from the caller's text
    (`artist_name:<text>*`), so an apostrophe or a slash is an FTS5 syntax
    error; the CLI lets that surface, but an agent passing "Guns N' Roses"
    should get the LIKE matches rather than an error, so here it falls back to
    them.
    """
    ids: list = []
    if "tracks_fts" in await db.table_names():
        results = await _fetch(
            db,
            _call(dq.build_artist_fts_candidates_sql, query=query, limit=limit),
            tolerate_sql_errors=True,
        )
        ids = dq.fts_artist_ids(results.rows) if results is not None else []
    if len(ids) < limit:
        like = await _fetch(
            db, _call(dq.build_artist_like_candidates_sql, query=query, limit=limit)
        )
        ids = dq.merge_artist_ids(ids, like.rows, limit)
    if not ids:
        return [], False
    stats = await _fetch(db, _call(dq.build_artist_search_stats_sql, artist_ids=ids))
    shaped = dq.shape_artists_by_search(stats.rows, query=query, limit=limit)
    return shaped[:ROW_CAP], len(shaped) > ROW_CAP or bool(stats.truncated)


def _found(match: dict) -> Detail:
    return {"found": True, "match": match, "message": None}


def _no_match(kind: str, what: str) -> Detail:
    return {
        "found": False,
        "match": None,
        "message": (
            f"No {kind} matches {what!r}. Use search_music to find the exact name."
        ),
    }


def _ambiguous(kind: str, what: str, matches, label) -> ToolError:
    return ToolError(
        f"More than one {kind} matches {what!r}: {_candidates(matches, label)}. "
        f"Be more specific, or pass the exact id from search_music."
    )
