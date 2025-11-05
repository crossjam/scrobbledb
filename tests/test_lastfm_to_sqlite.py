from xml.dom import minidom
import pytest
from scrobbledb import lastfm
import datetime as dt
from datetime import timezone
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
        "timestamp": dt.datetime(2008, 6, 9, 17, 16, 59, tzinfo=timezone.utc),
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
    # Test timestamp - should be timezone-aware UTC
    expected_timestamp = dt.datetime.fromtimestamp(1213031819, tz=timezone.utc)
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
    # sqlite-utils stores timestamps in ISO format with timezone
    assert plays[0]["timestamp"] in [
        "2008-06-09 17:16:59",
        "2008-06-09T17:16:59",
        "2008-06-09T17:16:59+00:00"
    ]

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
    play1 = {"track_id": "track-123", "timestamp": dt.datetime(2008, 6, 9, 17, 16, 59, tzinfo=timezone.utc)}
    play2 = {"track_id": "track-123", "timestamp": dt.datetime(2008, 6, 10, 18, 30, 0, tzinfo=timezone.utc)}
    play3 = {"track_id": "track-123", "timestamp": dt.datetime(2008, 6, 11, 12, 0, 0, tzinfo=timezone.utc)}

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
            "timestamp": dt.datetime(2008, 6, 9 + i, 17, 16, 59, tzinfo=timezone.utc),
        }
        lastfm.save_play(temp_db, play)

    lastfm.setup_fts5(temp_db)
    lastfm.rebuild_fts5(temp_db)

    # Search and verify play count
    results = lastfm.search_tracks(temp_db, "Beatles")
    assert len(results) == 1
    assert results[0]["play_count"] == 5


# Tests for new 'add' command functionality

def test_parse_timestamp_unix():
    """Test parsing Unix timestamp."""
    result = lastfm.parse_timestamp("1705329000")
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 15


def test_parse_timestamp_iso8601():
    """Test parsing ISO 8601 format."""
    result = lastfm.parse_timestamp("2024-01-15T14:30:00")
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 15
    assert result.hour == 14
    assert result.minute == 30


def test_parse_timestamp_various_formats():
    """Test parsing various timestamp formats."""
    formats = [
        "2024-01-15 14:30:00",
        "2024-01-15",
        "2024/01/15 14:30:00",
    ]
    for ts in formats:
        result = lastfm.parse_timestamp(ts)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15


def test_parse_timestamp_invalid():
    """Test parsing invalid timestamp raises error."""
    import pytest
    with pytest.raises(ValueError):
        lastfm.parse_timestamp("not-a-date")


def test_synthesize_mbids():
    """Test MBID generation is consistent."""
    artist = "The Beatles"
    album = "Abbey Road"
    track = "Come Together"

    artist_mbid, album_mbid, track_mbid = lastfm.synthesize_mbids(artist, album, track)

    # Should start with md5:
    assert artist_mbid.startswith("md5:")
    assert album_mbid.startswith("md5:")
    assert track_mbid.startswith("md5:")

    # Should be deterministic
    artist_mbid2, album_mbid2, track_mbid2 = lastfm.synthesize_mbids(artist, album, track)
    assert artist_mbid == artist_mbid2
    assert album_mbid == album_mbid2
    assert track_mbid == track_mbid2


def test_synthesize_mbids_different_inputs():
    """Test that different inputs generate different MBIDs."""
    artist1_mbid, _, _ = lastfm.synthesize_mbids("Artist 1", "Album", "Track")
    artist2_mbid, _, _ = lastfm.synthesize_mbids("Artist 2", "Album", "Track")

    assert artist1_mbid != artist2_mbid


def test_normalize_field_name():
    """Test field name normalization with aliases."""
    assert lastfm.normalize_field_name("timestamp") == "timestamp"
    assert lastfm.normalize_field_name("time") == "timestamp"
    assert lastfm.normalize_field_name("played_at") == "timestamp"
    assert lastfm.normalize_field_name("artist") == "artist"
    assert lastfm.normalize_field_name("artist_name") == "artist"
    assert lastfm.normalize_field_name("track") == "track"
    assert lastfm.normalize_field_name("song") == "track"
    assert lastfm.normalize_field_name("title") == "track"


