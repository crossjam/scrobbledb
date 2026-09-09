## Context

See `proposal.md — Why` for motivation.
The constraints that actually shape the approach:

- **The database is greenfield for HTTP.** No web dependency, no ASGI code, no
  `conftest.py`, no async tests exist.
  Everything here is new surface.
- **`plays.timestamp` is TEXT, not an epoch integer.** Verified uniform across all rows:
  UTC ISO-8601 with an explicit `+00:00` suffix (`2005-02-13T23:59:12+00:00` ..
  present). Because the format is homogeneous and lexicographically sortable, plain
  string `>=`/`<=` comparison is correct, and `strftime`, `date()` and `julianday()` all
  work directly. Both bounds in `domain_queries.py` are inclusive.
  No data cleaning is needed anywhere in this change.
- **`plays` has a compound TEXT primary key `(timestamp, track_id)`** and no rowid
  alias, so Datasette row URLs are `/db/plays/<timestamp>,<track_id>` with `+` and `:`
  escaped.
- **About half of all mbids are synthesized.** `lastfm.py:220-233` hashes
  `md5(artist_name)`, then `md5(artist_mbid + album_title)`, then
  `md5(album_mbid + track_title)` when last.fm returns no mbid.
  Album and artist identity is therefore title-derived for a large fraction of rows.
  `domain_queries.get_albums_list` already works around this with
  `GROUP BY albums.title COLLATE NOCASE` (`domain_queries.py:670`).
- **`tracks_fts` is a standalone FTS5 table, not `content=`-linked**
  (`lastfm.py:654-673`). Datasette’s automatic `?_search=` on `tracks` will not discover
  it. Its indexed columns are `artist_name`, `album_title`, `track_title`; the three
  `*_id` columns are `UNINDEXED`. Five shadow tables
  (`tracks_fts_data|_idx|_content|_docsize|_config`) exist and would otherwise clutter
  the table index.
- **There are no non-PK indexes at all.** Only the four implicit `sqlite_autoindex_*`.
  Every rollup does a full 3-way join.
- **`domain_queries.py` takes a `sqlite_utils.Database`,** not a Datasette `Database`,
  and opens its own connection.
  It cannot be called directly from Datasette request handlers without bypassing
  Datasette’s permission checks, query timeouts, and thread pool.
- **`tests/test_docs_generation.py` regenerates `docs/commands/*.md` in-process** by
  invoking `serve --help` through `CliRunner`, then asserts
  `git diff --name-only docs/commands` is empty.
  So `serve` must be importable and `--help`-able with `datasette` absent and with no
  side effects.
- **Python is `>=3.13`; CI matrix is 3.13 and 3.14.**

## Goals / Non-Goals

**Goals:**

- One source of SQL shared by the CLI, the web UI’s stored queries and the MCP tools, so
  the three cannot drift.
- Nothing on the web or MCP surface reaches SQLite outside Datasette’s execution path,
  and nothing executes without an authorization check.
- Read-only enforced at the SQLite connection level, not merely by convention.
- The `serve` extra is genuinely optional: absent it, nothing else in the CLI changes
  behavior, including docs generation.
- Domain customizations are scoped to servers scrobbledb starts, never to unrelated
  Datasette processes in the same environment.
- Parity with the CLI is a tested property, not an aspiration.

**Non-Goals:**

- Changing any `domain_queries.py` public function signature or return shape.
  The module is refactored internally (D4), but every existing caller and every existing
  test keeps working unchanged.
- Authentication, multi-user access, or public deployment.
  Localhost-only, single-actor.
  No `--cors`, no auth plugins, no publish story.
- Writing to the database from the web or MCP surface, ever.
- Custom Datasette templates, CSS, or a bespoke homepage.
  Stock Datasette chrome plus metadata descriptions.
- Replacing the Textual TUI (`scrobbledb browse`). Both surfaces coexist.

## Decisions

### D1: Embed Datasette in-process rather than shelling out to the `datasette` CLI

`serve` constructs `Datasette(...)` directly, calls `await ds.invoke_startup()`, and
hands `ds.app()` to `uvicorn` (already a Datasette dependency).

