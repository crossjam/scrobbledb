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

**One deliberate parity-breaking fix.** `get_albums_list` grouped by title alone while
selecting `MAX(albums.id)` and `MAX(artists.name)` as independent aggregates, so the two
could describe different rows.
Measured against the live database: of 2,215 rows, 909 reported an artist that does not
own the album id beside it.

The fix keeps the title grouping and corrects the attribution, which is where the defect
actually was. It applies to **every** album aggregate, not just the listing —
`get_top_albums` grouped by `albums.id, albums.title, artists.name`, so an album held
under several synthesized ids was ranked as several separate rows with its plays split
between them.

And once a row’s counts span a group of ids, a single `MAX(albums.id)` no longer
identifies what those counts describe: `albums list --expand` called
`get_album_tracks(db, album['album_id'])` on that one id and could therefore list fewer
tracks than the `track_count` printed beside it.
So the builders also return `album_ids` (`group_concat`) beside the representative
`album_id`, and expansion paths consume the full set.
`album_id` stays a stable single value for linking; `album_ids` is what the counts
actually refer to.

This is the one place in this change where CLI output deliberately changes, so the
existing album-listing tests were replaced with tests for the corrected expectations
rather than treated as a regression net.

#### Resolved: group on title, and decline to name an artist when the group spans several

The first pass of this correction grouped on `albums.artist_id, albums.title COLLATE
NOCASE`. That removed the false attribution but regressed **GitHub #47**, which was
filed with a screenshot of a DJ mix occupying ten rows of `albums list` — because
`albums.artist_id` is derived from the *track* artist, so a compilation has one album
row per contributor.
“Mushroom Jazz 7” exists under 16 artist ids; the live library is full of DJ mixes
shaped this way.

Both groupings were wrong, in opposite directions:

| Grouping | #47 | Attribution |
| --- | --- | --- |
| title only, `MAX(artists.name)` (original) | one row ✓ | 909 rows name an artist that does not own the album id beside it ✗ |
| `artist_id` + title (first pass) | one row per contributor ✗ | never misattributes ✓ |

The schema offers no way to tell a compilation from two distinct albums sharing a title
— there is no album-level artist and no compilation marker, and a compilation’s rows are
linked by nothing but the title.
Measured: 991 titles are held by more than one artist, 881 of them with roughly one
track per album row (compilation shape) and 110 with more; the sentinel title
`(unknown album)` spans 339 artists.
No threshold separates these cleanly.

So the resolution is to group on **title alone** and fix the attribution instead, since
the attribution was the actual defect:

```sql
CASE WHEN COUNT(DISTINCT artists.name COLLATE NOCASE) = 1
     THEN MIN(artists.name) ELSE 'Various Artists' END AS artist_name
```

A merged row either names the one artist that owns the whole group or names nobody.
It never picks a contributor and presents it as the album’s artist.

**Counting names rather than artist ids is deliberate.** The same artist commonly exists
under both an MBID and a synthesized `md5:` id, and counting ids reports “Various
Artists” for albums that plainly belong to one artist — 19 of them against the live
database, including “Endtroducing (Deluxe Edition)”.