def test_normalize_field_name_case_insensitive():
    """Test field name normalization is case insensitive."""
    assert lastfm.normalize_field_name("TIMESTAMP") == "timestamp"
    assert lastfm.normalize_field_name("Artist") == "artist"
    assert lastfm.normalize_field_name("TRACK_TITLE") == "track"


def test_parse_scrobble_dict_basic():
    """Test parsing basic scrobble dictionary."""
    data = {
        "timestamp": "2024-01-15T14:30:00",
        "artist": "The Beatles",
        "album": "Abbey Road",
        "track": "Come Together"
    }

    result = lastfm.parse_scrobble_dict(data)

    assert result["artist"]["name"] == "The Beatles"
    assert result["album"]["title"] == "Abbey Road"
    assert result["track"]["title"] == "Come Together"
    assert result["play"]["timestamp"].year == 2024


def test_parse_scrobble_dict_no_album():
    """Test parsing scrobble without album defaults to (unknown album)."""
    data = {
        "timestamp": "2024-01-15T14:30:00",
        "artist": "The Beatles",
        "track": "Come Together"
    }

    result = lastfm.parse_scrobble_dict(data)

    assert result["album"]["title"] == "(unknown album)"


def test_parse_scrobble_dict_field_aliases():
    """Test parsing scrobble with field aliases."""
    data = {
        "time": "2024-01-15T14:30:00",
        "artist_name": "The Beatles",
        "song": "Come Together"
    }

    result = lastfm.parse_scrobble_dict(data)

    assert result["artist"]["name"] == "The Beatles"
    assert result["track"]["title"] == "Come Together"


def test_parse_scrobble_dict_missing_artist():
    """Test parsing scrobble with missing artist raises error."""
    import pytest
    data = {
        "timestamp": "2024-01-15T14:30:00",
        "track": "Come Together"
    }

    with pytest.raises(ValueError, match="Missing required field: artist"):
        lastfm.parse_scrobble_dict(data)


def test_parse_scrobble_dict_missing_track():
    """Test parsing scrobble with missing track raises error."""
    import pytest
    data = {
        "timestamp": "2024-01-15T14:30:00",
        "artist": "The Beatles"
    }

    with pytest.raises(ValueError, match="Missing required field: track"):
        lastfm.parse_scrobble_dict(data)


def test_parse_scrobble_dict_missing_timestamp():
    """Test parsing scrobble with missing timestamp raises error."""
    import pytest
    data = {
        "artist": "The Beatles",
        "track": "Come Together"
    }

    with pytest.raises(ValueError, match="Missing required field: timestamp"):
        lastfm.parse_scrobble_dict(data)


def test_parse_scrobble_dict_with_line_number():
    """Test error messages include line number."""
    import pytest
    data = {
        "artist": "The Beatles",
        "track": "Come Together"
    }

    with pytest.raises(ValueError, match="Line 42: Missing required field: timestamp"):
        lastfm.parse_scrobble_dict(data, line_num=42)


def test_parse_scrobble_jsonl_valid():
    """Test parsing valid JSON line."""
    line = '{"timestamp": "2024-01-15T14:30:00", "artist": "The Beatles", "track": "Come Together"}'

    result = lastfm.parse_scrobble_jsonl(line)

    assert result["artist"]["name"] == "The Beatles"
    assert result["track"]["title"] == "Come Together"


def test_parse_scrobble_jsonl_invalid_json():
    """Test parsing invalid JSON raises error."""
    import pytest
    line = '{"timestamp": "2024-01-15T14:30:00", "artist": "The Beatles"'  # Missing closing brace

    with pytest.raises(ValueError, match="Invalid JSON"):
        lastfm.parse_scrobble_jsonl(line)


def test_parse_scrobble_jsonl_not_object():
    """Test parsing JSON that's not an object raises error."""
    import pytest
    line = '["array", "not", "object"]'

    with pytest.raises(ValueError, match="Expected JSON object"):
        lastfm.parse_scrobble_jsonl(line)


def test_detect_format_jsonl():
    """Test format detection for JSONL."""
    line = '{"timestamp": "2024-01-15T14:30:00", "artist": "The Beatles"}'
    assert lastfm.detect_format(line) == "jsonl"


