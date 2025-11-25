"""Tests for the ScrobbleDataAdapter used by the browse TUI."""

import pytest
from sqlite_utils import Database
from scrobbledb.browse import ScrobbleDataAdapter


@pytest.fixture
def sample_db():
    """Create a sample in-memory database with test data."""
    db = Database(memory=True)

    # Create artists
    db["artists"].insert_all([
        {"id": "artist1", "name": "The Beatles"},
        {"id": "artist2", "name": "Led Zeppelin"},
        {"id": "artist3", "name": "Pink Floyd"},
    ])

    # Create albums
    db["albums"].insert_all([
        {"id": "album1", "title": "Abbey Road", "artist_id": "artist1"},
        {"id": "album2", "title": "Led Zeppelin IV", "artist_id": "artist2"},
        {"id": "album3", "title": "The Dark Side of the Moon", "artist_id": "artist3"},
        {"id": "album4", "title": "Sgt. Pepper's", "artist_id": "artist1"},
    ])

    # Create tracks
    db["tracks"].insert_all([
        {"id": "track1", "title": "Come Together", "album_id": "album1"},
        {"id": "track2", "title": "Something", "album_id": "album1"},
        {"id": "track3", "title": "Stairway to Heaven", "album_id": "album2"},
        {"id": "track4", "title": "Time", "album_id": "album3"},
        {"id": "track5", "title": "Money", "album_id": "album3"},
        {"id": "track6", "title": "Lucy in the Sky", "album_id": "album4"},
    ])

    # Create plays
    db["plays"].insert_all([
        {"track_id": "track1", "timestamp": "2024-01-15T10:00:00"},
        {"track_id": "track1", "timestamp": "2024-01-16T11:00:00"},
        {"track_id": "track1", "timestamp": "2024-01-17T12:00:00"},
        {"track_id": "track2", "timestamp": "2024-01-10T09:00:00"},
        {"track_id": "track3", "timestamp": "2024-01-20T14:00:00"},
        {"track_id": "track3", "timestamp": "2024-01-21T15:00:00"},
        {"track_id": "track4", "timestamp": "2024-01-05T08:00:00"},
    ])

    return db


class TestScrobbleDataAdapter:
    """Tests for ScrobbleDataAdapter."""

    def test_get_total_count(self, sample_db):
        """Test getting total track count."""
        adapter = ScrobbleDataAdapter(sample_db)
        count = adapter.get_total_count()
        assert count == 6

    def test_get_total_count_with_filter(self, sample_db):
        """Test getting filtered track count."""
        adapter = ScrobbleDataAdapter(sample_db)

        # Filter by artist
        count = adapter.get_total_count(filter_text="Beatles")
        assert count == 3  # Come Together, Something, Lucy in the Sky

        # Filter by album
        count = adapter.get_total_count(filter_text="Dark Side")
        assert count == 2  # Time, Money

        # Filter by track
        count = adapter.get_total_count(filter_text="Stairway")
        assert count == 1

    def test_get_tracks_basic(self, sample_db):
        """Test basic track retrieval."""
        adapter = ScrobbleDataAdapter(sample_db)
        tracks = adapter.get_tracks(limit=10)

        assert len(tracks) == 6
        assert all("artist_name" in t for t in tracks)
        assert all("album_title" in t for t in tracks)
        assert all("track_title" in t for t in tracks)
        assert all("play_count" in t for t in tracks)

    def test_get_tracks_pagination(self, sample_db):
        """Test paginated track retrieval."""
        adapter = ScrobbleDataAdapter(sample_db)

        # Get first page
        page1 = adapter.get_tracks(offset=0, limit=3)
        assert len(page1) == 3

        # Get second page
        page2 = adapter.get_tracks(offset=3, limit=3)
        assert len(page2) == 3

        # Verify no overlap
        page1_ids = {t["track_id"] for t in page1}
        page2_ids = {t["track_id"] for t in page2}
        assert page1_ids.isdisjoint(page2_ids)

    def test_get_tracks_with_filter(self, sample_db):
        """Test filtered track retrieval."""
        adapter = ScrobbleDataAdapter(sample_db)

        tracks = adapter.get_tracks(filter_text="Beatles")
        assert len(tracks) == 3
        assert all("Beatles" in t["artist_name"] for t in tracks)

    def test_get_tracks_sort_by_plays(self, sample_db):
        """Test sorting tracks by play count."""
        adapter = ScrobbleDataAdapter(sample_db)

        # Sort by most played
        tracks = adapter.get_tracks(sort_by="plays_desc")
        play_counts = [t["play_count"] for t in tracks]
        assert play_counts == sorted(play_counts, reverse=True)

        # Sort by least played
        tracks = adapter.get_tracks(sort_by="plays_asc")
        play_counts = [t["play_count"] for t in tracks]
        assert play_counts == sorted(play_counts)

    def test_get_tracks_sort_by_artist(self, sample_db):
        """Test sorting tracks by artist name."""
        adapter = ScrobbleDataAdapter(sample_db)

        # Sort A-Z
        tracks = adapter.get_tracks(sort_by="artist_asc")
        artists = [t["artist_name"] for t in tracks]
        assert artists == sorted(artists)

        # Sort Z-A
        tracks = adapter.get_tracks(sort_by="artist_desc")
        artists = [t["artist_name"] for t in tracks]
        assert artists == sorted(artists, reverse=True)

    def test_get_tracks_includes_play_stats(self, sample_db):
        """Test that tracks include play statistics."""
        adapter = ScrobbleDataAdapter(sample_db)
        tracks = adapter.get_tracks()

        # Find Come Together which has 3 plays
        come_together = next(t for t in tracks if t["track_title"] == "Come Together")
        assert come_together["play_count"] == 3
        assert come_together["last_played"] is not None

        # Find Money which has 0 plays
        money = next(t for t in tracks if t["track_title"] == "Money")
        assert money["play_count"] == 0

    def test_get_artists(self, sample_db):
        """Test getting artist list."""
        adapter = ScrobbleDataAdapter(sample_db)
        artists = adapter.get_artists()

        assert len(artists) == 3
        assert all("name" in a for a in artists)
        assert all("track_count" in a for a in artists)

        # Beatles should have the most tracks
        beatles = next(a for a in artists if a["name"] == "The Beatles")
        assert beatles["track_count"] == 3

    def test_get_albums(self, sample_db):
        """Test getting album list."""
        adapter = ScrobbleDataAdapter(sample_db)
        albums = adapter.get_albums()

        assert len(albums) == 4
        assert all("title" in a for a in albums)
        assert all("artist_name" in a for a in albums)
        assert all("track_count" in a for a in albums)

    def test_get_albums_filtered_by_artist(self, sample_db):
        """Test getting albums filtered by artist."""
        adapter = ScrobbleDataAdapter(sample_db)
        albums = adapter.get_albums(artist_id="artist1")

        assert len(albums) == 2  # Abbey Road and Sgt. Pepper's
        assert all(a["artist_name"] == "The Beatles" for a in albums)

    def test_empty_database(self):
        """Test adapter behavior with empty database."""
        db = Database(memory=True)
        db["tracks"].create({"id": str, "title": str, "album_id": str})
        db["albums"].create({"id": str, "title": str, "artist_id": str})
        db["artists"].create({"id": str, "name": str})

        adapter = ScrobbleDataAdapter(db)

        assert adapter.get_total_count() == 0
        assert adapter.get_tracks() == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
