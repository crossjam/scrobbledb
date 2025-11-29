"""Tests for CLI commands and fixes."""

import pytest
import json
import tempfile
import os
from click.testing import CliRunner
from unittest.mock import Mock, patch
import sqlite_utils
import datetime as dt
from datetime import timezone

from scrobbledb import cli


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
def temp_auth():
    """Create a temporary auth file for testing."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    auth_data = {
        "lastfm_network": "lastfm",
        "lastfm_username": "testuser",
        "lastfm_api_key": "test_api_key",
        "lastfm_shared_secret": "test_secret",
        "lastfm_session_key": "test_session_key",
    }
    with open(path, "w") as f:
        json.dump(auth_data, f)
    yield path
    # Cleanup
    if os.path.exists(path):
        os.unlink(path)


class TestTableExistsFix:
    """Tests for the table.exists() method call fix.

    This verifies the fix from commit b18493b where db["table"].exists
    was changed to db["table"].exists() to properly check table existence.
    """

    def test_ingest_empty_database_no_plays_table(self, runner, temp_db, temp_auth):
        """Test ingest command on empty database without plays table.

        This tests the fix for db["plays"].exists → db["plays"].exists()
        Previously, checking .exists as a property would always return True
        (the method object exists), causing the code to query a non-existent table.
        """
        db_path, db = temp_db

        # Mock the network and user objects
        mock_user = Mock()
        mock_user.get_playcount.return_value = 0

        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=0):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=[]):
                    # Run ingest on empty database
                    result = runner.invoke(
                        cli.cli,
                        ["ingest", db_path, "-a", temp_auth, "--dry-run"],
                    )

                    # Should succeed without error
                    assert result.exit_code == 0, f"Command failed: {result.output}"

                    # Should not try to query non-existent plays table
                    assert "no such table: plays" not in result.output.lower()

    def test_ingest_database_with_empty_plays_table(self, runner, temp_db, temp_auth):
        """Test ingest command on database with empty plays table.

        This tests the case where the plays table exists but is empty,
        so max(timestamp) returns NULL, making since_date None.
        """
        db_path, db = temp_db

        # Create empty plays table
        db.execute("""
            CREATE TABLE plays (
                track_id TEXT,
                timestamp TEXT,
                PRIMARY KEY (timestamp, track_id)
            )
        """)

        # Mock the network and user objects
        mock_user = Mock()
        mock_user.get_playcount.return_value = 0

        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=0):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=[]):
                    # Run ingest
                    result = runner.invoke(
                        cli.cli,
                        ["ingest", db_path, "-a", temp_auth, "--dry-run"],
                    )

                    # Should succeed without AttributeError
                    assert result.exit_code == 0, f"Command failed: {result.output}"
                    assert "AttributeError" not in result.output
                    assert "'NoneType' object has no attribute 'isoformat'" not in result.output

    def test_index_no_tracks_table(self, runner, temp_db):
        """Test index command when tracks table doesn't exist.

        This tests the fix for db["tracks"].exists → db["tracks"].exists()
        Previously would incorrectly think the table exists and try to query it.
        """
        db_path, db = temp_db

        # Run index command on empty database
        result = runner.invoke(cli.cli, ["index", db_path])

        # Should fail gracefully with helpful error message
        assert result.exit_code != 0
        assert "No tracks found" in result.output or "not found" in result.output.lower()

        # Should not crash with SQL error
        assert "no such table: tracks" not in result.output.lower()


class TestSinceDateIsofixFormat:
    """Tests for the since_date.isoformat() NoneType fix.

    This verifies the fix where since_date could be None when:
    1. No --since-date is provided via CLI
    2. The plays table doesn't exist OR is empty (max(timestamp) returns NULL)
    """

    def test_ingest_no_since_date_no_plays_table(self, runner, temp_db, temp_auth):
        """Test ingest without --since-date and no plays table.

        Should display 'Fetching all scrobbles' instead of crashing.
        """
        db_path, db = temp_db

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=0):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=[]):
                    result = runner.invoke(
                        cli.cli,
                        ["ingest", db_path, "-a", temp_auth, "--dry-run"],
                    )

                    assert result.exit_code == 0, f"Command failed: {result.output}"
                    assert "Fetching all scrobbles" in result.output
                    assert "AttributeError" not in result.output

    def test_ingest_no_since_date_empty_plays_table(self, runner, temp_db, temp_auth):
        """Test ingest without --since-date and empty plays table.

        max(timestamp) returns NULL, so since_date becomes None.
        Should display 'Fetching all scrobbles' instead of crashing.
        """
        db_path, db = temp_db

        # Create empty plays table
        db.execute("""
            CREATE TABLE plays (
                track_id TEXT,
                timestamp TEXT,
                PRIMARY KEY (timestamp, track_id)
            )
        """)

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=0):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=[]):
                    result = runner.invoke(
                        cli.cli,
                        ["ingest", db_path, "-a", temp_auth, "--dry-run"],
                    )

                    assert result.exit_code == 0, f"Command failed: {result.output}"
                    assert "Fetching all scrobbles" in result.output
                    assert "AttributeError" not in result.output
                    assert "'NoneType' object has no attribute 'isoformat'" not in result.output

    def test_ingest_with_explicit_since_date(self, runner, temp_db, temp_auth):
        """Test ingest with explicit --since-date flag.

        Should display the provided date in the output.
        """
        db_path, db = temp_db

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=0):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=[]):
                    result = runner.invoke(
                        cli.cli,
                        [
                            "ingest",
                            db_path,
                            "-a",
                            temp_auth,
                            "--since-date",
                            "2024-01-01",
                            "--dry-run",
                        ],
                    )

                    assert result.exit_code == 0, f"Command failed: {result.output}"
                    assert "Fetching scrobbles since:" in result.output
                    assert "2024-01-01" in result.output

    def test_ingest_with_existing_plays(self, runner, temp_db, temp_auth):
        """Test ingest with existing plays in database.

        Should fetch max(timestamp) from plays table and use it as since_date.
        """
        db_path, db = temp_db

        # Create plays table with data
        db.execute("""
            CREATE TABLE plays (
                track_id TEXT,
                timestamp TEXT,
                PRIMARY KEY (timestamp, track_id)
            )
        """)
        db.execute("""
            INSERT INTO plays (track_id, timestamp)
            VALUES ('track-1', '2024-01-15T12:00:00')
        """)
        # Commit changes so they're visible to other connections
        db.conn.commit()

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=0):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=[]):
                    result = runner.invoke(
                        cli.cli,
                        ["ingest", db_path, "-a", temp_auth, "--dry-run"],
                    )

                    assert result.exit_code == 0, f"Command failed: {result.output}"
                    assert "Fetching scrobbles since:" in result.output
                    assert "2024-01-15" in result.output

    def test_ingest_with_until_date(self, runner, temp_db, temp_auth):
        """Test ingest with explicit --until-date flag.

        Should display the provided until date in the output.
        """
        db_path, db = temp_db

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=0):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=[]):
                    result = runner.invoke(
                        cli.cli,
                        [
                            "ingest",
                            db_path,
                            "-a",
                            temp_auth,
                            "--until-date",
                            "2024-12-31",
                            "--dry-run",
                        ],
                    )

                    assert result.exit_code == 0, f"Command failed: {result.output}"
                    assert "Fetching scrobbles until:" in result.output
                    assert "2024-12-31" in result.output

    def test_ingest_with_since_and_until_dates(self, runner, temp_db, temp_auth):
        """Test ingest with both --since-date and --until-date flags.

        Should display both dates in the output.
        """
        db_path, db = temp_db

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=0):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=[]):
                    result = runner.invoke(
                        cli.cli,
                        [
                            "ingest",
                            db_path,
                            "-a",
                            temp_auth,
                            "--since-date",
                            "2024-01-01",
                            "--until-date",
                            "2024-12-31",
                            "--dry-run",
                        ],
                    )

                    assert result.exit_code == 0, f"Command failed: {result.output}"
                    assert "Fetching scrobbles from" in result.output
                    assert "2024-01-01" in result.output
                    assert "2024-12-31" in result.output


class TestCombinedFixes:
    """Integration tests combining both fixes."""

    def test_full_workflow_empty_database(self, runner, temp_db, temp_auth):
        """Test complete workflow on empty database.

        This simulates a user running ingest on a brand new database,
        which exercises both fixes:
        1. Table existence check (plays table doesn't exist)
        2. None since_date handling
        """
        db_path, db = temp_db

        # Create minimal mock data
        mock_track = {
            "artist": {"id": "artist-1", "name": "Test Artist"},
            "album": {"id": "album-1", "title": "Test Album", "artist_id": "artist-1"},
            "track": {"id": "track-1", "title": "Test Track", "album_id": "album-1"},
            "play": {
                "track_id": "track-1",
                "timestamp": dt.datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            },
        }

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=1):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=[mock_track]):
                    with patch("scrobbledb.lastfm.setup_fts5"):
                        with patch("scrobbledb.lastfm.rebuild_fts5"):
                            result = runner.invoke(
                                cli.cli, ["ingest", db_path, "-a", temp_auth]
                            )

                            # Should complete successfully
                            assert result.exit_code == 0, f"Command failed: {result.output}"

                            # Should show "Fetching all scrobbles" (no since_date)
                            assert "Fetching all scrobbles" in result.output

                            # Should complete without errors
                            assert "AttributeError" not in result.output
                            assert "no such table" not in result.output.lower()

                            # Should show success message
                            assert "Successfully ingested" in result.output


class TestBatchInsert:
    """Tests for batch insert functionality."""

    def test_ingest_with_default_batch_size(self, runner, temp_db, temp_auth):
        """Test that ingest works with the default batch size."""
        db_path, db = temp_db

        # Create mock data with multiple tracks
        mock_tracks = []
        for i in range(5):
            mock_tracks.append({
                "artist": {"id": f"artist-{i}", "name": f"Artist {i}"},
                "album": {"id": f"album-{i}", "title": f"Album {i}", "artist_id": f"artist-{i}"},
                "track": {"id": f"track-{i}", "title": f"Track {i}", "album_id": f"album-{i}"},
                "play": {
                    "track_id": f"track-{i}",
                    "timestamp": dt.datetime(2024, 1, 15, 12, i, 0, tzinfo=timezone.utc),
                },
            })

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=5):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=mock_tracks):
                    with patch("scrobbledb.lastfm.setup_fts5"):
                        with patch("scrobbledb.lastfm.rebuild_fts5"):
                            result = runner.invoke(
                                cli.cli, ["ingest", db_path, "-a", temp_auth]
                            )

                            assert result.exit_code == 0, f"Command failed: {result.output}"
                            assert "Successfully ingested" in result.output

                            # Verify all records were inserted
                            assert db["artists"].count == 5
                            assert db["albums"].count == 5
                            assert db["tracks"].count == 5
                            assert db["plays"].count == 5

    def test_ingest_with_custom_batch_size(self, runner, temp_db, temp_auth):
        """Test that ingest works with a custom batch size option."""
        db_path, db = temp_db

        # Create mock data with multiple tracks
        mock_tracks = []
        for i in range(10):
            mock_tracks.append({
                "artist": {"id": f"artist-{i}", "name": f"Artist {i}"},
                "album": {"id": f"album-{i}", "title": f"Album {i}", "artist_id": f"artist-{i}"},
                "track": {"id": f"track-{i}", "title": f"Track {i}", "album_id": f"album-{i}"},
                "play": {
                    "track_id": f"track-{i}",
                    "timestamp": dt.datetime(2024, 1, 15, 12, i, 0, tzinfo=timezone.utc),
                },
            })

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=10):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=mock_tracks):
                    with patch("scrobbledb.lastfm.setup_fts5"):
                        with patch("scrobbledb.lastfm.rebuild_fts5"):
                            result = runner.invoke(
                                cli.cli, ["ingest", db_path, "-a", temp_auth, "--batch-size", "3"]
                            )

                            assert result.exit_code == 0, f"Command failed: {result.output}"
                            assert "Successfully ingested" in result.output

                            # Verify all records were inserted despite smaller batch size
                            assert db["artists"].count == 10
                            assert db["albums"].count == 10
                            assert db["tracks"].count == 10
                            assert db["plays"].count == 10

    def test_ingest_batch_size_larger_than_records(self, runner, temp_db, temp_auth):
        """Test ingest when batch size is larger than number of records."""
        db_path, db = temp_db

        # Create mock data with just 3 tracks (less than default batch size of 100)
        mock_tracks = []
        for i in range(3):
            mock_tracks.append({
                "artist": {"id": f"artist-{i}", "name": f"Artist {i}"},
                "album": {"id": f"album-{i}", "title": f"Album {i}", "artist_id": f"artist-{i}"},
                "track": {"id": f"track-{i}", "title": f"Track {i}", "album_id": f"album-{i}"},
                "play": {
                    "track_id": f"track-{i}",
                    "timestamp": dt.datetime(2024, 1, 15, 12, i, 0, tzinfo=timezone.utc),
                },
            })

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=3):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=mock_tracks):
                    with patch("scrobbledb.lastfm.setup_fts5"):
                        with patch("scrobbledb.lastfm.rebuild_fts5"):
                            result = runner.invoke(
                                cli.cli, ["ingest", db_path, "-a", temp_auth, "--batch-size", "100"]
                            )

                            assert result.exit_code == 0, f"Command failed: {result.output}"
                            assert "Successfully ingested" in result.output

                            # Verify all records were inserted even though batch wasn't full
                            assert db["artists"].count == 3
                            assert db["albums"].count == 3
                            assert db["tracks"].count == 3
                            assert db["plays"].count == 3

    def test_ingest_no_batch_mode(self, runner, temp_db, temp_auth):
        """Test ingest with --no-batch flag uses individual inserts."""
        db_path, db = temp_db

        # Create mock data
        mock_tracks = []
        for i in range(5):
            mock_tracks.append({
                "artist": {"id": f"artist-{i}", "name": f"Artist {i}"},
                "album": {"id": f"album-{i}", "title": f"Album {i}", "artist_id": f"artist-{i}"},
                "track": {"id": f"track-{i}", "title": f"Track {i}", "album_id": f"album-{i}"},
                "play": {
                    "track_id": f"track-{i}",
                    "timestamp": dt.datetime(2024, 1, 15, 12, i, 0, tzinfo=timezone.utc),
                },
            })

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=5):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=mock_tracks):
                    with patch("scrobbledb.lastfm.setup_fts5"):
                        with patch("scrobbledb.lastfm.rebuild_fts5"):
                            result = runner.invoke(
                                cli.cli, ["ingest", db_path, "-a", temp_auth, "--no-batch"]
                            )

                            assert result.exit_code == 0, f"Command failed: {result.output}"
                            assert "Successfully ingested" in result.output

                            # Verify all records were inserted
                            assert db["artists"].count == 5
                            assert db["albums"].count == 5
                            assert db["tracks"].count == 5
                            assert db["plays"].count == 5

    def test_ingest_reports_elapsed_time(self, runner, temp_db, temp_auth):
        """Test that ingest reports elapsed time."""
        db_path, db = temp_db

        # Create mock data
        mock_tracks = []
        for i in range(3):
            mock_tracks.append({
                "artist": {"id": f"artist-{i}", "name": f"Artist {i}"},
                "album": {"id": f"album-{i}", "title": f"Album {i}", "artist_id": f"artist-{i}"},
                "track": {"id": f"track-{i}", "title": f"Track {i}", "album_id": f"album-{i}"},
                "play": {
                    "track_id": f"track-{i}",
                    "timestamp": dt.datetime(2024, 1, 15, 12, i, 0, tzinfo=timezone.utc),
                },
            })

        mock_user = Mock()
        mock_network = Mock()
        mock_network.get_user.return_value = mock_user

        with patch("scrobbledb.lastfm.get_network", return_value=mock_network):
            with patch("scrobbledb.lastfm.recent_tracks_count", return_value=3):
                with patch("scrobbledb.lastfm.recent_tracks", return_value=mock_tracks):
                    with patch("scrobbledb.lastfm.setup_fts5"):
                        with patch("scrobbledb.lastfm.rebuild_fts5"):
                            result = runner.invoke(
                                cli.cli, ["ingest", db_path, "-a", temp_auth]
                            )

                            assert result.exit_code == 0, f"Command failed: {result.output}"
                            # Should show elapsed time in the output
                            assert "Total time:" in result.output
