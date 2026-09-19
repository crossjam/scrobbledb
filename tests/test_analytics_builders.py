"""
Tests for the analytics builders the CLI does not expose yet (tasks 3.5, 3.6).

`tests/test_query_builders.py` already holds these builders to the shared
contract -- purity, named/positional agreement, blank and string-typed
parameters -- by discovering every `build_*` function. What it cannot check is
whether the SQL computes the right thing, because it asserts nothing about
values.

So this file is about values. Every expectation below is worked out by hand
from the fixture and written as a literal; nothing here is produced by running
the query and pasting the result back, which would only assert that the query
does whatever it does.

The fixture is shaped for that: a three-day run and a two-day run of
consecutive listening plus two isolated days (so a streak query has something
to get wrong), a day carrying three plays of two tracks by one artist and a day
carrying two plays by two artists (so `scrobbles`, `unique_tracks` and
`unique_artists` are three different numbers rather than one repeated),
weekday coverage that separates a Monday-first index from SQLite's Sunday-first
one, and an artist whose first play inside a bounded window is not its first
play overall.
"""

from datetime import datetime, timezone

import pytest
import sqlite3
import sqlite_utils

from scrobbledb import domain_queries, lastfm
from scrobbledb.domain_queries import (
    SQL_FORM_POSITIONAL,
    build_artist_discovery_sql,
    build_daily_rollup_sql,
    build_day_of_week_sql,
    build_fts_search_sql,
    build_hour_of_day_sql,
    build_listening_streaks_sql,
    shape_artist_discovery,
    shape_daily_rollup,
    shape_day_of_week,
    shape_fts_search,
    shape_hour_of_day,
    shape_listening_streaks,
)

# Artists, albums and tracks. Titles share tokens across columns on purpose:
# "Three" appears as an artist name, an album title and a track title, which is
# what makes a cross-column full-text search distinguishable from a
# single-column one.
ARTISTS = [
    ("a1", "Artist One"),
    ("a2", "Artist Two"),
    ("a3", "Artist Three"),
]
ALBUMS = [
    ("alb1", "Album One", "a1"),
    ("alb2", "Album Two", "a1"),
    ("alb3", "Album Three", "a2"),
    ("alb4", "Album Four", "a3"),
]
TRACKS = [
    ("t1", "Track One", "alb1"),
    ("t2", "Track Two", "alb1"),
    ("t3", "Track Three", "alb2"),
    ("t4", "Track Four", "alb3"),
    ("t5", "Track Five", "alb3"),
    ("t6", "Track Six", "alb4"),
]

# Ten plays. Laid out as (timestamp, track) with the derived artist/album in
# the comment, since every expectation below is read off this table.
#
#   day         weekday    plays          artists   albums
#   2024-01-01  Monday     t1, t2, t1     a1        alb1        run of 3
#   2024-01-02  Tuesday    t3             a1        alb2         |
#   2024-01-03  Wednesday  t4             a2        alb3         |
#   2024-02-10  Saturday   t5             a2        alb3        run of 2
#   2024-02-11  Sunday     t6, t1         a3, a1    alb4, alb1   |
#   2024-03-05  Tuesday    t1             a1        alb1        alone
#   2024-03-20  Wednesday  t2             a1        alb1        alone
PLAYS = [
    ("2024-01-01T09:00:00+00:00", "t1"),
    ("2024-01-01T09:30:00+00:00", "t2"),
    # The same track a second time on the same day, so a day's play count and
    # its distinct-track count are different numbers.
    ("2024-01-01T21:00:00+00:00", "t1"),
    ("2024-01-02T09:00:00+00:00", "t3"),
    ("2024-01-03T22:00:00+00:00", "t4"),
    ("2024-02-10T09:00:00+00:00", "t5"),
    ("2024-02-11T14:00:00+00:00", "t6"),
    ("2024-02-11T22:00:00+00:00", "t1"),
    ("2024-03-05T09:00:00+00:00", "t1"),
    ("2024-03-20T09:00:00+00:00", "t2"),
]

