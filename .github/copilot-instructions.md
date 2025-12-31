# GitHub Copilot Instructions for scrobbledb

> Custom instructions for GitHub Copilot when working on the scrobbledb project.

## ⚠️ Critical: Always Use `uv` and `poe`

**This project uses `uv` (modern Python package manager) and `poe` (Poe the Poet task runner) exclusively.**

### Quick Reference

```bash
# Setup
uv sync                          # Install/sync dependencies

# Testing (use poe first!)
poe test                         # Run all tests
poe test:quick                   # Stop on first failure
poe test:cov                     # Coverage report

# Code Quality
poe lint                         # Check code style
poe lint:fix                     # Auto-fix issues
poe type                         # Type check
poe audit                        # Security scan
poe qa                           # Run all checks

# Running the app
uv run scrobbledb --help         # Main CLI
uv run scrobbledb search "query" # Run a command

# Direct pytest (when poe tasks aren't enough)
uv run pytest tests/test_cli.py -v
```

### Rules

- ✅ **DO**: Use `uv run` for all Python commands
- ✅ **DO**: Use `poe` for running tasks (tests, lint, type check)
- ✅ **DO**: Use `uv add` to add dependencies
- ❌ **DON'T**: Manually activate virtualenvs
- ❌ **DON'T**: Use `pip`, `poetry`, `pipenv`, or other package managers
- ❌ **DON'T**: Run `python`, `pytest`, or `ruff` directly without `uv run`

---

## Project Overview

**scrobbledb** is a Python CLI application that saves listening history from last.fm/libre.fm to a SQLite database. It's a modernization of Jacob Kaplan-Moss's lastfm-to-sqlite project.

**Technology Stack:**
- **Package Manager**: `uv` - Modern, fast Python package installer and resolver
- **Task Runner**: `poe` (Poe the Poet) - Defined in pyproject.toml
- **Language**: Python 3.11+
- **CLI Framework**: Click
- **UI/Output**: Rich (for tables, progress bars, styled output) and Textual (for TUI)
- **Database**: SQLite via sqlite-utils
- **API Client**: pylast (Last.fm API wrapper)
- **Testing**: pytest (run via `uv` or `poe`)
- **Type Checking**: ty (lenient configuration, run via `poe type`)
- **Linting**: ruff (run via `poe lint`)

## Repository Structure

```
scrobbledb/
├── src/scrobbledb/          # Main package source
│   ├── cli.py               # Main CLI entry point (Click commands)
│   ├── lastfm.py           # Last.fm API interaction and data models
│   ├── sql.py              # SQL subcommand (sqlite-utils wrappers)
│   ├── export.py           # Export command
│   ├── browse.py           # Data adapter for browsing
│   ├── tui.py              # Textual-based terminal UI
│   └── __init__.py
├── tests/                   # Test suite
├── plans/                   # Design documents and planning docs
├── pyproject.toml          # Project configuration
├── AGENTS.md               # Instructions for AI coding agents
├── CLAUDE.md               # Reference to AGENTS.md
└── README.md               # Project documentation
```

## Development Workflow with `uv` and `poe`

### First Time Setup

```bash
# Install dependencies from pyproject.toml and uv.lock
uv sync

# Verify installation
uv run scrobbledb --help
```

### Task Runner: `poe` (Preferred Method)

**All common development tasks are defined in `pyproject.toml` under `[tool.poe.tasks]`.**

Use `poe` for everything - it's cleaner and ensures consistency:

```bash
# List all available tasks with descriptions
poe

# Testing
poe test              # Run all tests with verbose output
poe test:cov          # Run tests with coverage report (terminal + HTML)
poe test:quick        # Run tests, stop on first failure (-x flag)

# Code Quality
poe lint              # Run ruff linter on src/ and tests/
poe lint:fix          # Auto-fix linting issues
poe type              # Run ty type checker on src/

# Security
poe audit             # Run pip-audit for vulnerability scanning

# Combined QA (runs lint, type, audit, test in sequence)
poe qa                # Run all quality assurance checks
```

### Direct `uv run` Commands (When Needed)

Only use direct `uv run` commands when you need custom flags not covered by `poe` tasks:

```bash
# Run CLI with custom arguments
uv run scrobbledb search "query"

# Run tests with specific options
uv run pytest tests/test_cli.py -v -k test_search
uv run pytest -q -x  # Quiet, stop on first failure
uv run pytest --cov=scrobbledb --cov-report=html

# Run tools with custom options
uv run ruff check src/ tests/ --fix
uv run ruff format src/ tests/
uv run ty check src/scrobbledb/cli.py
```

### Package Management with `uv`

```bash
# Add a new dependency
uv add package-name

# Add a development dependency
uv add --dev package-name

# Update dependencies
uv sync

# Lock dependencies
uv lock
```

### The `uv` Philosophy

- `uv` manages the virtual environment automatically in `.venv/`
- Never manually activate the virtualenv
- Always prefix Python commands with `uv run`
- `uv` is significantly faster than pip/poetry
- Dependencies are locked in `uv.lock` for reproducibility

## Database Schema

Core tables in the SQLite database:

- **`artists`** - Artist information (id, name)
- **`albums`** - Album information (id, title, artist_id)
- **`tracks`** - Track information (id, title, album_id)
- **`plays`** - Play events (track_id, timestamp)
- **`tracks_fts`** - FTS5 full-text search index

## CLI Architecture

### Command Structure

```
scrobbledb
├── auth              # Configure API credentials
├── ingest            # Import listening history from Last.fm
├── import            # Import scrobbles from file (JSONL, CSV, TSV)
├── index             # Setup/rebuild FTS5 search index
├── search            # Full-text search across tracks
├── browse            # Interactive TUI for browsing tracks
├── export            # Export data in various formats
├── config            # Configuration management
│   ├── init          # Initialize database
│   ├── reset         # Reset database
│   └── location      # Show config paths
└── sql               # SQL query commands (sqlite-utils wrappers)
    ├── query         # Execute SQL queries
    ├── tables        # List tables
    ├── schema        # Show schema
    ├── rows          # Browse table rows
    └── ...           # More sqlite-utils commands
```

### Design Patterns

1. **XDG Compliance**: All data stored in XDG-compliant directories
   - Use `get_default_db_path()`, `get_default_auth_path()` helpers
   - Located in `~/.local/share/dev.pirateninja.scrobbledb/`

2. **Rich Output**: Use Rich library for all terminal output
   - Tables: `rich.table.Table`
   - Progress bars: `rich.progress.Progress`
   - Panels: `rich.panel.Panel`
   - Console: `rich.console.Console`

3. **Database Operations**: Use sqlite-utils
   - Database class: `sqlite_utils.Database`
   - Table operations: `db.table("name")`
   - Query execution: `db.execute(sql)`

4. **Error Handling**: User-friendly error messages with exit codes
   - Show actionable suggestions
   - Use Rich for formatted error output
   - Exit with appropriate codes (0=success, 1=error)

## Coding Conventions

### Style

- **Python Version**: 3.11+ (use modern syntax where appropriate)
- **Type Hints**: Gradually adding type hints (lenient ty configuration)
- **Docstrings**: Use for public functions and classes
- **Line Length**: Follow ruff defaults (~88 characters)
- **Imports**: Organized and formatted by ruff

### Naming

- **Functions/Variables**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private**: Prefix with underscore `_private_function`

### CLI Options

- Long form: `--option-name`
- Short form: `-o` (single letter)
- Boolean flags: Use `is_flag=True`
- Paths: Use `click.Path()` with appropriate validators
- Defaults: Always show with `show_default=True` where relevant

### Database Queries

- Use parameterized queries: `db.execute(sql, [params])`
- Quote identifiers with square brackets: `[column_name]`
- Validate ORDER BY clauses before execution (see `sql.py` for example)
- Use appropriate indexes for performance

## Testing Guidelines

### Test Organization

- Test files mirror source structure: `tests/test_<module>.py`
- Use pytest fixtures for common setup
- Test database operations with temporary databases
- Use descriptive test names: `test_<function>_<scenario>`

### Running Tests (Use `poe` first)

**Preferred: Use `poe` tasks**
```bash
poe test              # Run all tests (pytest -v)
poe test:quick        # Stop on first failure (pytest -x)
poe test:cov          # Run with coverage report
```

