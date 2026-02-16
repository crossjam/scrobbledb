"""Tests for default sorting in list commands."""

import pytest
import json
import tempfile
import os
from click.testing import CliRunner
from scrobbledb.commands import albums, tracks, artists
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
    
    # Insert data
    # Artist A: 10 plays, last played 2024-01-01
    # Artist B: 5 plays, last played 2024-02-01 (More recent, fewer plays)
    
    db["artists"].insert_all([
        {"id": "art-a", "name": "Artist A"},
        {"id": "art-b", "name": "Artist B"},
    ])
    
    db["albums"].insert_all([
        {"id": "alb-a", "title": "Album A", "artist_id": "art-a"},
        {"id": "alb-b", "title": "Album B", "artist_id": "art-b"},
    ])
    
    db["tracks"].insert_all([
        {"id": "trk-a", "title": "Track A", "album_id": "alb-a"},
        {"id": "trk-b", "title": "Track B", "album_id": "alb-b"},
    ])
    
    # Plays for A (10 plays, old)
    for i in range(10):
        db["plays"].insert({
            "track_id": "trk-a",
            "timestamp": f"2024-01-01T12:00:0{i}"
        })
        
    # Plays for B (5 plays, recent)
    for i in range(5):
        db["plays"].insert({
            "track_id": "trk-b",
            "timestamp": f"2024-02-01T12:00:0{i}"
        })
        
    yield path
    
    db.close()
    if os.path.exists(path):
        os.unlink(path)

def test_albums_list_default_sort(runner, temp_db):
    """Test that albums list defaults to sorting by recent (last played)."""
    result = runner.invoke(albums.albums, ["list", "--database", temp_db, "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    
    # Should be sorted by recent: Album B (Feb) then Album A (Jan)
    assert len(data) == 2
    assert data[0]["album_title"] == "Album B"
    assert data[1]["album_title"] == "Album A"

def test_artists_list_default_sort(runner, temp_db):
    """Test that artists list defaults to sorting by recent (last played)."""
    result = runner.invoke(artists.artists, ["list", "--database", temp_db, "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    
    # Should be sorted by recent: Artist B (Feb) then Artist A (Jan)
    assert len(data) == 2
    assert data[0]["artist_name"] == "Artist B"
    assert data[1]["artist_name"] == "Artist A"

def test_tracks_list_default_sort(runner, temp_db):
    """Test that tracks list defaults to sorting by recent (last played)."""
    result = runner.invoke(tracks.tracks, ["list", "--database", temp_db, "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    
    # Should be sorted by recent: Track B (Feb) then Track A (Jan)
    assert len(data) == 2
    assert data[0]["track_title"] == "Track B"
    assert data[1]["track_title"] == "Track A"

def test_plays_list_default_sort(runner, temp_db):
    """Test that plays list defaults to sorting by recent (last played)."""
    from scrobbledb.commands import plays
    result = runner.invoke(plays.plays, ["list", "--database", temp_db, "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    
    # Should be sorted by recent: Feb plays then Jan plays
    # We inserted 5 Feb plays (Track B) and 10 Jan plays (Track A)
    # Total 15 plays.
    # The most recent should be from Feb.
    assert len(data) == 15
    assert "2024-02-01" in data[0]["timestamp"]
    assert "2024-01-01" in data[-1]["timestamp"]
