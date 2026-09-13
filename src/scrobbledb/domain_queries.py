"""
Domain query functions for scrobbledb.

This module provides shared query functions for domain-specific CLI commands,
including statistics, filtering, and aggregation queries.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
import dateparser
import dateutil.parser
import sqlite_utils

_WEEKDAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# Matches a trailing "Z" or numeric UTC offset (e.g. "-05:00", "+0530"),
# used to detect when an input explicitly pins an instant in time rather
# than describing a local wall-clock date/time.
_TZ_OFFSET_RE = re.compile(r"(?i)(Z|[+-]\d{2}:?\d{2})$")

# Builders render their SQL in one of two forms from a single SELECT body
# (design D4/D5). Both produce identical results; they differ only in how
# optional predicates are expressed, and therefore in what SQLite can index.
#
#   NAMED       ":since" placeholders and a dict of parameters. The string is
#               static, which is what a Datasette canned query requires, since
#               its parameters arrive from the URL. Optional bounds are always
#               present and guarded by the `:since = ''` idiom, so an omitted
#               bound is passed as an empty string rather than changing the SQL.
#
#   POSITIONAL  "?" placeholders and a list of parameters. The SQL is built per
#               call, so an absent bound is simply not rendered.
#
# Why both: the guard is not sargable, so the named form cannot use the
# plays(timestamp, track_id) primary-key index and degrades to a full scan.
# Measured against the live database, that costs up to 116x on a one-day range
# and nothing at all at full-table width (see design D5). The CLI and MCP paths
# build SQL per call and so use POSITIONAL; canned queries use NAMED.
SQL_FORM_NAMED = "named"
SQL_FORM_POSITIONAL = "positional"

# SQLite treats a negative LIMIT as unbounded, which lets the named form carry
# "LIMIT :limit" unconditionally and still express "no limit".
_NO_LIMIT = -1

# Entity lookups fetch one extra row so an ambiguous match is detectable.
_LOOKUP_LIMIT = 2

# Reported as an aggregated album's artist when the album's tracks span more
# than one artist -- a compilation or DJ mix. Album aggregates group on title
# alone so such an album stays one row (GitHub #47); naming any single
# contributor as the album's artist would be the false attribution that
# grouping on artist_id was introduced to remove, so the aggregate declines to
# name one instead. The per-artist detail is still reachable through
# `album_ids` and `albums list --expand`.
VARIOUS_ARTISTS = "Various Artists"

# Resolves an aggregated album's artist: the owning artist when the group has
# exactly one, the sentinel otherwise. MIN() is safe in the single-artist case
# because every row in the group then carries that one name.
#
# Counts distinct *names*, not artist ids, on purpose. The same artist often
# exists under several ids -- an MBID and a synthesized `md5:` one -- and
# counting ids would report "Various Artists" for an album that plainly belongs
# to one artist. Measured against the live database, counting ids mislabels 19
# albums this way, including "Endtroducing (Deluxe Edition)".
_AGGREGATE_ARTIST_NAME = f"""CASE
                WHEN COUNT(DISTINCT artists.name COLLATE NOCASE) = 1
                    THEN MIN(artists.name)
                ELSE '{VARIOUS_ARTISTS}'
            END"""


class _Params:
    """
    Accumulates bound parameters in whichever form the builder was asked for.

    `add()` binds a value and returns the placeholder text to embed in the SQL,
    so a builder never has to know which form it is rendering.
    """

    def __init__(self, form: str = SQL_FORM_NAMED):
        if form not in (SQL_FORM_NAMED, SQL_FORM_POSITIONAL):
            raise ValueError(f"unknown SQL form: {form!r}")
        self.form = form
        self._named: dict = {}
        self._positional: list = []

    def add(self, name: str, value) -> str:
        """Bind `value` under `name` and return its placeholder."""
        if self.form == SQL_FORM_NAMED:
            self._named[name] = value
            return f":{name}"
        self._positional.append(value)
        return "?"

    @property
    def values(self):
        """The bound parameters, as a dict for the named form and a list otherwise."""
        return self._named if self.form == SQL_FORM_NAMED else self._positional


def _time_bound_conditions(
    params: _Params,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    column: str = "plays.timestamp",
) -> list[str]:
    """
    Render the optional since/until bounds against `column`.

    In the named form both predicates are always emitted, guarded so that an
    empty string means "no bound". In the positional form only the bounds that
    were supplied are emitted at all, which is what preserves the index.
    """
    if params.form == SQL_FORM_NAMED:
        conditions = []
        for name, op, value in (("since", ">=", since), ("until", "<=", until)):
            placeholder = params.add(name, _to_utc_iso(value) if value else "")
            conditions.append(f"({placeholder} = '' OR {column} {op} {placeholder})")
        return conditions

    conditions = []
    if since:
        conditions.append(f"{column} >= {params.add('since', _to_utc_iso(since))}")
    if until:
        conditions.append(f"{column} <= {params.add('until', _to_utc_iso(until))}")
    return conditions


def _like_conditions(params: _Params, filters: dict) -> list[str]:
    """
    Render optional substring filters as LIKE predicates.

    `filters` maps parameter name to (column, value). As with the time bounds,
    the named form always emits every predicate under the empty-string guard and
    builds the wildcards in SQL, since a canned query receives the bare value
    from the URL; the positional form emits only the filters actually supplied.
    """
    conditions = []
    for name, (column, value) in filters.items():
        if params.form == SQL_FORM_NAMED:
            placeholder = params.add(name, value or "")
            conditions.append(
                f"({placeholder} = '' OR {column} LIKE '%' || {placeholder} || '%')"
            )
        elif value:
            conditions.append(f"{column} LIKE {params.add(name, f'%{value}%')}")
    return conditions


def _exact_conditions(params: _Params, filters: dict) -> list[str]:
    """
    Render optional exact-match filters, following `_like_conditions`.

    `filters` maps parameter name to (column, value).
    """
    conditions = []
    for name, (column, value) in filters.items():
        if params.form == SQL_FORM_NAMED:
            placeholder = params.add(name, value or "")
            conditions.append(f"({placeholder} = '' OR {column} = {placeholder})")
        elif value:
            conditions.append(f"{column} = {params.add(name, value)}")
    return conditions


def _split_ids(value) -> list[str]:
    """Split a group_concat() of ids back into a list."""
    if not value:
        return []
    return value.split(",")


def _sort_direction(order: str) -> str:
    """
    Validate a sort direction before it is interpolated into SQL.

    The CLI constrains this with click.Choice, but the builders are also called
    from the Datasette plugin and the MCP tools, where the value is not
    pre-validated, so the whitelist is enforced here rather than assumed.
    """
    direction = (order or "").upper()
    if direction not in ("ASC", "DESC"):
        raise ValueError(f"Unknown sort order: {order!r}")
    return direction


def _where_clause(conditions: list[str]) -> str:
    """Join rendered conditions into a WHERE clause, or nothing if there are none."""
    return "WHERE " + " AND ".join(conditions) if conditions else ""


def _as_int(value, name: str) -> int:
    """
    Coerce a value destined for SQL *text* to an integer, or refuse it.

    `_numeric` interpolates its fallback rather than binding it -- a bound
    parameter cannot serve as a COALESCE default in static SQL -- so the
    fallback must never be caller-controlled text. The CLI screens these with
    click's int type, but the builders are also called from the MCP tools and
    the plugin, where nothing has.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer, got {value!r}") from None