# A window that starts after the January run and ends between the two isolated
# March days, so it keeps exactly the four plays of 2024-02-10, 2024-02-11 and
# 2024-03-05. Timezone-aware on purpose: `_to_utc_iso` reads a naive datetime
# as local wall-clock time, which would make the boundary depend on the host's
# zone.
WINDOW_SINCE = datetime(2024, 2, 1, tzinfo=timezone.utc)
WINDOW_UNTIL = datetime(2024, 3, 6, tzinfo=timezone.utc)


@pytest.fixture
def analytics_db():
    """The fixture above, in a database carrying the production schema."""
    db = sqlite_utils.Database(memory=True)
    db.execute("CREATE TABLE artists (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    db.execute(
        "CREATE TABLE albums (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " artist_id TEXT NOT NULL REFERENCES artists(id))"
    )
    db.execute(
        "CREATE TABLE tracks (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " album_id TEXT NOT NULL REFERENCES albums(id))"
    )
    db.execute(
        "CREATE TABLE plays (timestamp TEXT NOT NULL,"
        " track_id TEXT NOT NULL REFERENCES tracks(id),"
        " PRIMARY KEY (timestamp, track_id))"
    )

    db["artists"].insert_all({"id": i, "name": n} for i, n in ARTISTS)
    db["albums"].insert_all(
        {"id": i, "title": t, "artist_id": a} for i, t, a in ALBUMS
    )
    db["tracks"].insert_all(
        {"id": i, "title": t, "album_id": a} for i, t, a in TRACKS
    )
    db["plays"].insert_all(
        {"timestamp": ts, "track_id": tid} for ts, tid in PLAYS
    )

    # Through the production seam rather than a hand-written CREATE, so the
    # search tests run against the table `scrobbledb index` actually builds --
    # column names, UNINDEXED ids and all.
    lastfm.setup_fts5(db)
    lastfm.rebuild_fts5(db)
    return db


def both_forms(db, builder, **kwargs):
    """
    Execute a builder in both forms and return the rows they agree on.

    Every test goes through this rather than through one form, so a value
    assertion covers the canned-query rendering and the CLI rendering at once.
    """
    named_sql, named_params = builder(**kwargs)
    pos_sql, pos_params = builder(**kwargs, form=SQL_FORM_POSITIONAL)

    named_rows = db.execute(named_sql, named_params).fetchall()
    pos_rows = db.execute(pos_sql, pos_params).fetchall()
    assert named_rows == pos_rows, "the two forms of this builder disagree"
    return named_rows


class TestDailyRollup:
    def test_one_row_per_day_with_plays(self, analytics_db):
        """Seven days have plays, most recent first."""
        rows = shape_daily_rollup(both_forms(analytics_db, build_daily_rollup_sql))

        assert rows == [
            {
                "day": "2024-03-20",
                "scrobbles": 1,
                "unique_artists": 1,
                "unique_albums": 1,
                "unique_tracks": 1,
            },
            {
                "day": "2024-03-05",
                "scrobbles": 1,
                "unique_artists": 1,
                "unique_albums": 1,
                "unique_tracks": 1,
            },
            {
                "day": "2024-02-11",
                "scrobbles": 2,
                "unique_artists": 2,
                "unique_albums": 2,
                "unique_tracks": 2,
            },
            {
                "day": "2024-02-10",
                "scrobbles": 1,
                "unique_artists": 1,
                "unique_albums": 1,
                "unique_tracks": 1,
            },
            {
                "day": "2024-01-03",
                "scrobbles": 1,
                "unique_artists": 1,
                "unique_albums": 1,
                "unique_tracks": 1,
            },
            {
                "day": "2024-01-02",
                "scrobbles": 1,
                "unique_artists": 1,
                "unique_albums": 1,
                "unique_tracks": 1,
            },
            # Three plays of two tracks by one artist off one album -- the
            # row that separates a play count from every distinct count beside
            # it, including distinct tracks.
            {
                "day": "2024-01-01",
                "scrobbles": 3,
                "unique_artists": 1,
                "unique_albums": 1,
                "unique_tracks": 2,
            },
        ]

    def test_limit_keeps_the_most_recent_days(self, analytics_db):
        """A limit of three against seven days keeps the newest three."""
        rows = shape_daily_rollup(
            both_forms(analytics_db, build_daily_rollup_sql, limit=3)
        )
        assert [row["day"] for row in rows] == [
            "2024-03-20",
            "2024-03-05",
            "2024-02-11",
        ]

    def test_bounds_are_inclusive_on_both_ends(self, analytics_db):
        rows = shape_daily_rollup(
            both_forms(
                analytics_db,
                build_daily_rollup_sql,
                since=WINDOW_SINCE,
                until=WINDOW_UNTIL,
            )
        )
        assert [(row["day"], row["scrobbles"]) for row in rows] == [
            ("2024-03-05", 1),
            ("2024-02-11", 2),
            ("2024-02-10", 1),
        ]

    @pytest.mark.parametrize("limit", [0, -3])
    def test_non_positive_limit_is_refused(self, limit):
        """Mirrors build_monthly_rollup_sql, which this query is the sibling of."""
        with pytest.raises(ValueError, match="limit"):
            build_daily_rollup_sql(limit=limit)


