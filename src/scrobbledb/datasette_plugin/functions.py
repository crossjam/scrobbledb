"""
Custom SQL functions registered on every Datasette connection.

Each one exposes logic that otherwise lives only in Python, so a canned query
or an ad hoc SQL statement can express scrobbledb's own time and naming
semantics. See design D6.

The functions are deliberately thin wrappers over the CLI's implementations
rather than reimplementations: `parse_when` must agree with `--since`/`--until`
to the exact UTC instant, or a browser form field and a command line with the
same text would select different rows.
"""

import functools
import time
from typing import Optional

from datasette import hookimpl

from scrobbledb import domain_format, domain_queries

# `dateparser` costs milliseconds per call, and SQLite may choose to evaluate a
# function in a WHERE clause once per row. The cache is what makes
# `parse_when` safe to put in a predicate; the `:since = ''` guard of design D5
# keeps it down to a handful of distinct arguments per query.
_PARSE_CACHE_SIZE = 512

# The cache key carries a coarse clock reading as well as the text, because
# relative expressions resolve against "now". Keyed on text alone, a
# long-running `serve` process would answer "yesterday" with whatever yesterday
# meant when the process started, and every later request would silently select
# the wrong range.
#
# One second is short enough that no bound is meaningfully stale -- the CLI's
# own `--since` reads the clock at an arbitrary instant anyway -- and long
# enough to keep the per-row protection the cache exists for, since a statement
# evaluating this function thousands of times does so well within a second.
_CACHE_GRANULARITY_SECONDS = 1


def _cache_generation() -> int:
    """
    Current cache generation, changing once per `_CACHE_GRANULARITY_SECONDS`.

    Factored out as a function so tests can pin it and observe cache behavior
    deterministically.
    """
    return int(time.time()) // _CACHE_GRANULARITY_SECONDS


@functools.lru_cache(maxsize=_PARSE_CACHE_SIZE)
def _parse_when_cached(text: str, _generation: int) -> Optional[str]:
    """
    Resolve one time expression to a UTC ISO 8601 string, or None.

    `_generation` is not used in the body; it is part of the key so a new
    generation forces a fresh parse. See `_cache_generation`.
    """
    parsed = domain_queries.parse_relative_time(text)
    if parsed is None:
        return None
    return domain_queries._to_utc_iso(parsed)


def parse_when(text) -> Optional[str]:
    """
    Resolve a human time expression to the UTC ISO 8601 form stored in
    `plays.timestamp`, so it can be compared directly.

    Accepts what `--since` and `--until` accept -- "yesterday", "last march",
    "3 weeks ago", "2024-01-01" -- and follows `_to_utc_iso` in reading a naive
    datetime as *local* wall clock. The import path's `parse_timestamp` reads
    naive input as UTC instead; this function reproduces the CLI filters, not
    the importer (design D6).

    Returns NULL rather than raising on input it cannot parse. A canned query
    passes the empty string for a bound the user left blank, and a raising
    function would make every such query fail instead of matching everything.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    if not text.strip():
        return None
    try:
        return _parse_when_cached(text, _cache_generation())
    except Exception:
        # A SQL function that raises aborts the whole statement. Anything the
        # parser can throw on hostile input becomes NULL instead.
        return None


def fuzz_partial_ratio(a, b) -> Optional[float]:
    """
    Fuzzy similarity between two strings, 0-100.

    The same scorer `artists search` re-ranks with, so SQL can order by
    closeness of match the way the CLI does.
    """
    if a is None or b is None:
        return None
    from rapidfuzz import fuzz

    return fuzz.partial_ratio(str(a).lower(), str(b).lower())


def month_name(month) -> Optional[str]:
    """Abbreviated month name for a month number, matching the CLI's tables."""
    if month is None:
        return None
    try:
        return domain_format._get_month_name(int(month))
    except (TypeError, ValueError):
        return None


def fmt_ts(ts) -> Optional[str]:
    """Render a stored timestamp the way the CLI renders it."""
    if ts is None:
        return None
    return domain_format.format_timestamp(ts)


#: Registered on every connection, name -> (arity, implementation, deterministic).
#:
#: `deterministic` asserts SQLite's contract: the same inputs *always* give the
#: same answer, for every accepted input rather than the expected ones. Two of
#: these qualify.
#:
#: `parse_when` does not -- it reads the wall clock, which is the whole point of
#: its cache generation.
#:
#: `fmt_ts` does not either, which is less obvious: it defers to
#: `dateutil.parser.parse`, which fills missing components from today's date, so
#: `fmt_ts('12:00')` and `fmt_ts('March')` both change from one day to the next.
#: It is deterministic for the full ISO timestamps the schema stores, but a SQL
#: function accepts whatever an ad hoc query passes it, and the contract covers
#: all of them.
#:
#: Both forgo the optimizer's hoist, which costs nothing that matters: neither
#: is used in a predicate by any builder.
SQL_FUNCTIONS = {
    "parse_when": (1, parse_when, False),
    "fuzz_partial_ratio": (2, fuzz_partial_ratio, True),
    "month_name": (1, month_name, True),
    "fmt_ts": (1, fmt_ts, False),
}


@hookimpl
def prepare_connection(conn):
    """
    Register scrobbledb's SQL functions on a Datasette connection.

    Only the genuinely deterministic functions carry `deterministic=True`.
    `parse_when` reads the wall clock, so claiming determinism for it would be
    false, and the flag would not buy what it appears to: measured, it permits
    a hoist for a single call site with a bound argument (28 invocations to 1)
    but still yields two resolutions for two call sites and one per row for a
    column-valued argument. It is an optimizer permission, not a guarantee of
    single evaluation.

    A canned query that needs one stable bound per statement must therefore say
    so in SQL -- resolving `parse_when` once in a materialized CTE -- rather
    than relying on this flag. See design D5.
    """
    for name, (arity, fn, deterministic) in SQL_FUNCTIONS.items():
        conn.create_function(name, arity, fn, deterministic=deterministic)
