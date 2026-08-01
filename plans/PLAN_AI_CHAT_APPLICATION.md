# Implement AI Chat for scrobbledb

## Summary

- Add a shared, read-only PydanticAI chat backend for the local scrobble database.
- Ship two front ends in the first pass: `scrobbledb chat` for a plain terminal REPL and `scrobbledb chat-ui` for a dedicated Textual chat app.
- Make the agent use explicit tools for schema introspection, safe SQL analytics, and FTS5 search instead of letting it operate against the database blindly.
- Add OpenTelemetry-based trace export so runs can go to any OTLP endpoint, with Logfire remaining optional rather than required.

## Key Changes

- In `src/scrobbledb/cli.py`, add:
  - `scrobbledb chat` interactive REPL command.
  - `scrobbledb chat-ui` command to launch a Textual chat screen.
  - Shared options on both commands: `--database`, `--model`, `--trace-endpoint`, `--trace-service-name`, `--show-tool-calls`.
- Add a new `scrobbledb.ai` package to hold the shared backend:
  - `agent.py`: constructs the PydanticAI agent and system instructions.
  - `tools.py`: tool wrappers for schema, search, and analytics.
  - `safety.py`: enforces read-only SQL execution.
  - `telemetry.py`: OTEL setup and exporter wiring.
  - `session.py` or equivalent: shared conversation runner used by both front ends.
- Define the tool surface as:
  - `schema_overview()`: tables, views, indexes, FTS presence, row counts where cheap.
  - `table_schema(table_name)`: columns, PK/FK info, create SQL.
  - `sample_rows(table_name, limit)`: small previews for grounding.
  - `run_sql_read_only(sql)`: single-statement `SELECT`/`WITH`/`EXPLAIN`/safe `PRAGMA` only, hard row cap, no writes, no `ATTACH`, no extensions.
  - `fts_search_tracks(query, limit)`, `fts_search_artists(query, limit)`, `fts_search_albums(query, limit)`, reusing existing FTS/domain query logic where possible.
  - `overview_stats()` and period/top-list helpers backed by existing query functions so the agent uses curated tools for common questions before falling back to SQL.
- Implement SQL safety with a dedicated sqlite connection using `PRAGMA query_only=ON`, one-statement validation, and an authorizer that rejects mutating or filesystem-related operations.
- Implement agent instructions so it:
  - uses FTS tools for "find/search/show me tracks/artists/albums" requests,
  - uses schema tools before SQL when structure is unclear,
  - uses SQL for aggregations and ad hoc analysis,
  - answers in plain language and only shows raw SQL/tool activity when `--show-tool-calls` is enabled.
- Build a dedicated Textual chat UI in `src/scrobbledb/tui.py` or a sibling module:
  - transcript pane,
  - input box,
  - status/tool activity pane,
  - no merge with the existing browse TUI in v1.
- Add docs for the new commands and regenerate CLI help snippets in `docs/commands/` and `docs/cli.md`.

## Public Interfaces

- New commands:
  - `scrobbledb chat`
  - `scrobbledb chat-ui`
- New command options:
  - `--model`
  - `--trace-endpoint`
  - `--trace-service-name`
  - `--show-tool-calls`
- Runtime config defaults:
  - `--database` keeps the existing XDG database default.
  - Model/provider credentials come from provider-standard environment variables.
  - OTEL flags override standard OTEL env vars when present.

## Test Plan

- Unit-test SQL safety to reject writes, multiple statements, `ATTACH`, extension loading, and oversized result sets.
- Unit-test schema tools and FTS tools against temporary sqlite fixtures, including the case where `tracks_fts` is missing.
- Add backend tests with a fake/stub agent model so chat orchestration is deterministic and does not require network access.
- Add CLI smoke tests for `chat --help`, startup validation, missing-database handling, and `--show-tool-calls` formatting.
- Add Textual smoke tests for the chat UI input/render loop using a stubbed backend.
- Regenerate docs and run the existing quick test suite plus the new chat-focused tests.

## Assumptions

- V1 is strictly read-only against the database.
- `clai` is treated as a generic CLI-chat direction, not IBM Project CLAI or another external framework.
- The first Textual version is a dedicated chat app, not a combined browse+chat workspace.
- Conversation history is in-memory per session only; transcript persistence is out of scope for this issue.
