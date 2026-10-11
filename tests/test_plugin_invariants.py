"""
Guard tests for invariants of the Datasette plugin rather than features of it.

- **SQLite is reached only through Datasette** (design D4). A plugin module
  that opened its own connection would bypass the thread pool, the time limit,
  row truncation and the read-only connection setup, and nothing else in the
  suite would notice because the rows would still be right.

- **One analytic, one source of SQL.** The canned query, the MCP tool and the
  CLI function for the same analytic share a builder, so they return the same
  rows. Checked for every analytic that has all three, with the set derived
  from the code rather than listed.

The third invariant, that every MCP tool refuses a caller without
`execute-sql` (design D11), is
`test_mcp_tools.py::test_every_domain_tool_is_refused_without_execute_sql`.
"""

import ast
import importlib
import inspect
from pathlib import Path

import pytest

pytest.importorskip("datasette")
pytest.importorskip("pytest_asyncio")
pytest.importorskip("datasette_mcp")

import datasette_mcp  # noqa: E402
import sqlite_utils  # noqa: E402
from mcp import Client  # noqa: E402

from scrobbledb import datasette_plugin  # noqa: E402
from scrobbledb import domain_queries as dq  # noqa: E402
from scrobbledb import serve as serve_module  # noqa: E402
from scrobbledb.datasette_plugin import queries as cat  # noqa: E402

PLUGIN_DIR = Path(datasette_plugin.__file__).parent

#: How many modules the plugin package has today. A scan that found fewer
#: would be passing over code it was meant to check.
PLUGIN_MODULE_FLOOR = 6


# --------------------------------------------------------------------------
# SQLite only through Datasette
# --------------------------------------------------------------------------


def plugin_sources():
    return sorted(PLUGIN_DIR.rglob("*.py"))


def scrobbledb_references(tree):
    """
    Every object the module reaches in another scrobbledb module, as
    (written name, object): `dq.get_top_artists` through a module alias, or a
    name brought in with `from scrobbledb.x import name`.
    """
    modules = {}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("scrobbledb."):
                    modules[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            if not node.module.startswith("scrobbledb"):
                continue
            for alias in node.names:
                qualified = f"{node.module}.{alias.name}"
                try:
                    importlib.import_module(qualified)
                except ImportError:
                    module = importlib.import_module(node.module)
                    found.append((qualified, getattr(module, alias.name)))
                else:
                    modules[alias.asname or alias.name] = qualified

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in modules
        ):
            module = importlib.import_module(modules[node.value.id])
            if hasattr(module, node.attr):
                found.append(
                    (
                        f"{modules[node.value.id]}.{node.attr}",
                        getattr(module, node.attr),
                    )
                )
    return found


def takes_a_database(obj) -> bool:
    """Whether `obj` is a function that executes against a database it is handed."""
    if not inspect.isfunction(obj):
        return False
    return any(
        param.name == "db" or param.annotation is sqlite_utils.Database
        for param in inspect.signature(obj).parameters.values()
    )


