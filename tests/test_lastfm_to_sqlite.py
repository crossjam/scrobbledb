from xml.dom import minidom
import pytest
from scrobbledb import lastfm
import datetime as dt
import sqlite_utils
import tempfile
import os


@pytest.fixture
def track_node():
    doc = minidom.parseString(
        """
        <track>
            <artist mbid="artist-123">Aretha Franklin</artist>
            <name>Sisters Are Doing It For Themselves</name>
            <mbid>track-123</mbid>
            <album mbid="album-123"/>
            <url>www.last.fm/music/Aretha+Franklin/_/Sisters+Are+Doing+It+For+Themselves</url>
            <date uts="1213031819">9 Jun 2008, 17:16</date>
            <streamable>1</streamable>
        </track>
        """
    )
    return doc.documentElement


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    db = sqlite_utils.Database(path)
    yield db
    # Cleanup
    db.close()
    os.unlink(path)


@pytest.fixture
def sample_artist_data():
    return {"id": "artist-123", "name": "Aretha Franklin"}


@pytest.fixture
def sample_album_data():
    return {
        "id": "album-123",
        "title": "Who's Zoomin' Who?",
        "artist_id": "artist-123",
    }


@pytest.fixture
def sample_track_data():
    return {
        "id": "track-123",
        "title": "Sisters Are Doing It For Themselves",
        "album_id": "album-123",
    }


@pytest.fixture
def sample_play_data():
    return {
        "track_id": "track-123",
        "timestamp": dt.datetime(2008, 6, 9, 17, 16, 59),
    }


def test_extract_track_data(track_node: minidom.Node):
    data = lastfm._extract_track_data(track_node)
    assert data["artist"] == {"id": "artist-123", "name": "Aretha Franklin"}
    assert data["album"] == {
        "artist_id": "artist-123",
        "id": "album-123",
        "title": "(unknown album)",
    }
    assert data["track"] == {
        "album_id": "album-123",
        "id": "track-123",
        "title": "Sisters Are Doing It For Themselves",
    }
    # Test timestamp - use fromtimestamp to match the implementation's timezone behavior
    expected_timestamp = dt.datetime.fromtimestamp(1213031819)
    assert data["play"] == {
        "track_id": "track-123",
        "timestamp": expected_timestamp,
    }


def test_save_artist(temp_db, sample_artist_data):
    """Test saving artist data to database."""
    lastfm.save_artist(temp_db, sample_artist_data)

    # Verify artist was inserted
    artists = list(temp_db["artists"].rows)
    assert len(artists) == 1
    assert artists[0]["id"] == "artist-123"
    assert artists[0]["name"] == "Aretha Franklin"

    # Verify table structure
    assert temp_db["artists"].pks == ["id"]
    assert "name" in temp_db["artists"].columns_dict


def test_save_artist_upsert(temp_db, sample_artist_data):
    """Test that saving the same artist twice doesn't create duplicates."""
    lastfm.save_artist(temp_db, sample_artist_data)

    # Save again with updated name
    updated_data = {"id": "artist-123", "name": "Aretha Louise Franklin"}
    lastfm.save_artist(temp_db, updated_data)

    # Verify only one artist exists with updated name
    artists = list(temp_db["artists"].rows)
    assert len(artists) == 1
    assert artists[0]["name"] == "Aretha Louise Franklin"


def test_save_album(temp_db, sample_artist_data, sample_album_data):
    """Test saving album data to database."""
    # First save the artist (foreign key dependency)
    lastfm.save_artist(temp_db, sample_artist_data)
    lastfm.save_album(temp_db, sample_album_data)

    # Verify album was inserted
    albums = list(temp_db["albums"].rows)
    assert len(albums) == 1
    assert albums[0]["id"] == "album-123"
    assert albums[0]["title"] == "Who's Zoomin' Who?"
    assert albums[0]["artist_id"] == "artist-123"

    # Verify foreign key relationship
    assert temp_db["albums"].pks == ["id"]


def test_save_track(temp_db, sample_artist_data, sample_album_data, sample_track_data):
    """Test saving track data to database."""
    # Save dependencies first
    lastfm.save_artist(temp_db, sample_artist_data)
    lastfm.save_album(temp_db, sample_album_data)
    lastfm.save_track(temp_db, sample_track_data)

    # Verify track was inserted
    tracks = list(temp_db["tracks"].rows)
    assert len(tracks) == 1
    assert tracks[0]["id"] == "track-123"
    assert tracks[0]["title"] == "Sisters Are Doing It For Themselves"
    assert tracks[0]["album_id"] == "album-123"

    # Verify table structure
    assert temp_db["tracks"].pks == ["id"]


