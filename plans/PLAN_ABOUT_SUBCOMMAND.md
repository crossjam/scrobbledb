# Plan: Add `about` Subcommand to scrobbledb

## Background

- **Issue**: GitHub Issue #14 requests an `about` subcommand that provides more detailed information about the project.
- **Current state**: The CLI already exposes `--version` and a `version` command, but there is no richer project overview command.
- **Goal**: Add a read-only `about` command that gives users a useful project summary, default storage locations, and next-step guidance.

## Problem Statement

Today, users can discover the installed version of scrobbledb, but they cannot ask the CLI basic questions such as:

- What is this tool for?
- Where does it store its data?
- Where is the default database?
- Where is the auth file?
- Where is the project hosted?
- What commands should I run first?

This information exists across `README.md`, package metadata, and helper functions in `src/scrobbledb/cli.py`, but it is not available through a dedicated command.

## Proposed Command

Add a new root-level command:

```bash
scrobbledb about
```

This command should be human-oriented and terminal-friendly. It should complement `scrobbledb version`, not replace it.

## Scope

### In Scope

- Add a root CLI command named `about`
- Display a concise project overview
- Display installed version
- Display repository URL
- Display authors / attribution
- Display default data directory
- Display default database path
- Display default auth path
- Display short getting-started hints
- Add tests
- Add command documentation
- Update README command overview

### Out of Scope

- Network calls
- Database inspection or health checks
- Auth validation
- Environment diagnosis beyond showing default paths
- JSON or machine-readable output modes
- Replacing the existing `version` command

## Existing Code and Reusable Pieces

The following functionality already exists and should be reused:

- `get_version("scrobbledb")` in `src/scrobbledb/cli.py`
- `get_data_dir()`
- `get_default_db_path()`
- `get_default_auth_path()`
- Rich console output patterns already used throughout the CLI

Relevant files:

- `src/scrobbledb/cli.py`
- `tests/test_cli.py`
- `README.md`
- `pyproject.toml`
- `docs/commands/version.md`
- `tests/test_docs_generation.py`

## Recommended Output

The command should print a compact, readable summary similar to:

- Project name: `scrobbledb`
- Version: installed package version
- Description: "Save data from last.fm/libre.fm to a SQLite database"
- Repository: `https://github.com/crossjam/scrobbledb`
- Authors: Jacob Kaplan-Moss and Brian M. Dennis
- Data directory: resolved XDG/platformdirs path
- Default database: resolved path to `scrobbledb.db`
- Default auth file: resolved path to `auth.json`
- Quick start hints:
  - `scrobbledb auth`
  - `scrobbledb config init`
  - `scrobbledb ingest`

## Implementation Approach

### Option A: Simple root command in `cli.py` (Recommended)

Add `@cli.command()` next to the existing `version` command and render the output with Rich.

Advantages:
- Minimal surface area
- Fits the current architecture
- Reuses existing helper functions
- Easy to test with `CliRunner`

Disadvantages:
- Some displayed metadata may need to be duplicated as short strings if not easy to retrieve from installed package metadata

### Option B: Separate module for informational commands

Create a new command module and register it from `cli.py`.

Advantages:
- Better separation if more metadata/info commands appear later

Disadvantages:
- Unnecessary indirection for a single small command
- Adds structure before there is a demonstrated need

**Recommendation**: Use Option A.

## Detailed Implementation Plan

### 1. Add failing tests first

Create tests in `tests/test_cli.py` that define the expected behavior.

Tests to add:

- `test_about_command_exists()`
  - Invoke `cli.cli` with `about`
  - Expect exit code `0`

- `test_about_command_includes_project_identity()`
  - Assert output includes `scrobbledb`
  - Assert output includes either `version` or the resolved version string
  - Assert output includes the GitHub repository URL

- `test_about_command_includes_default_paths()`
  - Assert output includes the default data dir, default DB path, and default auth path

- `test_about_help_is_available()`
  - Invoke `about --help`
  - Verify help text describes the purpose of the command

