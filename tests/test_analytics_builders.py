"""
Tests for the analytics builders the CLI does not expose yet (task 3.5).

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
import sqlite_utils

from scrobbledb import domain_queries
from scrobbledb.domain_queries import (
    SQL_FORM_POSITIONAL,
    build_artist_discovery_sql,
    build_daily_rollup_sql,
    build_day_of_week_sql,
    build_hour_of_day_sql,
    build_listening_streaks_sql,
    shape_artist_discovery,
    shape_daily_rollup,
    shape_day_of_week,
    shape_hour_of_day,
    shape_listening_streaks,
)

# Artists, albums and tracks.
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