def direct_connections(tree):
    """`sqlite_utils` imports and `sqlite3.connect` calls in one module."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [
                a.name for a in node.names if a.name.split(".")[0] == "sqlite_utils"
            ]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] == "sqlite_utils":
                found.append(f"from {node.module} import ...")
            elif node.module == "sqlite3":
                found += [
                    f"from sqlite3 import {a.name}"
                    for a in node.names
                    if a.name == "connect"
                ]
        elif (
            isinstance(node, ast.Attribute)
            and node.attr == "connect"
            and isinstance(node.value, ast.Name)
            and node.value.id == "sqlite3"
        ):
            found.append("sqlite3.connect")
    return found


def test_the_scan_sees_the_whole_plugin():
    names = {path.name for path in plugin_sources()}

    assert len(names) >= PLUGIN_MODULE_FLOOR
    assert {"mcp_tools.py", "queries.py", "__init__.py"} <= names


@pytest.mark.parametrize(
    "path", plugin_sources(), ids=lambda p: str(p.relative_to(PLUGIN_DIR))
)
def test_no_plugin_module_opens_its_own_connection(path):
    """Neither `sqlite_utils` nor `sqlite3.connect`: Datasette owns the connections."""
    assert direct_connections(ast.parse(path.read_text())) == []


@pytest.mark.parametrize(
    "path", plugin_sources(), ids=lambda p: str(p.relative_to(PLUGIN_DIR))
)
def test_no_plugin_module_calls_an_executor(path):
    """
    The `domain_queries.get_*` executors take a `sqlite_utils.Database`, so a
    plugin that reached one would have to have built a connection to call it.
    Only the pure builders and shapers are fair game (design D4).

    Derived from signatures rather than from a `get_` prefix, so an executor
    under any name is caught.
    """
    references = scrobbledb_references(ast.parse(path.read_text()))
    executors = sorted({name for name, obj in references if takes_a_database(obj)})

    assert executors == []


def test_the_executor_check_recognises_an_executor():
    """The control: the check above is not vacuously true."""
    tree = ast.parse("from scrobbledb import domain_queries as dq\ndq.get_top_artists")

    (reference,) = scrobbledb_references(tree)
    assert reference[0] == "scrobbledb.domain_queries.get_top_artists"
    assert takes_a_database(reference[1])
    assert not takes_a_database(dq.build_top_artists_sql)


# --------------------------------------------------------------------------
# Canned query, MCP tool and CLI agree
# --------------------------------------------------------------------------


def builders_used_by_the_tools():
    """Every `domain_queries.build_*` the MCP tools module refers to."""
    tree = ast.parse((PLUGIN_DIR / "mcp_tools.py").read_text())
    return {
        obj
        for name, obj in scrobbledb_references(tree)
        if name.startswith("scrobbledb.domain_queries.build_")
    }


def builders_used_by_the_cli():
    """Every `build_*` that a `domain_queries` executor calls."""
    tree = ast.parse(Path(dq.__file__).read_text())
    used = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and takes_a_database(
            getattr(dq, node.name)
        ):
            used |= {
                getattr(dq, name.id)
                for name in ast.walk(node)
                if isinstance(name, ast.Name) and name.id.startswith("build_")
            }
    return used


#: A bound that falls between plays, so it filters on any local clock, and a
#: limit below the number of rows each analytic would otherwise return.
SINCE = "2024-01-02"
LIMIT = 3


def bounded(**extra):
    """Bounded arguments in each surface's own vocabulary."""
    return (
        {"since": SINCE, "limit": LIMIT, **extra},
        {"since": SINCE, "limit": LIMIT, **extra},
        {"since": dq.parse_relative_time(SINCE), "limit": LIMIT},
    )


#: For each builder shared by a catalog entry and an MCP tool: the entry and its
#: parameters, the tool and its arguments, the CLI function and its arguments,
#: and how to get rows out of the tool's result. Time-ranged analytics appear
#: twice, unbounded and bounded, so the parameters are exercised too.
def three_way_cases():
    items = lambda r: r["items"]  # noqa: E731
    match = lambda r: [r["match"]]  # noqa: E731
    whole = lambda r: [r]  # noqa: E731

    cases = [
        (dq.build_overview_stats_sql, "overview", {}, "collection_overview", {},
         dq.get_overview_stats, {}, whole),
        (dq.build_artist_stats_sql, "artist_detail", {"artist_id": "a1"},
         "artist_details", {"name": "Artist One"},
         dq.get_artist_details, {"artist_name": "Artist One"}, match),
        (dq.build_album_stats_sql, "album_detail", {"album_id": "alb2"},
         "album_details", {"title": "Album Two"},
         dq.get_album_details, {"album_title": "Album Two"}, match),
        (dq.build_track_stats_sql, "track_detail", {"track_id": "t1"},
         "track_details", {"title": "Track One"},
         dq.get_track_details, {"track_title": "Track One"}, match),
    ]  # fmt: skip
    ranged = [
        (dq.build_top_artists_sql, "top_artists", "top_artists", {},
         dq.get_top_artists),
        (dq.build_top_albums_sql, "top_albums", "top_albums", {}, dq.get_top_albums),
        (dq.build_top_tracks_sql, "top_tracks", "top_tracks", {}, dq.get_top_tracks),
        (dq.build_plays_with_filters_sql, "plays_feed", "recent_plays", {},
         dq.get_plays_with_filters),
        (dq.build_monthly_rollup_sql, "monthly_rollup", "listening_rollup",
         {"period": "month"}, dq.get_monthly_rollup),
        (dq.build_yearly_rollup_sql, "yearly_rollup", "listening_rollup",
         {"period": "year"}, dq.get_yearly_rollup),
    ]  # fmt: skip
    for builder, entry, tool, tool_extra, cli in ranged:
        cases.append((builder, entry, {}, tool, tool_extra, cli, {}, items))
        canned, tool_args, cli_args = bounded()
        cases.append(
            (
                builder,
                entry,
                canned,
                tool,
                {**tool_args, **tool_extra},
                cli,
                cli_args,
                items,
            )
        )
    return cases


