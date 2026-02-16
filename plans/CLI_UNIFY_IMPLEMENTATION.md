# CLI Unification Implementation Progress

This document tracks the progress of the CLI interface standardization plan.

## Progress

- [x] **1. Refactor Shared Arguments**
    - [x] Create `src/scrobbledb/command_utils.py` for shared `click` options.
- [x] **2. Update `domain_queries.py`**
    - [x] Add `get_tracks_list`.
    - [x] Add `get_top_albums`.
    - [x] Update `get_albums_list` (grouping & aggregation).
- [x] **3. Update `domain_format.py`**
    - [x] Add `format_tracks_list`.
    - [x] Add `format_top_albums`.
    - [x] Update `format_albums_list` (grouped display).
- [x] **4. Implement New Commands**
    - [x] `scrobbledb tracks list` (`src/scrobbledb/commands/tracks.py`).
    - [x] `scrobbledb albums top` (`src/scrobbledb/commands/albums.py`).
- [x] **5. Update Existing Commands**
    - [x] Update `plays list` (limit=50, add `--period`).
    - [x] Update `tracks top` (add `--album` filter).
    - [x] Update `albums list` (add `--expand` flag).
    - [x] Apply shared argument decorators to all commands.
- [x] **6. Verification**
    - [x] Manual verification.
    - [x] Update/add tests.
    - [x] Regenerate CLI documentation snippets.

## Design Decisions & Changes

### 1. Refactor Shared Arguments
Created `src/scrobbledb/command_utils.py` containing:
- `database_option`
- `limit_option`
- `format_option`
- `fields_option`
- `time_range_options`
- `sort_options`
- `filter_options`
- `check_database` helper

### 2. Domain Queries
- Added `get_tracks_list` with comprehensive filtering.
- Added `get_top_albums` with time range support.
- `get_albums_list` already supported grouping, ensured it returns necessary data.
- Added `get_album_tracks` call in `list_albums` when expanded.

### 3. Domain Format
- Added `format_tracks_list` reusing `format_tracks_search`.
- Added `format_top_albums` similar to `format_top_artists`.
- Updated `format_albums_list` to support `expand=True`, rendering a panel per album with a nested track table.

### 4. Commands
- `tracks`: Added `list` command. Updated `top` with `--album`.
- `albums`: Added `top` command. Updated `list` with `--expand`.
- `artists` & `plays`: Refactored to use shared decorators.

### 5. Documentation
- Regenerated help snippets for all subcommands using `poe docs:cli` to ensure consistency between code and documentation.