*Why:* shelling out cannot register a plugin programmatically, cannot resolve the XDG
database path into the child reliably, and turns errors into subprocess exit codes.
In-process also makes the whole thing testable via `ds.client` with no port binding.

*Alternative rejected:* `subprocess.run(["datasette", db_path, "--metadata", ...])` with
a materialized metadata file.
Simpler, but it forces the plugin to be an installed entry point — which the
plugin-scoping decision (D3) explicitly rules out.

### D2: Import `datasette` lazily inside the command body

`src/scrobbledb/serve.py` defines the click command with no module-level `datasette`
import; the import happens inside the function, wrapped to convert `ImportError` into a
`click.ClickException` naming the extra.

*Why:* this is exactly the pattern `browse` already uses for Textual
(`from .tui import run_browser` inside the command body, `cli.py:1567+`), and it is what
keeps `serve --help` working — and therefore `tests/test_docs_generation.py` and
`poe docs:cli` passing — in an environment without the extra.

### D3: Register the plugin programmatically, not via an entry point

```python
from datasette.plugins import pm
from scrobbledb import datasette_plugin
if not pm.is_registered(datasette_plugin):
    pm.register(datasette_plugin, name="scrobbledb")
```

registered *before* `Datasette(...)` is constructed, since `prepare_connection` and
`canned_queries` fire during construction and request handling.

*Why:* a `[project.entry-points."datasette.plugins"]` table loads into **every**
Datasette process in the environment, including unrelated ones — a real hazard for a
user who has other Datasette databases.
Programmatic registration keeps the blast radius at exactly the servers scrobbledb
starts.

*Cost, accepted:* `datasette scrobbledb.db` run directly does not get the
customizations. Documented in `docs/commands/serve.md`.

*Consequence for tests:* `pm` is global and process-wide, so any test that registers
must `pm.unregister` in teardown or leak into sibling tests.
This mirrors the existing `reset_logger` autouse fixture at
`tests/test_logging.py:36-43`; the same shape applies here.

### D4: Extract pure builders and shapers from `domain_queries.py`; share them

Each `get_*` function in `domain_queries.py` currently mixes three concerns: building
SQL, executing it against a `sqlite_utils.Database`, and shaping rows into dicts.
Split the first and third out as pure functions and leave a thin executor behind:

```python
def build_top_artists_sql(limit=10, since=None, until=None) -> tuple[str, dict]: ...   # pure
def shape_top_artists(rows, total_plays, days) -> list[dict]: ...                      # pure

def get_top_artists(db, **kw):          # signature and behavior unchanged
    sql, params = build_top_artists_sql(**kw)
    return shape_top_artists(db.execute(sql, params).fetchall(), ...)
```

**Builders return a parameter `dict`, not a list.** D5’s canned-query form uses named
placeholders (`:since`), and Python’s `sqlite3` requires a mapping for those.
Supplying a sequence alongside named placeholders is a `DeprecationWarning` on 3.13 and
becomes a `sqlite3.ProgrammingError` on 3.14 — verified locally:

> `DeprecationWarning: Binding 1 (':a') is a named parameter, but you supplied a sequence
> which requires nameless (qmark) placeholders. Starting with Python 3.14 an
> sqlite3.ProgrammingError will be raised.`

This project’s CI matrix covers 3.14, so a `(str, list)` contract would be a guaranteed
runtime failure there, not a style preference.
If task 2.6 concludes the guarded form costs an index and the builders must also emit a
positional variant, that variant returns `(str, list)` with `?` placeholders and is used
only on the CLI and MCP paths — the named form and its dict stay the canned-query
contract.

The plugin imports the same builder and shaper and executes through Datasette:

```python
sql, params = build_top_artists_sql(**kw)
results = await datasette.get_database(name).execute(sql, params)
return shape_top_artists(results.rows, ...)
```