class TestHourOfDay:
    def test_counts_plays_per_hour_ascending(self, analytics_db):
        """
        Six plays at 09:xx, one at 14:00, one at 21:00, two at 22:00.

        The 09:30 play proves the hour is truncated rather than the timestamp
        compared, and the four distinct hours prove the ordering.
        """
        rows = shape_hour_of_day(both_forms(analytics_db, build_hour_of_day_sql))
        assert rows == [
            {"hour": 9, "scrobbles": 6},
            {"hour": 14, "scrobbles": 1},
            {"hour": 21, "scrobbles": 1},
            {"hour": 22, "scrobbles": 2},
        ]

    def test_hours_are_integers_not_zero_padded_text(self, analytics_db):
        """`strftime('%H')` yields '09'; the builder must CAST it."""
        rows = shape_hour_of_day(both_forms(analytics_db, build_hour_of_day_sql))
        assert all(isinstance(row["hour"], int) for row in rows)

    def test_bounds_narrow_the_distribution(self, analytics_db):
        rows = shape_hour_of_day(
            both_forms(
                analytics_db,
                build_hour_of_day_sql,
                since=WINDOW_SINCE,
                until=WINDOW_UNTIL,
            )
        )
        assert rows == [
            {"hour": 9, "scrobbles": 2},
            {"hour": 14, "scrobbles": 1},
            {"hour": 22, "scrobbles": 1},
        ]


class TestDayOfWeek:
    def test_weekday_index_is_monday_first(self, analytics_db):
        """
        0 is Monday, not Sunday.

        SQLite's `strftime('%w')` is Sunday-first, so the fixture is arranged
        to tell the conventions apart: under Sunday-first the counts would come
        back as 0:2, 1:3, 2:2, 3:2, 6:1.
        """
        rows = shape_day_of_week(both_forms(analytics_db, build_day_of_week_sql))
        assert rows == [
            {"weekday": 0, "weekday_name": "Monday", "scrobbles": 3},
            {"weekday": 1, "weekday_name": "Tuesday", "scrobbles": 2},
            {"weekday": 2, "weekday_name": "Wednesday", "scrobbles": 2},
            {"weekday": 5, "weekday_name": "Saturday", "scrobbles": 1},
            {"weekday": 6, "weekday_name": "Sunday", "scrobbles": 2},
        ]

    def test_names_agree_with_the_modules_weekday_names(self, analytics_db):
        """
        Derived from `_WEEKDAY_NAMES` rather than retyped.

        The parser indexes that tuple; if the SQL's CASE and the tuple ever
        disagree on order, the same integer means two different days in the two
        halves of the project.
        """
        rows = shape_day_of_week(both_forms(analytics_db, build_day_of_week_sql))
        assert rows, "fixture produced no weekday rows"
        for row in rows:
            expected = domain_queries._WEEKDAY_NAMES[row["weekday"]].capitalize()
            assert row["weekday_name"] == expected

    def test_bounds_narrow_the_distribution(self, analytics_db):
        rows = shape_day_of_week(
            both_forms(
                analytics_db,
                build_day_of_week_sql,
                since=WINDOW_SINCE,
                until=WINDOW_UNTIL,
            )
        )
        assert rows == [
            {"weekday": 1, "weekday_name": "Tuesday", "scrobbles": 1},
            {"weekday": 5, "weekday_name": "Saturday", "scrobbles": 1},
            {"weekday": 6, "weekday_name": "Sunday", "scrobbles": 2},
        ]