def _numeric(placeholder: str, default) -> str:
    """
    Wrap a placeholder so a blank or string-typed value still behaves as a number.

    Datasette hands canned-query parameters to SQLite as *strings*, and a
    parameter the user left blank arrives as `''`. Bound directly that breaks
    two ways: `LIMIT ''` raises "datatype mismatch", and `COUNT(*) >= ''`
    compares an affinity-less aggregate against text, which is always false, so
    a HAVING clause silently filters every row away.

    Blank becomes the builder's own default and anything else is cast, so one
    static string serves both a canned query and a typed CLI call.
    """
    return f"CAST(COALESCE(NULLIF({placeholder}, ''), {default}) AS INTEGER)"


def _json_array_param(params: _Params, name: str, values) -> str:
    """
    Bind a list of ids as one JSON array parameter.

    The `COALESCE(NULLIF(...))` mirrors `_numeric`: a canned query supplies a
    blank for an omitted parameter, and `json_each('')` raises "malformed
    JSON". An empty array is the right reading of "no ids given" -- it matches
    nothing, rather than failing the statement.
    """
    placeholder = params.add(name, json.dumps([str(v) for v in (values or [])]))
    if params.form != SQL_FORM_NAMED:
        return placeholder
    return f"COALESCE(NULLIF({placeholder}, ''), '[]')"


def _numeric_param(params: _Params, name: str, value, default=None) -> str:
    """
    Bind a numeric parameter, normalized when the form is the named one.

    The bound value is left as supplied, since the CAST handles a string at
    runtime, but the interpolated fallback is coerced to an integer first --
    it lands in SQL text, not in a parameter.
    """
    placeholder = params.add(name, value)
    if params.form != SQL_FORM_NAMED:
        return placeholder
    fallback = default if default is not None else value
    return _numeric(placeholder, _as_int(fallback, name))


def _limit_clause(params: _Params, limit: Optional[int]) -> str:
    """
    Render an optional LIMIT as a bound parameter rather than interpolated text.

    The named form always emits the clause, using the negative-limit sentinel to
    mean unbounded, so the SQL string stays static.
    """
    if params.form == SQL_FORM_NAMED:
        value = _NO_LIMIT if limit is None else _as_int(limit, "limit")
        return f"LIMIT {_numeric_param(params, 'limit', value, default=value)}"
    if limit is None:
        return ""
    return f"LIMIT {params.add('limit', limit)}"


def build_overview_stats_sql(form: str = SQL_FORM_NAMED) -> tuple[str, object]:
    """Build the overview statistics query. Pure: touches no database."""
    params = _Params(form)
    sql = """
        SELECT
            (SELECT COUNT(*) FROM plays) as total_scrobbles,
            (SELECT COUNT(*) FROM artists) as unique_artists,
            (SELECT COUNT(*) FROM albums) as unique_albums,
            (SELECT COUNT(*) FROM tracks) as unique_tracks,
            (SELECT MIN(timestamp) FROM plays) as first_scrobble,
            (SELECT MAX(timestamp) FROM plays) as last_scrobble
        """
    return sql, params.values


def shape_overview_stats(row) -> dict:
    """Shape a single overview row into its dict form. Pure."""
    return {
        "total_scrobbles": row[0] or 0,
        "unique_artists": row[1] or 0,
        "unique_albums": row[2] or 0,
        "unique_tracks": row[3] or 0,
        "first_scrobble": row[4],
        "last_scrobble": row[5],
    }


def get_overview_stats(db: sqlite_utils.Database) -> dict:
    """
    Get overview statistics for the entire database.

    Returns a dict with:
    - total_scrobbles: Total number of plays
    - unique_artists: Count of distinct artists
    - unique_albums: Count of distinct albums
    - unique_tracks: Count of distinct tracks
    - first_scrobble: Earliest play timestamp
    - last_scrobble: Most recent play timestamp
    """
    sql, params = build_overview_stats_sql(SQL_FORM_POSITIONAL)
    return shape_overview_stats(db.execute(sql, params).fetchone())


