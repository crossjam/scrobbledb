"""Tests for scrobbledb sql subcommands."""
import pytest
import tempfile
import os
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

    artist = {"id": "artist-1", "name": "The Beatles"}
    album = {"id": "album-1", "title": "Abbey Road", "artist_id": "artist-1"}
    track = {"id": "track-1", "title": "Come Together", "album_id": "album-1"}
    play = {"track_id": "track-1", "timestamp": dt.datetime(2024, 1, 15, 14, 30, tzinfo=timezone.utc)}

    lastfm.save_artist(db, artist)
    lastfm.save_album(db, album)
    lastfm.save_track(db, track)
    lastfm.save_play(db, play)
    lastfm.setup_fts5(db)

    yield db, path


def test_sql_triggers_command(populated_db):
    """Test the sql triggers command."""
    db, path = populated_db
    runner = CliRunner()

    # Run the triggers command
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'triggers'])

    # Should succeed
    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Should contain trigger names
    assert 'artists_ai' in result.output or 'artists_ad' in result.output
    assert 'albums_ai' in result.output or 'albums_ad' in result.output
    assert 'tracks_ai' in result.output or 'tracks_ad' in result.output


def test_sql_triggers_command_specific_table(populated_db):
    """Test the sql triggers command with a specific table."""
    db, path = populated_db
    runner = CliRunner()

    # Run the triggers command for just the artists table
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'triggers', 'artists'])

    # Should succeed
    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Should only contain artist triggers
    assert 'artists' in result.output


def test_sql_indexes_command(populated_db):
    """Test the sql indexes command."""
    db, path = populated_db
    runner = CliRunner()

    # Run the indexes command
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'indexes'])

    # Should succeed
    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Should contain index information
    assert 'sqlite_autoindex' in result.output or 'index_name' in result.output


def test_sql_indexes_command_specific_table(populated_db):
    """Test the sql indexes command with a specific table."""
    db, path = populated_db
    runner = CliRunner()

    # Run the indexes command for just the artists table
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'indexes', 'artists'])

    # Should succeed
    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Should contain artists table in output
    assert 'artists' in result.output


def test_sql_tables_command(populated_db):
    """Test the sql tables command."""
    db, path = populated_db
    runner = CliRunner()

    # Run the tables command
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'tables'])

    # Should succeed
    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Should contain table names
    assert 'artists' in result.output
    assert 'albums' in result.output
    assert 'tracks' in result.output
    assert 'plays' in result.output


def test_sql_schema_command(populated_db):
    """Test the sql schema command."""
    db, path = populated_db
    runner = CliRunner()

    # Run the schema command
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'schema'])

    # Should succeed
    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Should contain CREATE TABLE statements
    assert 'CREATE TABLE' in result.output
    assert 'artists' in result.output


def test_sql_query_command(populated_db):
    """Test the sql query command."""
    db, path = populated_db
    runner = CliRunner()

    # Run a simple query
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'query', 'SELECT name FROM artists'])

    # Should succeed
    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Should contain the artist name
    assert 'The Beatles' in result.output


def test_sql_rows_command(populated_db):
    """Test the sql rows command."""
    db, path = populated_db
    runner = CliRunner()

    # Run the rows command for artists table
    # Use the full table name as the TABLE argument (not -t/--table which is for formatting)
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'rows', 'artists', '--limit', '10'])

    # Should succeed
    assert result.exit_code == 0, f"Command failed: {result.output}"

    # Should contain the artist data
    assert 'The Beatles' in result.output


def test_sql_triggers_output_formats(populated_db):
    """Test that triggers command works with different output formats."""
    db, path = populated_db
    runner = CliRunner()

    # Test CSV format
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'triggers', '--csv'])
    assert result.exit_code == 0, f"CSV command failed: {result.output}"

    # Test TSV format
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'triggers', '--tsv'])
    assert result.exit_code == 0, f"TSV command failed: {result.output}"

    # Test newline-delimited JSON format
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'triggers', '--nl'])
    assert result.exit_code == 0, f"NL command failed: {result.output}"