class TestListeningStreaks:
    def test_finds_runs_of_consecutive_days(self, analytics_db):
        """
        Four runs: three days, two days, and two single days.

        Each run's `scrobbles` exceeds its `days`, which is what separates
        summing the plays in the run from counting the days in it. The two
        one-day runs tie on length and so exercise the start-date tiebreak.
        """
        rows = shape_listening_streaks(
            both_forms(analytics_db, build_listening_streaks_sql)
        )
        assert rows == [
            {
                "start_date": "2024-01-01",
                "end_date": "2024-01-03",
                "days": 3,
                "scrobbles": 5,
            },
            {
                "start_date": "2024-02-10",
                "end_date": "2024-02-11",
                "days": 2,
                "scrobbles": 3,
            },
            {
                "start_date": "2024-03-20",
                "end_date": "2024-03-20",
                "days": 1,
                "scrobbles": 1,
            },
            {
                "start_date": "2024-03-05",
                "end_date": "2024-03-05",
                "days": 1,
                "scrobbles": 1,
            },
        ]

    def test_several_plays_on_one_day_do_not_split_a_run(self, analytics_db):
        """
        2024-01-01 has three plays and 2024-02-11 has two.

        A gaps-and-islands query that numbered rows over the plays rather than
        over the distinct days would break both runs apart and report one-day
        streaks instead of a three-day and a two-day one.
        """
        rows = shape_listening_streaks(
            both_forms(analytics_db, build_listening_streaks_sql)
        )
        assert max(row["days"] for row in rows) == 3
        assert len(rows) == 4

    def test_limit_keeps_the_longest_runs(self, analytics_db):
        rows = shape_listening_streaks(
            both_forms(analytics_db, build_listening_streaks_sql, limit=2)
        )
        assert [row["days"] for row in rows] == [3, 2]

    def test_bounds_clip_the_runs_they_cross(self, analytics_db):
        """The window drops the January run entirely and keeps the February one."""
        rows = shape_listening_streaks(
            both_forms(
                analytics_db,
                build_listening_streaks_sql,
                since=WINDOW_SINCE,
                until=WINDOW_UNTIL,
            )
        )
        assert rows == [
            {
                "start_date": "2024-02-10",
                "end_date": "2024-02-11",
                "days": 2,
                "scrobbles": 3,
            },
            {
                "start_date": "2024-03-05",
                "end_date": "2024-03-05",
                "days": 1,
                "scrobbles": 1,
            },
        ]

    @pytest.mark.parametrize("limit", [0, -3])
    def test_non_positive_limit_is_refused(self, limit):
        with pytest.raises(ValueError, match="limit"):
            build_listening_streaks_sql(limit=limit)