**Alternative: Direct `uv run pytest` for custom flags**
```bash
uv run pytest                           # Run all tests
uv run pytest tests/test_cli.py         # Run specific test file
uv run pytest -k test_search            # Run tests matching pattern
uv run pytest -v --tb=short             # Verbose with short tracebacks
uv run pytest --lf                      # Run last failed tests
```

**Never run** `pytest` directly - always use `uv run pytest` or `poe test`

## Common Patterns

### Adding a New CLI Command

1. Define command in appropriate module (or create new one)
2. Use `@click.command()` decorator
3. Add options with proper validation
4. Include comprehensive help text with examples
5. Use Rich for output formatting
6. Handle errors gracefully
7. Register command in `cli.py`

Example:
```python
@cli.command()
@click.argument('query')
@click.option('--limit', '-l', type=int, default=20, 
              help='Maximum results', show_default=True)
def search(query, limit):
    """Search for tracks using full-text search.
    
    Example:
        scrobbledb search "rolling stones"
    """
    # Implementation
```

### Database Queries with Statistics

```python
# Query with joins and aggregations
sql = """
    SELECT 
        artists.name as artist_name,
        COUNT(plays.track_id) as play_count,
        MAX(plays.timestamp) as last_played
    FROM plays
    JOIN tracks ON plays.track_id = tracks.id
    JOIN albums ON tracks.album_id = albums.id
    JOIN artists ON albums.artist_id = artists.id
    GROUP BY artists.id
    ORDER BY play_count DESC
    LIMIT ?
"""
results = db.execute(sql, [limit]).fetchall()
```

### Rich Table Output

```python
from rich.table import Table
from rich.console import Console

console = Console()
table = Table(title="Search Results")
table.add_column("Artist", style="cyan")
table.add_column("Track", style="green")
table.add_column("Plays", justify="right", style="yellow")

for row in results:
    table.add_row(row['artist'], row['track'], str(row['plays']))

console.print(table)
```

## Key Dependencies

### Core Libraries

- **click** - CLI framework (used extensively)
- **rich** - Terminal formatting and tables
- **textual** - TUI framework (for browse command)
- **sqlite-utils** - SQLite database operations
- **pylast** - Last.fm API wrapper
- **stamina** - Retry logic for API requests
- **python-dateutil** - Date/time parsing
- **platformdirs** - XDG-compliant directory paths
- **loguru** - Logging (with loguru-config)

### Development Tools

- **pytest** - Testing framework
- **pytest-cov** - Coverage reporting
- **ruff** - Fast Python linter and formatter
- **ty** - Type checker
- **pip-audit** - Security vulnerability scanner
- **poethepoet** - Task runner

## XDG Directory Structure

Default locations (platform-specific):

```
# Linux/Unix
~/.local/share/dev.pirateninja.scrobbledb/
├── scrobbledb.db           # SQLite database
├── auth.json               # API credentials
└── loguru_config.toml      # Logging configuration

# macOS
~/Library/Application Support/dev.pirateninja.scrobbledb/

# Windows
%LOCALAPPDATA%\dev.pirateninja.scrobbledb\
```

## API Integration

### Last.fm API

- Use `pylast` library for all API interactions
- Implement retry logic with `stamina` for transient failures
- Handle rate limiting and errors gracefully
- Use session keys for authenticated requests

### Retry Pattern

```python
import stamina
from pylast import WSError

for attempt in stamina.retry_context(
    on=WSError,
    attempts=5,
    wait_initial=1.0,
    wait_max=16.0,
    wait_jitter=1.0,
):
    with attempt:
        # API request here
        pass
```

## Design Documents

All design documents are stored in `plans/` directory:

- `PLAN_SQL_SUBCOMMAND.md` - SQL subcommand design
- `PLAN_FOR_TRACK_BROWSING_TUI.md` - TUI browser design
- `PLAN_BATCH_INSERT.md` - Batch insert optimization
- `PLAN_FTS5_TRIGGER_FIX.md` - FTS5 index management
- `PLAN_RETRY_ON_FAILURE.md` - API retry logic
- `domain-specific-cli.md` - Domain-specific commands design

When implementing new features, check for existing design documents first.

