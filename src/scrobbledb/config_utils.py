"""
Configuration utilities for scrobbledb.

This module provides helper functions for getting configuration paths
and directories.
"""

from pathlib import Path
from platformdirs import user_data_dir, user_config_dir

APP_NAME = "dev.pirateninja.scrobbledb"


def get_data_dir():
    """Get the XDG compliant data directory for the app."""
    return Path(user_data_dir(APP_NAME))


def get_default_auth_path():
    """Get the default path for the auth.json file in XDG compliant directory."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "auth.json")


def get_default_db_path():
    """Get the default path for the database in XDG compliant directory."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "scrobbledb.db")


def get_default_log_config_path():
    """Get the default path for the log config file in XDG compliant directory."""
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / "loguru_config.toml")
