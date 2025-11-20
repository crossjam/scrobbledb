"""Tests for scrobbledb export command."""
import pytest
import tempfile
import os
import json
from pathlib import Path
from click.testing import CliRunner
from scrobbledb import cli, lastfm
import sqlite_utils


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    db = sqlite_utils.Database(path)
    yield db, path
    # Cleanup
    db.close()
    os.unlink(path)


@pytest.fixture
def populated_db(temp_db):
    """Create a temporary database with sample scrobble data."""
    db, path = temp_db

    # Create sample data
    import datetime as dt
    from datetime import timezone

    # Multiple artists, albums, tracks, and plays for better testing
    artists = [
        {"id": "artist-1", "name": "The Beatles"},
        {"id": "artist-2", "name": "Pink Floyd"},
    ]
    albums = [
        {"id": "album-1", "title": "Abbey Road", "artist_id": "artist-1"},
        {"id": "album-2", "title": "The Dark Side of the Moon", "artist_id": "artist-2"},
    ]
    tracks = [
        {"id": "track-1", "title": "Come Together", "album_id": "album-1"},
        {"id": "track-2", "title": "Something", "album_id": "album-1"},
        {"id": "track-3", "title": "Time", "album_id": "album-2"},
    ]
    plays = [
        {"track_id": "track-1", "timestamp": dt.datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)},
        {"track_id": "track-2", "timestamp": dt.datetime(2024, 1, 16, 15, 30, tzinfo=timezone.utc)},
        {"track_id": "track-3", "timestamp": dt.datetime(2024, 1, 17, 16, 30, tzinfo=timezone.utc)},
    ]

    for artist in artists:
        lastfm.save_artist(db, artist)
    for album in albums:
        lastfm.save_album(db, album)
    for track in tracks:
        lastfm.save_track(db, track)
    for play in plays:
        lastfm.save_play(db, play)
    lastfm.setup_fts5(db)

    yield db, path


def test_export_plays_preset_jsonl(populated_db):
    """Test exporting plays preset to JSONL format."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, ['export', '--database', path, 'plays'])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Parse JSONL output
    lines = [line for line in result.output.strip().split('\n') if line]
    assert len(lines) == 3  # 3 plays

    # Check first play has expected fields
    first_play = json.loads(lines[0])
    assert 'timestamp' in first_play
    assert 'track_title' in first_play
    assert 'album_title' in first_play
    assert 'artist_name' in first_play


def test_export_plays_preset_json(populated_db):
    """Test exporting plays preset to JSON format."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, ['export', '--database', path, 'plays', '--format', 'json'])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Parse JSON output
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert len(data) == 3  # 3 plays


def test_export_plays_preset_csv(populated_db):
    """Test exporting plays preset to CSV format."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, ['export', '--database', path, 'plays', '--format', 'csv'])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Parse CSV output
    lines = result.output.strip().split('\n')
    assert len(lines) == 4  # Header + 3 plays
    assert 'timestamp' in lines[0]
    assert 'track_title' in lines[0]


def test_export_plays_preset_tsv(populated_db):
    """Test exporting plays preset to TSV format."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, ['export', '--database', path, 'plays', '--format', 'tsv'])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Parse TSV output
    lines = result.output.strip().split('\n')
    assert len(lines) == 4  # Header + 3 plays
    assert '\t' in lines[0]  # TSV uses tabs


def test_export_tracks_preset(populated_db):
    """Test exporting tracks preset."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, ['export', '--database', path, 'tracks'])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    lines = [line for line in result.output.strip().split('\n') if line]
    assert len(lines) == 3  # 3 tracks

    first_track = json.loads(lines[0])
    assert 'title' in first_track
    assert 'album_title' in first_track
    assert 'artist_name' in first_track


def test_export_albums_preset(populated_db):
    """Test exporting albums preset."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, ['export', '--database', path, 'albums'])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    lines = [line for line in result.output.strip().split('\n') if line]
    assert len(lines) == 2  # 2 albums

    first_album = json.loads(lines[0])
    assert 'title' in first_album
    assert 'artist_name' in first_album
    assert 'track_count' in first_album