class TestArtistDiscovery:
    def test_reports_each_artists_earliest_play_newest_first(self, analytics_db):
        """
        MIN, not MAX, and descending, not ascending.

        With MAX the timestamps would be 2024-03-20, 2024-02-10 and
        2024-02-11; ascending would reverse the order. Both are visible here.
        """
        rows = shape_artist_discovery(
            both_forms(analytics_db, build_artist_discovery_sql)
        )
        assert rows == [
            {
                "artist_id": "a3",
                "artist_name": "Artist Three",
                "first_played": "2024-02-11T14:00:00+00:00",
            },
            {
                "artist_id": "a2",
                "artist_name": "Artist Two",
                "first_played": "2024-01-03T22:00:00+00:00",
            },
            {
                "artist_id": "a1",
                "artist_name": "Artist One",
                "first_played": "2024-01-01T09:00:00+00:00",
            },
        ]

    def test_limit_keeps_the_most_recent_discoveries(self, analytics_db):
        rows = shape_artist_discovery(
            both_forms(analytics_db, build_artist_discovery_sql, limit=2)
        )
        assert [row["artist_id"] for row in rows] == ["a3", "a2"]

    def test_first_play_is_relative_to_the_window(self, analytics_db):
        """
        Inside a window, "first" means first in the window.

        Artist One's earliest play overall is 2024-01-01, outside the window;
        inside it the earliest is 2024-02-11T22:00, which makes Artist One the
        most recent "discovery" of the three rather than the oldest.
        """
        rows = shape_artist_discovery(
            both_forms(
                analytics_db,
                build_artist_discovery_sql,
                since=WINDOW_SINCE,
                until=WINDOW_UNTIL,
            )
        )
        assert rows == [
            {
                "artist_id": "a1",
                "artist_name": "Artist One",
                "first_played": "2024-02-11T22:00:00+00:00",
            },
            {
                "artist_id": "a3",
                "artist_name": "Artist Three",
                "first_played": "2024-02-11T14:00:00+00:00",
            },
            {
                "artist_id": "a2",
                "artist_name": "Artist Two",
                "first_played": "2024-02-10T09:00:00+00:00",
            },
        ]

    @pytest.mark.parametrize("limit", [0, -3])
    def test_non_positive_limit_is_refused(self, limit):
        with pytest.raises(ValueError, match="limit"):
            build_artist_discovery_sql(limit=limit)


def search(db, query, **kwargs):
    """Run the search builder and return its shaped hits."""
    return shape_fts_search(
        both_forms(db, build_fts_search_sql, query=query, **kwargs)
    )


class TestFtsSearch:
    def test_a_single_hit_carries_every_column(self, analytics_db):
        """"Album Two" matches one row, so the whole shape is assertable."""
        assert search(analytics_db, "Album Two") == [
            {
                "track_id": "t3",
                "track_title": "Track Three",
                "album_id": "alb2",
                "album_title": "Album Two",
                "artist_id": "a1",
                "artist_name": "Artist One",
            }
        ]

    def test_album_id_comes_from_albums_not_the_indexed_copy(self, analytics_db):
        """
        The id is the one the rest of the schema agrees on.

        `tracks_fts` keeps its own UNINDEXED `album_id`, and a freshly rebuilt
        index copies the same value, so the two agree and a test against an
        untouched fixture cannot tell which column the query read. Making them
        disagree is what separates the join from the copy.
        """
        analytics_db.execute(
            "UPDATE tracks_fts SET album_id = 'stale-alb' WHERE track_id = 't3'"
        )
        assert analytics_db.execute(
            "SELECT album_id FROM tracks_fts WHERE track_id = 't3'"
        ).fetchone() == ("stale-alb",)

        assert [hit["album_id"] for hit in search(analytics_db, "Album Two")] == [
            "alb2"
        ]

    def test_searches_all_three_indexed_columns(self, analytics_db):
        """
        "Three" appears once per searchable column, in three different rows.

        A search restricted to any one column would return a strict subset of
        these four, so this fails for a single-column query rather than just
        returning fewer rows.
        """
        hits = search(analytics_db, "Three")
        assert sorted(hit["track_id"] for hit in hits) == ["t3", "t4", "t5", "t6"]

    def test_a_term_matches_across_columns_in_one_query(self, analytics_db):
        """"Four" is a track title on one row and an album title on another."""
        hits = search(analytics_db, "Four")
        assert sorted(hit["track_id"] for hit in hits) == ["t4", "t6"]

    def test_multiple_words_are_one_phrase_not_two_terms(self, analytics_db):
        """
        "Artist Three" is the artist name, adjacent; "Album Three" is not.

        As two independent terms the query would also return the Album Three
        rows, so this distinguishes a phrase from an implicit AND.
        """
        hits = search(analytics_db, "Artist Three")
        assert [hit["track_id"] for hit in hits] == ["t6"]

    def test_a_partial_word_matches_as_a_prefix(self, analytics_db):
        """A half-typed word finds the same rows the whole word does."""
        assert search(analytics_db, "Thre") == search(analytics_db, "Three")
        assert search(analytics_db, "Thre")

    def test_a_non_matching_term_returns_no_rows(self, analytics_db):
        assert search(analytics_db, "nosuchtermanywhere") == []

    def test_a_blank_term_returns_no_rows(self, analytics_db):
        """
        The default, and what Datasette sends for an omitted parameter.

        `MATCH ''` is an fts5 syntax error, so this is the case that would
        raise if the term were bound straight through.
        """
        assert search(analytics_db, "") == []

    def test_limit_caps_the_hits(self, analytics_db):
        """Four rows match "Three"; two is fewer, so the cap is observable."""
        assert len(search(analytics_db, "Three", limit=2)) == 2

    def test_the_term_is_bound_under_the_name_the_canned_query_uses(self):
        """The catalog's canned query refers to this parameter as `q`."""
        sql, params = build_fts_search_sql(query="anything")
        assert set(params) == {"q", "limit"}
        assert params["q"] == "anything"
        assert ":q" in sql

    def test_the_term_is_bound_rather_than_embedded_in_the_sql(self):
        """
        The raw term reaches SQLite as a parameter; the quoting is in the SQL.

        The builder must not pre-quote in Python either: the canned-query path
        never runs the builder with the user's term, so any Python-side
        sanitizing would protect the CLI and leave the web surface exposed.
        """
        nasty = "'); DROP TABLE plays; --"
        sql, params = build_fts_search_sql(query=nasty)
        assert nasty not in sql
        assert params["q"] == nasty

    def test_a_quote_heavy_term_is_a_harmless_search(self, analytics_db):
        """It searches for the literal phrase, and the database is untouched."""
        assert search(analytics_db, "'); DROP TABLE plays; --") == []
        assert analytics_db.execute("SELECT COUNT(*) FROM plays").fetchone()[0] == len(
            PLAYS
        )


