"""
Fixtures shared across the test suite.

Nothing here imports `datasette` at module level. It is an optional extra, and
a suite run without it has to skip the modules that need it rather than fail to
collect this file.
"""

import pytest

from scrobbledb import lastfm
from tests.library_fixture import populate

pytest_plugins = ["pytester"]


@pytest.fixture(autouse=True)
def isolate_datasette_plugins():
    """
    Remove any plugin a test registered with Datasette's plugin manager.

    `pm` is process-global, so a registration left behind -- by a fixture, or
    by `serve` itself, which registers before building the server -- would
    apply to every later test in the session, and the next attempt to register
    the same module would raise (design D3). The same shape as the autouse
    `reset_logger` in `tests/test_logging.py`.

    Taken as a snapshot rather than a list of names, so a plugin registered
    under a name nobody wrote down here is removed too.
    """
    try:
        from datasette.plugins import pm
    except ImportError:
        yield
        return

    before = {name for name, _ in pm.list_name_plugin()}
    yield
    for name, _ in pm.list_name_plugin():
        if name not in before:
            pm.unregister(name=name)


@pytest.fixture
def registered_plugin():
    """
    Register the scrobbledb plugin the way `serve` does, before any Datasette
    is built. `isolate_datasette_plugins` removes it afterwards.
    """
    from datasette.plugins import pm

    from scrobbledb import datasette_plugin

    pm.register(datasette_plugin, name="scrobbledb-test")


@pytest.fixture
def populated_db(tmp_path):
    """
    A populated scrobbledb database: 10 plays, 2 artists, 3 albums, 5 tracks,
    with the search index built.

    The index is built through the production seam -- the same two functions
    `scrobbledb index` calls -- rather than by a hand-written CREATE VIRTUAL
    TABLE, so a change to the indexed columns reaches this fixture.

    Modules testing the CLI's own query layer (`test_stats.py` and others)
    define a `populated_db` of their own, which takes precedence there.
    """
    path = tmp_path / "scrobbles.db"
    db = populate(path)
    lastfm.setup_fts5(db)
    lastfm.rebuild_fts5(db)
    db.conn.commit()
    db.close()
    return path


@pytest.fixture
def unindexed_db(tmp_path):
    """The same database with the base tables but no search index built."""
    path = tmp_path / "scrobbles.db"
    db = populate(path)
    db.conn.commit()
    db.close()
    return path
