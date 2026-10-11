"""
Tests for `scrobbledb serve`.

Two seams are used. Most behaviour -- database resolution, the startup
warnings, the bound-port error -- is decided before the server starts, so those
tests run the real command through `CliRunner` with `run_server` replaced by a
recorder: everything up to the event loop is production code. What can only be
seen on a live server -- the printed URLs answering, the plugin loaded, a clean
exit on Ctrl+C, the file left untouched -- runs `scrobbledb serve` as a
subprocess on a kernel-chosen port.
"""

import hashlib
import os
import queue
import re
import shlex
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request

import pytest
from click.testing import CliRunner

pytest.importorskip("datasette")
pytest.importorskip("pytest_asyncio")

import sqlite_utils  # noqa: E402

from scrobbledb import serve as serve_module  # noqa: E402
from scrobbledb.analytics_indexes import ANALYTICS_INDEXES  # noqa: E402
from scrobbledb.cli import cli  # noqa: E402

from tests import test_datasette_queries as catalog_tests  # noqa: E402

populated_db = catalog_tests.populated_db

SCROBBLE_TABLES = {"artists", "albums", "tracks", "plays"}


# --------------------------------------------------------------------------
# Fixtures and helpers
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def unregister_plugin():
    """
    `serve` registers the plugin with Datasette's process-global plugin
    manager, so every test here removes it afterwards (design D3). Left behind,
    it would make the next fixture that registers the same module raise.
    """
    yield
    from datasette.plugins import pm

    for name in (serve_module.PLUGIN_NAME, serve_module.MCP_PLUGIN_NAME):
        if pm.get_plugin(name) is not None:
            pm.unregister(name=name)


@pytest.fixture
def recorded_start(monkeypatch):
    """Replace the event loop with a recorder of what it would have served."""
    started = []

    async def record(ds, sock, host):
        started.append(
            {
                "paths": [db.path for db in ds.databases.values() if db.path],
                "port": sock.getsockname()[1],
                "host": host,
            }
        )

    monkeypatch.setattr(serve_module, "run_server", record)
    return started


@pytest.fixture
def indexed_db(populated_db):
    """`populated_db` with the analytics indexes created."""
    db = sqlite_utils.Database(populated_db)
    for statement in ANALYTICS_INDEXES.values():
        db.execute(statement)
    db.conn.commit()
    db.close()
    return populated_db


@pytest.fixture
def unpopulated_db(tmp_path):
    """A database file that exists but has never been ingested into."""
    path = tmp_path / "empty.db"
    db = sqlite_utils.Database(path)
    db["notes"].insert({"id": 1})
    db.close()
    return path


def invoke(*args):
    return CliRunner().invoke(cli, ["serve", *args], catch_exceptions=False)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def index_names(path):
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    finally:
        conn.close()


def subprocess_env():
    env = os.environ.copy()
    env.pop("FORCE_COLOR", None)
    env["COLUMNS"] = "200"
    return env


class LiveServer:
    """`scrobbledb serve` running as a real process on a kernel-chosen port."""

    #: Seconds to wait for the startup announcement before failing the test.
    STARTUP_TIMEOUT = 60

    def __init__(self, database):
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "scrobbledb", "serve", "-d", str(database), "--port", "0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=subprocess_env(),
        )
        # Both pipes are drained by threads for the life of the process, so the
        # startup wait below is a queue read with a timeout rather than a
        # `readline()` that blocks forever when startup stalls silently.
        self.stdout = queue.Queue()
        self.stderr = []
        self.readers = [
            threading.Thread(target=self._drain_stdout, daemon=True),
            threading.Thread(target=self._drain_stderr, daemon=True),
        ]
        for reader in self.readers:
            reader.start()

        self.lines = []
        deadline = time.monotonic() + self.STARTUP_TIMEOUT
        while not (self.lines and self.lines[-1].startswith("Press Ctrl+C")):
            # Checked before every read, not only when the queue runs dry: a
            # server printing endlessly would otherwise never reach the timeout.
            remaining = deadline - time.monotonic()
            try:
                if remaining <= 0:
                    raise queue.Empty
                line = self.stdout.get(timeout=remaining)
            except queue.Empty:
                self.kill()
                pytest.fail(
                    f"server did not finish starting within {self.STARTUP_TIMEOUT}s:"
                    f" {self.lines[-20:]!r} {self.err[-2000:]!r}"
                )
            if line is None:
                break
            self.lines.append(line)
        match = re.search(r"Serving scrobbledb at (\S+)", "".join(self.lines))
        if not match:
            self.kill()
            pytest.fail(f"no URL printed: {self.lines!r} {self.err!r}")
        self.url = match.group(1)

    def _drain_stdout(self):
        for line in self.proc.stdout:
            self.stdout.put(line)
        self.stdout.put(None)

    def _drain_stderr(self):
        for line in self.proc.stderr:
            self.stderr.append(line)

    @property
    def err(self):
        return "".join(self.stderr)

    def _finish(self):
        self.proc.wait(timeout=30)
        for reader in self.readers:
            reader.join(timeout=10)
        while not self.stdout.empty():
            line = self.stdout.get_nowait()
            if line is not None:
                self.lines.append(line)

    def get(self, path=""):
        with urllib.request.urlopen(self.url + path, timeout=10) as response:
            return response.status, response.read().decode()

    def interrupt(self):
        self.proc.send_signal(signal.SIGINT)
        self._finish()
        return self.proc.returncode, "".join(self.lines), self.err

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self._finish()


