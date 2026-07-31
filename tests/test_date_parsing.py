"""Tests for parse_relative_time() natural language date parsing (issue #19).

Phase 1 (Red): these cover the existing hand-rolled behavior (regression)
plus the natural-language expressions that parse_relative_time() should
support once Phase 2 swaps its body to use dateparser.
"""

from datetime import datetime, timedelta

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
        result = parse_relative_time("last Tuesday")
        assert result is not None
        assert result.strftime("%A") == "Tuesday"
        assert result < datetime.now()

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