@pytest.fixture
def tied_db():
    """
    A database where every ordering key before the id ties.

    Two artists share a name *and* a first-play timestamp; two tracks share an
    artist, an album, a title and therefore an FTS rank. Rows are inserted
    highest-id-first, so a query that leaves the order to the scan comes back
    in the opposite order from the one the id tiebreak asks for -- which is
    what makes the assertions below distinguish a total order from a lucky one.
    """
    db = sqlite_utils.Database(memory=True)
    db.execute("CREATE TABLE artists (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    db.execute(
        "CREATE TABLE albums (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " artist_id TEXT NOT NULL REFERENCES artists(id))"
    )
    db.execute(
        "CREATE TABLE tracks (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " album_id TEXT NOT NULL REFERENCES albums(id))"
    )
    db.execute(
        "CREATE TABLE plays (timestamp TEXT NOT NULL,"
        " track_id TEXT NOT NULL REFERENCES tracks(id),"
        " PRIMARY KEY (timestamp, track_id))"
    )

    # One artist under two ids -- an MBID and a synthesized md5: one is the
    # real-world shape of this -- with a play at the very same instant under
    # each, so `first_played` and `artist_name` both tie.
    db["artists"].insert_all(
        [{"id": "zz-artist", "name": "Tied Name"},
         {"id": "aa-artist", "name": "Tied Name"}]
    )
    db["albums"].insert_all(
        [{"id": "zz-album", "title": "Tied Album", "artist_id": "zz-artist"},
         {"id": "aa-album", "title": "Tied Album", "artist_id": "aa-artist"}]
    )
    db["tracks"].insert_all(
        [{"id": "zz-track", "title": "Tied Track", "album_id": "zz-album"},
         {"id": "aa-track", "title": "Tied Track", "album_id": "aa-album"}]
    )
    db["plays"].insert_all(
        [{"timestamp": "2024-05-05T12:00:00+00:00", "track_id": "zz-track"},
         {"timestamp": "2024-05-05T12:00:00+00:00", "track_id": "aa-track"}]
    )

    lastfm.setup_fts5(db)
    lastfm.rebuild_fts5(db)
    return db


