## 1. Dependencies and packaging

- [x] 1.1 Add
  `[project.optional-dependencies] serve = ["datasette>=1.0a39", "datasette-mcp>=0.2"]`
  to `pyproject.toml`; verify `uv sync --extra serve` resolves and
  `uv run datasette --version` reports 1.0a39 or later
- [x] 1.2 Add `datasette>=1.0a39`, `datasette-mcp>=0.2` and `pytest-asyncio` to
  `[dependency-groups] dev`; verify a bare `uv sync` installs them so CI has them
  without the extra
- [x] 1.3 Add explicit `[tool.setuptools.packages.find] where = ["src"]` (the project
  currently relies on implicit src-layout discovery) and extend
  `[tool.setuptools.package-data]` for the plugin’s config file; verify `uv build`
  produces a wheel containing `scrobbledb/datasette_plugin/`. The package-data pattern
  matches nothing until task 6.1 adds the config file, so it was verified by building
  against a temporary scaffold; 6.1 re-verifies with the real file
- [x] 1.4 Confirm `datasette` 1.0a39 installs on Python 3.14 (the CI matrix in
  `.github/workflows/qa.yml` covers 3.13 and 3.14); if it does not, record the
  constraint and plan to gate serve tests with `pytest.importorskip("datasette")` rather
  than pinning the project back
- [x] 1.5 Per design D9, confirm against the installed 1.0a39 whether table/column
  descriptions go in the `Datasette(metadata=...)` argument or the `config=` argument in
  the 1.0 config split; write the finding into `design.md` and use it in task 6.1

## 2. Refactor domain_queries.py into builders and shapers

- [x] 2.1 Split `get_overview_stats`, `get_monthly_rollup` and `get_yearly_rollup` into
  `build_*_sql() -> (sql, params)`, `shape_*(rows) -> list[dict]`, and a thin executor
  keeping the current signature (design D4); verify the existing `tests/test_stats.py`
  suite passes unchanged
- [x] 2.2 Apply the same split to `get_plays_with_filters`, `get_artists_with_stats`,
  `get_albums_list` and `get_tracks_list`; verify `tests/test_list_sorting.py` and
  `tests/test_plays_unify.py` pass unchanged
- [x] 2.3 Apply the same split to `get_artist_details`, `get_artist_top_tracks`,
  `get_artist_albums`, `get_album_details`, `get_album_tracks`, `get_track_details` and
  `get_track_plays`; verify the CLI suites pass unchanged.
  Fix `get_track_plays`’ f-string-interpolated `limit` (`domain_queries.py:1374`) to a
  bound parameter while in there
- [x] 2.4 Split the search functions `get_albums_by_search`, `get_tracks_by_search` and
  `get_artists_by_search`, keeping the Python-side rapidfuzz re-rank in the shaper;
  verify search behavior is unchanged