*Why:* `domain_queries.py` opens its own `sqlite_utils` connection (e.g.
`domain_queries.py:829`), which from inside a Datasette request handler would bypass the
shared thread pool, `sql_time_limit_ms` interrupts, `max_returned_rows` truncation, and
the connection our `prepare_connection` hook has prepared — meaning no `query_only=ON`
and no `parse_when()`. Executing through `Database.execute()` gets all of those.
Extracting the builders is what lets us have that *and* a single source of SQL.

*Why it is safe:* the public signatures do not move, so `tests/test_stats.py` and the
other existing suites are the regression net for the refactor.

*Two places this does not reach cleanly, handled explicitly:*

1. **Canned queries need static SQL with named parameters**, because parameters arrive
   from the URL — a builder emitting `?` placeholders cannot serve them.
   The builders therefore render their optional predicates in the guarded named form
   (D5) so one string serves both consumers.
   See the index risk below.
2. **Some functions issue multiple statements.** `get_top_artists` runs up to three — a
   total, the ranked set, and a date-range probe — and computes `percentage` and
   `avg_plays_per_day` in Python (`domain_queries.py:825-884`). A canned query is a
   single statement, so the builder folds the total into a scalar subquery
   (`COUNT(*) * 100.0 / (SELECT COUNT(*) FROM plays ...)`). The CLI adopts the same
   single-statement form so there is still one source of SQL; its externally observable
   output is unchanged, which the existing tests verify.

**One deliberate parity-breaking fix.** `get_albums_list` groups by title alone
(`domain_queries.py:670`) while selecting `MAX(albums.id)` and `MAX(artists.name)` as
independent aggregates, so the two can describe different rows.
Measured against the live database: 20,124 albums collapse to 2,215 rows, and 909 of
those rows report an artist that does not own the album id beside it.
Grouping by `albums.artist_id, albums.title COLLATE
NOCASE` yields 20,093 rows, so the md5-duplicate deduplication the grouping was meant to
provide only ever affected 31 albums — the other 17,878 merges were collateral damage.

The shared builder therefore emits the corrected grouping, and the CLI adopts it.
This is the one place in this change where CLI output deliberately changes, so the
existing album-listing tests must be updated to the corrected expectations rather than
treated as a regression net.
With `artist_id` in the grouping, `artists.name` is functionally dependent and can be
selected directly instead of via `MAX()`, which removes the mismatch at its source.

*Alternative rejected:* a separate SQL catalog in the plugin with parity tests against
the CLI. Smaller blast radius, but it duplicates every query and the parity tests only
catch drift after it happens.

### D5: Optional canned-query parameters use the `:param = ''` idiom

Datasette passes an empty string for a canned-query parameter the user left blank, so
every optional bound is written:

```sql
WHERE (:since = '' OR plays.timestamp >= parse_when(:since))
  AND (:until = '' OR plays.timestamp <= parse_when(:until))
```

*Why:* it is the only way to get genuinely optional parameters in a canned query, and
routing the bound through `parse_when()` is what makes `last march` work in a browser
form field — reproducing `--since`/`--until` semantics on the web without any Python in
the request path.

*Trade-off:* `parse_when('')` must return NULL rather than raise, and the `:since = ''`
guard must short-circuit before the comparison.
Both are covered by spec scenarios.

### D6: Custom SQL functions registered via `prepare_connection`, with caching

Four functions, all lifted from logic that currently only exists in Python:

| Function | Source | Notes |
| --- | --- | --- |
| `parse_when(text) -> str \| None` | `domain_queries.parse_relative_time` + `_to_utc_iso` | `functools.lru_cache`-wrapped; returns NULL on unparseable input |
| `fuzz_partial_ratio(a, b) -> float` | `rapidfuzz`, from `get_artists_by_search` (`domain_queries.py:694`) | already a runtime dependency |
| `month_name(n) -> str` | `domain_format.py:219` |  |
| `fmt_ts(text) -> str` | `domain_format.py:240` |  |

*Why caching matters:* `prepare_connection` fires per connection in Datasette’s thread
pool, and `dateparser` costs milliseconds per call.
Uncached, a `parse_when` in a `WHERE` clause that SQLite chooses to evaluate per row
would be pathological.
Caching plus the `:since = ''` guard keeps it to a handful of calls per query.

