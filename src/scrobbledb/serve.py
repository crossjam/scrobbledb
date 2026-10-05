"""
Serve a scrobbledb database over HTTP with an embedded Datasette.

Datasette runs in this process rather than as a `datasette` subprocess, so the
scrobbledb plugin can be registered programmatically and stays scoped to the
servers this command starts (design D1, D3).

Nothing here imports `datasette` or `uvicorn` at module level. Both belong to
the optional `serve` extra, and `scrobbledb serve --help` -- which the docs
generation test runs in-process -- has to work without it (design D2).
"""

import asyncio
import errno
import shlex
import socket
import sqlite3
from pathlib import Path

import click
from rich.markup import escape

from .analytics_indexes import missing_analytics_indexes
from .command_utils import check_database, console, database_option
from .config_utils import get_default_db_path

#: Name the scrobbledb plugin is registered under, and therefore the name
#: `/-/plugins.json` reports it by.
PLUGIN_NAME = "scrobbledb"

#: How to get the dependencies this command needs, for the error shown
#: without them.
INSTALL_HINT = (
    "The web server needs the 'serve' extra. Install it with "
    "`uv sync --extra serve` or `pip install 'scrobbledb[serve]'`."
)


def startup_warnings(path, explicit: bool = False) -> list[str]:
    """
    Everything worth telling the user about the database before serving it.

    When the database was named with `--database`, every remedy names it too:
    the commands default to the XDG database, and a remedy that silently acted
    on a different file would leave the reported problem in place.

    Read through a `mode=ro` connection: these checks are the only access
    `serve` makes outside Datasette, and they must not be the exception to its
    read-only guarantee. Each one reports a remedy and none applies it.
    """
    target = f" {shlex.quote(str(path))}" if explicit else ""
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "plays" not in tables:
            return [
                "This database has no plays yet. "
                f"Run `scrobbledb ingest{target}` to import your listening history."
            ]

        warnings = []
        missing = missing_analytics_indexes(conn)
        if missing:
            warnings.append(
                f"{len(missing)} analytics index(es) are missing, so analytical "
                f"queries may be slow. Run `scrobbledb index --analytics{target}` to create them."
            )

        if "tracks" in tables:
            track_count = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
            indexed = (
                conn.execute("SELECT COUNT(*) FROM tracks_fts").fetchone()[0]
                if "tracks_fts" in tables
                else 0
            )
            if indexed < track_count:
                warnings.append(
                    f"The search index covers {indexed:,} of {track_count:,} tracks "
                    f"({track_count - indexed:,} missing), so search results will be "
                    f"incomplete. Run `scrobbledb index{target}` to rebuild it."
                )
        return warnings
    finally:
        conn.close()


def register_plugin() -> None:
    """Register the scrobbledb plugin with Datasette, once per process."""
    from datasette.plugins import pm

    from scrobbledb import datasette_plugin

    if not pm.is_registered(datasette_plugin):
        pm.register(datasette_plugin, name=PLUGIN_NAME)


def build_datasette(path):
    """
    A Datasette serving `path` read-only with scrobbledb's customizations.

    The plugin is registered before construction, because `prepare_connection`
    and the stored queries are consulted from construction onward.
    """
    from datasette.app import Datasette

    from scrobbledb.datasette_plugin import add_read_only_database
    from scrobbledb.datasette_plugin import config as plugin_config

    register_plugin()
    name = Path(path).stem
    ds = Datasette(
        metadata=plugin_config.load_metadata(name),
        config=plugin_config.load_config(name),
    )
    add_read_only_database(ds, path, name=name)
    return ds


def mcp_available() -> bool:
    """Whether `datasette-mcp`, which owns the `/-/mcp` endpoint, is installed."""
    try:
        import datasette_mcp  # noqa: F401
    except ImportError:
        return False
    return True


def bind_socket(host: str, port: int) -> socket.socket:
    """
    Bind the listening socket before anything else starts.

    Binding here rather than inside uvicorn turns an address already in use
    into an error this command can word, instead of a uvicorn log line and a
    bare exit.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as e:
        sock.close()
        if e.errno == errno.EADDRINUSE:
            raise click.ClickException(
                f"Port {port} on {host} is already in use. Stop whatever is "
                f"listening there or choose another with --port."
            ) from e
        raise click.ClickException(f"Cannot listen on {host}:{port}: {e}") from e
    sock.listen(socket.SOMAXCONN)
    sock.setblocking(False)
    return sock


def display_host(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def announce(host: str, port: int) -> None:
    """Print where the web UI and the MCP endpoint can be reached."""
    base = f"http://{display_host(host)}:{port}"
    click.echo(f"Serving scrobbledb at {base}/")
    if mcp_available():
        click.echo(f"MCP endpoint at {base}/-/mcp")
    else:
        click.echo(
            "MCP endpoint unavailable: datasette-mcp is not installed. "
            "Install the 'serve' extra to enable it."
        )
    click.echo("Press Ctrl+C to stop.")


async def run_server(ds, sock: socket.socket, host: str) -> None:
    """Start Datasette, announce where it is, and serve until interrupted."""
    import uvicorn

    await ds.invoke_startup()

    announce(host, sock.getsockname()[1])

    server = uvicorn.Server(uvicorn.Config(ds.app(), log_level="warning"))
    await server.serve(sockets=[sock])


@click.command()
@database_option
@click.option(
    "--host",
    default="127.0.0.1",
    show_default=True,
    help="Interface to listen on. Anything other than localhost exposes your history.",
)
@click.option(
    "--port",
    type=click.IntRange(0, 65535),
    default=8001,
    show_default=True,
    help="Port to listen on.",
)
@click.pass_context
def serve(ctx, database, host, port):
    """
    Browse and query your scrobbles in a web browser.

    Starts a read-only Datasette web server over the database, with
    scrobbledb's stored queries and an MCP endpoint for AI assistants.
    The server runs in the foreground until interrupted with Ctrl+C.

    If --database is not specified, uses the default location in the XDG data
    directory.
    """
    try:
        import datasette.app  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as e:
        raise click.ClickException(INSTALL_HINT) from e

    path = database or get_default_db_path()
    check_database(ctx, path).close()
    sock = bind_socket(host, port)

    for warning in startup_warnings(path, explicit=database is not None):
        console.print(f"[yellow]![/yellow] {escape(warning)}")

    ds = build_datasette(path)
    try:
        asyncio.run(run_server(ds, sock, host))
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        ds.close()