def test_detect_format_csv():
    """Test format detection for CSV."""
    line = "timestamp,artist,track"
    assert lastfm.detect_format(line) == "csv"


def test_detect_format_tsv():
    """Test format detection for TSV."""
    line = "timestamp\tartist\ttrack"
    assert lastfm.detect_format(line) == "tsv"


def test_detect_format_defaults_to_jsonl():
    """Test format detection defaults to JSONL for ambiguous input."""
    line = "some random text"
    assert lastfm.detect_format(line) == "jsonl"


def test_add_scrobbles_basic(temp_db):
    """Test basic scrobble addition."""
    scrobbles = [
        {
            "artist": {"id": "artist-1", "name": "The Beatles"},
            "album": {"id": "album-1", "title": "Abbey Road", "artist_id": "artist-1"},
            "track": {"id": "track-1", "title": "Come Together", "album_id": "album-1"},
            "play": {"track_id": "track-1", "timestamp": dt.datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)},
        }
    ]

    stats = lastfm.add_scrobbles(temp_db, iter(scrobbles))

    assert stats['total_processed'] == 1
    assert stats['added'] == 1
    assert stats['skipped'] == 0
    assert len(stats['errors']) == 0


def test_add_scrobbles_with_limit(temp_db):
    """Test scrobble addition with limit."""
    scrobbles = [
        {
            "artist": {"id": f"artist-{i}", "name": f"Artist {i}"},
            "album": {"id": f"album-{i}", "title": f"Album {i}", "artist_id": f"artist-{i}"},
            "track": {"id": f"track-{i}", "title": f"Track {i}", "album_id": f"album-{i}"},
            "play": {"track_id": f"track-{i}", "timestamp": dt.datetime(2024, 1, 15, 14, i, tzinfo=timezone.utc)},
        }
        for i in range(10)
    ]

    stats = lastfm.add_scrobbles(temp_db, iter(scrobbles), limit=5)

    assert stats['total_processed'] == 6  # Processes one extra to detect limit
    assert stats['added'] == 5
    assert stats['limit_reached'] is True


def test_add_scrobbles_with_sample(temp_db):
    """Test scrobble addition with sampling."""
    scrobbles = [
        {
            "artist": {"id": f"artist-{i}", "name": f"Artist {i}"},
            "album": {"id": f"album-{i}", "title": f"Album {i}", "artist_id": f"artist-{i}"},
            "track": {"id": f"track-{i}", "title": f"Track {i}", "album_id": f"album-{i}"},
            "play": {"track_id": f"track-{i}", "timestamp": dt.datetime(2024, 1, 15, 14, 0, i, tzinfo=timezone.utc)},
        }
        for i in range(60)  # Use 60 items for valid seconds
    ]

    stats = lastfm.add_scrobbles(temp_db, iter(scrobbles), sample=0.5, seed=42)

    assert stats['total_processed'] == 60
    assert stats['sampled'] > 0
    assert stats['sampled'] < 60  # Should sample roughly 50%
    assert stats['added'] == stats['sampled']


def test_add_scrobbles_with_sample_seed_reproducible(temp_db):
    """Test that sampling with seed is reproducible."""
    scrobbles = [
        {
            "artist": {"id": f"artist-{i}", "name": f"Artist {i}"},
            "album": {"id": f"album-{i}", "title": f"Album {i}", "artist_id": f"artist-{i}"},
            "track": {"id": f"track-{i}", "title": f"Track {i}", "album_id": f"album-{i}"},
            "play": {"track_id": f"track-{i}", "timestamp": dt.datetime(2024, 1, 15, 14, i, tzinfo=timezone.utc)},
        }
        for i in range(50)
    ]

    # Run twice with same seed
    stats1 = lastfm.add_scrobbles(temp_db, iter(scrobbles), sample=0.5, seed=42)

    # Clear database
    temp_db.execute("DELETE FROM plays")
    temp_db.execute("DELETE FROM tracks")
    temp_db.execute("DELETE FROM albums")
    temp_db.execute("DELETE FROM artists")

    stats2 = lastfm.add_scrobbles(temp_db, iter(scrobbles), sample=0.5, seed=42)

    # Should sample same number with same seed
    assert stats1['sampled'] == stats2['sampled']