THREE_WAY_CASES = three_way_cases()

#: Columns the shared shapers decode rather than pass through, with the
#: decoder they use. `album_ids` leaves SQL as a `group_concat` string.
DECODED_COLUMNS = {"album_ids": dq._split_ids}


def as_shaped(row):
    return {
        column: DECODED_COLUMNS.get(column, lambda value: value)(value)
        for column, value in row.items()
    }


def case_id(case):
    builder, entry, canned = case[:3]
    return f"{entry}-{'bounded' if canned.get('since') else 'all'}"


def test_every_analytic_with_three_surfaces_is_compared():
    """
    The shared set is derived: builders that a catalog entry, an MCP tool and
    a CLI executor all use. A surface added later over a shared builder must
    be given a case here before the suite passes. (The daily rollup has no CLI
    executor, so it is not in the set.)
    """
    catalogued = {entry.builder for entry in cat.CATALOG}
    shared = catalogued & builders_used_by_the_tools() & builders_used_by_the_cli()
    compared = {case[0] for case in THREE_WAY_CASES}

    assert len(shared) >= 10, "the derivation found too few shared builders"
    assert sorted(b.__name__ for b in shared - compared) == []
    assert sorted(b.__name__ for b in compared - shared) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case", THREE_WAY_CASES, ids=case_id)
async def test_canned_query_tool_and_cli_return_the_same_rows(populated_db, case):
    """
    The tool and the CLI share a shaper as well as a builder, so they must
    agree exactly. A canned query is the builder's SQL alone, with no shaper,
    so its rows are compared against the shaped rows' own columns: a shaper
    may add fields (a rank, a rate) and decode a column it documents
    (`DECODED_COLUMNS`), but must not otherwise change what the SQL produced,
    nor its order.
    """
    _, entry, canned_params, tool, tool_args, cli, cli_args, rows_of = case

    serve_module.register_plugin()
    ds = serve_module.build_datasette(populated_db)
    await ds.invoke_startup()
    try:
        response = await ds.client.get(
            f"/{populated_db.stem}/{entry}.json",
            params={"_shape": "array", **canned_params},
        )
        assert response.status_code == 200, response.text
        canned = response.json()

        if canned_params.get("since"):
            unbounded = await ds.client.get(
                f"/{populated_db.stem}/{entry}.json", params={"_shape": "array"}
            )
            assert unbounded.json() != canned, "the bound changed nothing"

        async with Client(datasette_mcp.create_mcp_server(ds)) as client:
            result = await client.call_tool(tool, tool_args)
        assert not result.is_error, result.content[0].text
        from_tool = rows_of(result.structured_content)
    finally:
        ds.close()

    from_cli = cli(sqlite_utils.Database(populated_db), **cli_args)
    from_cli = from_cli if isinstance(from_cli, list) else [from_cli]

    assert canned, f"{entry} returned nothing; the comparison is vacuous"
    assert from_tool == from_cli
    assert [{column: row[column] for column in canned[0]} for row in from_tool] == [
        as_shaped(row) for row in canned
    ]
