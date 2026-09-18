"""
The first-party Datasette plugin shipped with scrobbledb.

Registered programmatically from `scrobbledb serve` via `datasette.plugins.pm`
rather than through a `datasette.plugins` entry point, so it never loads into
unrelated Datasette processes that happen to share the environment (design D3).

Pluggy discovers hookimpls as attributes of the registered module, so every
hook the plugin implements has to be named here -- it lives in a submodule for
readability, but only what this module re-exports is actually wired up.
"""

from scrobbledb.datasette_plugin.functions import prepare_connection
from scrobbledb.datasette_plugin.queries import startup

__all__ = ["prepare_connection", "startup"]