*Note on semantics:* `_to_utc_iso` (`domain_queries.py:272-285`) treats a naive datetime
as **local** wall clock, while the import path’s `parse_timestamp` (`lastfm.py:365-401`)
treats naive input as **UTC**. `parse_when` deliberately follows `_to_utc_iso`, because
it is reproducing `--since`/`--until`, not the importer.

### D7: Enforce read-only with `PRAGMA query_only=ON` **and** a SQLite authorizer

`prepare_connection` issues `PRAGMA query_only=ON` on every connection **and** installs
a `sqlite3` authorizer (`conn.set_authorizer`) that rejects `SQLITE_ATTACH`,
`SQLITE_DETACH`, extension loading, and every mutating action, in addition to whatever
mode Datasette opens the file in.

`query_only` alone is not sufficient and must not be described as if it were: it does
not block `ATTACH`, which can expose any other SQLite file the server process can read,
and it is itself resettable via `PRAGMA query_only=OFF`. Datasette’s
`validate_sql_select()` happens to reject both at the view layer, but the whole point of
this decision is a guarantee that does not depend on a layer above it.
The spec requires `ATTACH` to be rejected (`web-server/serve-command`, “Write statement
is rejected”), so the authorizer is what actually satisfies it.

*Why:* together they are a positive, testable guarantee that does not depend on getting
a Datasette-alpha constructor argument right, nor on Datasette’s SQL validation.
It also matches the read-only policy already written down in
`plans/PLAN_AI_CHAT_APPLICATION.md` (single-statement `SELECT`/`WITH`/`EXPLAIN`,
`PRAGMA query_only=ON`, authorizer rejecting `ATTACH` and extension loading), so the two
non-CLI surfaces converge on one posture.

*Alternative rejected:* passing the database via `Datasette(immutables=[path])`.
`immutable=1` is stronger and lets Datasette cache row counts, but it is a promise that
the file will not change while open — and a user running `scrobbledb ingest` in another
terminal during a serve session would break that promise with undefined results.
Regular open plus `query_only` degrades gracefully instead.

**Concurrency, measured.** Serving while an ingest is in flight is normal usage here,
not an edge case — a typical run is
`ingest -v --batch-size 250 --since-date "Jan 1, 2024"` lasting 40+ minutes.
The database is in rollback-journal mode, not WAL:

```
journal_mode : delete     busy_timeout : 5000
page_size    : 4096       foreign_keys : 0
```

Under `journal_mode=delete` a writer holds an EXCLUSIVE lock across commit, blocking
readers outright. Measured against the live database during an active ingest, 25
sequential joined counts over `plays JOIN tracks` gave a worst case of 0.072s with zero
errors — with a 250-row batch size the commit windows are short enough that readers slip
between them. So this is a known interaction, not a present defect.

One consequence to configure for: `busy_timeout` is 5000ms while Datasette’s default
`sql_time_limit_ms` is 1000ms, so a read landing in a commit window can trip Datasette’s
own limit and surface as a query error long before SQLite’s busy handler would give up.
The two must be set consistently (see task 6.4).

Switching to WAL would remove the contention entirely, but `journal_mode` is a
persistent write, so `serve` cannot do it without breaking its own read-only guarantee.
If wanted, it belongs to `config init` or an explicit opt-in command — the shape already
chosen for `index --analytics` in D10. Out of scope here.

### D8: MCP by dependency and hook, not by fork

`datasette-mcp>=0.2` is a plain dependency; it owns `/-/mcp`, the Streamable HTTP
transport, and `list_databases` / `get_database_schema` / `execute_sql`. scrobbledb
contributes only its own tools via the documented hook:

```python
@hookimpl
def register_mcp_tools(datasette, mcp):
    @mcp.tool()
    async def top_artists(since: str = "", until: str = "", limit: int = 10) -> list[dict]:
        """Most-played artists, optionally within a time range."""
```

*Why:* the hook exists for precisely this, upstream keeps owning transport and
permission enforcement, and scrobbledb inherits upstream fixes for free.
`datasette-mcp` also already carries a 1.0a/0.65 compatibility shim
(`hasattr(datasette, "allowed")`), so it is not itself a source of version fragility.