def test_export_artists_preset(populated_db):
    """Test exporting artists preset."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, ['export', '--database', path, 'artists'])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    lines = [line for line in result.output.strip().split('\n') if line]
    assert len(lines) == 2  # 2 artists

    first_artist = json.loads(lines[0])
    assert 'name' in first_artist
    assert 'album_count' in first_artist
    assert 'track_count' in first_artist
    assert 'play_count' in first_artist


def test_export_with_limit(populated_db):
    """Test exporting with --limit option."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, ['export', '--database', path, 'plays', '--limit', '2'])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    lines = [line for line in result.output.strip().split('\n') if line]
    assert len(lines) == 2  # Limited to 2


def test_export_with_columns(populated_db):
    """Test exporting with --columns option."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, [
        'export', '--database', path, 'plays',
        '--columns', 'timestamp,artist_name',
        '--format', 'json'
    ])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    data = json.loads(result.output)
    assert len(data) > 0

    # Should only have the specified columns
    assert set(data[0].keys()) == {'timestamp', 'artist_name'}


def test_export_custom_sql(populated_db):
    """Test exporting with custom SQL query."""
    db, path = populated_db
    runner = CliRunner()

    sql = "SELECT name FROM artists WHERE name LIKE '%Beatles%'"
    result = runner.invoke(cli.cli, ['export', '--database', path, '--sql', sql])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    lines = [line for line in result.output.strip().split('\n') if line]
    assert len(lines) == 1

    artist = json.loads(lines[0])
    assert artist['name'] == 'The Beatles'


def test_export_custom_sql_file(populated_db):
    """Test exporting with --sql-file option."""
    db, path = populated_db
    runner = CliRunner()

    # Create a temporary SQL file
    fd, sql_path = tempfile.mkstemp(suffix='.sql')
    try:
        os.write(fd, b"SELECT name FROM artists ORDER BY name")
        os.close(fd)

        result = runner.invoke(cli.cli, ['export', '--database', path, '--sql-file', sql_path])

        assert result.exit_code == 0, f"Command failed: {result.output}"

        lines = [line for line in result.output.strip().split('\n') if line]
        assert len(lines) == 2  # 2 artists
    finally:
        os.unlink(sql_path)


def test_export_dry_run(populated_db):
    """Test export with --dry-run option."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, ['export', '--database', path, 'plays', '--dry-run'])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Dry run should show SQL query, not actual data
    assert 'SQL Query:' in result.output
    assert 'SELECT' in result.output
    assert 'plays' in result.output
    # Should not contain actual data
    assert 'Come Together' not in result.output


def test_export_to_file(populated_db):
    """Test exporting to a file."""
    db, path = populated_db
    runner = CliRunner()

    fd, output_path = tempfile.mkstemp(suffix='.jsonl')
    os.close(fd)

    try:
        result = runner.invoke(cli.cli, [
            'export', '--database', path, 'plays',
            '--output', output_path
        ])

        assert result.exit_code == 0, f"Command failed: {result.output}"
        assert f'Exported 3 rows to {output_path}' in result.output

        # Check file contents
        content = Path(output_path).read_text()
        lines = [line for line in content.strip().split('\n') if line]
        assert len(lines) == 3
    finally:
        os.unlink(output_path)