@pytest.fixture
def live_server():
    servers = []

    def start(database):
        server = LiveServer(database)
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.kill()


# --------------------------------------------------------------------------
# 7.1 / 7.2  The command exists, and without the extra it says how to get it
# --------------------------------------------------------------------------


def test_serve_help_exits_zero():
    result = invoke("--help")
    assert result.exit_code == 0
    for option in ("--database", "--host", "--port", "127.0.0.1", "8001"):
        assert option in result.output


#: Run the CLI with `datasette` made unimportable. A `None` entry in
#: `sys.modules` makes every import of that name raise ImportError, which is
#: what an environment without the extra looks like to the code under test.
WITHOUT_EXTRA = """
import sys
for name in ("datasette", "datasette.app", "uvicorn"):
    sys.modules[name] = None
from scrobbledb.cli import cli
cli(sys.argv[1:], prog_name="scrobbledb")
"""


def run_without_extra(*args):
    return subprocess.run(
        [sys.executable, "-c", WITHOUT_EXTRA, *args],
        capture_output=True,
        text=True,
        env=subprocess_env(),
        timeout=60,
    )


def test_help_works_without_the_extra():
    for args in (["serve", "--help"], ["--help"]):
        result = run_without_extra(*args)
        assert result.returncode == 0, result.stderr
        assert "Traceback" not in result.stderr


def test_serve_without_the_extra_names_it(populated_db):
    result = run_without_extra("serve", "-d", str(populated_db))
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "serve" in result.stderr and "extra" in result.stderr
    assert "scrobbledb[serve]" in result.stderr


# --------------------------------------------------------------------------
# 7.3 / 7.4  Database resolution and the unpopulated pre-flight
# --------------------------------------------------------------------------


def test_missing_database_names_the_path(tmp_path, recorded_start):
    missing = tmp_path / "nowhere.db"
    result = invoke("-d", str(missing))
    assert result.exit_code != 0
    assert str(missing) in result.output.replace("\n", "")
    assert "scrobbledb config init" in result.output
    assert not recorded_start, "a server started against a missing database"


def test_missing_default_database_names_the_default(tmp_path, monkeypatch, recorded_start):
    default = tmp_path / "default.db"
    monkeypatch.setattr(serve_module, "get_default_db_path", lambda: str(default))
    result = invoke()
    assert result.exit_code != 0
    assert str(default) in result.output.replace("\n", "")
    assert not recorded_start


def test_database_option_overrides_the_default(
    tmp_path, monkeypatch, populated_db, recorded_start
):
    """The default is pointed at a missing file, so only the override can start."""
    monkeypatch.setattr(
        serve_module, "get_default_db_path", lambda: str(tmp_path / "absent.db")
    )
    result = invoke("-d", str(populated_db), "--port", "0")
    assert result.exit_code == 0, result.output
    assert recorded_start[0]["paths"] == [str(populated_db)]


def test_unpopulated_database_warns_and_still_starts(unpopulated_db, recorded_start):
    result = invoke("-d", str(unpopulated_db), "--port", "0")
    assert result.exit_code == 0, result.output
    assert "no plays" in result.output
    assert "scrobbledb ingest" in result.output
    assert recorded_start, "the server did not start"


