"""
The first-party Datasette plugin shipped with scrobbledb.

Registered programmatically from `scrobbledb serve` via `datasette.plugins.pm`
rather than through a `datasette.plugins` entry point, so it never loads into
unrelated Datasette processes that happen to share the environment (design D3).
"""

from scrobbledb.datasette_plugin.functions import prepare_connection

__all__ = ["prepare_connection"]
