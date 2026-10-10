"""
Tests for `domain_queries.days_in_period`, the span behind avg_plays_per_day.

The clock is passed in, so none of these depends on when they run. The function
is shared by the CLI and the MCP tools, and the one case with a history here is
the one that went wrong: a period with only an upper bound used to be measured
as `until - now`, which is negative for any `until` in the past.
"""

from datetime import datetime, timedelta, timezone

import pytest

from scrobbledb.domain_queries import days_in_period, needs_date_range

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
FIRST = "2020-01-01T00:00:00+00:00"
LAST = "2026-09-30T00:00:00+00:00"
RANGE = (FIRST, LAST)


def utc(year, month, day):
    return datetime(year, month, day, tzinfo=timezone.utc)


def test_a_lower_bound_alone_runs_to_now():
    assert days_in_period(utc(2026, 9, 1), None, None, NOW) == 30


def test_both_bounds_span_the_gap_between_them():
    assert days_in_period(utc(2026, 9, 1), utc(2026, 9, 11), None, NOW) == 10


def test_an_upper_bound_alone_runs_from_the_first_play():
    until = utc(2024, 1, 1)
    expected = (until - datetime.fromisoformat(FIRST)).days
    assert expected > 1000, "fixture span too short to tell the formulas apart"
    assert days_in_period(None, until, RANGE, NOW) == expected


def test_an_upper_bound_alone_does_not_depend_on_now():
    until = utc(2024, 1, 1)
    earlier = days_in_period(None, until, RANGE, NOW)
    later = days_in_period(None, until, RANGE, NOW + timedelta(days=900))
    assert earlier == later > 0


def test_no_bounds_runs_from_the_first_play_to_the_last():
    assert days_in_period(None, None, RANGE, NOW) == (
        datetime.fromisoformat(LAST) - datetime.fromisoformat(FIRST)
    ).days


@pytest.mark.parametrize(
    "since, until",
    [
        (None, utc(2019, 1, 1)),  # before the first play
        (utc(2026, 9, 11), utc(2026, 9, 1)),  # reversed
        (utc(2026, 9, 30), utc(2026, 9, 30)),  # empty
        (utc(2027, 1, 1), None),  # in the future
    ],
)
def test_a_period_is_never_less_than_a_day(since, until):
    assert days_in_period(since, until, RANGE, NOW) == 1


@pytest.mark.parametrize("since, until", [(None, None), (None, utc(2024, 1, 1))])
def test_an_empty_history_is_one_day(since, until):
    assert days_in_period(since, until, None, NOW) == 1
    assert days_in_period(since, until, (None, None), NOW) == 1


def test_a_naive_bound_is_local_wall_clock():
    naive = datetime(2026, 9, 1)
    assert days_in_period(naive, None, None, NOW) == (
        NOW - naive.astimezone().astimezone(timezone.utc)
    ).days


@pytest.mark.parametrize(
    "since, until, expected",
    [
        (None, None, True),
        (None, utc(2024, 1, 1), True),
        (utc(2024, 1, 1), None, False),
        (utc(2024, 1, 1), utc(2024, 2, 1), False),
    ],
)
def test_the_date_range_is_needed_whenever_there_is_no_lower_bound(
    since, until, expected
):
    assert needs_date_range(since, until) is expected
    # And the claim is true: with the range withheld the answer is the fallback
    # exactly when the range was needed.
    withheld = days_in_period(since, until, None, NOW)
    given = days_in_period(since, until, RANGE, NOW)
    assert (withheld != given) is expected or withheld == given == 1


def test_a_naive_now_is_local_wall_clock_like_every_other_input():
    """Used to raise TypeError subtracting a naive instant from an aware one."""
    naive_now = NOW.astimezone().replace(tzinfo=None)
    assert naive_now.tzinfo is None
    assert days_in_period(utc(2026, 9, 1), None, None, naive_now) == days_in_period(
        utc(2026, 9, 1), None, None, NOW
    )
