# Implementation Plan: CLI Interface Standardization

This plan outlines the steps to unify the `scrobbledb` CLI subcommands (`albums`, `artists`, `plays`, and `tracks`) for a consistent and predictable user experience, as recommended in the code review.

## 1. Goal
Unify command structures, argument names, default values, and output formats across all entity groups.

## 2. New Commands to Implement

### `scrobbledb tracks list`
Allow browsing all tracks with filters and sorting.
- **Location**: `src/scrobbledb/commands/tracks.py`
- **Arguments**: 
    - `--artist`, `--artist-id`
    - `--album`, `--album-id`
    - `--sort` (plays, name, recent)
    - `--order` (desc, asc)
    - `--limit` (default: 50)
    - `--min-plays` (default: 0)
    - `--format` (table, csv, json, jsonl)
    - `--fields`

### `scrobbledb albums top`
Show top albums by play count with time range support.
- **Location**: `src/scrobbledb/commands/albums.py`
- **Arguments**:
    - `-s, --since`
    - `-u, --until`
    - `--period` (week, month, quarter, year, all-time)
    - `--limit` (default: 10)
    - `--artist`
    - `--format` (table, csv, json, jsonl)
    - `--fields`

## 3. Standardization Tasks

### A. Default Limits
Ensure consistent `--limit` defaults:
- `list` commands: **50** (Update `plays list` from 20 to 50)
- `search` commands: **20** (Currently consistent)
- `top` commands: **10** (Currently consistent)

### B. Sorting & Ordering
Standardize `--sort` and `--order` for `list` commands:
- **Options**: `plays`, `name`, `recent`.
- **Default Sort**: `recent` (was `plays`).
- **Order**: `desc` (default), `asc`.
- **Affects**: `albums list`, `artists list`, `tracks list` (new).

### C. Filtering
Ensure consistent filter availability:
- **`albums` commands**: Ensure `--artist` and `--artist-id` are available where appropriate.
- **`tracks` commands**: 
    - Add `--album` filter to `tracks top`.
    - Ensure `--artist`, `--artist-id`, `--album`, `--album-id` are available in `tracks list`.

### D. Time Ranges
Standardize time range options for all `top` and history-based commands:
- Support `-s, --since`, `-u, --until`, and `--period` consistently.
- **Affects**: `artists top`, `tracks top`, `albums top` (new), and `plays list` (add `--period`).

### E. Output & Fields
- **Formats**: Ensure `list`, `search`, and `top` support `[table|csv|json|jsonl]`.
- **Formats**: Ensure `show` supports `[table|json|jsonl]`.
- **Field Names**: Audit column names in `--fields` to use `plays` consistently (instead of `play_count` or `count`).

### F. Albums List Improvements (Issue #47)
Update `scrobbledb albums list` to improve usability:
- **Grouping**: Group results by album (default behavior). The current implementation lists individual tracks or duplicate entries for albums.
- **Last Played**: Display the "Last Played" date using the most recent track played from that album.
- **Expansion**: Add an `--expand` flag to optionally show all recent tracks played from a grouped album.
- **Formatting**: Update table output to reflect grouped data clearly.

## 4. Implementation Steps

1.  **Refactor Shared Arguments**: 
    - Create a helper in `src/scrobbledb/cli.py` or a new `src/scrobbledb/command_utils.py` to provide common `click` options (e.g., `@common_options`, `@time_range_options`).
2.  **Update `domain_queries.py`**:
    - Add `get_tracks_list` to support the new `tracks list` command.
    - Add `get_top_albums` to support the new `albums top` command.
    - **Update `get_albums_list`**: Modify query to group by album and aggregate `last_played`. Support fetching tracks for `--expand`.
3.  **Update `domain_format.py`**:
    - Add formatting helpers for the new commands.
    - Ensure field mappings use `plays` consistently.
    - **Update `format_albums_list`**: Support grouped album display and expanded track view.
4.  **Implement New Commands**:
    - `scrobbledb tracks list` in `src/scrobbledb/commands/tracks.py`.
    - `scrobbledb albums top` in `src/scrobbledb/commands/albums.py`.
5.  **Update Existing Commands**:
    - Update `plays list` default limit and add `--period`.
    - Update `tracks top` to add `--album` filter.
    - **Update `albums list`**: Add `--expand` flag and integrate with updated query logic.
    - Ensure all commands use the shared argument decorators.
6.  **Verification**:
    - Manual verification of each command's help output and execution.
    - Verify `albums list` grouping and expansion.
    - Update/add tests in `tests/` to cover new commands and standardized arguments.