def test_save_play(temp_db, sample_artist_data, sample_album_data, sample_track_data, sample_play_data):
    """Test saving play data to database."""
    # Save dependencies first
    lastfm.save_artist(temp_db, sample_artist_data)
    lastfm.save_album(temp_db, sample_album_data)
    lastfm.save_track(temp_db, sample_track_data)
    lastfm.save_play(temp_db, sample_play_data)

    # Verify play was inserted
    plays = list(temp_db["plays"].rows)
    assert len(plays) == 1
    assert plays[0]["track_id"] == "track-123"
    # sqlite-utils stores timestamps in ISO format
    assert plays[0]["timestamp"] in ["2008-06-09 17:16:59", "2008-06-09T17:16:59"]

    # Verify composite primary key
    assert set(temp_db["plays"].pks) == {"timestamp", "track_id"}


def test_save_complete_scrobble(temp_db, track_node):
    """Test saving a complete scrobble with all related data."""
    # Extract data from track node
    data = lastfm._extract_track_data(track_node)

    # Save all related data
    lastfm.save_artist(temp_db, data["artist"])
    lastfm.save_album(temp_db, data["album"])
    lastfm.save_track(temp_db, data["track"])
    lastfm.save_play(temp_db, data["play"])

    # Verify all tables have data
    assert temp_db["artists"].count == 1
    assert temp_db["albums"].count == 1
    assert temp_db["tracks"].count == 1
    assert temp_db["plays"].count == 1

    # Verify relationships through joins
    play = temp_db.execute("""
        SELECT
            plays.timestamp,
            tracks.title as track_title,
            albums.title as album_title,
            artists.name as artist_name
        FROM plays
        JOIN tracks ON plays.track_id = tracks.id
        JOIN albums ON tracks.album_id = albums.id
        JOIN artists ON albums.artist_id = artists.id
    """).fetchone()

    assert play[1] == "Sisters Are Doing It For Themselves"  # track title
    assert play[2] == "(unknown album)"  # album title
    assert play[3] == "Aretha Franklin"  # artist name


def test_save_multiple_plays_same_track(temp_db, sample_artist_data, sample_album_data, sample_track_data):
    """Test saving multiple plays of the same track."""
    # Save dependencies
    lastfm.save_artist(temp_db, sample_artist_data)
    lastfm.save_album(temp_db, sample_album_data)
    lastfm.save_track(temp_db, sample_track_data)

    # Save multiple plays at different times
    play1 = {"track_id": "track-123", "timestamp": dt.datetime(2008, 6, 9, 17, 16, 59)}
    play2 = {"track_id": "track-123", "timestamp": dt.datetime(2008, 6, 10, 18, 30, 0)}
    play3 = {"track_id": "track-123", "timestamp": dt.datetime(2008, 6, 11, 12, 0, 0)}

    lastfm.save_play(temp_db, play1)
    lastfm.save_play(temp_db, play2)
    lastfm.save_play(temp_db, play3)

    # Verify all plays were saved
    plays = list(temp_db["plays"].rows)
    assert len(plays) == 3
    assert all(play["track_id"] == "track-123" for play in plays)

    # Verify plays are ordered by timestamp
    timestamps = [play["timestamp"] for play in plays]
    assert timestamps == sorted(timestamps)


def test_setup_fts5(temp_db, sample_artist_data, sample_album_data, sample_track_data):
    """Test setting up FTS5 virtual table and triggers."""
    # Save some data first
    lastfm.save_artist(temp_db, sample_artist_data)
    lastfm.save_album(temp_db, sample_album_data)
    lastfm.save_track(temp_db, sample_track_data)

    # Set up FTS5
    lastfm.setup_fts5(temp_db)

    # Verify FTS5 table exists
    assert "tracks_fts" in temp_db.table_names()

    # Verify FTS5 table has correct columns
    columns = [col.name for col in temp_db["tracks_fts"].columns]
    assert "artist_name" in columns
    assert "album_title" in columns
    assert "track_title" in columns
    assert "artist_id" in columns
    assert "album_id" in columns
    assert "track_id" in columns


