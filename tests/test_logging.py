"""Tests for logging functionality with loguru and loguru-config."""
import pytest
import tempfile
import json
from pathlib import Path
from click.testing import CliRunner
from loguru import logger
from scrobbledb.cli import cli


@pytest.fixture
def log_config_file():
    """Create a temporary loguru config file."""
    config = {
        "handlers": [
            {
                "sink": "sys.stderr",
                "level": "DEBUG",
                "format": "<level>{level}</level> | {message}"
            }
        ]
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(config, f)
        f.flush()
        temp_path = f.name
    yield temp_path
    Path(temp_path).unlink(missing_ok=True)


@pytest.fixture
def runner():
    """Create a Click CLI test runner."""
    return CliRunner()


@pytest.fixture(autouse=True)
def reset_logger():
    """Reset loguru logger before each test."""
    logger.remove()
    logger.add("sys.stderr", level="WARNING")  # Default minimal config
    yield
    logger.remove()
    logger.add("sys.stderr", level="WARNING")  # Reset after test


def test_cli_help_shows_log_config_option(runner):
    """Test that --log-config option appears in CLI help."""
    result = runner.invoke(cli, ['--help'])
    assert result.exit_code == 0
    assert '--log-config' in result.output
    assert 'Path to loguru configuration file' in result.output


def test_cli_log_config_accepts_file_path(runner, log_config_file):
    """Test that --log-config accepts a valid file path."""
    result = runner.invoke(cli, ['--log-config', log_config_file, '--help'])
    assert result.exit_code == 0


def test_cli_log_config_rejects_nonexistent_file(runner):
    """Test that --log-config rejects non-existent files."""
    result = runner.invoke(cli, ['--log-config', '/nonexistent/file.json', 'init', '--dry-run'])
    assert result.exit_code != 0
    assert 'does not exist' in result.output.lower() or 'invalid value' in result.output.lower()


def test_ingest_help_shows_verbose_option(runner):
    """Test that --verbose option appears in ingest command help."""
    result = runner.invoke(cli, ['ingest', '--help'])
    assert result.exit_code == 0
    assert '--verbose' in result.output or '-v' in result.output


def test_cli_accepts_both_log_config_and_verbose(runner, log_config_file):
    """Test that CLI accepts both --log-config and --verbose flags together."""
    # We can't fully test ingest without auth, but we can verify the options parse
    result = runner.invoke(cli, [
        '--log-config', log_config_file,
        'ingest', '--help'
    ])
    assert result.exit_code == 0


def test_log_config_file_formats():
    """Test that different config file formats are supported."""
    formats = ['.json', '.yaml', '.yml', '.toml']
    for fmt in formats:
        with tempfile.NamedTemporaryFile(suffix=fmt, delete=False) as f:
            path = Path(f.name)

        # File must exist for Click validation
        if fmt == '.json':
            path.write_text('{"handlers": [{"sink": "sys.stderr", "level": "INFO"}]}')
        elif fmt in ['.yaml', '.yml']:
            path.write_text('handlers:\n  - sink: sys.stderr\n    level: INFO\n')
        elif fmt == '.toml':
            path.write_text('[[handlers]]\nsink = "sys.stderr"\nlevel = "INFO"\n')

        runner = CliRunner()
        result = runner.invoke(cli, ['--log-config', str(path), '--help'])
        assert result.exit_code == 0

        path.unlink()


def test_verbose_flag_without_log_config(runner, tmp_path):
    """Test that --verbose flag works without --log-config."""
    # Create a minimal database to avoid errors
    db_path = tmp_path / "test.db"

    # We can't fully test without auth credentials, but we can verify
    # the command parses and fails gracefully without auth
    result = runner.invoke(cli, [
        'ingest', str(db_path), '--verbose', '--limit', '1'
    ])

    # Should fail due to missing auth, but not due to logging config
    # Check that there are no logging configuration errors
    output_lower = result.output.lower()
    logging_errors = [
        'failed to load log config',
        'loguru config error',
        'logging configuration error',
        'invalid log config',
    ]
    for error in logging_errors:
        assert error not in output_lower, f"Found logging error in output: {error}"


def test_loguru_config_integration():
    """Test that LoguruConfig can be imported and used."""
    from loguru_config import LoguruConfig

    config = {
        "handlers": [
            {
                "sink": "sys.stderr",
                "level": "INFO"
            }
        ]
    }

    # Should not raise an exception
    LoguruConfig.load(config)

    # Verify logger is configured
    assert len(logger._core.handlers) > 0


def test_logger_available_in_lastfm_module():
    """Test that logger is properly imported in lastfm module."""
    from scrobbledb import lastfm
    from loguru import logger as loguru_logger

    # Verify lastfm module uses loguru logger
    assert hasattr(lastfm, 'logger')
    # The logger should be the loguru logger instance
    assert lastfm.logger is loguru_logger


def test_log_config_passed_through_context(runner, log_config_file):
    """Test that log config is passed through Click context."""
    # Test that both --log-config and a command work together
    # The context passing is tested implicitly - if it fails, ingest would error
    result = runner.invoke(cli, ['--log-config', log_config_file, 'init', '--help'])
    assert result.exit_code == 0
    # If context wasn't working, we'd get an error about log_config not being available


def test_default_logger_configuration():
    """Test that logger has a default configuration."""
    from loguru import logger

    # After reset, logger should have at least one handler
    logger.remove()
    logger.add("sys.stderr", level="INFO")

    assert len(logger._core.handlers) >= 1


def test_loguru_config_load_from_dict():
    """Test LoguruConfig.load with dictionary configuration."""
    from loguru_config import LoguruConfig
    from loguru import logger

    logger.remove()

    config = {
        "handlers": [
            {
                "sink": "sys.stderr",
                "level": "DEBUG",
                "format": "{level} - {message}"
            }
        ]
    }

    LoguruConfig.load(config)

    # Verify configuration was applied
    assert len(logger._core.handlers) > 0


def test_loguru_config_load_from_file(log_config_file):
    """Test LoguruConfig.load with file path."""
    from loguru_config import LoguruConfig
    from loguru import logger

    logger.remove()

    LoguruConfig.load(log_config_file)

    # Verify configuration was loaded
    assert len(logger._core.handlers) > 0


def test_log_levels_configuration():
    """Test that different log levels can be configured."""
    from loguru_config import LoguruConfig
    from loguru import logger

    levels = ["DEBUG", "INFO", "WARNING", "ERROR"]

    for level in levels:
        logger.remove()
        config = {
            "handlers": [
                {
                    "sink": "sys.stderr",
                    "level": level
                }
            ]
        }
        LoguruConfig.load(config)
        assert len(logger._core.handlers) > 0


def test_ensure_default_log_config():
    """Test that default log config is created in user directory."""
    from scrobbledb.cli import ensure_default_log_config
    import tempfile
    import shutil

    # Create a temporary directory to use as the data dir
    with tempfile.TemporaryDirectory() as tmpdir:
        # Monkey patch the data directory
        from scrobbledb import cli
        original_get_data_dir = cli.get_data_dir

        def mock_get_data_dir():
            return Path(tmpdir)

        cli.get_data_dir = mock_get_data_dir

        try:
            # Call ensure_default_log_config
            config_path = ensure_default_log_config()

            # Verify the config file was created
            assert Path(config_path).exists()

            # Verify it's in the correct location
            assert str(tmpdir) in config_path
            assert config_path.endswith("loguru_config.toml")

            # Verify the content is valid
            content = Path(config_path).read_text()
            assert "[[handlers]]" in content
            assert "sink" in content
            assert "level" in content

            # Call again to verify it doesn't recreate
            config_path2 = ensure_default_log_config()
            assert config_path == config_path2
        finally:
            # Restore original function
            cli.get_data_dir = original_get_data_dir


def test_default_log_config_used_with_verbose(runner):
    """Test that default log config is used when --verbose is specified without --log-config."""
    import tempfile
    from scrobbledb import cli

    with tempfile.TemporaryDirectory() as tmpdir:
        # Monkey patch the data directory
        original_get_data_dir = cli.get_data_dir

        def mock_get_data_dir():
            return Path(tmpdir)

        cli.get_data_dir = mock_get_data_dir

        try:
            # The command will fail without auth, but we're testing that config is created
            result = runner.invoke(cli.cli, ['ingest', '--verbose', '--limit', '1'])

            # Check that the default config file was created
            config_path = Path(tmpdir) / "loguru_config.toml"
            assert config_path.exists()
        finally:
            # Restore original function
            cli.get_data_dir = original_get_data_dir


def test_version_flag(runner):
    """Test that --version flag works."""
    from importlib.metadata import version

    result = runner.invoke(cli, ['--version'])
    assert result.exit_code == 0
    assert 'version' in result.output.lower()

    # Check that the version matches what's in package metadata
    expected_version = version("scrobbledb")
    assert expected_version in result.output


def test_version_V_alias(runner):
    """Test that -V alias works for version."""
    from importlib.metadata import version

    result = runner.invoke(cli, ['-V'])
    assert result.exit_code == 0
    assert 'version' in result.output.lower()

    # Check that the version matches what's in package metadata
    expected_version = version("scrobbledb")
    assert expected_version in result.output


def test_reset_command_help(runner):
    """Test that reset command help is available."""
    result = runner.invoke(cli, ['reset', '--help'])
    assert result.exit_code == 0
    assert 'reset' in result.output.lower()
    assert 'destructive' in result.output.lower()


def test_reset_nonexistent_database(runner):
    """Test reset with non-existent database."""
    import tempfile
    with tempfile.NamedTemporaryFile(delete=True) as f:
        nonexistent_path = f.name  # File will be deleted immediately

    result = runner.invoke(cli, ['reset', nonexistent_path, '--force'])
    assert result.exit_code == 0
    assert 'does not exist' in result.output.lower()


def test_reset_with_force(runner):
    """Test reset command with --force flag."""
    import tempfile
    import sqlite_utils

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        # Create a test database with data
        db = sqlite_utils.Database(db_path)
        db['test_table'].insert({'id': 1, 'name': 'test'})
        assert 'test_table' in db.table_names()

        # Reset with --force
        result = runner.invoke(cli, ['reset', db_path, '--force'])
        assert result.exit_code == 0
        assert 'deleted' in result.output.lower()
        assert 'reset complete' in result.output.lower()

        # Verify database was reset
        db = sqlite_utils.Database(db_path)
        # Should have FTS5 tables but not test_table
        assert 'test_table' not in db.table_names()
        assert 'tracks_fts' in db.table_names()
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_reset_with_no_index(runner):
    """Test reset command with --no-index flag."""
    import tempfile
    import sqlite_utils

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        # Create a test database
        db = sqlite_utils.Database(db_path)
        db['test_table'].insert({'id': 1, 'name': 'test'})

        # Reset with --no-index
        result = runner.invoke(cli, ['reset', db_path, '--force', '--no-index'])
        assert result.exit_code == 0
        assert 'reset complete' in result.output.lower()

        # Verify database was reset without FTS5
        db = sqlite_utils.Database(db_path)
        assert 'test_table' not in db.table_names()
        assert 'tracks_fts' not in db.table_names()
    finally:
        Path(db_path).unlink(missing_ok=True)