def build_monthly_rollup_sql(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the per-month rollup query. Pure: touches no database."""
    if limit is not None:
        limit = _as_int(limit, "limit")
        if limit <= 0:
            raise ValueError("limit must be a positive integer")

    params = _Params(form)
    where_clause = _where_clause(_time_bound_conditions(params, since, until))
    limit_clause = _limit_clause(params, limit)

    sql = f"""
        SELECT
            CAST(strftime('%Y', plays.timestamp) AS INTEGER) as year,
            CAST(strftime('%m', plays.timestamp) AS INTEGER) as month,
            COUNT(*) as scrobbles,
            COUNT(DISTINCT artists.id) as unique_artists,
            COUNT(DISTINCT albums.id) as unique_albums,
            COUNT(DISTINCT tracks.id) as unique_tracks
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {where_clause}
        GROUP BY year, month
        ORDER BY year DESC, month DESC
        {limit_clause}
    """
    return sql, params.values


def shape_monthly_rollup(rows) -> list[dict]:
    """Shape per-month rollup rows into dicts. Pure."""
    return [
        {
            "year": row[0],
            "month": row[1],
            "scrobbles": row[2],
            "unique_artists": row[3],
            "unique_albums": row[4],
            "unique_tracks": row[5],
        }
        for row in rows
    ]


def get_monthly_rollup(
    db: sqlite_utils.Database,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Get scrobble statistics rolled up by month.

    Args:
        db: Database connection
        since: Optional start date filter
        until: Optional end date filter
        limit: Optional limit on number of results

    Returns a list of dicts, each containing:
    - year: The year
    - month: The month (1-12)
    - scrobbles: Number of plays in that month
    - unique_artists: Distinct artists played that month
    - unique_albums: Distinct albums played that month
    - unique_tracks: Distinct tracks played that month
    """
    sql, params = build_monthly_rollup_sql(
        since=since, until=until, limit=limit, form=SQL_FORM_POSITIONAL
    )
    return shape_monthly_rollup(db.execute(sql, params).fetchall())


def build_yearly_rollup_sql(
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """
    Build the per-year rollup query. Pure: touches no database.

    Unlike the monthly rollup, a non-positive limit is ignored rather than
    rejected -- preserving this function's long-standing behavior.
    """
    params = _Params(form)
    where_clause = _where_clause(_time_bound_conditions(params, since, until))
    limit_value = (
        None
        if limit is None or _as_int(limit, "limit") <= 0
        else _as_int(limit, "limit")
    )
    limit_clause = _limit_clause(params, limit_value)

    sql = f"""
        SELECT
            CAST(strftime('%Y', plays.timestamp) AS INTEGER) as year,
            COUNT(*) as scrobbles,
            COUNT(DISTINCT artists.id) as unique_artists,
            COUNT(DISTINCT albums.id) as unique_albums,
            COUNT(DISTINCT tracks.id) as unique_tracks
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {where_clause}
        GROUP BY year
        ORDER BY year DESC
        {limit_clause}
    """
    return sql, params.values


def shape_yearly_rollup(rows) -> list[dict]:
    """Shape per-year rollup rows into dicts. Pure."""
    return [
        {
            "year": row[0],
            "scrobbles": row[1],
            "unique_artists": row[2],
            "unique_albums": row[3],
            "unique_tracks": row[4],
        }
        for row in rows
    ]


def get_yearly_rollup(
    db: sqlite_utils.Database,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Get scrobble statistics rolled up by year.

    Args:
        db: Database connection
        since: Optional start date filter
        until: Optional end date filter
        limit: Optional limit on number of results

    Returns a list of dicts, each containing:
    - year: The year
    - scrobbles: Number of plays in that year
    - unique_artists: Distinct artists played that year
    - unique_albums: Distinct albums played that year
    - unique_tracks: Distinct tracks played that year
    """
    sql, params = build_yearly_rollup_sql(
        since=since, until=until, limit=limit, form=SQL_FORM_POSITIONAL
    )
    return shape_yearly_rollup(db.execute(sql, params).fetchall())


def parse_relative_time(time_str: str) -> Optional[datetime]:
    """
    Parse relative time expressions and absolute dates via dateparser.

    Supports natural language ("yesterday", "last month", "Monday",
    "3 weeks ago", "January 2024") as well as ISO 8601 and other common
    date formats.

    Returns:
        datetime object or None if parsing fails
    """
    normalized = time_str.strip()

    # dateparser resolves a bare weekday name to its most recent past
    # occurrence, but doesn't understand the "last <weekday>" phrasing --
    # strip the "last" so it falls back to that same resolution. That
    # resolution lands on *today* when today is that weekday, so
    # "last <weekday>" needs an extra week subtracted in that case (see
    # below) to actually mean the previous occurrence.
    last_weekday = re.match(r"(?i)^last\s+(\w+)$", normalized)
    is_last_weekday_phrase = bool(
        last_weekday and last_weekday.group(1).lower() in _WEEKDAY_NAMES
    )
    if is_last_weekday_phrase:
        normalized = last_weekday.group(1)

    # An explicit offset (e.g. "-05:00" or "Z") pins a specific instant;
    # parse it timezone-aware so the offset isn't silently discarded, then
    # normalize below to UTC. This is returned aware (unlike the naive
    # local wall-clock values this function returns for relative/local
    # expressions) so the instant stays unambiguous -- converting it to a
    # naive local value instead would be lossy across a DST fall-back,
    # where a given local wall-clock time occurs twice.
    has_explicit_offset = bool(_TZ_OFFSET_RE.search(normalized))

    result = dateparser.parse(
        normalized,
        settings={
            "RETURN_AS_TIMEZONE_AWARE": has_explicit_offset,
            "PREFER_DAY_OF_MONTH": "first",
        },
    )

    if result is None:
        try:
            result = dateutil.parser.parse(time_str)
        except (ValueError, TypeError):
            return None

    if result.tzinfo is not None:
        result = result.astimezone(timezone.utc)

    if is_last_weekday_phrase and result.date() >= datetime.now().date():
        result -= timedelta(weeks=1)

    return result


def _to_utc_iso(value):
    """
    Convert a since/until filter bound to a UTC ISO 8601 string for SQL
    comparison against plays.timestamp, which is stored as UTC-aware ISO
    8601 (see lastfm._extract_track_data). Naive datetimes -- the
    convention returned by parse_relative_time() and parse_period_to_dates()
    -- are assumed to represent local wall-clock time and are converted
    accordingly, so filtering is correct on non-UTC hosts.
    """
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.astimezone()
    return value.astimezone(timezone.utc).isoformat()


def parse_period_to_dates(period: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Convert period string to since/until dates.

    Supported periods:
    - 'week': last 7 days
    - 'month': last 30 days
    - 'quarter': last 90 days
    - 'year': last 365 days
    - 'all-time': no date filter (returns None, None)

    Returns:
        Tuple of (since, until) datetime objects
    """
    from datetime import timedelta

    now = datetime.now()
    period = period.lower().strip()

    if period == "week":
        return (now - timedelta(days=7), now)
    elif period == "month":
        return (now - timedelta(days=30), now)
    elif period == "quarter":
        return (now - timedelta(days=90), now)
    elif period == "year":
        return (now - timedelta(days=365), now)
    elif period == "all-time":
        return (None, None)
    else:
        raise ValueError(f"Unknown period: {period}")


def build_plays_with_filters_sql(
    limit: int = 20,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    track: Optional[str] = None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the filtered plays query. Pure: touches no database."""
    params = _Params(form)
    conditions = _time_bound_conditions(params, since, until)
    conditions += _like_conditions(
        params,
        {
            "artist": ("artists.name", artist),
            "album": ("albums.title", album),
            "track": ("tracks.title", track),
        },
    )

    sql = f"""
        SELECT
            plays.timestamp,
            artists.name as artist_name,
            tracks.title as track_title,
            albums.title as album_title
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {_where_clause(conditions)}
        ORDER BY plays.timestamp DESC
        LIMIT {_numeric_param(params, "limit", limit)}
    """
    return sql, params.values


def shape_plays_with_filters(rows) -> list[dict]:
    """Shape filtered play rows into dicts. Pure."""
    return [
        {
            "timestamp": row[0],
            "artist_name": row[1],
            "track_title": row[2],
            "album_title": row[3],
        }
        for row in rows
    ]


def get_plays_with_filters(
    db: sqlite_utils.Database,
    limit: int = 20,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    track: Optional[str] = None,
) -> list[dict]:
    """
    Query plays with various filters.

    Args:
        db: Database connection
        limit: Maximum number of plays to return
        since: Start date filter
        until: End date filter
        artist: Artist name filter (partial match)
        album: Album title filter (partial match)
        track: Track title filter (partial match)

    Returns:
        List of dicts with play information
    """
    sql, params = build_plays_with_filters_sql(
        limit=limit,
        since=since,
        until=until,
        artist=artist,
        album=album,
        track=track,
        form=SQL_FORM_POSITIONAL,
    )
    return shape_plays_with_filters(db.execute(sql, params).fetchall())


def build_artists_with_stats_sql(
    limit: int = 50,
    sort_by: str = "plays",
    order: str = "desc",
    min_plays: int = 0,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the artist statistics query. Pure: touches no database."""
    if sort_by == "plays":
        order_clause = f"ORDER BY play_count {_sort_direction(order)}"
    elif sort_by == "name":
        order_clause = f"ORDER BY artist_name {_sort_direction(order)}"
    elif sort_by == "recent":
        order_clause = "ORDER BY last_played DESC"
    else:
        raise ValueError(f"Unknown sort_by: {sort_by}")

    params = _Params(form)
    where_clause = _where_clause(_time_bound_conditions(params, since, until))

    sql = f"""
        SELECT
            artists.id as artist_id,
            artists.name as artist_name,
            COUNT(*) as play_count,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(DISTINCT albums.id) as album_count,
            MAX(plays.timestamp) as last_played
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {where_clause}
        GROUP BY artists.id, artists.name
        HAVING play_count >= {_numeric_param(params, "min_plays", min_plays)}
        {order_clause}
        LIMIT {_numeric_param(params, "limit", limit)}
    """
    return sql, params.values


def shape_artists_with_stats(rows) -> list[dict]:
    """Shape artist statistics rows into dicts. Pure."""
    return [
        {
            "artist_id": row[0],
            "artist_name": row[1],
            "play_count": row[2],
            "track_count": row[3],
            "album_count": row[4],
            "last_played": row[5],
        }
        for row in rows
    ]


def get_artists_with_stats(
    db: sqlite_utils.Database,
    limit: int = 50,
    sort_by: str = "plays",
    order: str = "desc",
    min_plays: int = 0,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> list[dict]:
    """
    Query artists with aggregated statistics.

    Args:
        db: Database connection
        limit: Maximum number of artists to return
        sort_by: Sort field ('plays', 'name', or 'recent')
        order: Sort order ('asc' or 'desc')
        min_plays: Minimum play count filter
        since: Start date filter
        until: End date filter

    Returns:
        List of dicts with artist statistics
    """
    sql, params = build_artists_with_stats_sql(
        limit=limit,
        sort_by=sort_by,
        order=order,
        min_plays=min_plays,
        since=since,
        until=until,
        form=SQL_FORM_POSITIONAL,
    )
    return shape_artists_with_stats(db.execute(sql, params).fetchall())


def build_albums_by_search_sql(
    query: str = "",
    artist: Optional[str] = None,
    limit: int = 20,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the album title search query. Pure: touches no database."""
    params = _Params(form)
    conditions = _like_conditions(
        params,
        {"query": ("albums.title", query), "artist": ("artists.name", artist)},
    )
    sql = f"""
        SELECT
            albums.id as album_id,
            albums.title as album_title,
            artists.name as artist_name,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM albums
        JOIN artists ON albums.artist_id = artists.id
        LEFT JOIN tracks ON tracks.album_id = albums.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        {_where_clause(conditions)}
        GROUP BY albums.id, albums.title, artists.name
        ORDER BY play_count DESC, albums.title ASC
        LIMIT {_numeric_param(params, "limit", limit)}
    """
    return sql, params.values


def shape_albums_by_search(rows) -> list[dict]:
    """Shape album search rows into dicts. Pure."""
    return [
        {
            "album_id": row[0],
            "album_title": row[1],
            "artist_name": row[2],
            "track_count": row[3],
            "play_count": row[4],
            "last_played": row[5],
        }
        for row in rows
    ]


def get_albums_by_search(
    db: sqlite_utils.Database,
    query: str,
    artist: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Search albums by title with optional artist filter.

    Args:
        db: Database connection
        query: Search query for album title
        artist: Optional artist name filter
        limit: Maximum results

    Returns:
        List of dicts with album information
    """
    sql, params = build_albums_by_search_sql(
        query=query, artist=artist, limit=limit, form=SQL_FORM_POSITIONAL
    )
    return shape_albums_by_search(db.execute(sql, params).fetchall())


def build_tracks_by_search_sql(
    query: str = "",
    artist: Optional[str] = None,
    album: Optional[str] = None,
    limit: int = 20,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the track title search query. Pure: touches no database."""
    params = _Params(form)
    conditions = _like_conditions(
        params,
        {
            "query": ("tracks.title", query),
            "artist": ("artists.name", artist),
            "album": ("albums.title", album),
        },
    )
    sql = f"""
        SELECT
            tracks.id as track_id,
            tracks.title as track_title,
            artists.name as artist_name,
            albums.title as album_title,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        {_where_clause(conditions)}
        GROUP BY tracks.id, tracks.title, artists.name, albums.title
        ORDER BY play_count DESC, tracks.title ASC
        LIMIT {_numeric_param(params, "limit", limit)}
    """
    return sql, params.values


def shape_tracks_by_search(rows) -> list[dict]:
    """Shape track search rows into dicts. Pure."""
    return [
        {
            "track_id": row[0],
            "track_title": row[1],
            "artist_name": row[2],
            "album_title": row[3],
            "play_count": row[4],
            "last_played": row[5],
        }
        for row in rows
    ]


def get_tracks_by_search(
    db: sqlite_utils.Database,
    query: str,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Search tracks by title with optional filters.

    Args:
        db: Database connection
        query: Search query for track title
        artist: Optional artist name filter
        album: Optional album title filter
        limit: Maximum results

    Returns:
        List of dicts with track information
    """
    sql, params = build_tracks_by_search_sql(
        query=query, artist=artist, album=album, limit=limit,
        form=SQL_FORM_POSITIONAL,
    )
    return shape_tracks_by_search(db.execute(sql, params).fetchall())


def _album_sort_column(sort: str) -> str:
    """Map an album sort key to its ORDER BY column."""
    if sort == "name":
        return "albums.title"
    if sort == "recent":
        return "last_played"
    return "play_count"


def build_albums_list_sql(
    artist: Optional[str] = None,
    artist_id: Optional[str] = None,
    limit: int = 50,
    sort: str = "plays",
    order: str = "desc",
    min_plays: int = 0,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """
    Build the album listing query. Pure: touches no database.

    Groups by ``albums.title COLLATE NOCASE`` so one album is one row even when
    its tracks are credited to many artists, which is the shape of a
    compilation or DJ mix (GitHub #47).

    The defect this replaces was not the merge itself but the attribution:
    ``album_id`` and ``artist_name`` used to be independent ``MAX()``
    aggregates, so a row could name an artist that did not own the album id
    beside it -- 909 such rows against the live database. Here ``artist_name``
    is derived from the group: the owning artist when the group has exactly
    one, and ``VARIOUS_ARTISTS`` when it spans several. No row names an artist
    that does not own the album.

    ``album_id`` remains a single stable representative for linking;
    ``album_ids`` carries every id in the group, which is what the counts
    beside it actually describe. See design D4.
    """
    params = _Params(form)
    conditions = _like_conditions(params, {"artist": ("artists.name", artist)})
    conditions += _exact_conditions(params, {"artist_id": ("artists.id", artist_id)})

    sql = f"""
        SELECT
            MAX(albums.id) as album_id,
            group_concat(DISTINCT albums.id) as album_ids,
            albums.title as album_title,
            {_AGGREGATE_ARTIST_NAME} as artist_name,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM albums
        JOIN artists ON albums.artist_id = artists.id
        LEFT JOIN tracks ON tracks.album_id = albums.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        {_where_clause(conditions)}
        GROUP BY albums.title COLLATE NOCASE
        HAVING play_count >= {_numeric_param(params, "min_plays", min_plays)}
        ORDER BY {_album_sort_column(sort)} {_sort_direction(order)}
        LIMIT {_numeric_param(params, "limit", limit)}
    """
    return sql, params.values


def shape_albums_list(rows) -> list[dict]:
    """Shape album listing rows into dicts. Pure."""
    return [
        {
            "album_id": row[0],
            "album_ids": _split_ids(row[1]),
            "album_title": row[2],
            "artist_name": row[3],
            "track_count": row[4],
            "play_count": row[5],
            "last_played": row[6],
        }
        for row in rows
    ]


def get_albums_list(
    db: sqlite_utils.Database,
    artist: Optional[str] = None,
    artist_id: Optional[str] = None,
    limit: int = 50,
    sort: str = "plays",
    order: str = "desc",
    min_plays: int = 0,
) -> list[dict]:
    """
    List albums with optional artist filter.

    Args:
        db: Database connection
        artist: Optional artist name filter
        artist_id: Optional artist ID filter
        limit: Maximum results
        sort: Sort by plays, name, or recent
        order: Sort order (asc or desc)
        min_plays: Minimum play count filter

    Returns:
        List of dicts with album information
    """
    sql, params = build_albums_list_sql(
        artist=artist,
        artist_id=artist_id,
        limit=limit,
        sort=sort,
        order=order,
        min_plays=min_plays,
        form=SQL_FORM_POSITIONAL,
    )
    return shape_albums_list(db.execute(sql, params).fetchall())


def build_artist_fts_candidates_sql(
    query: str = "",
    limit: int = 20,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """
    Build the FTS5 candidate query for artist search. Pure: touches no database.

    Over-fetches relative to `limit` because the candidates are re-ranked in
    Python afterwards, so the final ordering is not the one SQL returns.
    """
    params = _Params(form)
    # FTS5 MATCH expression - a prefix search within the artist_name column.
    match_expr = params.add("match", f"artist_name:{query}*")
    sql = f"""
        SELECT DISTINCT
            tracks_fts.artist_id,
            tracks_fts.artist_name
        FROM tracks_fts
        WHERE tracks_fts MATCH {match_expr}
        LIMIT {_numeric_param(params, "limit", limit)} * 3
    """
    return sql, params.values


def build_artist_like_candidates_sql(
    query: str = "",
    limit: int = 20,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the LIKE candidate query for artist search. Pure."""
    params = _Params(form)
    conditions = _like_conditions(params, {"query": ("artists.name", query)})
    sql = f"""
        SELECT DISTINCT artists.id
        FROM artists
        {_where_clause(conditions)}
        LIMIT {_numeric_param(params, "limit", limit)} * 2
    """
    return sql, params.values


def build_artist_search_stats_sql(
    artist_ids=None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """
    Build the statistics query for a set of candidate artists. Pure.

    The ids are bound as a single JSON array rather than an expanded IN list,
    so the SQL text does not vary with the number of candidates.
    """
    params = _Params(form)
    sql = f"""
        SELECT
            artists.id as artist_id,
            artists.name as artist_name,
            COUNT(DISTINCT albums.id) as album_count,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM artists
        LEFT JOIN albums ON albums.artist_id = artists.id
        LEFT JOIN tracks ON tracks.album_id = albums.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        WHERE artists.id IN (
            SELECT value FROM json_each({_json_array_param(params, "artist_ids", artist_ids)})
        )
        GROUP BY artists.id, artists.name
    """
    return sql, params.values


def shape_artists_by_search(rows, query: str = "", limit: int = 20) -> list[dict]:
    """
    Shape candidate artist rows into dicts, re-ranked by fuzzy match. Pure.

    The re-rank stays on this side of the boundary rather than in SQL: SQLite
    returns the candidate set, rapidfuzz decides the order.
    """
    from rapidfuzz import fuzz

    results = [
        {
            "artist_id": row[0],
            "artist_name": row[1],
            "album_count": row[2],
            "track_count": row[3],
            "play_count": row[4],
            "last_played": row[5],
        }
        for row in rows
    ]

    for result in results:
        result["fuzzy_score"] = fuzz.partial_ratio(
            query.lower(), result["artist_name"].lower()
        )

    # Sort by fuzzy score (descending), then by play count
    results.sort(key=lambda x: (x["fuzzy_score"], x["play_count"]), reverse=True)

    return results[:limit]


def get_artists_by_search(
    db: sqlite_utils.Database,
    query: str,
    limit: int = 20,
) -> list[dict]:
    """
    Search artists by name using FTS5 and fuzzy matching.

    Args:
        db: Database connection
        query: Search query for artist name
        limit: Maximum results

    Returns:
        List of dicts with artist information
    """
    # First try FTS5 search if the tracks_fts table exists
    if "tracks_fts" in db.table_names():
        fts_sql, fts_params = build_artist_fts_candidates_sql(
            query=query, limit=limit, form=SQL_FORM_POSITIONAL
        )
        fts_results = db.execute(fts_sql, fts_params).fetchall()
        artist_ids = list(set(row[0] for row in fts_results))
    else:
        # Fallback to LIKE search if FTS5 not available
        artist_ids = []

    # If FTS5 didn't return enough results, supplement with LIKE search
    if len(artist_ids) < limit:
        like_sql, like_params = build_artist_like_candidates_sql(
            query=query, limit=limit, form=SQL_FORM_POSITIONAL
        )
        like_ids = [row[0] for row in db.execute(like_sql, like_params).fetchall()]

        # Combine FTS and LIKE results, removing duplicates
        all_ids = artist_ids + [aid for aid in like_ids if aid not in artist_ids]
        artist_ids = all_ids[: limit * 2]

    if not artist_ids:
        return []

    stats_sql, stats_params = build_artist_search_stats_sql(
        artist_ids, form=SQL_FORM_POSITIONAL
    )
    return shape_artists_by_search(
        db.execute(stats_sql, stats_params).fetchall(), query=query, limit=limit
    )


def _days_in_period(
    db: sqlite_utils.Database,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> int:
    """
    Number of days the requested period spans, for avg_plays_per_day.

    Deliberately left on the executor path rather than folded into the shared
    SQL: with no bounds it has to probe the database for the first and last
    play, which a single-statement canned query cannot do. Naive bounds are
    read as local wall-clock time, matching `_to_utc_iso`.
    """
    now = datetime.now(timezone.utc)
    if since and until:
        if since.tzinfo is None:
            since = since.astimezone()
        if until.tzinfo is None:
            until = until.astimezone()
        return (
            until.astimezone(timezone.utc) - since.astimezone(timezone.utc)
        ).days or 1
    if since:
        if since.tzinfo is None:
            since = since.astimezone()
        return (now - since.astimezone(timezone.utc)).days or 1
    if until:
        if until.tzinfo is None:
            until = until.astimezone()
        return (until.astimezone(timezone.utc) - now).days or 1

    # All time - calculate from first to last play
    date_range = db.execute(
        "SELECT MIN(timestamp), MAX(timestamp) FROM plays"
    ).fetchone()
    if not (date_range[0] and date_range[1]):
        return 1
    first = (
        dateutil.parser.parse(date_range[0])
        if isinstance(date_range[0], str)
        else date_range[0]
    )
    last = (
        dateutil.parser.parse(date_range[1])
        if isinstance(date_range[1], str)
        else date_range[1]
    )
    return (last - first).days or 1


def build_top_artists_sql(
    limit: int = 10,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """
    Build the top-artists query as a single statement. Pure.

    The period total that `percentage` divides by is a scalar subquery rather
    than a second round trip, so one statement serves a canned query. NULLIF
    keeps an empty period from raising; the shaper reads NULL back as zero.
    Note the placeholders are added in the order they appear in the SQL text,
    which is what the positional form requires.
    """
    params = _Params(form)
    total_conditions = _time_bound_conditions(params, since, until)
    row_conditions = _time_bound_conditions(params, since, until)

    sql = f"""
        SELECT
            artists.id as artist_id,
            artists.name as artist_name,
            COUNT(*) as play_count,
            COUNT(*) * 1.0 / NULLIF((
                SELECT COUNT(*) FROM plays {_where_clause(total_conditions)}
            ), 0) * 100 as percentage
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {_where_clause(row_conditions)}
        GROUP BY artists.id, artists.name
        ORDER BY play_count DESC
        LIMIT {_numeric_param(params, "limit", limit)}
    """
    return sql, params.values


def shape_top_artists(rows, days: int = 1) -> list[dict]:
    """Shape top-artist rows into ranked dicts. Pure."""
    return [
        {
            "rank": i + 1,
            "artist_id": row[0],
            "artist_name": row[1],
            "play_count": row[2],
            "percentage": row[3] or 0,
            "avg_plays_per_day": row[2] / days,
        }
        for i, row in enumerate(rows)
    ]


def get_top_artists(
    db: sqlite_utils.Database,
    limit: int = 10,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
) -> list[dict]:
    """
    Get top artists by play count with flexible time range.

    Args:
        db: Database connection
        limit: Number of artists to return
        since: Start date filter
        until: End date filter

    Returns:
        List of dicts with artist statistics including rank and percentage
    """
    sql, params = build_top_artists_sql(
        limit=limit, since=since, until=until, form=SQL_FORM_POSITIONAL
    )
    rows = db.execute(sql, params).fetchall()
    return shape_top_artists(rows, days=_days_in_period(db, since, until))


# The join chain every play-scoped aggregate walks, shared so the scalar-subquery
# total and the ranked set cannot drift apart.
_PLAYS_JOINS = """
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
"""


def build_top_tracks_sql(
    limit: int = 10,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    artist: Optional[str] = None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the top-tracks query as a single statement. Pure. See D4."""
    params = _Params(form)

    def filters():
        conditions = _time_bound_conditions(params, since, until)
        conditions += _like_conditions(params, {"artist": ("artists.name", artist)})
        return _where_clause(conditions)

    total_where = filters()
    row_where = filters()

    sql = f"""
        SELECT
            tracks.id as track_id,
            tracks.title as track_title,
            artists.name as artist_name,
            albums.title as album_title,
            COUNT(*) as play_count,
            COUNT(*) * 1.0 / NULLIF((
                SELECT COUNT(*) {_PLAYS_JOINS} {total_where}
            ), 0) * 100 as percentage
        {_PLAYS_JOINS}
        {row_where}
        GROUP BY tracks.id, tracks.title, artists.name, albums.title
        ORDER BY play_count DESC
        LIMIT {_numeric_param(params, "limit", limit)}
    """
    return sql, params.values


def shape_top_tracks(rows) -> list[dict]:
    """Shape top-track rows into ranked dicts. Pure."""
    return [
        {
            "rank": i + 1,
            "track_id": row[0],
            "track_title": row[1],
            "artist_name": row[2],
            "album_title": row[3],
            "play_count": row[4],
            "percentage": row[5] or 0,
        }
        for i, row in enumerate(rows)
    ]


def get_top_tracks(
    db: sqlite_utils.Database,
    limit: int = 10,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    artist: Optional[str] = None,
) -> list[dict]:
    """
    Get top tracks by play count with flexible time range.

    Args:
        db: Database connection
        limit: Number of tracks to return
        since: Start date filter
        until: End date filter
        artist: Optional artist name filter

    Returns:
        List of dicts with track statistics including rank and percentage
    """
    sql, params = build_top_tracks_sql(
        limit=limit, since=since, until=until, artist=artist,
        form=SQL_FORM_POSITIONAL,
    )
    return shape_top_tracks(db.execute(sql, params).fetchall())


def build_artist_lookup_sql(
    artist_id=None,
    artist_name: Optional[str] = None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """
    Build the artist resolution query. Pure: touches no database.

    Returns up to `_LOOKUP_LIMIT` rows so a caller can detect an ambiguous
    name match rather than silently taking the first.
    """
    params = _Params(form)
    conditions = _exact_conditions(params, {"artist_id": ("id", artist_id)})
    conditions += _like_conditions(params, {"artist_name": ("name", artist_name)})
    sql = f"""
        SELECT id, name
        FROM artists
        {_where_clause(conditions)}
        LIMIT {_LOOKUP_LIMIT}
    """
    return sql, params.values


def build_artist_stats_sql(
    artist_id=None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the per-artist statistics query. Pure: touches no database."""
    params = _Params(form)
    sql = f"""
        SELECT
            COUNT(*) as play_count,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(DISTINCT albums.id) as album_count,
            MIN(plays.timestamp) as first_played,
            MAX(plays.timestamp) as last_played
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        WHERE albums.artist_id = {params.add("artist_id", artist_id)}
    """
    return sql, params.values


def shape_artist_details(artist_row, stats) -> dict:
    """Combine an artist row and its statistics row into a dict. Pure."""
    return {
        "artist_id": artist_row[0],
        "artist_name": artist_row[1],
        "play_count": stats[0],
        "track_count": stats[1],
        "album_count": stats[2],
        "first_played": stats[3],
        "last_played": stats[4],
    }


def get_artist_details(
    db: sqlite_utils.Database,
    artist_id: Optional[int] = None,
    artist_name: Optional[str] = None,
) -> Optional[dict]:
    """
    Get detailed information about a specific artist.

    Args:
        db: Database connection
        artist_id: Artist ID (exact match)
        artist_name: Artist name (partial match if no ID provided)

    Returns:
        Dict with artist details or None if not found
    """
    if not artist_id and not artist_name:
        raise ValueError("Either artist_id or artist_name must be provided")

    # An id resolves on its own; a name is only consulted when no id was given.
    sql, params = build_artist_lookup_sql(
        artist_id=artist_id,
        artist_name=None if artist_id else artist_name,
        form=SQL_FORM_POSITIONAL,
    )
    matches = db.execute(sql, params).fetchall()
    if not matches:
        return None
    if len(matches) > 1:
        # Multiple matches - caller should handle disambiguation
        raise ValueError(f"Multiple artists match '{artist_name}'")
    artist_row = matches[0]

    stats_sql, stats_params = build_artist_stats_sql(
        artist_id=artist_row[0], form=SQL_FORM_POSITIONAL
    )
    return shape_artist_details(
        artist_row, db.execute(stats_sql, stats_params).fetchone()
    )


def build_artist_top_tracks_sql(
    artist_id=None,
    limit: int = 10,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build an artist's top-tracks query. Pure: touches no database."""
    params = _Params(form)
    sql = f"""
        SELECT
            tracks.id as track_id,
            tracks.title as track_title,
            albums.title as album_title,
            COUNT(*) as play_count,
            MAX(plays.timestamp) as last_played
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        WHERE albums.artist_id = {params.add("artist_id", artist_id)}
        GROUP BY tracks.id, tracks.title, albums.title
        ORDER BY play_count DESC
        LIMIT {_numeric_param(params, "limit", limit)}
    """
    return sql, params.values


def shape_artist_top_tracks(rows) -> list[dict]:
    """Shape an artist's top-track rows into dicts. Pure."""
    return [
        {
            "track_id": row[0],
            "track_title": row[1],
            "album_title": row[2],
            "play_count": row[3],
            "last_played": row[4],
        }
        for row in rows
    ]


def get_artist_top_tracks(
    db: sqlite_utils.Database,
    artist_id: int,
    limit: int = 10,
) -> list[dict]:
    """
    Get top tracks for a specific artist.

    Args:
        db: Database connection
        artist_id: Artist ID
        limit: Maximum number of tracks

    Returns:
        List of dicts with track information
    """
    sql, params = build_artist_top_tracks_sql(
        artist_id=artist_id, limit=limit, form=SQL_FORM_POSITIONAL
    )
    return shape_artist_top_tracks(db.execute(sql, params).fetchall())


def build_artist_albums_sql(
    artist_id=None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build an artist's album listing query. Pure: touches no database."""
    params = _Params(form)
    sql = f"""
        SELECT
            albums.id as album_id,
            albums.title as album_title,
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM albums
        LEFT JOIN tracks ON tracks.album_id = albums.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        WHERE albums.artist_id = {params.add("artist_id", artist_id)}
        GROUP BY albums.id, albums.title
        ORDER BY play_count DESC
    """
    return sql, params.values


def shape_artist_albums(rows) -> list[dict]:
    """Shape an artist's album rows into dicts. Pure."""
    return [
        {
            "album_id": row[0],
            "album_title": row[1],
            "track_count": row[2],
            "play_count": row[3],
            "last_played": row[4],
        }
        for row in rows
    ]


def get_artist_albums(
    db: sqlite_utils.Database,
    artist_id: int,
) -> list[dict]:
    """
    Get all albums for a specific artist.

    Args:
        db: Database connection
        artist_id: Artist ID

    Returns:
        List of dicts with album information
    """
    sql, params = build_artist_albums_sql(
        artist_id=artist_id, form=SQL_FORM_POSITIONAL
    )
    return shape_artist_albums(db.execute(sql, params).fetchall())


def build_album_lookup_sql(
    album_id=None,
    album_title: Optional[str] = None,
    artist_name: Optional[str] = None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the album resolution query. Pure: touches no database."""
    params = _Params(form)
    conditions = _exact_conditions(params, {"album_id": ("albums.id", album_id)})
    conditions += _like_conditions(
        params,
        {
            "album_title": ("albums.title", album_title),
            "artist_name": ("artists.name", artist_name),
        },
    )
    sql = f"""
        SELECT albums.id, albums.title, artists.name
        FROM albums
        JOIN artists ON albums.artist_id = artists.id
        {_where_clause(conditions)}
        LIMIT {_LOOKUP_LIMIT}
    """
    return sql, params.values


def build_album_stats_sql(
    album_id=None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the per-album statistics query. Pure: touches no database."""
    params = _Params(form)
    sql = f"""
        SELECT
            COUNT(DISTINCT tracks.id) as track_count,
            COUNT(plays.timestamp) as play_count,
            MIN(plays.timestamp) as first_played,
            MAX(plays.timestamp) as last_played
        FROM albums
        LEFT JOIN tracks ON tracks.album_id = albums.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        WHERE albums.id = {params.add("album_id", album_id)}
    """
    return sql, params.values


def shape_album_details(album_row, stats) -> dict:
    """Combine an album row and its statistics row into a dict. Pure."""
    return {
        "album_id": album_row[0],
        "album_title": album_row[1],
        "artist_name": album_row[2],
        "track_count": stats[0],
        "play_count": stats[1],
        "first_played": stats[2],
        "last_played": stats[3],
    }


def get_album_details(
    db: sqlite_utils.Database,
    album_id: Optional[int] = None,
    album_title: Optional[str] = None,
    artist_name: Optional[str] = None,
) -> Optional[dict]:
    """
    Get detailed information about a specific album.

    Args:
        db: Database connection
        album_id: Album ID (exact match)
        album_title: Album title (partial match if no ID provided)
        artist_name: Artist name for disambiguation

    Returns:
        Dict with album details or None if not found
    """
    if not album_id and not album_title:
        raise ValueError("Either album_id or album_title must be provided")

    # An id resolves on its own; the title and artist filters are only
    # consulted when no id was given.
    sql, params = build_album_lookup_sql(
        album_id=album_id,
        album_title=None if album_id else album_title,
        artist_name=None if album_id else artist_name,
        form=SQL_FORM_POSITIONAL,
    )
    matches = db.execute(sql, params).fetchall()
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"Multiple albums match '{album_title}'")
    album_row = matches[0]

    stats_sql, stats_params = build_album_stats_sql(
        album_id=album_row[0], form=SQL_FORM_POSITIONAL
    )
    return shape_album_details(
        album_row, db.execute(stats_sql, stats_params).fetchone()
    )


def build_album_tracks_sql(
    album_ids=None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """
    Build the album track listing query. Pure: touches no database.

    The album ids are bound as a single JSON array parameter rather than an
    expanded `IN (?, ?, ...)` list, so one static SQL string serves both a
    variable-length CLI call and a canned query, which can only bind scalars.
    """
    params = _Params(form)
    sql = f"""
        SELECT
            tracks.id as track_id,
            tracks.title as track_title,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM tracks
        LEFT JOIN plays ON plays.track_id = tracks.id
        WHERE tracks.album_id IN (
            SELECT value FROM json_each({_json_array_param(params, "album_ids", album_ids)})
        )
        GROUP BY tracks.id, tracks.title
        ORDER BY tracks.id ASC
    """
    return sql, params.values


def shape_album_tracks(rows) -> list[dict]:
    """Shape album track rows into dicts. Pure."""
    return [
        {
            "track_id": row[0],
            "track_title": row[1],
            "play_count": row[2],
            "last_played": row[3],
        }
        for row in rows
    ]


def get_album_tracks(
    db: sqlite_utils.Database,
    album_id: int,
) -> list[dict]:
    """
    Get all tracks for a specific album.

    Args:
        db: Database connection
        album_id: Album ID

    Returns:
        List of dicts with track information
    """
    return get_album_tracks_for_ids(db, [album_id])


def get_album_tracks_for_ids(
    db: sqlite_utils.Database,
    album_ids,
) -> list[dict]:
    """
    Get all tracks across a group of album ids.

    The same album can exist under several synthesized `md5:` ids, and
    `get_albums_list` reports counts spanning that whole alias group. Callers
    that expand a listed album into its tracks must therefore cover every id in
    the group, not just the representative one, or they can show fewer tracks
    than the track_count printed beside it. See design D4.
    """
    sql, params = build_album_tracks_sql(album_ids, form=SQL_FORM_POSITIONAL)
    return shape_album_tracks(db.execute(sql, params).fetchall())


def build_track_lookup_sql(
    track_id=None,
    track_title: Optional[str] = None,
    artist_name: Optional[str] = None,
    album_title: Optional[str] = None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the track resolution query. Pure: touches no database."""
    params = _Params(form)
    conditions = _exact_conditions(params, {"track_id": ("tracks.id", track_id)})
    conditions += _like_conditions(
        params,
        {
            "track_title": ("tracks.title", track_title),
            "artist_name": ("artists.name", artist_name),
            "album_title": ("albums.title", album_title),
        },
    )
    sql = f"""
        SELECT tracks.id, tracks.title, artists.name, albums.title
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        {_where_clause(conditions)}
        LIMIT {_LOOKUP_LIMIT}
    """
    return sql, params.values


def build_track_stats_sql(
    track_id=None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the per-track statistics query. Pure: touches no database."""
    params = _Params(form)
    sql = f"""
        SELECT
            COUNT(*) as play_count,
            MIN(timestamp) as first_played,
            MAX(timestamp) as last_played
        FROM plays
        WHERE track_id = {params.add("track_id", track_id)}
    """
    return sql, params.values


def shape_track_details(track_row, stats) -> dict:
    """Combine a track row and its statistics row into a dict. Pure."""
    return {
        "track_id": track_row[0],
        "track_title": track_row[1],
        "artist_name": track_row[2],
        "album_title": track_row[3],
        "play_count": stats[0],
        "first_played": stats[1],
        "last_played": stats[2],
    }


def get_track_details(
    db: sqlite_utils.Database,
    track_id: Optional[int] = None,
    track_title: Optional[str] = None,
    artist_name: Optional[str] = None,
    album_title: Optional[str] = None,
) -> Optional[dict]:
    """
    Get detailed information about a specific track.

    Args:
        db: Database connection
        track_id: Track ID (exact match)
        track_title: Track title (partial match if no ID provided)
        artist_name: Artist name for disambiguation
        album_title: Album title for disambiguation

    Returns:
        Dict with track details or None if not found
    """
    if not track_id and not track_title:
        raise ValueError("Either track_id or track_title must be provided")

    # An id resolves on its own; the title and disambiguating filters are only
    # consulted when no id was given.
    sql, params = build_track_lookup_sql(
        track_id=track_id,
        track_title=None if track_id else track_title,
        artist_name=None if track_id else artist_name,
        album_title=None if track_id else album_title,
        form=SQL_FORM_POSITIONAL,
    )
    matches = db.execute(sql, params).fetchall()
    if not matches:
        return None
    if len(matches) > 1:
        raise ValueError(f"Multiple tracks match '{track_title}'")
    track_row = matches[0]

    stats_sql, stats_params = build_track_stats_sql(
        track_id=track_row[0], form=SQL_FORM_POSITIONAL
    )
    return shape_track_details(
        track_row, db.execute(stats_sql, stats_params).fetchone()
    )


def build_track_plays_sql(
    track_id=None,
    limit: Optional[int] = None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """
    Build a track's play-history query. Pure: touches no database.

    The limit was previously interpolated into the SQL text; it is bound here.
    A falsy limit means unbounded, preserving the previous behavior.
    """
    params = _Params(form)
    sql = f"""
        SELECT timestamp
        FROM plays
        WHERE track_id = {params.add("track_id", track_id)}
        ORDER BY timestamp DESC
        {_limit_clause(params, limit or None)}
    """
    return sql, params.values


def shape_track_plays(rows) -> list[dict]:
    """Shape play-history rows into dicts. Pure."""
    return [{"timestamp": row[0]} for row in rows]


def get_track_plays(
    db: sqlite_utils.Database,
    track_id: int,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Get play history for a specific track.

    Args:
        db: Database connection
        track_id: Track ID
        limit: Optional limit on number of plays

    Returns:
        List of dicts with play timestamps
    """
    sql, params = build_track_plays_sql(
        track_id=track_id, limit=limit, form=SQL_FORM_POSITIONAL
    )
    return shape_track_plays(db.execute(sql, params).fetchall())


def _track_sort_column(sort: str) -> str:
    """Map a track sort key to its ORDER BY column."""
    if sort == "name":
        return "tracks.title"
    if sort == "recent":
        return "last_played"
    return "play_count"


def build_tracks_list_sql(
    artist: Optional[str] = None,
    artist_id: Optional[str] = None,
    album: Optional[str] = None,
    album_id: Optional[str] = None,
    limit: int = 50,
    sort: str = "plays",
    order: str = "desc",
    min_plays: int = 0,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """Build the track listing query. Pure: touches no database."""
    params = _Params(form)
    conditions = _like_conditions(
        params,
        {"artist": ("artists.name", artist), "album": ("albums.title", album)},
    )
    conditions += _exact_conditions(
        params,
        {"artist_id": ("artists.id", artist_id), "album_id": ("albums.id", album_id)},
    )

    sql = f"""
        SELECT
            tracks.id as track_id,
            tracks.title as track_title,
            artists.name as artist_name,
            albums.title as album_title,
            COUNT(plays.timestamp) as play_count,
            MAX(plays.timestamp) as last_played
        FROM tracks
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
        LEFT JOIN plays ON plays.track_id = tracks.id
        {_where_clause(conditions)}
        GROUP BY tracks.id, tracks.title, artists.name, albums.title
        HAVING play_count >= {_numeric_param(params, "min_plays", min_plays)}
        ORDER BY {_track_sort_column(sort)} {_sort_direction(order)}
        LIMIT {_numeric_param(params, "limit", limit)}
    """
    return sql, params.values


def shape_tracks_list(rows) -> list[dict]:
    """Shape track listing rows into dicts. Pure."""
    return [
        {
            "track_id": row[0],
            "track_title": row[1],
            "artist_name": row[2],
            "album_title": row[3],
            "play_count": row[4],
            "last_played": row[5],
        }
        for row in rows
    ]


def get_tracks_list(
    db: sqlite_utils.Database,
    artist: Optional[str] = None,
    artist_id: Optional[str] = None,
    album: Optional[str] = None,
    album_id: Optional[str] = None,
    limit: int = 50,
    sort: str = "plays",
    order: str = "desc",
    min_plays: int = 0,
) -> list[dict]:
    """
    List tracks with optional filters.

    Args:
        db: Database connection
        artist: Optional artist name filter
        artist_id: Optional artist ID filter
        album: Optional album title filter
        album_id: Optional album ID filter
        limit: Maximum results
        sort: Sort by plays, name, or recent
        order: Sort order (asc or desc)
        min_plays: Minimum play count filter

    Returns:
        List of dicts with track information
    """
    sql, params = build_tracks_list_sql(
        artist=artist,
        artist_id=artist_id,
        album=album,
        album_id=album_id,
        limit=limit,
        sort=sort,
        order=order,
        min_plays=min_plays,
        form=SQL_FORM_POSITIONAL,
    )
    return shape_tracks_list(db.execute(sql, params).fetchall())


def build_top_albums_sql(
    limit: int = 10,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    artist: Optional[str] = None,
    form: str = SQL_FORM_NAMED,
) -> tuple[str, object]:
    """
    Build the top-albums query as a single statement. Pure.

    Uses the same grouping as `build_albums_list_sql`:
    ``albums.title COLLATE NOCASE``, with the artist derived from the group.
    Grouping by ``albums.id`` -- as this query previously did -- splits one
    album's play count across every identifier it was stored under, so a
    heavily played compilation could be ranked below albums it outplays. The
    listing and the ranking have to agree on what an album is. See design D4.
    """
    params = _Params(form)

    def filters():
        conditions = _time_bound_conditions(params, since, until)
        conditions += _like_conditions(params, {"artist": ("artists.name", artist)})
        return _where_clause(conditions)

    total_where = filters()
    row_where = filters()

    sql = f"""
        SELECT
            MAX(albums.id) as album_id,
            group_concat(DISTINCT albums.id) as album_ids,
            albums.title as album_title,
            {_AGGREGATE_ARTIST_NAME} as artist_name,
            COUNT(*) as play_count,
            COUNT(*) * 1.0 / NULLIF((
                SELECT COUNT(*) {_PLAYS_JOINS} {total_where}
            ), 0) * 100 as percentage
        {_PLAYS_JOINS}
        {row_where}
        GROUP BY albums.title COLLATE NOCASE
        ORDER BY play_count DESC
        LIMIT {_numeric_param(params, "limit", limit)}
    """
    return sql, params.values


def shape_top_albums(rows) -> list[dict]:
    """Shape top-album rows into ranked dicts. Pure."""
    return [
        {
            "rank": i + 1,
            "album_id": row[0],
            "album_ids": _split_ids(row[1]),
            "album_title": row[2],
            "artist_name": row[3],
            "play_count": row[4],
            "percentage": row[5] or 0,
        }
        for i, row in enumerate(rows)
    ]


def get_top_albums(
    db: sqlite_utils.Database,
    limit: int = 10,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    artist: Optional[str] = None,
) -> list[dict]:
    """
    Get top albums by play count with flexible time range.

    Args:
        db: Database connection
        limit: Number of albums to return
        since: Start date filter
        until: End date filter
        artist: Optional artist name filter

    Returns:
        List of dicts with album statistics including rank and percentage
    """
    sql, params = build_top_albums_sql(
        limit=limit, since=since, until=until, artist=artist,
        form=SQL_FORM_POSITIONAL,
    )
    return shape_top_albums(db.execute(sql, params).fetchall())