*Hookspec ordering is safe:* `datasette_mcp` calls `pm.add_hookspecs(hookspecs)` at
import time, and pluggy’s `add_hookspecs` wires up matching hookimpls on
already-registered plugins.
So it does not matter whether our module is registered before or after `datasette_mcp`
is imported.

*But unmatched hookimpls are a hazard:* if `datasette-mcp` is not installed, a
`register_mcp_tools` hookimpl sits unmatched in `pm`, and `pm.check_pending()` would
raise. Mitigation: `register_mcp_tools` lives in its own module
(`datasette_plugin/mcp_tools.py`) that `serve` registers **only** after confirming
`datasette_mcp` imports.
This is also what makes the “MCP support not installed → server still starts, prints how
to enable it” scenario work.

### D9: Target Datasette 1.0a38, and verify the alpha surface at implementation time

Chosen for the `datasette.yaml` config format and the `datasette.allowed()` /
`DatabaseResource` permissions API that `datasette-mcp` 0.2 targets natively.

The specific 1.0a constructor arguments this design leans on — `metadata=` for table and
column descriptions versus `config=` for settings, and whether descriptions moved wholly
out of `metadata` in the 1.0 config split — **must be confirmed against the installed
1.0a38** rather than assumed.
This is called out as an explicit first task, not left as an open question, because
getting it wrong is a compile-time failure with an obvious fix, not a design change: the
catalog and the hooks are unaffected either way.

`prepare_connection`, `canned_queries`, `startup` and `register_routes` are stable
across 0.65 and 1.0a, so the bulk of the plugin is insulated from the alpha.

### D10: `--analytics` extends the existing `index` command; `serve` only warns

Four indexes: `plays(track_id)`, `tracks(album_id)`, `albums(artist_id)`, and an
expression index on `strftime('%Y-%m', timestamp)`. All `CREATE INDEX IF NOT EXISTS`, so
idempotent by construction.

*Why on `index` rather than as a `serve` side effect:* `serve`’s read-only guarantee is
the more valuable property.
A server that silently writes to the database the first time you point it at one is a
surprising and hard-to-audit behavior, and it would contradict D7. `serve` detects
absence by inspecting `sqlite_master` and prints a one-line remedy.

### D11: MCP tools authorize explicitly; `db.execute()` alone is not enough

`Database.execute()` is a low-level executor and performs **no** permission checks —
authorization in Datasette lives at the view layer.
So every scrobbledb MCP tool checks before it executes, the same way `datasette-mcp`
does for its own tools:

```python
if not await datasette.allowed(actor, "execute-sql", DatabaseResource(db_name)):
    raise PermissionError(...)
results = await datasette.get_database(db_name).execute(sql, params)
```

A test asserts that each registered tool is refused when the actor lacks `execute-sql`,
so a tool shipped without its check fails the suite rather than silently reaching the
database.

*Exact 1.0a38 API to verify at implementation time:* `datasette-mcp` 0.2 imports
`DatabaseResource` from `datasette.resources` and calls `datasette.allowed(...)`, with a
`hasattr(datasette, "allowed")` fallback to `permission_allowed(...)` for 0.65. Since
this design targets 1.0a38 only, the fallback is unnecessary, but the resource class and
argument order must be confirmed against the installed alpha rather than assumed.

*Alternative rejected:* routing tools through
`datasette.client.get("/db/query.json?...")`, an internal ASGI request that traverses
the entire view stack, so nothing is bypassed by construction rather than by remembering
to write the check. Rejected because the internal client does not carry the MCP caller’s
actor — it would need a signed `ds_actor` cookie threaded through — and it adds a JSON
serialize/deserialize round-trip.
Disproportionate for a localhost single-actor server, but the right escalation if
scrobbledb ever grows real multi-user auth.

## Risks / Trade-offs

- **Datasette 1.0 alpha churn** → Pin `datasette>=1.0a38` and keep the plugin on hooks
  stable across 0.65/1.0a (`prepare_connection`, `canned_queries`). The only
  alpha-specific surface is the constructor’s metadata/config split, isolated to one
  call site in `serve.py`.
