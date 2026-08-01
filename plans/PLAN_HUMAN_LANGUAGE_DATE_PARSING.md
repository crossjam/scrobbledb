# Plan: Human Language Date Parsing (Issue #19)

## Background

- **Issue**: GitHub Issue #19 requests that users be able to supply natural language like `yesterday`, `last month`, or `Monday` wherever a date is accepted.
- **Current state**: A hand-rolled `parse_relative_time()` in `domain_queries.py` handles a narrow set of patterns (`today`, `yesterday`, `last week/month/year`, `N days/weeks/months/years ago`) then falls back to `dateutil.parser.parse()`. All five command modules (`plays`, `tracks`, `albums`, `artists`, `stats`) call this function. The `ingest` command in `cli.py` bypasses it entirely and calls `dateutil.parser.parse()` directly.
- **Key finding**: `dateparser` — a library that handles the full natural-language date surface the issue asks for — is **already declared as a dependency** in `pyproject.toml` but is never imported anywhere in the codebase.

## Goal

Replace the custom parsing logic with `dateparser` so that every `--since`, `--until`, `--since-date`, and `--until-date` option accepts expressions like:

- `yesterday`, `today`
- `last month`, `last week`, `last year`
- `Monday`, `last Tuesday`
- `3 weeks ago`, `6 months ago`
- `January 2024`, `Jan 15`
- ISO 8601 dates (must continue to work)

---

## Implementation Phases (TDD Red → Green)

### Phase 1 — Red: Write failing tests

Create `tests/test_date_parsing.py` covering `parse_relative_time()`:

**Must still pass (regression):**
- `"2024-01-15"` → datetime(2024, 1, 15)
- `"today"` → today's date
- `"yesterday"` → yesterday's date
- `"7 days ago"` → ~7 days before now
- `"last month"` → ~1 month before now
- `""` / `"garbage"` → `None`

**New cases (will fail until Phase 2):**
- `"Monday"` → most recent Monday
- `"last Tuesday"` → datetime (last Tuesday)
- `"3 weeks ago"` → ~21 days before now
- `"January 2024"` → datetime(2024, 1, 1) (or first of month)
- `"6 months ago"` → ~6 months before now

Run `uv run poe test:quick` — expect new test cases to fail.

### Phase 2 — Green: Replace `parse_relative_time()`

In `src/scrobbledb/domain_queries.py`, replace the body of `parse_relative_time()` (currently lines 196–257) with:

```python
import dateparser

def parse_relative_time(time_str: str) -> Optional[datetime]:
    result = dateparser.parse(
        time_str,
        settings={"RETURN_AS_TIMEZONE_AWARE": False, "PREFER_DAY_OF_MONTH": "first"},
    )
    if result:
        return result
    try:
        return dateutil.parser.parse(time_str)
    except (ValueError, TypeError):
        return None
```

Run `uv run poe test:quick` — all tests including new cases should now pass.

### Phase 3 — Green: Fix `ingest` in `cli.py`

In `src/scrobbledb/cli.py`, import `parse_relative_time` from `domain_queries` and replace the two direct `dateutil.parser.parse()` calls for `since_date` / `until_date` (around lines 898 and 901) with `parse_relative_time()`.

Run `uv run poe test:quick` — no regressions.

### Phase 4 — Polish: Update help text

In each command file, extend the `--since` / `--until` `help=` strings to mention natural language. Pattern to apply across all five command modules and `cli.py`:

> `"Filter from DATE (ISO 8601 or natural language: yesterday, last month, Monday)"`

Files: `commands/plays.py`, `commands/tracks.py`, `commands/albums.py`, `commands/artists.py`, `commands/stats.py`, `cli.py`.

Run `uv run poe lint` to catch any formatting issues.

---

## Files to Modify

| File | Change |
|------|--------|
| `tests/test_date_parsing.py` | **New** — full test suite for `parse_relative_time()` |
| `src/scrobbledb/domain_queries.py` | Replace body of `parse_relative_time()` with `dateparser` |
| `src/scrobbledb/cli.py` | Replace 2 direct `dateutil` calls in `ingest` |
| `src/scrobbledb/commands/plays.py` | Update `--since`/`--until` help text |
| `src/scrobbledb/commands/tracks.py` | Update `--since`/`--until` help text |
| `src/scrobbledb/commands/albums.py` | Update `--since`/`--until` help text |
| `src/scrobbledb/commands/artists.py` | Update `--since`/`--until` help text |
| `src/scrobbledb/commands/stats.py` | Update `--since`/`--until` help text |

No new dependencies needed — `dateparser>=1.1.0` is already in `pyproject.toml`.

---

## Verification

```bash
# Full test suite after each phase
uv run poe test:quick

# Smoke test natural language expressions end-to-end
uv run scrobbledb plays list --since "last month" --limit 5
uv run scrobbledb plays list --since "yesterday"
uv run scrobbledb tracks top --since "Monday"
uv run scrobbledb stats monthly --since "3 weeks ago"

# Regression: ISO dates must still work
uv run scrobbledb plays list --since "2024-01-01" --until "2024-12-31" --limit 5
```
