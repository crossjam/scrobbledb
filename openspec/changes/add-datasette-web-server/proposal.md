## Why

scrobbledb has a rich, normalized listening history (`artists` → `albums` → `tracks` →
`plays`, ~47k plays in a typical database) and 23 hand-tuned analytical query builders
in `src/scrobbledb/domain_queries.py`, but every one of them is reachable only through
the CLI or the Textual TUI. There is no HTTP surface at all: a full grep for
`datasette|uvicorn|fastapi|asgi|starlette` across the repo returns zero hits.
That means the data cannot be linked to, explored ad hoc in a browser, faceted, or
consumed by an LLM agent without shelling out to `scrobbledb sql query` and parsing
text.

Datasette already solves the “explorable SQLite over HTTP” problem, and `datasette-mcp`
already solves “expose a Datasette instance over MCP”. What neither of them knows is
scrobbledb’s data model — that `plays.timestamp` is a UTC ISO-8601 *string*, that album
identity is fuzzy because roughly half of all mbids are synthesized `md5:` hashes, that
`tracks_fts` is a standalone FTS5 table Datasette’s automatic search will not find, or
what “top artists since last March” means.
This change supplies exactly that missing domain knowledge as a first-party Datasette
plugin, so the generic tools become scrobbledb-aware.

## What Changes

- **New `scrobbledb serve` command** that boots Datasette **in-process** (not by
  shelling out to the `datasette` CLI) against the resolved scrobbledb database —
  `--database` if given, otherwise the XDG default from `get_default_db_path()`. Binds
  `127.0.0.1` by default, opens the database **read-only** (deliberately not immutable —
  see design D7), and imports `datasette` lazily inside the command body so
  `scrobbledb --help` and the cog docs build keep working without the extra installed.
- **New optional `serve` extra** (`datasette>=1.0a38`, `datasette-mcp>=0.2`) under
  `[project.optional-dependencies]`, plus the same packages in the `dev` dependency
  group so `uv sync` and CI can exercise them.
- **New in-repo Datasette plugin** at `src/scrobbledb/datasette_plugin/`, registered
  **programmatically** with `datasette.plugins.pm` inside `serve` only.
  No `datasette.plugins` entry point, so the plugin never leaks into unrelated Datasette
  processes sharing the environment.
- **An internal refactor of `domain_queries.py`** splitting each query function into a
  pure SQL builder, a pure row shaper, and a thin executor.
  Public signatures and return shapes are unchanged, so every existing caller and test
  keeps working; the point is that the web and MCP surfaces can then reuse the *same*
  SQL rather than duplicating it, while executing through Datasette’s connection pool,
  query timeout and truncation handling.
- **Canned queries** contributed via the `canned_queries()` hook, built from those
  shared builders and covering the aggregates already implemented in `domain_queries.py`
  (overview, monthly/yearly rollups, top artists/albums/tracks with percentage,
  artist/album/track detail and their play histories, denormalized play feed, FTS-backed
  search), and filling the gaps that module leaves open: daily rollup, hour-of-day and
  day-of-week listening clocks, listening streaks, and first-play/discovery dates.
- **Custom SQL functions** registered via `prepare_connection()`, lifting logic that
  currently only exists in Python into SQL: `parse_when(text)` (dateparser +
  `_to_utc_iso` semantics, so `:since` accepts `"last march"`),
  `fuzz_partial_ratio(a, b)` (rapidfuzz, from `get_artists_by_search`), `month_name(n)`
  and `fmt_ts(text)` (from `domain_format.py`).
- **Datasette configuration** describing the domain: table/column descriptions, default
  sorts, facets, hidden FTS shadow tables
  (`tracks_fts_data|idx|content|docsize|config`), and `allow_sql` posture.
- **MCP endpoint** by depending on `datasette-mcp` for `/-/mcp` (Streamable HTTP) and
  its three read-only built-ins (`list_databases`, `get_database_schema`,
  `execute_sql`), then registering scrobbledb-specific tools through its documented
  `register_mcp_tools(datasette, mcp)` hook so agents can ask domain questions without
  writing SQL. Each tool performs an explicit authorization check before executing,
  since Datasette’s low-level `Database.execute()` does not check permissions on its
  own.
- **`scrobbledb index --analytics`**: an opt-in flag on the existing `index` command
  that creates the non-PK indexes the database currently lacks entirely —
  `plays(track_id)`, `tracks(album_id)`, `albums(artist_id)`, and an expression index on
  `strftime('%Y-%m', timestamp)`. `serve` itself never writes; it detects missing
  indexes and points at this command.
