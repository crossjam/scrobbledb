"""
Contract tests for the shared SQL builders.

The builders in `domain_queries` are the single source of SQL for three
consumers: the CLI, the Datasette canned queries, and the MCP tools. Two
properties have to hold for that sharing to be safe, and both are enforced
here by discovering every `build_*` function rather than by listing them, so a
new builder is covered the moment it is added.

1. **Builders are pure.** They take no database argument and touch no
   connection, so the plugin can execute their output through Datasette's
   connection -- with `query_only`, the time limit, and the row cap applied --
   instead of opening its own.

2. **Named placeholders come with a mapping.** Python's sqlite3 requires a dict
   for named parameters. Passing a sequence is a DeprecationWarning on 3.13 and
   a ProgrammingError on 3.14, which this project's CI matrix covers, so the
   3.13 job has to fail on it rather than waiting for the 3.14 job.

See design D4 of the add-datasette-web-server change.
"""

import inspect
import re
import sqlite3
import warnings

import pytest
import sqlite_utils

from scrobbledb import domain_queries

# Matches a named placeholder (":since"), which is also how the guard idiom
# ":since = ''" spells it. Bare ":" never appears otherwise in this SQL.
_PLACEHOLDER_RE = re.compile(r":(\w+)")

# Builders whose defaults do not produce executable SQL on their own. The FTS
# MATCH expression needs a term -- "artist_name:*" is not a valid FTS5 query --
# and the id-set builders need something in their JSON array to be meaningful.
_EXECUTION_ARGS = {
    "build_artist_fts_candidates_sql": {"query": "alpha"},
    "build_artist_search_stats_sql": {"artist_ids": ["art-1"]},
    "build_album_tracks_sql": {"album_ids": ["alb-1"]},
}


def _builders():
    """Every public builder in domain_queries, discovered by name."""
    found = [
        (name, fn)
        for name, fn in inspect.getmembers(domain_queries, inspect.isfunction)
        if name.startswith("build_") and fn.__module__ == domain_queries.__name__
    ]
    assert found, "no builders discovered - has the naming convention changed?"
    return found


BUILDERS = _builders()
BUILDER_IDS = [name for name, _ in BUILDERS]


@pytest.fixture
def populated_db():
    """A minimal database carrying the full schema, including tracks_fts."""
    db = sqlite_utils.Database(memory=True)
    db.execute("CREATE TABLE artists (id TEXT PRIMARY KEY, name TEXT)")
    db.execute(
        "CREATE TABLE albums (id TEXT PRIMARY KEY, title TEXT, artist_id TEXT)"
    )
    db.execute(
        "CREATE TABLE tracks (id TEXT PRIMARY KEY, title TEXT, album_id TEXT)"
    )
    db.execute(
        "CREATE TABLE plays (track_id TEXT, timestamp TEXT,"
        " PRIMARY KEY (timestamp, track_id))"
    )
    db.execute(
        "CREATE VIRTUAL TABLE tracks_fts USING fts5"
        " (track_id, track_title, artist_id, artist_name, album_title)"
    )

    db["artists"].insert({"id": "art-1", "name": "Artist Alpha"})
    db["albums"].insert({"id": "alb-1", "title": "Album One", "artist_id": "art-1"})
    db["tracks"].insert({"id": "trk-1", "title": "Track One", "album_id": "alb-1"})
    db["plays"].insert(
        {"track_id": "trk-1", "timestamp": "2024-01-01T12:00:00+00:00"}
    )
    db.execute(
        "INSERT INTO tracks_fts (track_id, track_title, artist_id, artist_name,"
        " album_title) VALUES ('trk-1', 'Track One', 'art-1', 'Artist Alpha',"
        " 'Album One')"
    )
    return db


@pytest.mark.parametrize("name,builder", BUILDERS, ids=BUILDER_IDS)
def test_builder_needs_no_database(name, builder):
    """A builder is callable with no arguments at all -- no db, no connection."""
    signature = inspect.signature(builder)
    assert "db" not in signature.parameters, f"{name} takes a database argument"

    sql, params = builder()
    assert isinstance(sql, str) and sql.strip()
    assert isinstance(params, dict), f"{name} returned {type(params).__name__}"


@pytest.mark.parametrize("name,builder", BUILDERS, ids=BUILDER_IDS)
def test_named_params_match_placeholders_exactly(name, builder):
    """
    The dict's keys are exactly the placeholders in the SQL.

    A missing key is a runtime error; a surplus key is dead weight that hides a
    renamed placeholder. Both are caught by requiring equality.
    """
    sql, params = builder()
    in_sql = set(_PLACEHOLDER_RE.findall(sql))
    assert in_sql == set(params), (
        f"{name}: SQL has {sorted(in_sql)}, params have {sorted(params)}"
    )


@pytest.mark.parametrize("name,builder", BUILDERS, ids=BUILDER_IDS)
def test_named_form_executes_without_deprecation(name, builder, populated_db):
    """
    Every builder's named output executes, with DeprecationWarning fatal.

    This is the 3.14 guard: binding a sequence to named placeholders warns on
    3.13 and raises there, so turning the warning into an error makes the 3.13
    job catch what would otherwise only surface on 3.14.
    """
    sql, params = builder(**_EXECUTION_ARGS.get(name, {}))

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        populated_db.execute(sql, params).fetchall()