Measured outcome: 20,124 albums aggregate to **2,215 rows** (restoring #47’s grouping),
**972** of them reported as `Various Artists`, **zero** attribution defects, and every
album id accounted for in exactly one group.

*The residual cost, accepted deliberately:* two genuinely distinct albums that share a
title merge into one `Various Artists` row.
That is the price of a schema with no album-level artist, and it is the quieter failure
— a row that declines to name an artist is honest about its uncertainty, where naming
one contributor of a 16-artist mix is not.
`album_ids` carries the whole group and `albums list --expand` reaches the per-artist
detail, so nothing is lost, only aggregated.

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

#### A canned query must resolve `parse_when` once, in SQL

`parse_when` reads the wall clock, so it is **not** registered `deterministic=True` —
claiming otherwise would be false, and the flag does not deliver what it appears to.
Measured: with the flag set, a single call site with a bound argument is hoisted (28
invocations to 1), but two call sites still resolve independently and a column-valued
argument is evaluated once per row.
It is an optimizer permission, not a guarantee.

So any canned query that needs one stable bound per statement must say so in SQL:

```sql
WITH bound AS MATERIALIZED (SELECT parse_when(:since) AS since_utc)
SELECT ... FROM plays, bound
WHERE (:since = '' OR plays.timestamp >= bound.since_utc)
```

Verified to resolve exactly once.
Without it, a statement spanning a cache-generation boundary can compare early rows
against one instant and later rows against another, making the result depend on scan
order. Task group 3 owns the canned queries and is where this shape has to be applied;
the builders themselves bind an already-converted UTC string, so none of them emits
`parse_when` today.

#### Measured: the guard does defeat the index, so builders emit both forms

Task 2.11 ran `EXPLAIN QUERY PLAN` against the live 48,400-play database.
The positional form uses the primary-key index:

```
SEARCH plays USING COVERING INDEX sqlite_autoindex_plays_1 (timestamp>? AND timestamp<?)
```

while the guarded named form, with both bounds supplied, degrades to `SCAN plays`.
SQLite cannot use an index for `(:since = '' OR plays.timestamp >= :since)` because the
disjunction is not sargable — it must evaluate the `OR` per row.

The cost depends entirely on how much of the table the range excludes.
Top-artists over a range, best of 7, results identical in every case:

| Range | Positional | Guarded | Slowdown |
| --- | --- | --- | --- |
| one day | 0.1 ms | 6.2 ms | **116x** |
| one week | 0.5 ms | 6.7 ms | 15x |
| one month | 2.5 ms | 8.5 ms | 3.4x |
| one year | 26.7 ms | 30.5 ms | 1.1x |
| all time | 196.4 ms | 180.1 ms | 0.9x |

Narrow ranges — the common interactive case — are where the guard hurts most, and they
are exactly the queries that should feel instant.
At full-table width the guard is free, and marginally faster, because a scan is what an
unbounded query does anyway.

So the builders render **both forms from one SELECT body**, as D4 anticipated.
The body, the joins, the grouping and the ordering are written once; only the optional
predicates differ:

- **named/guarded** (`(:since = '' OR plays.timestamp >= :since)`, params as a `dict`) —
  the canned-query contract, where parameters arrive from the URL and the SQL must be a
  static string.
- **positional** (`plays.timestamp >= ?` emitted only when the bound is present, params
  as a `list`) — the CLI and MCP paths, which build SQL per call and can therefore omit
  absent predicates entirely and keep the index.

This keeps one source of SQL per query while letting each consumer pay only the cost its
execution model forces.
The canned queries remain unindexed on narrow ranges; the analytics indexes of D10 are
the answer there, not a second SQL catalog.

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

### D7: Enforce read-only at three layers — `mode=ro`, `query_only`, and an authorizer

The database is registered with an explicit SQLite open mode of `ro`, and
`prepare_connection` additionally issues `PRAGMA query_only=ON` on every connection and
installs a `sqlite3` authorizer (`conn.set_authorizer`) rejecting `SQLITE_ATTACH`,
`SQLITE_DETACH`, extension loading, and every mutating action.

**On the open mode specifically.** Datasette’s `Database.connect()` builds its URI like
this (`datasette/database.py`):

```python
if self.is_mutable:
    qs = "?mode=ro"
else:
    qs = "?immutable=1"
assert not (write and not self.is_mutable)
if write:
    qs = ""                       # write connections drop mode=ro entirely
if self.mode is not None:
    qs = f"?mode={self.mode}"     # explicit mode wins over everything above
```

So a mutable database’s *read* connections are already opened `mode=ro` — it is not true
that they are read-write at the open-mode level.
The real gap is narrower and worth closing anyway: the `write=True` branch clears the
query string entirely, so any caller of `db.execute_write()` gets a read-write handle,
and the read-only property otherwise rests on an implicit default rather than something
this design states. Passing `mode="ro"` to `Database(...)` takes final precedence over
both branches, which makes the guarantee explicit and closes the write path without
reaching for `immutable=1`.

`query_only` alone is not sufficient and must not be described as if it were: it does
not block `ATTACH`, which can expose any other SQLite file the server process can read,
and it is itself resettable via `PRAGMA query_only=OFF`. Datasette’s
`validate_sql_select()` happens to reject both at the view layer, but the whole point of
this decision is a guarantee that does not depend on a layer above it.
The spec requires `ATTACH` to be rejected (`web-server/serve-command`, “Write statement
is rejected”), so the authorizer is what actually satisfies it.

**What each layer actually stops.** Measured on Python 3.13 / SQLite 3.47.1 against a
`mode=ro` connection:

| statement | `mode=ro` alone | `query_only=ON` | authorizer needed? |
| --- | --- | --- | --- |
| `INSERT`/`UPDATE`/`DELETE`, DDL on main | blocked | blocked | defence in depth |
| `CREATE TEMP TABLE` / `TEMP VIEW` | **allowed** | blocked | **yes — `query_only` is resettable** |
| `REINDEX` | blocked | blocked | defence in depth |
| `ANALYZE` | blocked | blocked | defence in depth |
| `ATTACH` / `DETACH` | allowed | allowed | **yes — only layer** |
| `VACUUM INTO '<path>'` | blocked | blocked | **yes — `query_only` is resettable** |
| `PRAGMA journal_mode=WAL` | blocked | blocked | **yes — `query_only` is resettable** |
| `load_extension()` | refused by Python’s default | — | **yes — the default is a flag Datasette flips** |

**Corrected in task group 5.** The `REINDEX` row above read “allowed / allowed / only
layer” and was wrong: re-measured on the same Python 3.13 / SQLite 3.47.1, `REINDEX`
raises “attempt to write a readonly database” on a `mode=ro` connection *and* on a
writable connection with `query_only=ON`. It stays on the deny list as defence in depth,
but it is not a case with no second line of defence.
`ATTACH` and `DETACH` are — they are permitted by both other layers, on a writable
connection and a read-only one alike.

So the three layers are not redundant restatements of one another.
`ATTACH` and `DETACH` reach the database unless the authorizer stops them, and with them
`VACUUM INTO`, which SQLite reports to the authorizer as a `SQLITE_ATTACH` naming the
output file rather than as a write.
Temp-object creation is stopped by `query_only` during normal operation, but
`query_only` is resettable via `PRAGMA query_only=OFF`, so under a guarantee that must
not depend on a layer above it the authorizer is the only durable protection there too —
which is why the deny list below includes the `_TEMP_` variants.
The authorizer must therefore deny, at minimum: `SQLITE_INSERT`, `SQLITE_UPDATE`,
`SQLITE_DELETE`, `SQLITE_ALTER_TABLE`, the `SQLITE_CREATE_*` and `SQLITE_DROP_*`
families **including their `_TEMP_` and `_VTABLE` variants**, `SQLITE_REINDEX`,
`SQLITE_ANALYZE`, `SQLITE_ATTACH`, `SQLITE_DETACH`, and extension loading.

**Pragmas are decided by name, not by whether they carry a value.** The obvious rule —
“refuse any pragma that assigns something” — cannot be written: SQLite hands the
authorizer `SQLITE_PRAGMA` with the pragma in `arg1` and, identically in `arg2`, either
the assigned value or the call argument.
`PRAGMA journal_mode=WAL` and `PRAGMA table_xinfo(artists)` are indistinguishable, so
that rule denies Datasette’s own schema introspection.
The policy is therefore an allowlist of read-only introspection pragmas, which is also
the stronger shape: a pragma nobody has thought of yet is denied rather than permitted.
Two entries on it are not obvious and were found by running the server rather than by
reading: FTS5 issues `PRAGMA data_version` internally on every `MATCH`, and
`sqlite_utils.Database(conn)` — which Datasette constructs around the served connection
to resolve foreign-key label columns — sets `PRAGMA recursive_triggers=on` in its
constructor.
Allowing the latter is safe because no trigger can fire when every statement
that would fire one is denied.

One consequence to keep in mind when reading tests: `PRAGMA query_only` cannot be read
through the authorizer either, for the same reason — allowing the read would allow
`PRAGMA query_only=OFF`. Observing layer 2 means lifting layer 3 for the duration.

**Datasette 1.0a39 installs an authorizer of its own**, in
`utils/sql_analysis.analyze_sql_tables`, and finishes by calling
`conn.set_authorizer(None)` — which would strip this plugin’s policy off any connection
it ran against. It does not, because `Database.analyze_sql` routes through
`execute_isolated_fn`, which opens a fresh connection for the call and closes it
afterwards, and that connection never passes through `prepare_connection`. It is worth
re-checking on each alpha bump: if analysis ever moves onto the pooled read connection,
the authorizer has to be reinstalled after it.

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
Explicit `mode="ro"` plus `query_only` plus the authorizer degrades gracefully instead:
read-only at the open-mode level, without promising the file will not change.

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

### D9: Target Datasette 1.0a39, and verify the alpha surface at implementation time

Chosen for the `datasette.yaml` config format and the `datasette.allowed()` /
`DatabaseResource` permissions API that `datasette-mcp` 0.2 targets natively.

`prepare_connection`, `canned_queries`, `startup` and `register_routes` are stable
across 0.65 and 1.0a, so the bulk of the plugin is insulated from the alpha.

#### Verified against the installed alpha (task group 1)

The floor is **`datasette>=1.0a39`**, not the `1.0a38` this section originally named.
1.0a39 and its stable-branch twin 0.65.4, both released 2026-09-11, are the
[September security releases](https://datasette.io/blog/2026/september-security-releases/);
1.0a38 is affected and must not be resolvable.
The fixes are directly relevant to what this change builds: table and view permission
checks now honor SQLite’s case-insensitive names, viewing an FTS index table now checks
permission on the table it draws from, FTS index detection uses parameterized SQL and
treats wildcards in table names literally, `sqlite_stat1`–`sqlite_stat4` are denied by
default, and extension loading is disabled after any `--load-extension` arguments are
processed (which group 5 relies on).

`datasette-mcp` resolves to **0.2** and pulls `mcp` **2.2.0**, clear of every published
advisory for the SDK — the most recent, GHSA-vj7q-gjh5-988w, tops out at `< 1.28.1`.
`starlette` 1.6.0 and `uvicorn` 0.52.4 likewise sit above every advisory range.

Both install and import on **Python 3.14.0** as well as 3.13, so the CI matrix needs no
`pytest.importorskip("datasette")` gate and the project is not pinned back.

**Ad hoc SQL moved in 1.0a.** Queries are served from `/<db>/-/query` (JSON at
`/<db>/-/query.json?sql=...`); the 0.x `/<db>.json?sql=...` form still works but
**302-redirects** there.
Any test asserting `status_code == 200` against the old URL fails on the redirect rather
than on anything real — found while verifying task 4.5, whose text named the old form.

**The 1.0 config split, settled empirically — descriptions stay in `metadata=`.**
`Datasette.__init__` calls `move_table_config(metadata, config)`, which relocates
exactly these keys out of `metadata` and into `config`:

```
hidden, sort, sort_desc, size, sortable_columns,
label_column, facets, fts_table, fts_pk, searchmode
```

Everything else a table entry can carry — `description`, `description_html`, `title`,
and the per-column `columns` mapping — is left in `metadata` and is read from there by
the table view. Passing a description through `config=` instead renders **nothing**: it
is silently ignored, with no warning and no error.
So the split this change must follow is

| Goes in `metadata=` | Goes in `config=` |
| --- | --- |
| table `description`, per-column `columns` descriptions (task 6.1) | hidden FTS shadow tables (6.2), default `sort_desc` and `facets` on `plays` (6.3) |
|  | `settings.sql_time_limit_ms` (6.4) |

`move_table_config` means a single combined file passed as `metadata=` happens to work
today, because the config-shaped keys get migrated out for you.
**Do not rely on it** — it is a 0.x compatibility shim inside an alpha.
Task 6.1 ships the two concerns as the two things 1.0 natively loads from a config
directory, `metadata.yaml` and `datasette.yaml`, and passes them to the matching
constructor argument.

**The core `sqlite-utils` floor moves to 4.0.** `datasette` 1.0a3x requires
`sqlite-utils>=4.0`, while this project declared `>=1.12.1` and was resolving to 3.39.
Because task 1.2 puts `datasette` in the `dev` dependency group, a bare `uv sync` pins
sqlite-utils 4.x for every developer and for CI, not just for serve users — so the old
floor described an environment nobody actually ran.
Rather than leave the declaration lying, the core dependency is raised to
**`sqlite-utils>=4.0`**, which is both datasette’s own floor and a verified one: the
suite passes on a forced `sqlite-utils==4.0` install (247 passed) as well as on the
resolved 4.2.1.

This does raise the core package’s install surface — `scrobbledb` no longer installs
against sqlite-utils 3.x for anyone, including users who never touch `serve`. That is
the intended trade: the 3.x path was already untested in practice.

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

*Exact 1.0a39 API to verify at implementation time:* `datasette-mcp` 0.2 imports
`DatabaseResource` from `datasette.resources` and calls `datasette.allowed(...)`, with a
`hasattr(datasette, "allowed")` fallback to `permission_allowed(...)` for 0.65. Since
this design targets 1.0a39 only, the fallback is unnecessary, but the resource class and
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

- **Datasette 1.0 alpha churn** → Pin `datasette>=1.0a39` and keep the plugin on hooks
  stable across 0.65/1.0a (`prepare_connection`, `canned_queries`). The only
  alpha-specific surface is the constructor’s metadata/config split, isolated to one
  call site in `serve.py`.
- ~~**`datasette` 1.0a38 may not support Python 3.14, which is in the CI matrix**~~ →
  **Retired in task group 1.** 1.0a39 and `datasette-mcp` 0.2 install and import on
  Python 3.14.0, so no `pytest.importorskip("datasette")` gate is needed and the project
  is not pinned back. See the verification notes under D9.
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