def test_populated_database_does_not_warn_about_plays(indexed_db, recorded_start):
    result = invoke("-d", str(indexed_db), "--port", "0")
    assert result.exit_code == 0, result.output
    assert "scrobbledb ingest" not in result.output


# --------------------------------------------------------------------------
# 7.5  Plugin registration
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_built_server_lists_the_plugin(populated_db):
    """
    Datasette names plugins by module `__name__` in `/-/plugins.json`, not by
    the name they were registered under, so that is what is asserted.
    """
    from datasette.plugins import pm

    from scrobbledb import datasette_plugin

    ds = serve_module.build_datasette(populated_db)
    try:
        assert pm.get_plugin(serve_module.PLUGIN_NAME) is datasette_plugin
        response = await ds.client.get("/-/plugins.json")
        names = {plugin["name"] for plugin in response.json()}
        assert datasette_plugin.__name__ in names
    finally:
        ds.close()


def test_registration_is_idempotent(populated_db):
    """A second build in the same process must not raise on re-registration."""
    serve_module.build_datasette(populated_db).close()
    serve_module.build_datasette(populated_db).close()


# --------------------------------------------------------------------------
# 7.7  Announced URLs
# --------------------------------------------------------------------------


def test_announce_prints_both_urls(capsys):
    serve_module.announce("127.0.0.1", 9000)
    out = capsys.readouterr().out
    assert "http://127.0.0.1:9000/" in out
    assert "http://127.0.0.1:9000/-/mcp" in out


def test_announce_without_mcp_says_how_to_enable_it(capsys, monkeypatch):
    monkeypatch.setattr(serve_module, "mcp_available", lambda: False)
    serve_module.announce("0.0.0.0", 9000)
    out = capsys.readouterr().out
    assert "http://0.0.0.0:9000/" in out
    assert "/-/mcp" not in out
    assert "unavailable" in out and "serve" in out


# --------------------------------------------------------------------------
# 7.8 / 7.9  Startup warnings: report, never repair
# --------------------------------------------------------------------------


def test_missing_analytics_indexes_warn(populated_db):
    warnings = serve_module.startup_warnings(populated_db)
    assert any("scrobbledb index --analytics" in w for w in warnings), warnings


def test_present_analytics_indexes_do_not_warn(indexed_db):
    assert not any(
        "--analytics" in w for w in serve_module.startup_warnings(indexed_db)
    )


def test_equivalent_indexes_under_other_names_do_not_warn(populated_db):
    """
    The warning follows what the indexes cover, so a database indexed by hand
    is not told to run a command that would create nothing.
    """
    conn = sqlite3.connect(populated_db)
    conn.execute("CREATE INDEX a ON plays(track_id)")
    conn.execute("CREATE INDEX b ON tracks(album_id, title)")
    conn.execute("CREATE INDEX c ON albums(artist_id)")
    conn.commit()
    conn.close()
    assert not any(
        "--analytics" in w for w in serve_module.startup_warnings(populated_db)
    )


def test_each_missing_analytics_index_is_detected(indexed_db):
    """Dropping any single index is enough to bring the warning back."""
    assert len(ANALYTICS_INDEXES) >= 3
    for name, statement in ANALYTICS_INDEXES.items():
        conn = sqlite3.connect(indexed_db)
        conn.execute(f"DROP INDEX {name}")
        conn.commit()
        try:
            warnings = serve_module.startup_warnings(indexed_db)
            assert any("--analytics" in w for w in warnings), name
        finally:
            conn.execute(statement)
            conn.commit()
            conn.close()


def drop_from_search_index(path, count):
    conn = sqlite3.connect(path)
    conn.execute(
        "DELETE FROM tracks_fts WHERE rowid IN"
        " (SELECT rowid FROM tracks_fts LIMIT ?)",
        (count,),
    )
    conn.commit()
    conn.close()


def test_short_search_index_warns_with_the_shortfall(indexed_db):
    total = sqlite3.connect(indexed_db).execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    assert total >= 3, "fixture too small to leave a distinct shortfall"
    drop_from_search_index(indexed_db, 2)

    warnings = serve_module.startup_warnings(indexed_db)
    stale = [w for w in warnings if "search index" in w]
    assert stale, warnings
    assert f"{total - 2:,} of {total:,}" in stale[0]
    assert "2 missing" in stale[0]
    assert "scrobbledb index" in stale[0]


def test_matching_search_index_does_not_warn(indexed_db):
    assert serve_module.startup_warnings(indexed_db) == []