def test_add_scrobbles_no_duplicates(temp_db):
    """Test duplicate detection."""
    # Add initial scrobble
    scrobble = {
        "artist": {"id": "artist-1", "name": "The Beatles"},
        "album": {"id": "album-1", "title": "Abbey Road", "artist_id": "artist-1"},
        "track": {"id": "track-1", "title": "Come Together", "album_id": "album-1"},
        "play": {"track_id": "track-1", "timestamp": dt.datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)},
    }

    # Add first time (no_duplicates not set)
    lastfm.add_scrobbles(temp_db, iter([scrobble]))

    # Verify it was added
    assert temp_db["plays"].count == 1

    # Try to add same scrobble again with no_duplicates
    stats = lastfm.add_scrobbles(temp_db, iter([scrobble]), no_duplicates=True)

    # Should be skipped as duplicate
    assert stats['added'] == 0
    assert stats['skipped'] == 1

    # Verify still only one play in database
    assert temp_db["plays"].count == 1


def test_add_scrobbles_skip_errors(temp_db):
    """Test skip errors mode."""
    # Note: We can't easily test database constraint errors in unit tests
    # because sqlite-utils is very permissive. This test verifies that
    # skip_errors mode works by not raising exceptions.
    # A real error would come from malformed data in the parsing phase.

    scrobbles = [
        {
            "artist": {"id": "artist-1", "name": "The Beatles"},
            "album": {"id": "album-1", "title": "Abbey Road", "artist_id": "artist-1"},
            "track": {"id": "track-1", "title": "Come Together", "album_id": "album-1"},
            "play": {"track_id": "track-1", "timestamp": dt.datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)},
        },
    ]

    # This should succeed without errors
    stats = lastfm.add_scrobbles(temp_db, iter(scrobbles), skip_errors=True)

    assert stats['total_processed'] == 1
    assert stats['added'] == 1
    assert len(stats['errors']) == 0


def test_add_scrobbles_combined_options(temp_db):
    """Test combining multiple options."""
    scrobbles = [
        {
            "artist": {"id": f"artist-{i}", "name": f"Artist {i}"},
            "album": {"id": f"album-{i}", "title": f"Album {i}", "artist_id": f"artist-{i}"},
            "track": {"id": f"track-{i}", "title": f"Track {i}", "album_id": f"album-{i}"},
            "play": {"track_id": f"track-{i}", "timestamp": dt.datetime(2024, 1, 15, 14, 0, i, tzinfo=timezone.utc)},
        }
        for i in range(60)  # Use 60 items for valid seconds
    ]

    # Sample 50%, limit to 10
    stats = lastfm.add_scrobbles(temp_db, iter(scrobbles), sample=0.5, limit=10, seed=42)

    assert stats['total_processed'] <= 60
    assert stats['added'] == 10
    assert stats['limit_reached'] is True


def test_parse_timestamp_returns_utc(temp_db):
    """Test that parsed timestamps are timezone-aware and in UTC."""
    # Unix timestamp
    ts = lastfm.parse_timestamp("1213031819")
    assert ts.tzinfo is not None
    assert ts.tzinfo == timezone.utc

    # ISO 8601
    ts = lastfm.parse_timestamp("2024-01-15T14:30:00")
    assert ts.tzinfo is not None
    assert ts.tzinfo == timezone.utc

    # Common format
    ts = lastfm.parse_timestamp("2024-01-15 14:30:00")
    assert ts.tzinfo is not None
    assert ts.tzinfo == timezone.utc


def test_parse_timestamp_converts_to_utc(temp_db):
    """Test that timestamps with timezones are converted to UTC."""
    # Parse a timestamp with timezone offset (EST = UTC-5)
    ts = lastfm.parse_timestamp("2024-01-15T14:30:00-05:00")
    assert ts.tzinfo == timezone.utc
    # 14:30 EST = 19:30 UTC
    assert ts.hour == 19
    assert ts.minute == 30


def test_extract_track_data_timezone_aware(track_node):
    """Test that _extract_track_data returns timezone-aware timestamps."""
    data = lastfm._extract_track_data(track_node)
    timestamp = data["play"]["timestamp"]
    assert timestamp.tzinfo is not None
    assert timestamp.tzinfo == timezone.utc