- **`datasette` 1.0a38 may not support Python 3.14, which is in the CI matrix** → Verify
  before wiring CI. If unsupported, gate the serve tests on
  `pytest.importorskip("datasette")` so the 3.14 job stays green rather than pinning the
  whole project back.
- **`pm.register` is process-global; leaking it breaks unrelated tests** → Mandatory
  `pm.unregister` teardown fixture, following the `reset_logger` precedent at
  `tests/test_logging.py:36-43`.
- **`parse_when` inside a `WHERE` clause could be evaluated per row** → `lru_cache` on
  the underlying parser, plus the `:since = ''` short-circuit.
  If profiling still shows a problem, the fallback is to resolve bounds in the MCP tool
  layer and leave the canned queries taking pre-normalized ISO strings, at the cost of
  the natural-language UX in the browser.
- **Canned queries are slow without the analytics indexes** — a full 3-way join over
  ~47k plays per request, and Datasette’s default SQL time limit is 1s → `serve` warns
  at startup with the exact remedy.
  If rollups still exceed the limit on large databases, raise `sql_time_limit_ms` in the
  served config.
- **The `md5:` identity problem produces duplicate-looking albums** → Album aggregates
  group by `title COLLATE NOCASE`, replicating `domain_queries.py:670`. This is a
  genuine trade-off: two distinct albums that share a title collapse into one row.
  It is the behavior the CLI already has, and diverging would break the CLI-parity
  tests.
- **Two new dev dependencies (`pytest-asyncio`, and `httpx` via Datasette) for HTTP
  coverage** → They land in `[dependency-groups] dev` so `uv sync` in CI picks them up;
  `[project.optional-dependencies] serve` stays limited to what a user actually needs at
  runtime.
- **The FTS index is only made fully consistent by `rebuild_fts5()` at the very end of
  `ingest`** (`cli.py:994`), so during any long ingest it is incomplete, and after an
  interrupted one it stays incomplete indefinitely.
  On the web and MCP surfaces that is silent — search returns fewer rows, with no error
  → `serve` warns at startup when `COUNT(tracks)` and `COUNT(tracks_fts)` diverge,
  reusing the detection pattern built for missing analytics indexes.
  Root cause is tracked separately in kata#91w2 and is out of scope here; surfacing the
  staleness is in scope, because a search surface that silently under-reports is worse
  than one that says so.
- **The `domain_queries.py` refactor touches all 23 query functions in a 1577-line
  module** → Public signatures and return shapes are held constant, so the existing
  suites (`tests/test_stats.py`, `tests/test_list_sorting.py`, `tests/test_cli.py`) are
  the regression net. Do the extraction function by function with the suite green at each
  step, not as one sweep.
- **Folding `get_top_artists`’ three statements into one changes the CLI’s SQL** →
  Externally observable output is unchanged and the existing tests assert it.
  The `avg_plays_per_day` date-range probe stays a separate query on the CLI path only,
  since it has no canned-query equivalent.
- **The guarded predicate form (D5) may defeat `sqlite_autoindex_plays_1`** — `plays`’
  primary key is `(timestamp, track_id)`, so timestamp is the leading column and a bare
  range predicate can use that index, whereas
  `(:since = '' OR plays.timestamp >= :since)` may not → Verify with
  `EXPLAIN QUERY PLAN` before committing to a single rendering.
  If the guard is costly, have the builder render two predicate forms from one SELECT
  body: the guarded named form for canned queries, the dynamic positional form for the
  CLI and MCP paths.

## Migration Plan

No migration. This is purely additive: no schema change, no change to any existing
command’s behavior, no change to the base dependency set.

- **Deploy:** `uv sync --extra serve` (or `pip install 'scrobbledb[serve]'`), then
  `scrobbledb serve`.
- **Rollback:** uninstall the extra.
  `scrobbledb serve` then fails with an install hint and every other command is
  unaffected. Nothing to undo in the database.
- **The one durable side effect** a user can produce is `scrobbledb index --analytics`,
  which is opt-in and reversible with `DROP INDEX`.