def test_sql_indexes_output_formats(populated_db):
    """Test that indexes command works with different output formats."""
    db, path = populated_db
    runner = CliRunner()

    # Test CSV format
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'indexes', '--csv'])
    assert result.exit_code == 0, f"CSV command failed: {result.output}"

    # Test TSV format
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'indexes', '--tsv'])
    assert result.exit_code == 0, f"TSV command failed: {result.output}"

    # Test newline-delimited JSON format
    result = runner.invoke(cli.cli, ['sql', '--database', path, 'indexes', '--nl'])
    assert result.exit_code == 0, f"NL command failed: {result.output}"


def test_sql_triggers_no_database_error():
    """Test that triggers command works with non-existent database."""
    runner = CliRunner()

    # Run triggers on a non-existent database
    # Note: sqlite-utils creates an empty database if it doesn't exist,
    # so this doesn't actually error but returns empty results
    result = runner.invoke(cli.cli, ['sql', '--database', '/tmp/test_nonexistent_triggers.db', 'triggers'])

    # Should succeed (sqlite-utils creates empty DB and returns empty results)
    assert result.exit_code == 0
    # Result should be an empty JSON array
    assert result.output.strip() == '[]'


def test_sql_indexes_no_database_error():
    """Test that indexes command works with non-existent database."""
    runner = CliRunner()

    # Run indexes on a non-existent database
    # Note: sqlite-utils creates an empty database if it doesn't exist,
    # so this doesn't actually error but returns empty results
    result = runner.invoke(cli.cli, ['sql', '--database', '/tmp/test_nonexistent_indexes.db', 'indexes'])

    # Should succeed (sqlite-utils creates empty DB and returns empty results)
    assert result.exit_code == 0
    # Result should be an empty JSON array
    assert result.output.strip() == '[]'


def test_sql_rows_order_by_validation_rejects_sql_injection(populated_db):
    """Test that ORDER BY validation rejects SQL injection attempts."""
    db, path = populated_db
    runner = CliRunner()

    # Test various SQL injection attempts in ORDER BY
    malicious_inputs = [
        "name; DROP TABLE artists",
        "name--",
        "name/*comment*/",
        "(SELECT 1)",
        "name UNION SELECT password FROM users",
        "name; DELETE FROM artists",
        "CASE WHEN (1=1) THEN name ELSE 0 END",
    ]

    for malicious in malicious_inputs:
        result = runner.invoke(cli.cli, [
            'sql', '--database', path, 'rows', 'artists',
            '--order', malicious
        ])

        # Should fail with error message
        assert result.exit_code != 0, f"Should reject malicious ORDER BY: {malicious}"
        assert "Invalid ORDER BY clause" in result.output, f"Should show error for: {malicious}"


def test_sql_rows_order_by_validation_allows_safe_input(populated_db):
    """Test that ORDER BY validation allows safe column references."""
    db, path = populated_db
    runner = CliRunner()

    # Test various safe ORDER BY clauses (using actual columns that exist)
    safe_inputs = [
        "name",
        "name ASC",
        "name DESC",
        "id, name",
        "id ASC, name DESC",
        "[name]",  # Bracketed identifiers
    ]

    for safe in safe_inputs:
        result = runner.invoke(cli.cli, [
            'sql', '--database', path, 'rows', 'artists',
            '--order', safe
        ])

        # Should succeed
        assert result.exit_code == 0, f"Should allow safe ORDER BY: {safe}, got error: {result.output}"