- **Docs**: `docs/commands/serve.md` with the standard cog block, plus the `docs/cli.md`
  command table and the README command overview.

Not breaking: every existing command, the database schema, and the CLI surface are
unchanged. The `serve` extra is opt-in; without it installed, `scrobbledb serve` exits
with an actionable install hint rather than an ImportError traceback.

## Capabilities

### New Capabilities

- `web-server/serve-command`: The `scrobbledb serve` CLI command and the embedded
  Datasette lifecycle — database resolution, read-only enforcement, bind address and
  port, plugin registration, startup validation, graceful shutdown, and the behavior
  when the optional dependency is absent.
- `web-server/domain-customizations`: The scrobbledb Datasette plugin’s domain layer —
  the catalog of canned queries and their parameters, the custom SQL functions and their
  semantics, and the metadata/config that describes scrobbledb’s tables to Datasette.
- `web-server/mcp-endpoint`: The MCP surface — the `/-/mcp` endpoint, the
  scrobbledb-specific tools registered through `register_mcp_tools`, their input/output
  contracts, and the read-only and permission guarantees they inherit from Datasette.
- `database/analytics-indexes`: The `scrobbledb index --analytics` behavior — which
  indexes are created, idempotency, and how other commands detect and report their
  absence.

### Modified Capabilities

<!-- None. openspec/specs/ is currently empty (.gitkeep only), so there are no existing
     capability specs whose requirements this change alters. The `index` command's new
     --analytics flag is captured as the new `database/analytics-indexes` capability above. -->

## Impact

**New code**
- `src/scrobbledb/serve.py` — the `serve` command (follows the `export.py`
  single-command module pattern; deferred heavy import like `browse` does with
  `from .tui import run_browser`).
- `src/scrobbledb/datasette_plugin/` — new package: `__init__.py` (hookimpls),
  `queries.py` (canned query SQL), `functions.py` (custom SQL functions), `mcp_tools.py`
  (`register_mcp_tools`), and a packaged config/metadata file.

**Modified code**
- `src/scrobbledb/domain_queries.py` — internal split into pure builders, pure shapers,
  and thin executors across all 23 query functions.
  No public signature or return-shape changes; the existing suites are the regression
  net.
- `src/scrobbledb/cli.py` — `cli.add_command(serve_command.serve)` alongside the
  existing block; `--analytics` flag on the `index` command.
- `pyproject.toml` — `[project.optional-dependencies] serve`, `[dependency-groups] dev`
  additions, an explicit `[tool.setuptools.packages.find] where = ["src"]` (currently
  relying on implicit src-layout discovery), and `[tool.setuptools.package-data]` for
  the plugin’s config file.
- `docs/cli.md`, `README.md`, new `docs/commands/serve.md`.

**Dependencies**
- `datasette>=1.0a38` — alpha line, chosen deliberately for the `datasette.yaml` config
  format and the `datasette.allowed()` / `DatabaseResource` permissions API that
  `datasette-mcp` targets natively.
  Alpha churn is an accepted risk.
- `datasette-mcp>=0.2` (pulls `mcp>=2.1.1`; requires Python >=3.10, satisfied by this
  project’s >=3.13).
- Both optional. Core CLI dependencies are untouched.

**Data**
- Read-only against the scrobbledb database.
  The only write path introduced anywhere in this change is the explicitly opt-in
  `scrobbledb index --analytics`.

**Security posture**
- The repo already has an explicit SQL-injection stance (`sql.py:_is_safe_order_clause`,
  `plans/SECURITY_REMEDIATION.md`) and `plans/PLAN_AI_CHAT_APPLICATION.md` specifies a
  read-only SQL policy.
  `serve` extends that to a network listener: localhost-only default bind, read-only
  connections enforced by both `PRAGMA query_only=ON` and a SQLite authorizer, and no
  write endpoints.

**Testing**
- No `conftest.py` exists today and fixtures are copy-pasted per module; the
  `populated_db` builder at `tests/test_stats.py:47-144` is the reusable seed.
  Canned queries and SQL functions are testable as plain functions against that fixture
  with no server. Real HTTP/MCP coverage needs `pytest-asyncio` (and `httpx`, via
  `Datasette(...).client`) as new dev dependencies.
- `tests/test_docs_generation.py` regenerates `docs/commands/*.md` in-process and
  asserts a clean git tree, so `serve --help` must be importable and side-effect-free
  without `datasette` installed.