## Security Considerations

1. **SQL Injection**: Always use parameterized queries
2. **Path Traversal**: Validate file paths with `click.Path()`
3. **Credentials**: Never log or print sensitive data
4. **Dependencies**: Run `poe audit` or `pip-audit` regularly

## Performance Tips

1. **Database Indexes**: Ensure appropriate indexes exist
   - `plays(timestamp)` for time-range queries
   - `plays(track_id, timestamp)` for track history
   
2. **Batch Operations**: Use batch inserts when importing large datasets
   - See `_ingest_batch()` in `cli.py`
   
3. **FTS5 Search**: Use full-text search index when available
   - Check for `tracks_fts` table existence
   - Fallback to SQL LIKE if not available

## Common Gotchas

1. **❌ Never activate virtualenvs manually** - Always use `uv run` or `poe`
2. **❌ Never run `python` directly** - Use `uv run python` instead
3. **❌ Never run `pytest` directly** - Use `poe test` or `uv run pytest`
4. **✅ Always use `poe` for standard tasks** - Faster and more consistent
5. **✅ Use `uv add` to add dependencies** - Not `pip install`
6. **Quote SQL identifiers** - Use square brackets `[column_name]` for special characters
7. **Rich output to files** - Check if output is a terminal: `console.is_terminal`
8. **Date parsing** - Use `dateutil.parser` for flexible date handling
9. **Database paths** - Always support `--database` option to override defaults

## When to Use What

### CLI Framework
- **Click commands**: For all CLI commands
- **Rich**: For human-readable terminal output
- **Textual**: For interactive TUIs (e.g., browse command)

### Database Access
- **sqlite-utils**: For general database operations
- **Raw SQL**: For complex queries with aggregations
- **FTS5**: For full-text search (when available)

### Output Formats
- **Rich Table**: Default for human-readable output
- **JSON**: For machine-readable output (use `--format json`)
- **CSV**: For spreadsheet export (use `--format csv`)

## Contributing Workflow

When suggesting code or making changes:

### 1. Setup and Dependencies
- Install dependencies: `uv sync`
- Add new dependencies: `uv add package-name` (not `pip install`)
- Update lock file: `uv lock`

### 2. Development Cycle
- Run the CLI: `uv run scrobbledb <command>`
- Run tests: `poe test` or `poe test:quick`
- Check types: `poe type`
- Lint code: `poe lint` or `poe lint:fix`

### 3. Before Committing
```bash
# Run all quality checks
poe qa

# Or run individually:
poe lint          # Check code style
poe type          # Check types
poe audit         # Check security vulnerabilities
poe test          # Run all tests
```

### 4. Code Standards
- Follow existing patterns in the codebase
- Always use `uv run` or `poe` - never bare Python commands
- Include comprehensive help text and examples in CLI commands
- Add tests for new functionality (run with `poe test`)
- Update relevant design documents in `plans/`
- Use Rich for all terminal output
- Handle errors with user-friendly messages

### 5. Common Task Commands

| Task | Command | Notes |
|------|---------|-------|
| Run app | `uv run scrobbledb <cmd>` | Main CLI entry point |
| Run tests | `poe test` | Preferred over direct pytest |
| Quick test | `poe test:quick` | Stop on first failure |
| Test coverage | `poe test:cov` | Generates HTML report |
| Lint check | `poe lint` | Check without fixing |
| Lint fix | `poe lint:fix` | Auto-fix issues |
| Type check | `poe type` | Run ty type checker |
| Security scan | `poe audit` | Check for vulnerabilities |
| All QA checks | `poe qa` | Runs lint, type, audit, test |
| List tasks | `poe` | Shows all available tasks |

## Resources

- **Repository**: https://github.com/crossjam/scrobbledb
- **Original Project**: https://github.com/jacobian/lastfm-to-sqlite
- **Last.fm API**: https://www.last.fm/api
- **pylast**: https://github.com/pylast/pylast
- **Rich**: https://rich.readthedocs.io/
- **Textual**: https://textual.textualize.io/
- **Click**: https://click.palletsprojects.com/

---

*These instructions help GitHub Copilot understand the scrobbledb project structure, conventions, and development workflow.*
