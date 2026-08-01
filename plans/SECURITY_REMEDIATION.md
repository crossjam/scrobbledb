# Security Remediation Plan

> Based on security review conducted 2025-06-14.  
> All findings are local-only CLI surface; no network-facing attack surface exists.

## 1. Auth file permissions (HIGH)

**Problem:** `auth.json` (API key, API secret, session key) is written with default
permissions (0644), making it readable by any user on the system.

**Fix location:** `src/scrobbledb/config_utils.py` and `src/scrobbledb/cli.py`

**Steps:**
1. Add a helper `_write_auth_file(path, data)` to `config_utils.py` that:
   - Writes JSON to a temp file in the same directory
   - Atomically renames into place (os.replace)
   - Sets permissions to 0o600 on the final file
2. Replace the two inline `json.dump(auth_data, open(auth, "w"))` calls in `cli.py`
   (one in `auth` command, check for any in `ingest` or others) with the helper.
3. Add a migration: if auth.json already exists with lax permissions, fix them on
   next `auth` run (or `config init`).
4. Add a test that asserts auth.json has mode 0o600 after write.

```python
# config_utils.py - new helper
import os
import json
import tempfile
from pathlib import Path

def write_auth_file(path: str | Path, data: dict) -> None:
    """Write auth data with restricted permissions (owner read/write only)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".auth-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)  # atomic on same filesystem
    except Exception:
        os.unlink(tmp)
        raise
```

## 2. Raw SQL escape hatches (HIGH)

**Problem:** `sql query`, `export --sql`, and `sql rows --where` allow arbitrary SQL
execution. By design for power users but unguarded.

**Fix location:** `src/scrobbledb/sql.py`, `src/scrobbledb/export.py`, docs

**Steps:**
1. Add a policy note to the `sql` group help text and the top-level README:
   "These commands pass SQL directly to sqlite3 — prefer domain commands
   (plays, albums, artists, tracks) for parameterized, injection-safe queries."
2. Consider a `--safe` flag on `sql query` that rejects writes (INSERT/UPDATE/DELETE/DROP).
   This would still allow arbitrary SELECT but prevent accidental data destruction.
   (Optional — low priority since it's a local tool.)
3. Add a note in `sql rows` help that `--where` takes raw SQL and
   `--param` is the safe path for user-supplied values. This already exists
   in the docstring but could be more prominent.

## 3. Export `--output` overwrite warning (MEDIUM)

**Problem:** `scrobbledb export --output /some/path` silently overwrites files.

**Fix location:** `src/scrobbledb/export.py`

**Steps:**
1. Before writing to `--output` (when it's not stdout), check if the file exists.
2. If it exists and stdin is a TTY (interactive), prompt for confirmation via
   `click.confirm`. Skip prompt with `--force`/`--yes` flag.
3. Add test: verify prompt fires when file exists.

```python
# In export(), before Path(output).write_text(...)
if output != "-" and Path(output).exists() and not force:
    if not click.confirm(f"File '{output}' exists. Overwrite?"):
        raise click.Abort()
```

## 4. `loguru-config` fork review (MEDIUM)

**Problem:** Dependency pinned to a personal GitHub fork.

**Fix location:** `pyproject.toml`

**Steps:**
1. Review the `crossjam/loguru-config` fork diff against upstream to confirm
   changes are benign / necessary.
2. If changes are minor patches, upstream them and switch back to PyPI release.
3. If the fork is essential, document why in pyproject.toml or a SECURITY.md.
4. Consider adding a Dependabot or Renovate config to track this dependency.

## 5. Credentials in verbose logging (LOW)

**Problem:** `--verbose` enables loguru debug logging. If a future change logs
API responses verbatim, session keys or tokens could leak into log files.

**Fix location:** `src/scrobbledb/cli.py` (ingest function), `src/scrobbledb/lastfm.py`

**Steps:**
1. Audit `lastfm.py` for any `logger.debug` calls that might output raw API
   responses, tokens, or credentials.
2. Add a note in the logging section of the code: "Do not log raw API responses
   or authentication material."
3. Consider a `loguru` filter that sanitizes known credential keys from log
   output. (Optional — belt and suspenders.)

## 6. FTS5 query errors for special characters (LOW)

**Problem:** FTS5 MATCH queries with special characters (~, *, ", etc.) produce
cryptic SQLite errors instead of helpful messages.

**Fix location:** `src/scrobbledb/lastfm.py` (`search_tracks`), `src/scrobbledb/cli.py` (`search`)

**Steps:**
1. In `search_tracks()`, catch `sqlite3.OperationalError` from FTS5 MATCH and
   re-raise with a user-friendly message.
2. Optionally: add FTS5 query sanitization (escape special chars or wrap in
   double-quotes) before passing to MATCH.

## Execution order

1. Auth file permissions (simple fix, highest impact)
2. Export overwrite warning (simple fix, user safety)
3. FTS5 error messages (simple fix, UX)
4. Raw SQL documentation (docs only, no code change)
5. loguru-config fork review (investigation, no immediate code change)
6. Credential logging audit (investigation + possible log filter)