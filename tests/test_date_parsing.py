"""Tests for parse_relative_time() natural language date parsing (issue #19).

Phase 1 (Red): these cover the existing hand-rolled behavior (regression)
plus the natural-language expressions that parse_relative_time() should
support once Phase 2 swaps its body to use dateparser.
"""

import calendar
from datetime import datetime, timedelta

import pytest

from scrobbledb.domain_queries import parse_relative_time


class TestRegressionCases:
    """Expressions the current hand-rolled implementation already supports."""

    def test_iso_date(self):
        result = parse_relative_time("2024-01-15")
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_today(self):
        result = parse_relative_time("today")
        now = datetime.now()
        assert result.year == now.year
        assert result.month == now.month
        assert result.day == now.day

    def test_yesterday(self):
        result = parse_relative_time("yesterday")
        yesterday = datetime.now() - timedelta(days=1)
        assert result.year == yesterday.year
        assert result.month == yesterday.month
        assert result.day == yesterday.day

    def test_days_ago(self):
        result = parse_relative_time("7 days ago")
        expected = datetime.now() - timedelta(days=7)
        assert abs((result - expected).total_seconds()) < 5

    def test_last_month(self):
        result = parse_relative_time("last month")
        assert result is not None
        assert result < datetime.now()

    def test_empty_string_returns_none(self):
        assert parse_relative_time("") is None

    def test_garbage_returns_none(self):
        assert parse_relative_time("garbage") is None


class TestNaturalLanguageCases:
    """New expressions expected to fail until Phase 2 swaps in dateparser."""

    def test_weekday_name(self):
        result = parse_relative_time("Monday")
        assert result is not None
        assert result.strftime("%A") == "Monday"
        assert result <= datetime.now()

    def test_last_weekday_name(self):
        now = datetime.now()
        result = parse_relative_time("last Tuesday")
        assert result is not None
        assert result.strftime("%A") == "Tuesday"
        assert result.date() < now.date()

        # "last Tuesday" must resolve to the immediately preceding Tuesday,
        # even when today itself is Tuesday (in which case the naive
        # "most recent Tuesday" resolution would otherwise land on today).
        days_since_tuesday = (now.weekday() - 1) % 7 or 7
        expected_date = (now - timedelta(days=days_since_tuesday)).date()
        assert result.date() == expected_date

    def test_last_weekday_name_when_today_matches(self, monkeypatch):
        """"last <weekday>" must not resolve to today.

        dateparser resolves a bare weekday name that matches today to
        today itself (at midnight); simulate that response regardless of
        the actual day the test happens to run on, and confirm
        parse_relative_time() steps back an extra week.
        """
        import scrobbledb.domain_queries as domain_queries

        today_midnight = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        monkeypatch.setattr(
            domain_queries.dateparser, "parse", lambda *args, **kwargs: today_midnight
        )

        result = parse_relative_time("last Tuesday")
        assert result is not None
        assert result.date() == (today_midnight - timedelta(weeks=1)).date()

    def test_explicit_utc_offset_is_not_discarded(self):
        """An explicit offset must shift the instant, not just get dropped.

        "-05:00" and "+00:00" five hours apart must resolve to the same
        instant, not to the same literal wall-clock digits. The result is
        returned timezone-aware (normalized to UTC) so the instant stays
        unambiguous.
        """
        offset_minus_five = parse_relative_time("2024-01-01T00:00:00-05:00")
        equivalent_utc = parse_relative_time("2024-01-01T05:00:00+00:00")
        utc_midnight = parse_relative_time("2024-01-01T00:00:00+00:00")

        assert offset_minus_five is not None
        assert offset_minus_five.tzinfo is not None
        assert offset_minus_five == equivalent_utc
        assert offset_minus_five != utc_midnight

    def test_explicit_offset_disambiguates_dst_fallback_overlap(self):
        """During the US DST fall-back on 2024-11-03, local clocks show
        01:30 twice (first EDT, then EST an hour later). An explicit
        offset must resolve each to its own distinct instant rather than
        collapsing both onto the same ambiguous local wall-clock value.
        """
        first_occurrence = parse_relative_time("2024-11-03T01:30:00-04:00")
        second_occurrence = parse_relative_time("2024-11-03T01:30:00-05:00")

        assert first_occurrence is not None
        assert second_occurrence is not None
        assert first_occurrence != second_occurrence
        assert (second_occurrence - first_occurrence) == timedelta(hours=1)

    def test_n_weeks_ago(self):
        result = parse_relative_time("3 weeks ago")
        expected = datetime.now() - timedelta(weeks=3)
        assert abs((result - expected).total_seconds()) < 5

    def test_month_and_year(self):
        result = parse_relative_time("January 2024")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1

    def test_n_months_ago(self):
        result = parse_relative_time("6 months ago")
        expected = datetime.now() - timedelta(days=6 * 30)
        assert abs((result - expected).days) <= 5