def test_artist_discovery_breaks_a_full_tie_on_artist_id(tied_db):
    """
    Same name, same first play: the id decides, so a LIMIT is reproducible.

    Without the id key the two rows are interchangeable to SQLite and
    `limit=1` returns whichever the scan reached first -- here, the one
    inserted first, which is the wrong one.
    """
    rows = shape_artist_discovery(
        both_forms(tied_db, build_artist_discovery_sql)
    )
    assert [row["artist_id"] for row in rows] == ["aa-artist", "zz-artist"]

    capped = shape_artist_discovery(
        both_forms(tied_db, build_artist_discovery_sql, limit=1)
    )
    assert [row["artist_id"] for row in capped] == ["aa-artist"]


def test_fts_search_breaks_a_full_tie_on_track_id(tied_db):
    """
    Identical artist, album, title and rank: the track id decides.

    Two copies of one track -- an album and its reissue, a duplicate import --
    are exactly this, and without the id key a capped search returns an
    arbitrary one of them.
    """
    hits = shape_fts_search(both_forms(tied_db, build_fts_search_sql, query="Tied"))
    assert [hit["track_id"] for hit in hits] == ["aa-track", "zz-track"]

    capped = shape_fts_search(
        both_forms(tied_db, build_fts_search_sql, query="Tied", limit=1)
    )
    assert [hit["track_id"] for hit in capped] == ["aa-track"]


# Terms that are *not* valid fts5 query syntax. Bound to MATCH unmodified each
# one raises -- "fts5: syntax error", "unknown special query", "unterminated
# string" or "no such column" -- which is the whole reason the builder
# neutralizes the term in SQL. Ordinary keystrokes, all of them: a lone
# asterisk, a half-typed quotation, a hyphen, the word "or".
SYNTAX_ERROR_TERMS = [
    "",
    "   ",
    "*",
    "**",
    '"',
    '"""',
    'a"b',
    "NEAR(",
    "(",
    "OR",
    "AND",
    "NOT",
    "^",
    "-",
    "{",
    "}",
    ":",
    "col:",
]

# Terms that are legal fts5 but mean something other than what was typed:
# `OR` and `NEAR` are operators, and a trailing `*` is a prefix marker. The
# builder searches for them literally instead, so none of them can reach the
# query as an operator.
OPERATOR_TERMS = ["beta OR alpha", "Three NEAR Four", "Album OR Artist"]


@pytest.mark.parametrize("term", SYNTAX_ERROR_TERMS)
def test_hostile_term_raises_when_bound_to_match_unmodified(analytics_db, term):
    """
    The control: each of these really does break a bare `tracks_fts MATCH ?`.

    Without it the test below would pass against a search that returned
    nothing for everything, and look protective while protecting nothing.
    """
    with pytest.raises(sqlite3.OperationalError):
        analytics_db.execute(
            "SELECT track_id FROM tracks_fts WHERE tracks_fts MATCH ?", [term]
        ).fetchall()


@pytest.mark.parametrize("term", SYNTAX_ERROR_TERMS)
def test_hostile_term_searches_for_nothing_instead_of_raising(analytics_db, term):
    """
    Anything a user can type is a search, never an error.

    A canned query binds the URL parameter straight to this static SQL, so
    there is no Python between the browser and MATCH to sanitize anything --
    which is why the neutralizing lives in the SQL.
    """
    assert search(analytics_db, term) == []


@pytest.mark.parametrize("term", OPERATOR_TERMS)
def test_operator_words_are_searched_literally(analytics_db, term):
    """No row contains these as a phrase, and none of them acts as an operator."""
    assert search(analytics_db, term) == []


def test_a_stray_asterisk_inside_a_term_is_harmless(analytics_db):
    """"Three*" is legal fts5, but it is treated as text like everything else."""
    assert search(analytics_db, "Three*") == search(analytics_db, "Three")