def test_absent_search_index_warns(tmp_path):
    path = tmp_path / "scrobbles.db"
    catalog_tests._populate(path).close()
    warnings = serve_module.startup_warnings(path)
    assert any("search index covers 0 of" in w for w in warnings), warnings


def remedies_for_every_warning(tmp_path, name):
    """
    Two databases at `tmp_path / name` that between them raise every warning:
    one never ingested into, one with no analytics indexes and a short search
    index. Returns the warnings from both, served as if named explicitly.
    """
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    empty = tmp_path / "a" / name
    sqlite_utils.Database(empty)["notes"].insert({"id": 1})
    short = tmp_path / "b" / name
    catalog_tests._populate(short).close()
    return {
        empty: serve_module.startup_warnings(empty, explicit=True),
        short: serve_module.startup_warnings(short, explicit=True),
    }


def test_every_remedy_names_an_explicit_database(tmp_path):
    """
    The remedy commands default to the XDG database, so a remedy for a database
    named with `--database` that left the path off would repair the wrong file.
    The path has a space in it, so it must arrive shell-quoted.
    """
    found = remedies_for_every_warning(tmp_path, "my scrobbles.db")
    warnings = [w for ws in found.values() for w in ws]
    assert len(warnings) >= 3, "fixtures do not raise every warning"
    for path, ws in found.items():
        for warning in ws:
            assert f"{shlex.quote(str(path))}`" in warning, warning


def test_remedies_for_the_default_database_name_no_path(populated_db):
    drop_from_search_index(populated_db, 1)
    warnings = serve_module.startup_warnings(populated_db)
    assert len(warnings) == 2
    for warning in warnings:
        assert str(populated_db) not in warning


def test_a_path_with_markup_characters_prints_intact(
    tmp_path, monkeypatch, recorded_start
):
    """Rich would read `[b]` in a path as markup and drop it from the remedy."""
    monkeypatch.chdir(tmp_path)
    sqlite_utils.Database("a [b].db")["notes"].insert({"id": 1})
    result = invoke("-d", "a [b].db", "--port", "0")
    assert result.exit_code == 0, result.output
    assert "scrobbledb ingest 'a [b].db'" in result.output


# --------------------------------------------------------------------------
# 7.10  Bound port
# --------------------------------------------------------------------------


def test_bound_port_names_the_port(populated_db, recorded_start):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    port = blocker.getsockname()[1]
    try:
        result = invoke("-d", str(populated_db), "--port", str(port))
    finally:
        blocker.close()
    assert result.exit_code != 0
    assert f"Port {port}" in result.output and "--port" in result.output
    assert not recorded_start


# --------------------------------------------------------------------------
# 7.6 / 7.7 / 7.8 / 7.9 / 7.10  A real session
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform == "win32", reason="interrupts the server with SIGINT, which is POSIX-only"
)
def test_live_session(live_server, populated_db):
    """
    Start the real command, browse it, interrupt it.

    The database lacks the analytics indexes and has a short search index, so
    the same session proves that both are reported and neither is repaired,
    and the hash proves nothing else was written either.
    """
    drop_from_search_index(populated_db, 1)
    indexes_before = index_names(populated_db)
    fts_before = sqlite3.connect(populated_db).execute(
        "SELECT COUNT(*) FROM tracks_fts"
    ).fetchone()[0]
    digest = sha256(populated_db)

    server = live_server(populated_db)
    assert re.match(r"http://127\.0\.0\.1:\d+/$", server.url)
    assert f"MCP endpoint at {server.url}-/mcp" in "".join(server.lines)

    status, body = server.get()
    assert status == 200
    status, body = server.get(populated_db.stem)
    assert status == 200
    for table in SCROBBLE_TABLES:
        assert f'href="/{populated_db.stem}/{table}"' in body, table
    for table in SCROBBLE_TABLES:
        assert server.get(f"{populated_db.stem}/{table}")[0] == 200

    returncode, out, err = server.interrupt()
    assert returncode == 0, err
    assert "Traceback" not in err
    assert "scrobbledb index --analytics" in err
    assert "search index covers" in err

    assert index_names(populated_db) == indexes_before
    assert not set(ANALYTICS_INDEXES) & index_names(populated_db)
    assert sqlite3.connect(populated_db).execute(
        "SELECT COUNT(*) FROM tracks_fts"
    ).fetchone()[0] == fts_before
    assert sha256(populated_db) == digest