#: A fixed local "now": a Sunday evening, clear of any DST changeover.
#:
#: Evening matters for the story rather than the mechanism. The defect this
#: guards against showed up when the UTC date had already rolled over to the
#: next day -- 20:00 onwards in US Eastern time -- because dateparser, left
#: without a base, resolved weekday names and bare times of day against UTC.
PINNED_NOW = datetime(2025, 6, 15, 21, 30)


@pytest.fixture
def pinned_clock(monkeypatch):
    """
    Pin the clock parse_relative_time reads, and only that clock.

    dateparser's own clock is deliberately left alone. That is what makes
    these tests deterministic in both directions: with the fix, every result
    follows the pinned instant; without it, dateparser reads the real clock,
    which is nowhere near 2025-06-15, so the tests fail on every run instead
    of only during the evening window the original test happened to catch.
    """
    import scrobbledb.domain_queries as domain_queries

    class PinnedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is None, "parse_relative_time reads a naive local clock"
            return PINNED_NOW

    monkeypatch.setattr(domain_queries, "datetime", PinnedDatetime)
    return PINNED_NOW


class TestResolvesAgainstTheLocalClock:
    """Every relative expression is resolved against the same local "now"."""

    WEEKDAYS = list(calendar.day_name)

    def test_all_seven_weekdays_are_covered(self):
        assert len(self.WEEKDAYS) == 7

    @pytest.mark.parametrize("name", list(calendar.day_name))
    def test_a_bare_weekday_is_its_most_recent_occurrence(self, pinned_clock, name):
        """
        Never in the future, and never more than six days back.

        On the named day itself that is today at midnight. Every weekday is
        checked rather than only Monday, because the old failure moved with
        the clock: "Monday" broke on Sunday evenings, "Tuesday" on Monday
        evenings, and so on.
        """
        target = list(calendar.day_name).index(name)
        days_back = (pinned_clock.weekday() - target) % 7
        expected = (pinned_clock - timedelta(days=days_back)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        result = parse_relative_time(name)

        assert result == expected
        assert result <= pinned_clock

    def test_a_bare_time_of_day_is_today(self, pinned_clock):
        """
        "noon" is today's noon, not tomorrow's.

        The same missing base sent bare times of day to the UTC date, so in
        the evening window this resolved to the next day.
        """
        assert parse_relative_time("noon") == pinned_clock.replace(
            hour=12, minute=0, second=0, microsecond=0
        )

    def test_last_weekday_on_that_weekday_steps_back_a_week(self, pinned_clock):
        """
        The "last <weekday>" adjustment reads the same clock dateparser was given.

        On a Sunday, "last Sunday" is a week ago -- which only holds if the
        resolved Sunday and the comparison against "today" agree on what today
        is.
        """
        assert pinned_clock.weekday() == 6, "the pinned instant must be a Sunday"
        assert parse_relative_time("last Sunday") == datetime(2025, 6, 8)

    def test_relative_offsets_follow_the_same_clock(self, pinned_clock):
        """The expressions that already used local time still agree with it."""
        assert parse_relative_time("yesterday") == pinned_clock - timedelta(days=1)
        assert parse_relative_time("3 weeks ago") == pinned_clock - timedelta(weeks=3)
