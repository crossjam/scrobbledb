# Code Review: scrobbledb
**Date:** 2026-02-15
**Reviewer:** Gemini CLI

## Summary

This review focuses on the `scrobbledb` codebase, specifically the CLI structure, core
logic separation, and overall code health. The project is well-structured using `click`
and `sqlite-utils`, but `src/scrobbledb/cli.py` has grown too large and mixes CLI concerns
with business logic.

## Key Findings & Recommendations

### 1. Refactor `src/scrobbledb/cli.py` (High Priority)

**Observation:**
The `src/scrobbledb/cli.py` file is over 900 lines long and contains the implementation for
multiple complex commands (`ingest`, `import`, `index`, `search`, `config`, `init`,
`reset`, `auth`). This makes the file hard to navigate and maintain.

**Recommendation:**
Split `cli.py` into smaller, command-specific modules within `src/scrobbledb/commands/`.
The `cli.py` file should only be responsible for the main entry point group and
registering subcommands.

**Proposed Structure:**
*   `src/scrobbledb/commands/ingest.py`: Move `ingest` command and its helper functions
    (`_ingest_no_batch`, `_ingest_batch`).
*   `src/scrobbledb/commands/import_cmd.py`: Move `import` command (renaming to avoid
    keyword conflict).
*   `src/scrobbledb/commands/search.py`: Move `search` and `index` commands.
*   `src/scrobbledb/commands/config.py`: Move `config` group and `init`, `reset`,
    `location` commands.
*   `src/scrobbledb/commands/auth.py`: Move `auth` command.

### 2. Extract Business Logic from CLI (Medium Priority)

**Observation:**
Significant business logic resides directly in CLI command functions. For example,
`_ingest_no_batch` and `_ingest_batch` in `cli.py` contain core logic for processing
tracks and saving them to the database. The `init` command contains logic for checking
system state.

**Recommendation:**
Move core business logic to `src/scrobbledb/lastfm.py` or new dedicated service modules.
*   **Ingestion Logic:** Move `_ingest_no_batch` and `_ingest_batch` to `lastfm.py` or a new
    `ingest_service.py`. The CLI should only handle argument parsing and UI (progress
    bars).
*   **Initialization Logic:** The `init` command's dry-run logic duplicates the actual
    execution logic. Refactor this into a "Plan/Execute" pattern where a
    `plan_initialization()` function returns a list of required actions, which the CLI can
    then display (dry-run) or execute.

### 3. Centralize Constants (Low Priority)

**Observation:**
File names like "auth.json", "scrobbledb.db", "loguru_config.toml" and environment variable
names are hardcoded as string literals in multiple places (`cli.py`, `config_utils.py`).

**Recommendation:**
Create a `src/scrobbledb/constants.py` file to hold these values. This ensures
consistency and makes it easier to change defaults in the future.

### 4. Enhance Type Hinting (Medium Priority)

**Observation:**
While some parts of `lastfm.py` use type hints, coverage is inconsistent.
`_extract_track_data` and API response parsing logic lack comprehensive type annotations.

**Recommendation:**
Add type hints to all functions in `lastfm.py` and new command modules. Use `mypy` or
`pyright` to verify type safety.

### 5. Improve Error Handling (Medium Priority)

**Observation:**
There are several broad `except Exception:` blocks in `cli.py`.

**Recommendation:**
Define a custom exception hierarchy for the application (e.g., `ScrobbleDBError`,
`ConfigError`, `APIError`). Catch specific exceptions where possible and let the
top-level CLI handler manage unexpected errors with a user-friendly message (and full
traceback only in verbose/debug mode).

### 6. Dependency Injection for Testing (Low Priority)

**Observation:**
Functions like `get_default_db_path` are called directly, making it harder to test
commands with temporary databases without mocking.

**Recommendation:**
Pass configuration objects or paths as arguments to business logic functions, rather than
having them call global configuration getters. This is already partially done with
`ctx.obj['database']` in `sql.py`, which is a good pattern to extend.

## specific Refactoring Steps

1.  **Create new command modules** in `src/scrobbledb/commands/`.
2.  **Move `ingest` logic**:
    *   Extract `_ingest_batch` and `_ingest_no_batch` to `src/scrobbledb/ingest_logic.py`.
    *   Move `ingest` command to `src/scrobbledb/commands/ingest.py`.
3.  **Move `search/index` logic**:
    *   Move `search` and `index` commands to `src/scrobbledb/commands/search.py`.
4.  **Move `config/auth` logic**:
    *   Move `config`, `init`, `reset`, `location` to `src/scrobbledb/commands/config.py`.
    *   Move `auth` to `src/scrobbledb/commands/auth.py`.
5.  **Clean up `cli.py`**:
    *   Remove moved code.
    *   Import and register new command groups/commands.
6.  **Verify**: Run tests to ensure no regressions.

## CLI Interface Standardization Plan

### Summary
The subcommands `albums`, `artists`, `plays`, and `tracks` have inconsistent structures,
argument names, and defaults. This plan aims to unify them for a predictable user
experience.

### 1. Unified Command Structure
Ensure all entity groups (`albums`, `artists`, `tracks`) have a consistent set of core
commands where applicable.

*   **`list`**: Browse the library (Missing in `tracks`).
*   **`search`**: Fuzzy search (Present in all entities; missing in `plays` but `list` with
    filters covers it).
*   **`show`**: Detail view (Present in all entities; missing in `plays` as they are
    events).
*   **`top`**: Statistics/Ranking (Missing in `albums`).

**Action Items:**
*   Implement `scrobbledb tracks list`: Allow browsing all tracks with filters (artist,
    album) and sorting.
*   Implement `scrobbledb albums top`: Show top albums by play count with time range
    support.

### 2. Standardize Arguments & Defaults
Make argument names and default values consistent across all commands.

*   **`--limit`**:
    *   `list` commands: Default to **50**.
    *   `search` commands: Default to **20**.
    *   `top` commands: Default to **10**.
*   **Sorting (`list` commands)**:
    *   Support `--sort` and `--order` consistently.
    *   Standard options: `plays` (default), `name`, `recent`.
*   **Filtering**:
    *   Ensure `--artist` filter is available on all `albums` and `tracks` commands.
    *   Add `--album` filter to `tracks top`.
    *   Consider adding ID-based filters (`--artist-id`, `--album-id`) consistently to
        avoid ambiguity, or document name matching behavior clearly.
*   **Time Ranges (`top` commands)**:
    *   Ensure `albums top` (new), `artists top`, and `tracks top` all support:
        *   `-s, --since`
        *   `-u, --until`
        *   `--period` (week, month, quarter, year, all-time)

### 3. Output Consistency
*   **`--format`**:
    *   Ensure `list`, `search`, and `top` support `[table|csv|json|jsonl]`.
    *   Ensure `show` supports `[table|json|jsonl]` (CSV is rarely useful for single
        hierarchical objects).
*   **Fields**:
    *   Audit column names in `--fields` to ensuring naming is consistent (e.g., `plays`
        everywhere, not `count` or `play_count`).

### 4. Implementation Strategy
*   Refactor `src/scrobbledb/commands/` modules to share common argument definitions (using
    `click` decorators or shared constants) to prevent future drift.
*   Update `tracks.py` to add `list` command.
*   Update `albums.py` to add `top` command.
*   Update existing commands to match new defaults.