### 2. Implement the `about` command in `src/scrobbledb/cli.py`

Add a new command near `version`:

- Resolve version with `get_version("scrobbledb")`
- Resolve paths with existing helper functions
- Render output using Rich (panel, plain lines, or a table)
- Keep the output concise and stable for test assertions

Behavior requirements:

- Must not require an initialized database
- Must not require auth configuration
- Must not require network access
- Must succeed on a fresh install

### 3. Keep `version` and `about` responsibilities separate

Do not change these existing behaviors:

- `scrobbledb --version`
- `scrobbledb -V`
- `scrobbledb version`

`version` should remain terse and script-friendly.

`about` should remain explanatory and user-facing.

### 4. Add command documentation

Create a new docs file:

- `docs/commands/about.md`

Pattern it after existing command docs such as `docs/commands/version.md`.

Include:
- one-line description
- cog-generated `--help` snippet
- a short example using `uv run scrobbledb about`
- a short explanation of when to use the command

### 5. Update README command overview

Modify `README.md` to include `about` in the command overview.

Recommended placement:
- under the "Advanced" section near `version`
- or under a general informational/utilities grouping if the command list is reorganized later

### 6. Regenerate and verify CLI docs

This repository checks that generated CLI documentation stays in sync.

After adding the new command docs, run:

```bash
uv run poe docs:cli
```

This should update the embedded help output in `docs/commands/about.md` and any other touched command docs.

### 7. Run focused verification

Run:

```bash
uv run pytest tests/test_cli.py -q
uv run pytest tests/test_docs_generation.py -q
```

Optionally run broader verification:

```bash
uv run poe test:quick
```

## Example Help Text Direction

Suggested help description:

- "Display information about the scrobbledb project."
- "Shows project summary, version, repository URL, and default storage paths."

Suggested command output structure:

```text
scrobbledb
version: 1.2.0
summary: Save data from last.fm/libre.fm to a SQLite database
repository: https://github.com/crossjam/scrobbledb
authors: Jacob Kaplan-Moss; Brian M. Dennis
data directory: /path/to/data
default database: /path/to/scrobbledb.db
default auth file: /path/to/auth.json
next steps: scrobbledb auth | scrobbledb config init | scrobbledb ingest
```

The implementation may use Rich styling, but the underlying content should stay stable and testable.

## Risks and Pitfalls

1. **Overengineering metadata lookup**
   - Avoid complicated package metadata parsing if short stable strings are easier and more reliable.

2. **Blurring `version` and `about`**
   - Keep `version` terse.
   - Put richer human-facing content in `about`.

3. **Tests tied too tightly to Rich formatting**
   - Assert on stable content, not exact spacing or panel borders.

4. **Forgetting docs sync**
   - `tests/test_docs_generation.py` will fail if generated docs are stale.

5. **Adding status logic accidentally**
   - Resist checking file existence or DB state in v1.
   - Keep the command informational, not diagnostic.

## Success Criteria

- ✅ `scrobbledb about` exists as a root command
- ✅ The command exits successfully on a fresh environment
- ✅ Output includes project identity, version, repo URL, and default paths
- ✅ `scrobbledb about --help` is available and clear
- ✅ `docs/commands/about.md` exists
- ✅ `README.md` mentions the command
- ✅ CLI docs regenerate cleanly
- ✅ Relevant tests pass

## Suggested Commit Sequence

1. Add tests for `about`
2. Implement `about` command
3. Add docs file and README update
4. Regenerate docs
5. Run tests
6. Commit as:

```bash
git commit -m "feat: add about subcommand plan"
```

## Future Enhancements (Not Required for Issue #14)

Possible later additions after the MVP lands:

- Show license information
- Show whether the default DB/auth files exist
- Show current configured scrobble network
- Show install location or Python environment details
- Add `--json` output if machine-readable metadata ever becomes useful

---

This plan intentionally keeps the first implementation small, useful, and consistent with the existing CLI architecture.