@pytest.mark.parametrize("name,builder", BUILDERS, ids=BUILDER_IDS)
def test_positional_form_executes_and_agrees_with_named(name, builder, populated_db):
    """
    The two forms are renderings of one query, so they must return the same rows.

    This is what lets the CLI keep the index while canned queries keep static
    SQL -- if the forms could disagree, they would be two queries.
    """
    kwargs = _EXECUTION_ARGS.get(name, {})
    named_sql, named_params = builder(**kwargs)
    pos_sql, pos_params = builder(
        **kwargs, form=domain_queries.SQL_FORM_POSITIONAL
    )
    assert isinstance(pos_params, list), f"{name} positional params must be a list"

    named_rows = populated_db.execute(named_sql, named_params).fetchall()
    pos_rows = populated_db.execute(pos_sql, pos_params).fetchall()
    assert named_rows == pos_rows, f"{name}: forms disagree"


def test_no_builder_or_shaper_touches_a_connection():
    """
    Builders and shapers must not reach the database.

    Checked against the functions' own bytecode names rather than the module's
    imports, since `domain_queries` legitimately imports sqlite_utils for its
    executors.
    """
    forbidden = {"execute", "table_names", "fetchall", "fetchone", "cursor"}
    offenders = []

    for name, fn in inspect.getmembers(domain_queries, inspect.isfunction):
        if fn.__module__ != domain_queries.__name__:
            continue
        if not (name.startswith("build_") or name.startswith("shape_")):
            continue
        used = set(fn.__code__.co_names)
        if used & forbidden:
            offenders.append((name, sorted(used & forbidden)))

    assert offenders == [], f"pure functions reaching the database: {offenders}"


def test_positional_form_omits_absent_bounds():
    """
    The positional form renders only the bounds it was given.

    This is the whole point of having two forms: an absent bound leaves no
    predicate behind, so SQLite can still use the plays(timestamp, track_id)
    index. The named form, by contrast, always carries both.
    """
    sql, params = domain_queries.build_yearly_rollup_sql(
        form=domain_queries.SQL_FORM_POSITIONAL
    )
    assert "timestamp" not in sql.split("GROUP BY")[0].split("JOIN")[-1]
    assert params == []

    named_sql, named_params = domain_queries.build_yearly_rollup_sql()
    assert ":since" in named_sql and ":until" in named_sql
    assert named_params["since"] == "" and named_params["until"] == ""


def test_guarded_and_unguarded_forms_select_the_same_rows(populated_db):
    """A supplied bound filters identically whichever form renders it."""
    from datetime import datetime

    since = datetime(2024, 1, 1)
    named_sql, named_params = domain_queries.build_monthly_rollup_sql(since=since)
    pos_sql, pos_params = domain_queries.build_monthly_rollup_sql(
        since=since, form=domain_queries.SQL_FORM_POSITIONAL
    )

    assert (
        populated_db.execute(named_sql, named_params).fetchall()
        == populated_db.execute(pos_sql, pos_params).fetchall()
    )


def test_limit_is_bound_not_interpolated():
    """
    LIMIT arrives as a parameter, never as SQL text.

    get_track_plays previously interpolated it.
    """
    sql, params = domain_queries.build_track_plays_sql(track_id="trk-1", limit=5)
    assert "LIMIT :limit" in sql
    assert params["limit"] == 5
    assert "LIMIT 5" not in sql


def test_unknown_sort_order_is_refused():
    """
    A sort direction outside the whitelist raises rather than reaching SQL.

    The CLI screens this with click.Choice, but MCP callers do not.
    """
    with pytest.raises(ValueError, match="sort order"):
        domain_queries.build_albums_list_sql(order="; DROP TABLE plays --")


def test_unknown_sql_form_is_refused():
    with pytest.raises(ValueError, match="unknown SQL form"):
        domain_queries.build_overview_stats_sql(form="qmark")


def test_negative_limit_sentinel_means_unbounded(populated_db):
    """
    The named form's "no limit" sentinel really is unbounded in SQLite.

    The static named SQL always carries LIMIT :limit, so an absent limit has to
    be expressible as a value rather than by dropping the clause.
    """
    db = populated_db
    for i in range(2, 6):
        db["plays"].insert(
            {"track_id": "trk-1", "timestamp": f"2024-01-0{i}T12:00:00+00:00"}
        )

    sql, params = domain_queries.build_track_plays_sql(track_id="trk-1")
    assert params["limit"] == -1
    assert len(db.execute(sql, params).fetchall()) == 5


def test_builders_bind_values_rather_than_embedding_them():
    """
    A quote-heavy filter value lands in the parameters, not in the SQL text.

    Not a claim that string building is safe -- a claim that these builders do
    not do it for user-supplied values.
    """
    nasty = "'; DROP TABLE plays; --"
    sql, params = domain_queries.build_plays_with_filters_sql(artist=nasty)

    assert nasty not in sql
    assert nasty in params.values()

    # And it executes as an ordinary, harmless filter.
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE artists (id TEXT PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE albums (id TEXT PRIMARY KEY, title TEXT, artist_id TEXT)")
    conn.execute("CREATE TABLE tracks (id TEXT PRIMARY KEY, title TEXT, album_id TEXT)")
    conn.execute("CREATE TABLE plays (track_id TEXT, timestamp TEXT)")
    assert conn.execute(sql, params).fetchall() == []
    assert conn.execute("SELECT COUNT(*) FROM plays").fetchone()[0] == 0