def test_rebuild_fts5(temp_db, sample_artist_data, sample_album_data, sample_track_data):
    """Test rebuilding FTS5 index from existing data."""
    # Save test data
    lastfm.save_artist(temp_db, sample_artist_data)
    lastfm.save_album(temp_db, sample_album_data)
    lastfm.save_track(temp_db, sample_track_data)

    # Set up and rebuild FTS5
    lastfm.setup_fts5(temp_db)
    lastfm.rebuild_fts5(temp_db)

    # Verify FTS5 table has data
    fts_count = temp_db.execute("SELECT COUNT(*) FROM tracks_fts").fetchone()[0]
    assert fts_count == 1

    # Verify the indexed data is correct
    result = temp_db.execute("""
        SELECT artist_name, album_title, track_title
        FROM tracks_fts
    """).fetchone()
    assert result[0] == "Aretha Franklin"
    assert result[1] == "Who's Zoomin' Who?"
    assert result[2] == "Sisters Are Doing It For Themselves"


def test_search_tracks_basic(temp_db, sample_artist_data, sample_album_data, sample_track_data, sample_play_data):
    """Test basic track search functionality."""
    # Save test data
    lastfm.save_artist(temp_db, sample_artist_data)
    lastfm.save_album(temp_db, sample_album_data)
    lastfm.save_track(temp_db, sample_track_data)
    lastfm.save_play(temp_db, sample_play_data)

    # Set up FTS5 and rebuild
    lastfm.setup_fts5(temp_db)
    lastfm.rebuild_fts5(temp_db)

    # Search for "Aretha"
    results = lastfm.search_tracks(temp_db, "Aretha")
    assert len(results) == 1
    assert results[0]["artist_name"] == "Aretha Franklin"
    assert results[0]["track_title"] == "Sisters Are Doing It For Themselves"
    assert results[0]["album_title"] == "Who's Zoomin' Who?"
    assert results[0]["play_count"] == 1


def test_search_tracks_by_artist(temp_db):
    """Test searching by artist name."""
    # Create test data with multiple artists
    artists = [
        {"id": "artist-1", "name": "The Beatles"},
        {"id": "artist-2", "name": "The Rolling Stones"},
        {"id": "artist-3", "name": "Pink Floyd"},
    ]
    albums = [
        {"id": "album-1", "title": "Abbey Road", "artist_id": "artist-1"},
        {"id": "album-2", "title": "Let It Bleed", "artist_id": "artist-2"},
        {"id": "album-3", "title": "The Dark Side of the Moon", "artist_id": "artist-3"},
    ]
    tracks = [
        {"id": "track-1", "title": "Come Together", "album_id": "album-1"},
        {"id": "track-2", "title": "Gimme Shelter", "album_id": "album-2"},
        {"id": "track-3", "title": "Time", "album_id": "album-3"},
    ]

    for artist in artists:
        lastfm.save_artist(temp_db, artist)
    for album in albums:
        lastfm.save_album(temp_db, album)
    for track in tracks:
        lastfm.save_track(temp_db, track)

    # Set up FTS5
    lastfm.setup_fts5(temp_db)
    lastfm.rebuild_fts5(temp_db)

    # Search for "Beatles"
    results = lastfm.search_tracks(temp_db, "Beatles")
    assert len(results) == 1
    assert results[0]["artist_name"] == "The Beatles"
    assert results[0]["track_title"] == "Come Together"


def test_search_tracks_by_track_title(temp_db):
    """Test searching by track title."""
    # Create test data
    artist = {"id": "artist-1", "name": "The Beatles"}
    album = {"id": "album-1", "title": "Abbey Road", "artist_id": "artist-1"}
    track = {"id": "track-1", "title": "Come Together", "album_id": "album-1"}

    lastfm.save_artist(temp_db, artist)
    lastfm.save_album(temp_db, album)
    lastfm.save_track(temp_db, track)

    lastfm.setup_fts5(temp_db)
    lastfm.rebuild_fts5(temp_db)

    # Search for track title
    results = lastfm.search_tracks(temp_db, "Together")
    assert len(results) == 1
    assert results[0]["track_title"] == "Come Together"