def test_export_no_headers_csv(populated_db):
    """Test CSV export with --no-headers option."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, [
        'export', '--database', path, 'plays',
        '--format', 'csv', '--no-headers'
    ])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    lines = result.output.strip().split('\n')
    # Should have 3 lines (no header)
    assert len(lines) == 3
    # First line should not be a header
    assert 'timestamp' not in lines[0]


def test_export_sample(populated_db):
    """Test export with --sample option."""
    db, path = populated_db
    runner = CliRunner()

    # Use a seed for reproducibility
    result = runner.invoke(cli.cli, [
        'export', '--database', path, 'plays',
        '--sample', '0.5', '--seed', '42'
    ])

    assert result.exit_code == 0, f"Command failed: {result.output}"

    lines = [line for line in result.output.strip().split('\n') if line]
    # With sample 0.5 and seed 42, we should get a subset
    # (exact count depends on random sampling, but should be 0-3)
    assert 0 <= len(lines) <= 3


def test_export_sample_with_seed_reproducible(populated_db):
    """Test that --sample with --seed produces reproducible results."""
    db, path = populated_db
    runner = CliRunner()

    # Run twice with same seed
    result1 = runner.invoke(cli.cli, [
        'export', '--database', path, 'plays',
        '--sample', '0.5', '--seed', '123'
    ])
    result2 = runner.invoke(cli.cli, [
        'export', '--database', path, 'plays',
        '--sample', '0.5', '--seed', '123'
    ])

    assert result1.output == result2.output


def test_export_no_preset_no_sql_error(populated_db):
    """Test that export fails without preset or SQL."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, ['export', '--database', path])

    assert result.exit_code != 0
    assert 'Must specify either a PRESET, --sql, or --sql-file' in result.output


def test_export_multiple_sources_error(populated_db):
    """Test that export fails with multiple sources."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, [
        'export', '--database', path, 'plays',
        '--sql', 'SELECT * FROM artists'
    ])

    assert result.exit_code != 0
    assert 'Cannot specify more than one' in result.output


def test_export_invalid_sample_range(populated_db):
    """Test that export fails with invalid --sample value."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, [
        'export', '--database', path, 'plays',
        '--sample', '1.5'
    ])

    assert result.exit_code != 0
    assert '--sample must be between 0.0 and 1.0' in result.output


def test_export_sample_zero_error(populated_db):
    """Test that export fails with --sample 0.0."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, [
        'export', '--database', path, 'plays',
        '--sample', '0.0'
    ])

    assert result.exit_code != 0
    assert '--sample cannot be 0.0' in result.output


def test_export_seed_without_sample_error(populated_db):
    """Test that export fails with --seed but no --sample."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, [
        'export', '--database', path, 'plays',
        '--seed', '42'
    ])

    assert result.exit_code != 0
    assert '--seed requires --sample' in result.output


def test_export_sql_validation_warning(populated_db):
    """Test SQL validation warning for non-scrobble queries."""
    db, path = populated_db
    runner = CliRunner()

    # Query that doesn't reference scrobble tables
    result = runner.invoke(cli.cli, [
        'export', '--database', path,
        '--sql', 'SELECT 1 as num'
    ], input='n\n')  # Answer 'n' to the confirmation prompt

    assert result.exit_code == 1  # Should abort
    assert 'Warning:' in result.output
    assert 'does not reference scrobble tables' in result.output


def test_export_empty_result(temp_db):
    """Test exporting with empty results."""
    db, path = temp_db
    runner = CliRunner()

    # Initialize database structure by creating a dummy artist
    # Then query with a WHERE clause that returns no results
    artist = {"id": "temp-artist", "name": "Temp Artist"}
    lastfm.save_artist(db, artist)

    result = runner.invoke(cli.cli, [
        'export', '--database', path,
        '--sql', 'SELECT * FROM artists WHERE name = "nonexistent"',
        '--format', 'json'
    ])

    assert result.exit_code == 0, f"Command failed: {result.output}"
    assert result.output.strip() == '[]'


def test_export_with_limit_and_columns(populated_db):
    """Test combining --limit and --columns options."""
    db, path = populated_db
    runner = CliRunner()

    result = runner.invoke(cli.cli, [
        'export', '--database', path, 'plays',
        '--limit', '1',
        '--columns', 'artist_name',
        '--format', 'json'
    ])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert set(data[0].keys()) == {'artist_name'}