- [x] 2.5 Correct `get_albums_list`’s attribution: group on
  `albums.title COLLATE NOCASE` so a compilation stays one row (GitHub #47), and derive
  `artist_name` from the group — the owning artist when the group resolves to one name,
  `Various Artists` otherwise — instead of an independent `MAX()` (design D4). Verify a
  DJ mix returns one row, duplicate identifiers collapse, one artist under several ids
  is still named, and no row reports an artist that does not own its group.
  Against the live database: 2,215 rows, 972 `Various Artists`, and the 909
  misattributed rows eliminated
- [x] 2.6 Apply the same grouping and derived attribution to `get_top_albums`, which
  grouped by `albums.id, albums.title, artists.name` and therefore split one album’s
  plays across every identifier it was stored under; verify a DJ mix ranks as a single
  row with its plays summed, and that the album-aggregate requirement holds for every
  album aggregate rather than only the listing
- [x] 2.7 Update the existing album-listing tests to the corrected expectations — this
  is the one deliberate CLI output change in this change, so failures here are the
  intended new behavior, not regressions; verify the full suite passes afterward
- [x] 2.8 Return the group’s constituent album ids alongside the representative one —
  `group_concat(albums.id)` as `album_ids` — so callers that resolve an album back to
  its tracks can cover the whole alias group instead of one arbitrary `MAX(albums.id)`;
  verify `album_ids` contains every id in the group and that `album_id` remains a stable
  representative for linking
- [x] 2.9 Fix `scrobbledb albums list --expand`, which calls
  `get_album_tracks(db, album['album_id'])` on the representative id alone
  (`commands/albums.py:251-252`) while `track_count` and `play_count` cover the whole
  group, so an expanded album can list fewer tracks than its own count claims; make it
  expand across `album_ids`. Verify against the 31 alias groups in the live database
  that expanded track counts equal the reported `track_count`
- [x] 2.10 Fold `get_top_artists`, `get_top_tracks` and `get_top_albums` into
  single-statement builders, moving the `percentage` total into a scalar subquery
  (`COUNT(*) * 100.0 / (SELECT COUNT(*) FROM plays ...)`) per design D4; keep the
  `avg_plays_per_day` date-range probe on the CLI executor path only.
  Verify the existing tests assert identical output before and after
- [x] 2.11 Render optional predicates in the guarded named form of design D5 and run
  `EXPLAIN QUERY PLAN` on a time-ranged query to check whether the guard defeats
  `sqlite_autoindex_plays_1` on `plays(timestamp, track_id)`; if it does, have the
  builder render both a guarded named form and a dynamic positional form from one SELECT
  body, and record the finding in `design.md`
- [x] 2.12 Verify no builder or shaper imports `sqlite_utils` or touches a connection —
  a test asserting every `build_*` function is callable with no database argument and
  returns a `(str, dict)` pair whose dict keys exactly match the named placeholders in
  the SQL
- [x] 2.13 Verify the parameter mapping is a `dict` and not a sequence: named
  placeholders with a sequence are a `DeprecationWarning` on Python 3.13 and a
  `sqlite3.ProgrammingError` on 3.14, which the CI matrix covers (design D4). Add a test
  that executes every builder’s output against the `populated_db` fixture with
  `-W error::DeprecationWarning` so a regression fails on 3.13 rather than waiting for
  3.14

## 3. Plugin query catalog

- [ ] 3.1 Create `src/scrobbledb/datasette_plugin/__init__.py` and `queries.py` mapping
  each shared builder to a catalog entry (name, title, description, builder reference);
  verify a test enumerates the catalog and asserts every entry has all fields and a
  unique name
- [ ] 3.2 Project the catalog into the `canned_queries(datasette, database, actor)`
  hook; verify every entry appears on the database index page with its description and
  executes successfully against the `populated_db` fixture
  (`tests/test_stats.py:47-144`)
- [ ] 3.3 Verify optional bounds behave correctly through the hook: omitting both covers
  the full history, supplying both applies an inclusive range on each end
- [ ] 3.4 Confirm every album aggregate in the shared builders groups by
  `albums.title COLLATE NOCASE` and derives `artist_name` from the group per task 2.5 —
  never by `albums.id`, which fails to collapse synthesized aliases, and never naming a
  single contributor as the album’s artist; verify a compilation stays one row,
  duplicate ids collapse, one artist under several ids is still named, and any group
  spanning several artist names reports `Various Artists`
- [ ] 3.5 Add builders for the analytics the CLI lacks — daily rollup, hour-of-day
  distribution, day-of-week distribution, consecutive-day streaks (gap-and-islands over
  `julianday(date(timestamp))`), per-artist first-play discovery dates — in the same
  `domain_queries.py` builder style so the CLI can adopt them later; verify each against
  `populated_db` with hand-computed expected values
- [ ] 3.6 Add the FTS search entry using `tracks_fts MATCH :q` over
  `artist_name`/`album_title`/`track_title`; verify it returns matches on the fixture
  and an empty result set (not an error) for a non-matching term
- [ ] 3.7 Make the search entry fail with a message naming `scrobbledb index` when
  `tracks_fts` is absent; verify with a fixture database that has the base tables but no
  FTS table

## 4. Custom SQL functions

- [x] 4.1 Implement `datasette_plugin/functions.py` with `parse_when`,
  `fuzz_partial_ratio`, `month_name` and `fmt_ts` per design D6, reusing
  `domain_queries.parse_relative_time` / `_to_utc_iso`, `rapidfuzz`, and
  `domain_format.py:219,240`; verify unit tests call each as a plain Python function
- [x] 4.2 Confirm `parse_when` follows `_to_utc_iso`’s local-wall-clock reading of naive
  datetimes rather than `lastfm.parse_timestamp`’s UTC reading; verify with a test
  asserting a naive input resolves to the same UTC ISO string the CLI’s `--since`
  produces for that input
- [x] 4.3 Make `parse_when` return NULL on unparseable input instead of raising; verify
  a SQL query containing `parse_when('not a date')` still executes and yields NULL
- [x] 4.4 Wrap the parser in `functools.lru_cache` per design D6; verify a test that
  repeated calls with the same argument invoke the underlying `dateparser` path once
- [x] 4.5 Register all four via the `prepare_connection` hook; verify each resolves in
  ad hoc SQL through `Datasette(...).client.get("/<db>/-/query.json?sql=...")` — the
  1.0a query endpoint, since the 0.x `/<db>.json?sql=` form 302-redirects there (design
  D9)

## 5. Read-only enforcement

- [ ] 5.1 Register the database with an explicit SQLite open mode of `ro` —
  `Database(ds, path=..., mode="ro")` — so the read-only property is stated rather than
  inherited from Datasette’s default, and so the `write=True` branch that clears the URI
  query string cannot produce a read-write handle (design D7); verify the connection URI
  carries `mode=ro` and that `db.execute_write()` fails rather than succeeding
- [ ] 5.2 Issue `PRAGMA query_only=ON` in `prepare_connection` per design D7; verify
  `INSERT`, `UPDATE`, `DELETE` and `DROP` submitted through the query interface are each
  rejected
- [ ] 5.3 Install a `sqlite3` authorizer via `conn.set_authorizer` in
  `prepare_connection` rejecting `SQLITE_ATTACH`, `SQLITE_DETACH`, extension loading and
  every mutating action (design D7)
- [ ] 5.4 Prove the authorizer policy in isolation, on a **writable temporary database**
  with `query_only` off, so neither `mode=ro` nor `query_only` can mask a missing rule —
  verified necessary: on a `mode=ro` connection with `query_only=OFF`, SQLite still
  rejects `INSERT` itself with “attempt to write a readonly database”, so a test run
  against the served connection would pass even with no authorizer installed at all.
  Table-driven over the denied action set: `SQLITE_INSERT`, `SQLITE_UPDATE`,
  `SQLITE_DELETE`, `SQLITE_ALTER_TABLE`, every `SQLITE_CREATE_*` and `SQLITE_DROP_*`
  including the `_TEMP_TABLE`/`_TEMP_INDEX`/`_TEMP_TRIGGER`/`_TEMP_VIEW` and `_VTABLE`
  variants, `SQLITE_REINDEX`, `SQLITE_ANALYZE`, `SQLITE_ATTACH`, `SQLITE_DETACH`.
  Include a `SELECT` control that must still succeed.
  Verify that removing any single rule fails the suite
- [ ] 5.5 Cover the three statements that reach the database unless the authorizer stops
  them, since these are the cases with no second line of defence: `REINDEX` is allowed
  by both `mode=ro` and `query_only=ON`, and `ATTACH`/`DETACH` are allowed by both;
  verify each is denied on the real served connection, not only on the isolated test
  connection
- [ ] 5.6 Distinguish authorizer denial from Python’s default refusal for extension
  loading: `SELECT load_extension(...)` raises “not authorized” on a connection with
  **no** authorizer at all, so the naive case proves nothing.
  Call `enable_load_extension(True)` first, then verify the authorizer still denies it
- [ ] 5.7 Verify `VACUUM INTO` and `PRAGMA journal_mode=WAL` are rejected on the served
  connection — both produce files on disk rather than writing rows, so they are not
  covered by the row-mutation cases above
- [ ] 5.8 Open the database non-immutably despite the `ro` mode, per the alternative
  rejected in D7; verify the server still starts and serves after the database file is
  modified by an out-of-band `ingest`
- [ ] 5.9 Verify a full session — start, browse tables, run every canned query, shut
  down — leaves the database file byte-identical (hash before and after), including when
  the analytics indexes are absent

## 6. Datasette metadata and configuration

- [ ] 6.1 Ship two packaged files per the D9 finding — `metadata.yaml` carrying the
  table `description` and per-column `columns` descriptions for `artists`, `albums`,
  `tracks` and `plays`, and `datasette.yaml` carrying the config-side keys used by
  6.2–6.4 — loaded via `importlib.resources.files(...)` following the
  `ensure_default_log_config` precedent at `cli.py:100-113` and passed to the matching
  `Datasette(metadata=..., config=...)` arguments; verify the descriptions render on
  each table page, and do not route them through `config=`, where 1.0a39 ignores them
  silently
- [ ] 6.2 Hide the five FTS shadow tables (`tracks_fts_data`, `_idx`, `_content`,
  `_docsize`, `_config`); verify the database index page lists exactly the four scrobble
  tables plus `tracks_fts`
- [ ] 6.3 Set the default sort on `plays` to most-recent-first and add facets matching
  the TUI’s whitelists (`browse.py:22,31,39`); verify the default `plays` page returns
  descending timestamps
- [ ] 6.4 Set `sql_time_limit_ms` high enough that rollups complete on an unindexed
  ~47k-play database, and reconcile it with the database’s 5000ms `busy_timeout` so a
  read landing in an ingest commit window does not trip Datasette’s limit first (design
  D7); verify the monthly rollup succeeds with no analytics indexes, and that queries
  succeed against a database being written by a concurrent ingest

## 7. The serve command

- [ ] 7.1 Create `src/scrobbledb/serve.py` with a click command following the
  `export.py` single-command module pattern, options `--database/-d`, `--host` (default
  `127.0.0.1`), `--port` (default `8001`); wire it with
  `cli.add_command(serve_command.serve)` alongside the block at `cli.py:144-157`; verify
  `scrobbledb serve --help` exits 0
- [ ] 7.2 Import `datasette` lazily inside the command body per design D2 and convert
  `ImportError` into a `click.ClickException` naming the extra; verify in an environment
  without the extra that `scrobbledb serve` exits non-zero with the install hint and
  `scrobbledb serve --help` still exits 0
- [ ] 7.3 Resolve the database with `check_database` (`command_utils.py:156-173`);
  verify a missing database exits non-zero naming the path and pointing at
  `scrobbledb config init`, and that `--database` overrides the XDG default
- [ ] 7.4 Warn but still start when the database exists without a `plays` table,
  mirroring the `browse` pre-flight at `cli.py:1567+`; verify the warning text and that
  the server starts
- [ ] 7.5 Register the plugin with `pm.register(datasette_plugin, name="scrobbledb")`
  before constructing `Datasette`, guarded by `pm.is_registered`; verify
  `/-/plugins.json` on a running server lists `scrobbledb`
- [ ] 7.6 Construct `Datasette`, `await ds.invoke_startup()`, and serve `ds.app()`
  through uvicorn; verify the printed URL responds 200 and the database index page lists
  the four tables
- [ ] 7.7 Print both the web UI URL and the MCP endpoint URL at startup; verify both
  appear in the output
- [ ] 7.8 Detect missing analytics indexes by inspecting `sqlite_master` and print the
  `scrobbledb index --analytics` remedy without creating them; verify the warning
  appears on an unindexed database, is absent on an indexed one, and that the indexes
  are still absent after the session
- [ ] 7.9 Detect a stale search index by comparing `COUNT(tracks)` against
  `COUNT(tracks_fts)` and warn at startup naming the shortfall and the rebuild command,
  reusing the detection pattern from 7.8; verify the warning appears on a database whose
  index is short, is absent when the counts match, and that serving never rebuilds the
  index
- [ ] 7.10 Handle a bound port with an actionable error naming the port, and handle
  interrupt with a clean exit 0 and no traceback; verify both

## 8. MCP tools

- [ ] 8.1 Create `datasette_plugin/mcp_tools.py` holding the `register_mcp_tools`
  hookimpl in its own module per design D8, registered by `serve` only after
  `datasette_mcp` imports successfully; verify that with `datasette-mcp` absent the
  server still starts, prints that MCP is unavailable with how to enable it, and that
  `pm.check_pending()` does not raise
- [ ] 8.2 Wrap the shared builders from group 2 as MCP tools, executing through
  `await datasette.get_database(name).execute(sql, params)` and shaping with the shared
  shapers — never opening a `sqlite_utils.Database` — covering overview, top artists,
  top albums, top tracks, recent plays, artist/album/track detail, search, and time
  rollups; verify an MCP client listing tools sees all of them alongside the three
  upstream built-ins
- [ ] 8.3 Add an explicit authorization check to every tool before it executes, per
  design D11, since `Database.execute()` performs no permission checks of its own;
  verify a caller lacking `execute-sql` is refused by each tool
- [ ] 8.4 Confirm the 1.0a39 authorization API shape (`datasette.allowed(...)` and the
  `DatabaseResource` import path used by `datasette-mcp` 0.2) against the installed
  alpha rather than assuming it; record the confirmed form in `design.md` D11
- [ ] 8.5 Give every tool a description and a typed input schema marking optional
  parameters; verify the listed schema for a time-ranged tool shows
  `since`/`until`/`limit` as optional
- [ ] 8.6 Accept CLI time vocabulary on range parameters via `parse_when`; verify
  `6 months ago` returns the same rows as the equivalent CLI invocation, and that an
  uninterpretable bound returns an error naming the value with an example of an accepted
  form
- [ ] 8.7 Return a structured no-match result for an unknown artist and an error listing
  candidates for an ambiguous one, mirroring `domain_queries.get_artist_details`’s
  LIMIT-2 ambiguity check; verify both
- [ ] 8.8 Cap result rows and signal truncation in the response; verify a tool call that
  would exceed the cap reports truncation
- [ ] 8.9 Verify MCP inherits the read-only guarantee: a write statement through
  `execute_sql` fails, and a full MCP session leaves the database file unchanged

## 9. Analytics indexes

- [ ] 9.1 Add `--analytics` to the existing `index` command creating `plays(track_id)`,
  `tracks(album_id)`, `albums(artist_id)` and an expression index on
  `strftime('%Y-%m', timestamp)`, all as `CREATE INDEX IF NOT EXISTS`; verify each index
  appears in `sqlite_master` afterward
- [ ] 9.2 Verify `scrobbledb index` without the flag behaves exactly as before (existing
  tests unchanged and passing)
- [ ] 9.3 Verify idempotency: a second `--analytics` run succeeds, reports the indexes
  already exist, and creates nothing
- [ ] 9.4 Verify row data is untouched by index creation, and that running `--analytics`
  against a database with no scrobble tables reports nothing to index and exits 0
- [ ] 9.5 Verify a top-artists and a monthly-rollup query return identical results
  before and after indexing, and that `EXPLAIN QUERY PLAN` shows index use afterward

## 10. Test infrastructure

- [ ] 10.1 Add a `pm.unregister` teardown fixture per design D3, following the autouse
  `reset_logger` precedent at `tests/test_logging.py:36-43`; verify a test registering
  the plugin does not leak it into a subsequent test in the same session
- [ ] 10.2 Add a shared `populated_db` fixture based on `tests/test_stats.py:47-144` for
  the new test modules; verify both a canned-query test and an HTTP test build on it
- [ ] 10.3 Add HTTP-level tests using `Datasette(...).client` with `pytest-asyncio`,
  guarded by `pytest.importorskip("datasette")` so environments without the extra skip
  rather than fail; verify the suite passes both with and without the extra installed
- [ ] 10.4 Add a test asserting the web and MCP surfaces reach SQLite only through
  Datasette — no `sqlite_utils.Database` is constructed anywhere under
  `datasette_plugin/`; verify by import-graph or source inspection over the package
- [ ] 10.5 Add a test enumerating every registered MCP tool and asserting each is
  refused for an actor lacking `execute-sql`, so a tool shipped without its D11 check
  fails the suite; verify the test fails when a check is deliberately removed
- [ ] 10.6 Add a test asserting the canned query, the MCP tool, and the CLI function for
  the same analytic return identical rows on the same fixture — the three-way check that
  the shared builders of group 2 actually stayed shared; verify for every analytic that
  has all three surfaces

## 11. Documentation

- [ ] 11.1 Add `docs/commands/serve.md` using the cog block from
  `docs/commands/sql.md:7-13`, documenting that a plain `datasette scrobbledb.db`
  invocation does not get the customizations (design D3); verify `poe docs:cli`
  regenerates it and leaves the git tree clean
- [ ] 11.2 Add `serve` to the `docs/cli.md` command table (alphabetical) and the README
  “Command Overview” at `README.md:132-160`; verify by reading the rendered tables
- [ ] 11.3 Document the MCP endpoint URL and an example MCP client configuration in
  `docs/commands/serve.md`; verify a client configured from those instructions connects
  and lists the scrobbledb tools

## 12. Final verification

- [ ] 12.1 Run `uv run poe qa` (lint, type, audit, test) with the serve extra installed;
  verify all four stages pass
- [ ] 12.2 Run `uv run poe test` in an environment without the serve extra; verify the
  suite passes with serve tests skipped and `tests/test_docs_generation.py` still green
- [ ] 12.3 End-to-end against a real database: `scrobbledb serve`, browse the four
  tables, run every canned query from the UI, connect an MCP client to `/-/mcp` and
  exercise each scrobbledb tool; verify results match the equivalent CLI commands and
  the database file hash is unchanged
