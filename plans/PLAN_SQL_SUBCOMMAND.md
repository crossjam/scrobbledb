# Plan: Integrate sqlite-utils Read-Only CLI Commands into scrobbledb

## Background

- **Issue**: GitHub Issue #3 requests easy database access via sqlite-utils CLI integration
- **Approach**: Create a `sql` subcommand that provides passthrough access to sqlite-utils commands
- **Default behavior**: All commands should default to the scrobbledb database in the XDG data directory
- **Phase 1 scope**: Read-only commands only (safe database exploration)

## Read-Only Commands to Integrate (12 commands)

Based on sqlite-utils 3.38, the following commands are read-only:

1. **`query`** (default) - Execute SQL queries and return results as JSON/CSV/TSV/table
2. **`tables`** - List all tables with optional counts, columns, and schema
3. **`views`** - List all views in the database
4. **`schema`** - Show full schema for database or specific tables
5. **`rows`** - Output all rows from a specified table
6. **`indexes`** - Show indexes for the database or specific tables
7. **`triggers`** - Show triggers configured in the database
8. **`search`** - Execute full-text search against a table
9. **`dump`** - Output SQL dump of schema and contents
10. **`analyze-tables`** - Analyze columns in tables (metadata analysis)
11. **`memory`** - Execute SQL against in-memory database with imported data
12. **`plugins`** - List installed sqlite-utils plugins

## Implementation Approach

### Option A: Click Group Wrapper (Recommended)

Create a new `sql` command group that wraps sqlite-utils commands with:
- Automatic database path injection (defaults to scrobbledb database)
- Preserved original command options and arguments
- Ability to override database path if needed

**Advantages:**
- Clean integration with existing CLI structure
- Maintains scrobbledb's XDG directory convention
- Users can optionally specify different database paths
- Each command remains independently testable

### Option B: Direct Command Import

Import sqlite-utils click commands directly and register them as subcommands.

**Advantages:**
- Less code duplication
- Direct access to upstream functionality

**Disadvantages:**
- Harder to customize default database behavior
- May require monkey-patching

## Detailed Implementation Plan

### 1. Create new `sql.py` module (`src/scrobbledb/sql.py`)

- Import necessary sqlite-utils CLI components
- Create a new Click group for `sql` subcommand
- Implement database path defaulting logic

### 2. Implement command wrappers for each read-only command

Each wrapper will:
- Accept optional `--database` parameter (defaults to `get_default_db_path()`)
- Pass through all other options to sqlite-utils command
- Maintain original help text and option names
- Handle database path injection transparently

### 3. Register `sql` group in main CLI (`src/scrobbledb/cli.py`)

- Import the sql command group
- Register it with `cli.add_command(sql, "sql")`

### 4. Example usage patterns

```bash
# Use default scrobbledb database
scrobbledb sql query "SELECT * FROM tracks LIMIT 10"
scrobbledb sql tables --counts
scrobbledb sql schema tracks
scrobbledb sql rows plays --limit 20

# Override database path when needed
scrobbledb sql query "SELECT * FROM users" --database /path/to/other.db
```

## Technical Implementation Details

### Command Wrapping Pattern

```python
@sql.command()
@click.argument("sql_query", required=True)
@click.option("--database", type=click.Path(), default=None,
              help="Database path (default: XDG data dir)")
@click.option(/* other sqlite-utils options */)
def query(database, sql_query, **kwargs):
    """Execute SQL query (wraps sqlite-utils query)"""
    if database is None:
        database = get_default_db_path()
    # Call sqlite-utils command with injected database path
    # and forwarded options
```

### Alternative: Context-based Approach

```python
@click.group()
@click.option("--database", type=click.Path(), default=None,
              help="Database path (default: XDG data dir)")
@click.pass_context
def sql(ctx, database):
    """SQLite database query and inspection commands"""
    ctx.ensure_object(dict)
    ctx.obj['database'] = database or get_default_db_path()
```

## Phase 1 Deliverables

### 1. Core implementation

- `src/scrobbledb/sql.py` with read-only command wrappers
- Integration with main CLI
- Default database path handling

### 2. Priority commands (MVP)

- `query` - Most essential for database exploration
- `tables` - List tables with counts
- `schema` - View table structure
- `rows` - Browse table data

### 3. Secondary commands

- `views`, `indexes`, `triggers` - Schema inspection
- `search` - Full-text search functionality
- `dump` - Database export
- `analyze-tables` - Column analysis

### 4. Documentation

- Update README with `sql` subcommand examples
- Add help text explaining default database behavior
- Document how to override database path

### 5. Testing

- Unit tests for command wrappers
- Integration tests with test database
- Verify default path behavior
- Test database path override

## Future Phases (Out of Scope for Phase 1)

### Phase 2: Write commands (requires more careful consideration)

- Commands that modify schema: `create-table`, `add-column`, `create-index`, etc.
- Data modification: `insert`, `upsert`, `bulk`
- Potentially destructive: `drop-table`, `transform`, `vacuum`

### Phase 3: Advanced features

- Custom sqlite-utils plugins for scrobbledb-specific operations
- Integration with scrobbledb's FTS5 search
- Bulk export/import workflows

## Security & Safety Considerations

1. **Read-only focus**: Phase 1 limits risk by only exposing read operations
2. **SQL injection**: Users can write arbitrary SQL via `query` command, but:
   - This is expected behavior for power users
   - Database file permissions provide protection
   - Read-only commands can't cause data loss
3. **File access**: Database path validation ensures users can only access intended files

## Success Criteria

- ✅ Users can execute SQL queries against scrobbledb database without specifying path
- ✅ All 12 read-only sqlite-utils commands are accessible via `scrobbledb sql`
- ✅ Original sqlite-utils functionality preserved (all options work)
- ✅ Database path can be overridden when needed
- ✅ Help text clearly documents default behavior
- ✅ Tests verify correct database path handling

## Open Questions

### 1. Command naming

Should we use `sql` or `db` for the subcommand group?

**Recommendation**: `sql` (aligns with issue description and sqlite-utils nature)

### 2. Backward compatibility

Should we also support `scrobbledb query` directly?

**Recommendation**: No, keep commands organized under `sql` group

### 3. Output format defaults

Should we override any sqlite-utils defaults?

**Recommendation**: Preserve sqlite-utils defaults (JSON by default)

---

This plan provides a safe, incremental approach to integrating sqlite-utils functionality while maintaining scrobbledb's ease-of-use through automatic database path handling.