def test_sql_rows_order_by_validation_allows_bracketed_names(populated_db):
    """Test that ORDER BY validation allows bracketed column names with spaces."""
    db, path = populated_db
    runner = CliRunner()

    # Create a table with a column name that has spaces
    db.execute("""
        CREATE TABLE test_order_table (
            id INTEGER PRIMARY KEY,
            "artist name" TEXT
        )
    """)
    db.execute("""
        INSERT INTO test_order_table VALUES (1, 'The Beatles'), (2, 'Pink Floyd')
    """)
    db.conn.commit()  # Ensure data is committed

    # Test ORDER BY with bracketed identifier
    result = runner.invoke(cli.cli, [
        'sql', '--database', path, 'rows', 'test_order_table',
        '--order', '[artist name] DESC'
    ])

    assert result.exit_code == 0, f"Should allow bracketed ORDER BY: {result.output}"
    assert 'The Beatles' in result.output or 'Pink Floyd' in result.output


def test_sql_rows_column_quoting(populated_db):
    """Test that column names with spaces are properly quoted."""
    db, path = populated_db
    runner = CliRunner()

    # Create a table with column names that need quoting
    db.execute("""
        CREATE TABLE test_table (
            "column with spaces" TEXT,
            "another-column" TEXT
        )
    """)
    db.execute("""
        INSERT INTO test_table VALUES ('value1', 'value2')
    """)
    db.conn.commit()  # Ensure data is committed

    # Should properly quote column names
    result = runner.invoke(cli.cli, [
        'sql', '--database', path, 'rows', 'test_table',
        '-c', 'column with spaces',
        '-c', 'another-column'
    ])

    assert result.exit_code == 0, f"Failed to handle quoted columns: {result.output}"
    assert 'value1' in result.output
    assert 'value2' in result.output


def test_sql_rows_table_name_quoting(populated_db):
    """Test that table names with special characters are properly quoted."""
    db, path = populated_db
    runner = CliRunner()

    # Create a table with a name that needs quoting
    db.execute("""
        CREATE TABLE "table-with-dashes" (
            id INTEGER PRIMARY KEY,
            name TEXT
        )
    """)
    db.execute("""
        INSERT INTO "table-with-dashes" VALUES (1, 'test')
    """)
    db.conn.commit()  # Ensure data is committed

    # Should properly quote table name
    result = runner.invoke(cli.cli, [
        'sql', '--database', path, 'rows', 'table-with-dashes'
    ])

    assert result.exit_code == 0, f"Failed to handle quoted table: {result.output}"
    assert 'test' in result.output


def test_sql_rows_parameterized_where_clause(populated_db):
    """Test that parameterized queries work with WHERE clause."""
    db, path = populated_db
    runner = CliRunner()

    # Create additional test data
    import datetime as dt
    from datetime import timezone

    artist2 = {"id": "artist-2", "name": "Pink Floyd"}
    lastfm.save_artist(db, artist2)

    # Use parameterized query for WHERE clause
    result = runner.invoke(cli.cli, [
        'sql', '--database', path, 'rows', 'artists',
        '--where', 'name = :artist_name',
        '-p', 'artist_name', 'The Beatles'
    ])

    assert result.exit_code == 0, f"Parameterized query failed: {result.output}"
    assert 'The Beatles' in result.output
    assert 'Pink Floyd' not in result.output


def test_sql_rows_security_order_by_edge_cases(populated_db):
    """Test ORDER BY validation edge cases."""
    db, path = populated_db
    runner = CliRunner()

    # Test edge cases that should be rejected
    rejected_cases = [
        "name, (SELECT 1)",  # Subquery in list
        "name;",             # Trailing semicolon
        "name OR 1=1",       # SQL injection attempt
        "name AND DELETE",   # SQL keyword
    ]

    for test_case in rejected_cases:
        result = runner.invoke(cli.cli, [
            'sql', '--database', path, 'rows', 'artists',
            '--order', test_case
        ])
        assert result.exit_code != 0, f"Should reject: {test_case}"

    # Test edge cases that should be allowed
    allowed_cases = [
        "name",
        "id",
        "id, name",
    ]

    for test_case in allowed_cases:
        result = runner.invoke(cli.cli, [
            'sql', '--database', path, 'rows', 'artists',
            '--order', test_case
        ])
        assert result.exit_code == 0, f"Should allow: {test_case}, got: {result.output}"
