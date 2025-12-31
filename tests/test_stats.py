"""Tests for stats commands and domain query functions."""

import pytest
import json
import tempfile
import os
from datetime import datetime, timedelta
from click.testing import CliRunner
import sqlite_utils

from scrobbledb import cli
from scrobbledb.domain_queries import (
    get_overview_stats,
    get_monthly_rollup,
    get_yearly_rollup,
    parse_relative_time,
)
from scrobbledb.domain_format import (
    format_output,
)


@pytest.fixture
def runner():
    """Create a Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = sqlite_utils.Database(path)
    yield path, db
    # Cleanup
    db.close()
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def populated_db(temp_db):
    """Create a temporary database with test data."""
    path, db = temp_db

    # Create tables
    db.execute(
        """
        CREATE TABLE artists (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        )
    """
    )
    db.execute(
        """
        CREATE TABLE albums (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            artist_id TEXT NOT NULL,
            FOREIGN KEY (artist_id) REFERENCES artists(id)
        )
    """
    )
    db.execute(
        """
        CREATE TABLE tracks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            album_id TEXT NOT NULL,
            FOREIGN KEY (album_id) REFERENCES albums(id)
        )
    """
    )
    db.execute(
        """
        CREATE TABLE plays (
            timestamp TEXT NOT NULL,
            track_id TEXT NOT NULL,
            PRIMARY KEY (timestamp, track_id),
            FOREIGN KEY (track_id) REFERENCES tracks(id)
        )
    """
    )

    # Insert test data
    # 2 artists
    db.execute("INSERT INTO artists (id, name) VALUES ('a1', 'Artist One')")
    db.execute("INSERT INTO artists (id, name) VALUES ('a2', 'Artist Two')")

    # 3 albums (2 for artist one, 1 for artist two)
    db.execute(
        "INSERT INTO albums (id, title, artist_id) VALUES ('alb1', 'Album One', 'a1')"
    )
    db.execute(
        "INSERT INTO albums (id, title, artist_id) VALUES ('alb2', 'Album Two', 'a1')"
    )
    db.execute(
        "INSERT INTO albums (id, title, artist_id) VALUES ('alb3', 'Album Three', 'a2')"
    )

    # 5 tracks
    db.execute(
        "INSERT INTO tracks (id, title, album_id) VALUES ('t1', 'Track One', 'alb1')"
    )
    db.execute(
        "INSERT INTO tracks (id, title, album_id) VALUES ('t2', 'Track Two', 'alb1')"
    )
    db.execute(
        "INSERT INTO tracks (id, title, album_id) VALUES ('t3', 'Track Three', 'alb2')"
    )
    db.execute(
        "INSERT INTO tracks (id, title, album_id) VALUES ('t4', 'Track Four', 'alb3')"
    )
    db.execute(
        "INSERT INTO tracks (id, title, album_id) VALUES ('t5', 'Track Five', 'alb3')"
    )

    # 10 plays across multiple months/years
    plays = [
        ("2023-06-15T10:00:00", "t1"),
        ("2023-06-16T11:00:00", "t2"),
        ("2023-07-01T12:00:00", "t1"),
        ("2023-12-25T08:00:00", "t3"),
        ("2024-01-01T00:00:00", "t4"),
        ("2024-01-15T14:00:00", "t5"),
        ("2024-02-14T18:00:00", "t1"),
        ("2024-03-10T09:00:00", "t2"),
        ("2024-03-20T16:00:00", "t3"),
        ("2024-03-25T20:00:00", "t4"),
    ]
    for ts, track_id in plays:
        db.execute(
            "INSERT INTO plays (timestamp, track_id) VALUES (?, ?)", [ts, track_id]
        )

    db.conn.commit()
    yield path, db


class TestDomainQueries:
    """Tests for domain query functions."""

    def test_get_overview_stats(self, populated_db):
        """Test overview statistics query."""
        path, db = populated_db
        stats = get_overview_stats(db)

        assert stats["total_scrobbles"] == 10
        assert stats["unique_artists"] == 2
        assert stats["unique_albums"] == 3
        assert stats["unique_tracks"] == 5
        assert stats["first_scrobble"] == "2023-06-15T10:00:00"
        assert stats["last_scrobble"] == "2024-03-25T20:00:00"

    def test_get_overview_stats_empty_db(self, temp_db):
        """Test overview statistics on empty database."""
        path, db = temp_db

        # Create empty tables
        db.execute("CREATE TABLE artists (id TEXT PRIMARY KEY, name TEXT)")
        db.execute(
            "CREATE TABLE albums (id TEXT PRIMARY KEY, title TEXT, artist_id TEXT)"
        )
        db.execute(
            "CREATE TABLE tracks (id TEXT PRIMARY KEY, title TEXT, album_id TEXT)"
        )
        db.execute("CREATE TABLE plays (timestamp TEXT, track_id TEXT)")

        stats = get_overview_stats(db)

        assert stats["total_scrobbles"] == 0
        assert stats["unique_artists"] == 0
        assert stats["unique_albums"] == 0
        assert stats["unique_tracks"] == 0
        assert stats["first_scrobble"] is None
        assert stats["last_scrobble"] is None

    def test_get_monthly_rollup(self, populated_db):
        """Test monthly rollup query."""
        path, db = populated_db
        rows = get_monthly_rollup(db)

        # Should have 5 months: Jun 2023, Jul 2023, Dec 2023, Jan 2024, Feb 2024, Mar 2024
        assert len(rows) == 6

        # Check most recent month (March 2024 - should be first)
        assert rows[0]["year"] == 2024
        assert rows[0]["month"] == 3
        assert rows[0]["scrobbles"] == 3

    def test_get_monthly_rollup_with_limit(self, populated_db):
        """Test monthly rollup with limit."""
        path, db = populated_db
        rows = get_monthly_rollup(db, limit=3)

        assert len(rows) == 3

    def test_get_monthly_rollup_with_since(self, populated_db):
        """Test monthly rollup with since filter."""
        path, db = populated_db
        since = datetime(2024, 1, 1)
        rows = get_monthly_rollup(db, since=since)

        # Should only have months from 2024
        assert len(rows) == 3
        for row in rows:
            assert row["year"] == 2024

    def test_get_yearly_rollup(self, populated_db):
        """Test yearly rollup query."""
        path, db = populated_db
        rows = get_yearly_rollup(db)

        assert len(rows) == 2

        # Check 2024 (most recent, should be first)
        assert rows[0]["year"] == 2024
        assert rows[0]["scrobbles"] == 6

        # Check 2023
        assert rows[1]["year"] == 2023
        assert rows[1]["scrobbles"] == 4

    def test_get_yearly_rollup_with_limit(self, populated_db):
        """Test yearly rollup with limit."""
        path, db = populated_db
        rows = get_yearly_rollup(db, limit=1)

        assert len(rows) == 1
        assert rows[0]["year"] == 2024


class TestParseRelativeTime:
    """Tests for relative time parsing."""

    def test_parse_today(self):
        """Test parsing 'today'."""
        result = parse_relative_time("today")
        now = datetime.now()
        assert result.year == now.year
        assert result.month == now.month
        assert result.day == now.day

    def test_parse_yesterday(self):
        """Test parsing 'yesterday'."""
        result = parse_relative_time("yesterday")
        yesterday = datetime.now() - timedelta(days=1)
        assert result.year == yesterday.year
        assert result.month == yesterday.month
        assert result.day == yesterday.day

    def test_parse_days_ago(self):
        """Test parsing 'N days ago'."""
        result = parse_relative_time("7 days ago")
        expected = datetime.now() - timedelta(days=7)
        # Allow some tolerance for test execution time
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_weeks_ago(self):
        """Test parsing 'N weeks ago'."""
        result = parse_relative_time("2 weeks ago")
        expected = datetime.now() - timedelta(weeks=2)
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_months_ago(self):
        """Test parsing 'N months ago'."""
        result = parse_relative_time("3 months ago")
        assert result is not None
        # Month calculation is more complex, just verify it's in the past
        assert result < datetime.now()

    def test_parse_years_ago(self):
        """Test parsing 'N years ago'."""
        result = parse_relative_time("1 year ago")
        assert result is not None
        now = datetime.now()
        # Should be roughly a year ago
        assert result.year == now.year - 1 or (
            result.year == now.year and result.month < now.month
        )

    def test_parse_last_week(self):
        """Test parsing 'last week'."""
        result = parse_relative_time("last week")
        expected = datetime.now() - timedelta(weeks=1)
        assert abs((result - expected).total_seconds()) < 1

    def test_parse_last_month(self):
        """Test parsing 'last month'."""
        result = parse_relative_time("last month")
        assert result is not None
        assert result < datetime.now()

    def test_parse_last_year(self):
        """Test parsing 'last year'."""
        result = parse_relative_time("last year")
        assert result is not None
        now = datetime.now()
        assert result.year == now.year - 1 or result < now

    def test_parse_iso_date(self):
        """Test parsing ISO 8601 date."""
        result = parse_relative_time("2024-06-15")
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15

    def test_parse_iso_datetime(self):
        """Test parsing ISO 8601 datetime."""
        result = parse_relative_time("2024-06-15T14:30:00")
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 30

    def test_parse_invalid_returns_none(self):
        """Test that invalid strings return None."""
        result = parse_relative_time("invalid date string xyz")
        assert result is None


class TestFormatOutput:
    """Tests for output formatting."""

    def test_format_json(self):
        """Test JSON output format."""
        rows = [{"a": 1, "b": "test"}]
        output = format_output(rows, "json")
        parsed = json.loads(output)
        assert parsed == rows

    def test_format_jsonl(self):
        """Test JSONL output format."""
        rows = [{"a": 1}, {"a": 2}]
        output = format_output(rows, "jsonl")
        lines = output.strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"a": 1}
        assert json.loads(lines[1]) == {"a": 2}

    def test_format_csv(self):
        """Test CSV output format."""
        rows = [{"name": "test", "value": 123}]
        output = format_output(rows, "csv")
        lines = [line.rstrip("\r") for line in output.strip().split("\n")]
        assert lines[0] == "name,value"
        assert lines[1] == "test,123"

    def test_format_csv_no_headers(self):
        """Test CSV output without headers."""
        rows = [{"name": "test", "value": 123}]
        output = format_output(rows, "csv", no_headers=True)
        lines = output.strip().split("\n")
        assert len(lines) == 1
        assert lines[0] == "test,123"

    def test_format_empty_rows(self):
        """Test formatting empty rows."""
        assert format_output([], "json") == "[]"
        assert format_output([], "jsonl") == ""
        assert format_output([], "csv") == ""


class TestStatsCommands:
    """Tests for stats CLI commands."""

    def test_stats_overview(self, runner, populated_db):
        """Test stats overview command."""
        path, db = populated_db
        result = runner.invoke(cli.cli, ["stats", "overview", "-d", path])

        assert result.exit_code == 0
        assert "Scrobble Overview" in result.output
        assert "10" in result.output  # Total scrobbles

    def test_stats_overview_json(self, runner, populated_db):
        """Test stats overview with JSON output."""
        path, db = populated_db
        result = runner.invoke(cli.cli, ["stats", "overview", "-d", path, "-f", "json"])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert isinstance(output, list)
        assert output[0]["total_scrobbles"] == 10

    def test_stats_monthly(self, runner, populated_db):
        """Test stats monthly command."""
        path, db = populated_db
        result = runner.invoke(cli.cli, ["stats", "monthly", "-d", path])

        assert result.exit_code == 0
        assert "Monthly Statistics" in result.output

    def test_stats_monthly_with_limit(self, runner, populated_db):
        """Test stats monthly with limit."""
        path, db = populated_db
        result = runner.invoke(cli.cli, ["stats", "monthly", "-d", path, "-l", "3"])

        assert result.exit_code == 0
        # Should only show 3 months

    def test_stats_monthly_json(self, runner, populated_db):
        """Test stats monthly with JSON output."""
        path, db = populated_db
        result = runner.invoke(cli.cli, ["stats", "monthly", "-d", path, "-f", "json"])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert isinstance(output, list)
        assert len(output) == 6  # 6 months of data

    def test_stats_monthly_csv(self, runner, populated_db):
        """Test stats monthly with CSV output."""
        path, db = populated_db
        result = runner.invoke(cli.cli, ["stats", "monthly", "-d", path, "-f", "csv"])

        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert "year" in lines[0]
        assert "month" in lines[0]
        assert "scrobbles" in lines[0]

    def test_stats_yearly(self, runner, populated_db):
        """Test stats yearly command."""
        path, db = populated_db
        result = runner.invoke(cli.cli, ["stats", "yearly", "-d", path])

        assert result.exit_code == 0
        assert "Yearly Statistics" in result.output

    def test_stats_yearly_json(self, runner, populated_db):
        """Test stats yearly with JSON output."""
        path, db = populated_db
        result = runner.invoke(cli.cli, ["stats", "yearly", "-d", path, "-f", "json"])

        assert result.exit_code == 0
        output = json.loads(result.output)
        assert isinstance(output, list)
        assert len(output) == 2  # 2 years of data

    def test_stats_with_since_filter(self, runner, populated_db):
        """Test stats commands with --since filter."""
        path, db = populated_db
        result = runner.invoke(
            cli.cli, ["stats", "monthly", "-d", path, "-s", "2024-01-01", "-f", "json"]
        )

        assert result.exit_code == 0
        output = json.loads(result.output)
        # Should only include 2024 data
        for row in output:
            assert row["year"] == 2024

    def test_stats_with_until_filter(self, runner, populated_db):
        """Test stats commands with --until filter."""
        path, db = populated_db
        result = runner.invoke(
            cli.cli, ["stats", "monthly", "-d", path, "-u", "2023-12-31", "-f", "json"]
        )

        assert result.exit_code == 0
        output = json.loads(result.output)
        # Should only include 2023 data
        for row in output:
            assert row["year"] == 2023

    def test_stats_missing_database(self, runner):
        """Test stats command with missing database."""
        result = runner.invoke(
            cli.cli, ["stats", "overview", "-d", "/nonexistent/path.db"]
        )

        assert result.exit_code != 0
        assert "Database not found" in result.output

    def test_stats_help(self, runner):
        """Test stats help output."""
        result = runner.invoke(cli.cli, ["stats", "--help"])

        assert result.exit_code == 0
        assert "overview" in result.output
        assert "monthly" in result.output
        assert "yearly" in result.output