def test_search_tracks_by_album(temp_db):
    """Test searching by album title."""
    # Create test data
    artist = {"id": "artist-1", "name": "Pink Floyd"}
    album = {"id": "album-1", "title": "The Dark Side of the Moon", "artist_id": "artist-1"}
    tracks = [
        {"id": "track-1", "title": "Time", "album_id": "album-1"},
        {"id": "track-2", "title": "Money", "album_id": "album-1"},
    ]

    lastfm.save_artist(temp_db, artist)
    lastfm.save_album(temp_db, album)
    for track in tracks:
        lastfm.save_track(temp_db, track)

    lastfm.setup_fts5(temp_db)
    lastfm.rebuild_fts5(temp_db)

    # Search for album
    results = lastfm.search_tracks(temp_db, "Dark Side")
    assert len(results) == 2
    assert all(r["album_title"] == "The Dark Side of the Moon" for r in results)


def test_search_tracks_with_limit(temp_db):
    """Test search with result limit."""
    # Create test data with multiple tracks
    artist = {"id": "artist-1", "name": "The Beatles"}
    album = {"id": "album-1", "title": "Abbey Road", "artist_id": "artist-1"}
    tracks = [
        {"id": f"track-{i}", "title": f"Song {i}", "album_id": "album-1"}
        for i in range(10)
    ]

    lastfm.save_artist(temp_db, artist)
    lastfm.save_album(temp_db, album)
    for track in tracks:
        lastfm.save_track(temp_db, track)

    lastfm.setup_fts5(temp_db)
    lastfm.rebuild_fts5(temp_db)

    # Search with limit
    results = lastfm.search_tracks(temp_db, "Beatles", limit=5)
    assert len(results) == 5


def test_search_no_results(temp_db, sample_artist_data, sample_album_data, sample_track_data):
    """Test search that returns no results."""
    lastfm.save_artist(temp_db, sample_artist_data)
    lastfm.save_album(temp_db, sample_album_data)
    lastfm.save_track(temp_db, sample_track_data)

    lastfm.setup_fts5(temp_db)
    lastfm.rebuild_fts5(temp_db)

    # Search for something that doesn't exist
    results = lastfm.search_tracks(temp_db, "Nonexistent Artist")
    assert len(results) == 0


def test_fts5_trigger_on_insert(temp_db):
    """Test that FTS5 index is automatically updated when new tracks are inserted."""
    # Insert initial data to create the tables
    artist = {"id": "artist-1", "name": "The Beatles"}
    album = {"id": "album-1", "title": "Abbey Road", "artist_id": "artist-1"}
    track = {"id": "track-1", "title": "Come Together", "album_id": "album-1"}

    lastfm.save_artist(temp_db, artist)
    lastfm.save_album(temp_db, album)
    lastfm.save_track(temp_db, track)

    # Set up FTS5 with triggers AFTER tables exist
    lastfm.setup_fts5(temp_db)

    # Insert MORE data to test that triggers work
    artist2 = {"id": "artist-2", "name": "The Rolling Stones"}
    album2 = {"id": "album-2", "title": "Let It Bleed", "artist_id": "artist-2"}
    track2 = {"id": "track-2", "title": "Gimme Shelter", "album_id": "album-2"}

    lastfm.save_artist(temp_db, artist2)
    lastfm.save_album(temp_db, album2)
    lastfm.save_track(temp_db, track2)

    # Verify FTS5 index was automatically populated by triggers for the new data
    results = lastfm.search_tracks(temp_db, "Stones")
    assert len(results) == 1
    assert results[0]["artist_name"] == "The Rolling Stones"
    assert results[0]["track_title"] == "Gimme Shelter"


def test_search_tracks_with_play_count(temp_db):
    """Test that search results include play count."""
    # Create test data
    artist = {"id": "artist-1", "name": "The Beatles"}
    album = {"id": "album-1", "title": "Abbey Road", "artist_id": "artist-1"}
    track = {"id": "track-1", "title": "Come Together", "album_id": "album-1"}

    lastfm.save_artist(temp_db, artist)
    lastfm.save_album(temp_db, album)
    lastfm.save_track(temp_db, track)

    # Add multiple plays
    for i in range(5):
        play = {
            "track_id": "track-1",
            "timestamp": dt.datetime(2008, 6, 9 + i, 17, 16, 59),
        }
        lastfm.save_play(temp_db, play)

    lastfm.setup_fts5(temp_db)
    lastfm.rebuild_fts5(temp_db)

    # Search and verify play count
    results = lastfm.search_tracks(temp_db, "Beatles")
    assert len(results) == 1
    assert results[0]["play_count"] == 5

