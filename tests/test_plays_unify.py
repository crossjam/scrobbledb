"""Tests for plays subcommand unification."""

import pytest
import json
import tempfile
import os
from click.testing import CliRunner
from scrobbledb.commands import plays
import sqlite_utils

@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = sqlite_utils.Database(path)
    
    # Setup schema
    db.execute("""
        CREATE TABLE artists (
            id TEXT PRIMARY KEY,
            name TEXT
        )
    """)
    db.execute("""
        CREATE TABLE albums (
            id TEXT PRIMARY KEY,
            title TEXT,
            artist_id TEXT,
            FOREIGN KEY(artist_id) REFERENCES artists(id)
        )
    """)
    db.execute("""
        CREATE TABLE tracks (
            id TEXT PRIMARY KEY,
            title TEXT,
            album_id TEXT,
            FOREIGN KEY(album_id) REFERENCES albums(id)
        )
    """)
    db.execute("""
        CREATE TABLE plays (
            track_id TEXT,
            timestamp TEXT,
            FOREIGN KEY(track_id) REFERENCES tracks(id)
        )
    """)
    
    # Insert 60 plays
    db["artists"].insert({"id": "art-1", "name": "Artist 1"})
    db["albums"].insert({"id": "alb-1", "title": "Album 1", "artist_id": "art-1"})
    db["tracks"].insert({"id": "trk-1", "title": "Track 1", "album_id": "alb-1"})
    
    for i in range(60):
        db["plays"].insert({
            "track_id": "trk-1",
            "timestamp": f"2024-01-01T12:00:{i:02d}"
        })
        
    yield path
    
    db.close()
    if os.path.exists(path):
        os.unlink(path)

def test_plays_list_default_limit(runner, temp_db):
    """Test that plays list defaults to a limit of 50."""
    result = runner.invoke(plays.plays, ["list", "--database", temp_db, "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    
    # Should be exactly 50 (the new default)
    assert len(data) == 50

def test_plays_list_custom_limit(runner, temp_db):
    """Test that plays list respects custom limit."""
    result = runner.invoke(plays.plays, ["list", "--database", temp_db, "--limit", "10", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    
    assert len(data) == 10

def test_plays_list_period_week(runner, temp_db):
    """Test that plays list supports --period."""
    # Since all our test data is from 2024-01-01, a 'week' period (last 7 days from now) should return nothing
    # unless we mock datetime.now().
    # But we can at least verify the argument is accepted and doesn't crash.
    result = runner.invoke(plays.plays, ["list", "--database", temp_db, "--period", "week"])
    assert result.exit_code == 0
    # It might say "No plays found" if the date range doesn't match
    # which is expected since the test data is old.
