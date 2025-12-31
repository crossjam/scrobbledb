# Plan: Domain-Specific CLI Commands for Scrobbledb

_Generated: 2025-12-31_

## Background

Currently, scrobbledb provides powerful database access through the `sql` subcommand, which allows users to execute raw SQL queries against their listening history. However, this approach requires SQL knowledge and understanding of the database schema. To improve usability for common music investigation tasks, we need domain-specific CLI commands that abstract away SQL complexity.

This plan outlines new CLI commands for investigating **Plays**, **Tracks**, **Albums**, and **Artists** without requiring raw SQL knowledge.

## Goals

- Enable non-technical users to investigate their listening history without SQL
- Provide intuitive, domain-specific commands for common music analysis tasks
- Support filtering, time ranges, and sorting for flexible data exploration
- Maintain consistency with existing scrobbledb CLI patterns and libraries
- Leverage `click` for command-line interface and `rich` for formatted output

## Database Schema Reference

The scrobbledb database has four core tables:

- **`artists`** - Artist information (id, name)
- **`albums`** - Album information (id, title, artist_id)
- **`tracks`** - Track information (id, title, album_id)
- **`plays`** - Play events (track_id, timestamp)

## Implementation Approach

### Technology Stack

- **CLI Framework**: `click` - Already used throughout scrobbledb
- **Output Formatting**: `rich` - Already used for tables, progress bars, and styled output
- **Database Access**: `sqlite_utils` - Existing dependency for database operations

### Implementation Guidelines

When implementing these domain-specific commands, follow these principles:

1. **Database Location**: Use existing helper functions to locate the scrobbledb SQLite database
   - Use `get_default_db_path()` from `cli.py` to get the default database location
   - Use `get_data_dir()` for XDG-compliant data directory access
   - Always support `--database` / `-d` option to override the default path

2. **Database Access**: Prefer the `sqlite-utils` Python API over raw SQL queries
   - Use `sqlite_utils.Database` class for database operations
   - Use `.execute()` for parameterized queries when SQL is needed
   - Leverage `sqlite-utils` table methods (`.rows`, `.search()`, etc.) where applicable
   - See `lastfm.py` and `sql.py` for examples of sqlite-utils usage

3. **Database Extensions**: Extend the database connection with domain-specific functionality
   - Register custom SQL functions for common operations (e.g., timestamp parsing/formatting)
   - Use SQLite's `create_function()` to add helpers like date range filters
   - Example: Register a `parse_relative_time()` function for "7 days ago" expressions
   - See `stamina` retry logic in `lastfm.py` for patterns to follow

4. **Output Format**:
   - **Default**: Console output using Rich tables, panels, and formatted text
   - **Additional formats**: Support `--format` option with:
     - `table` (default): Rich table output for human-readable display
     - `csv`: Comma-separated values for spreadsheet import
     - `json`: JSON object (single object or array of objects)
     - `jsonl`: JSON Lines format (one JSON object per line, newline-delimited)
   - Use Rich's `Console` class and check `console.is_terminal` for appropriate formatting
   - See `export.py` for examples of multiple output format support

5. **Rich Output**: Default to using Rich for all console presentation
   - Use `rich.table.Table` for tabular data
   - Use `rich.panel.Panel` for summary information and headers
   - Use `rich.console.Console` for all output operations
   - Use `rich.progress.Progress` for long-running operations
   - Follow existing patterns in `cli.py`, `search()`, and `browse` commands

### Command Structure

All domain-specific commands will be organized under their respective top-level command groups:

```
scrobbledb plays ...     # Play history commands
scrobbledb albums ...    # Album investigation commands
scrobbledb artists ...   # Artist investigation commands
scrobbledb tracks ...    # Track investigation commands
```

Each command group will support common options:
- `--database` / `-d` - Override default database path (consistent with existing commands)
- Output formatting options where applicable (table, CSV, JSON)

## Detailed Command Specifications

### 1. Plays Commands (`scrobbledb plays`)

#### `scrobbledb plays list`

List recent plays with filtering and pagination.

**Purpose**: View listening history chronologically with flexible filtering.

**Options**:
- `--limit` / `-l` - Maximum number of plays to return (default: 20)
- `--since` / `-s` - Show plays since date/time (ISO 8601 format or relative like "7 days ago")
- `--until` / `-u` - Show plays until date/time (ISO 8601 format)
- `--artist` - Filter by artist name (case-insensitive partial match)
- `--album` - Filter by album title (case-insensitive partial match)
- `--track` - Filter by track title (case-insensitive partial match)
- `--format` - Output format: `table` (default), `csv`, `json`, `jsonl`
- `--database` / `-d` - Database path (defaults to XDG data directory)

**Output Columns**:
- Timestamp (formatted: YYYY-MM-DD HH:MM:SS)
- Artist
- Track
- Album

**Examples**:
```bash
# List last 20 plays
scrobbledb plays list

# List last 50 plays
scrobbledb plays list --limit 50

# List plays in the last week
scrobbledb plays list --since "7 days ago"

# List plays for a specific artist
scrobbledb plays list --artist "Pink Floyd" --limit 100

# List plays in a specific date range
scrobbledb plays list --since 2024-01-01 --until 2024-12-31

# Export to CSV
scrobbledb plays list --format csv > my_plays.csv
```

**Implementation Notes**:
- Use `dateutil.parser` for flexible date parsing (already a dependency)
- Support relative time expressions like "7 days ago", "1 month ago", "yesterday"
- Join plays → tracks → albums → artists for complete information
- Order by timestamp DESC (most recent first)
- Use rich Table for default output with proper column alignment

---

### 2. Albums Commands (`scrobbledb albums`)

#### `scrobbledb albums search`

Search for albums using fuzzy matching.

**Purpose**: Find albums by partial name, useful when you don't remember exact titles.

**Arguments**:
- `QUERY` - Search query for album title (case-insensitive partial match)

**Options**:
- `--limit` / `-l` - Maximum results (default: 20)
- `--artist` - Filter by artist name
- `--format` - Output format: `table` (default), `csv`, `json`, `jsonl`
- `--database` / `-d` - Database path

**Output Columns**:
- Album Title
- Artist
- Track Count (number of tracks in album)
- Play Count (total plays across all tracks)
- Last Played (most recent play of any track from album)

**Examples**:
```bash
# Search for albums with "dark" in the title
scrobbledb albums search "dark"

# Search for albums by specific artist
scrobbledb albums search "dark" --artist "Pink Floyd"

# Get top 10 results
scrobbledb albums search "greatest" --limit 10
```

**Implementation Notes**:
- Use SQL LIKE with wildcards for fuzzy matching: `WHERE title LIKE '%query%'`
- Aggregate play counts and track counts using GROUP BY
- Order by relevance (exact matches first) then by play count
- Consider using FTS5 index if available for better search performance

#### `scrobbledb albums show`

Display detailed information about a specific album and list its tracks.

**Purpose**: View all tracks in an album with play statistics.

**Arguments**:
- `ALBUM_TITLE` - Album title (must be an exact match, or use `--album-id`)

**Options**:
- `--album-id` - Use album ID instead of title
- `--artist` - Artist name (to disambiguate albums with same title)
- `--format` - Output format: `table` (default), `csv`, `json`, `jsonl`
- `--database` / `-d` - Database path

**Output**:

First, display album summary:
- Album Title
- Artist
- Total Tracks
- Total Plays
- First Played
- Last Played

Then, display track listing:
- Track Number (if available)
- Track Title
- Play Count
- Last Played

**Examples**:
```bash
# Show tracks in an album
scrobbledb albums show "The Dark Side of the Moon"

# Disambiguate by artist
scrobbledb albums show "Rubber Soul" --artist "The Beatles"

# Use album ID
scrobbledb albums show --album-id 42
```

**Implementation Notes**:
- First query album table to find matching album
- If multiple albums match, show error and list candidates with artists
- Query tracks joined with plays for statistics
- Use rich Panel for album summary, Table for track listing
- Handle case where album has no plays (show tracks but no play stats)

---

### 3. Artists Commands (`scrobbledb artists`)

#### `scrobbledb artists list`

List all artists in the database with play statistics.

**Purpose**: Browse all artists you've listened to with sorting options.

**Options**:
- `--limit` / `-l` - Maximum results (default: 50)
- `--sort` - Sort by: `plays` (default), `name`, `recent`
- `--order` - Sort order: `desc` (default), `asc`
- `--min-plays` - Show only artists with at least N plays
- `--format` - Output format: `table` (default), `csv`, `json`, `jsonl`
- `--database` / `-d` - Database path

**Output Columns**:
- Artist Name
- Total Plays
- Track Count (unique tracks)
- Album Count (unique albums)
- Last Played

**Examples**:
```bash
# List top 50 artists by play count
scrobbledb artists list

# List all artists alphabetically
scrobbledb artists list --sort name --order asc --limit 1000

# List artists with at least 100 plays
scrobbledb artists list --min-plays 100

# Show recently played artists
scrobbledb artists list --sort recent
```

**Implementation Notes**:
- Aggregate plays by artist_id
- Count distinct tracks and albums per artist
- Use MAX(plays.timestamp) for last_played
- Support three sort modes:
  - `plays`: ORDER BY play_count DESC
  - `name`: ORDER BY artist_name ASC/DESC
  - `recent`: ORDER BY last_played DESC
- Use rich Table with proper numeric alignment for counts

#### `scrobbledb artists top`

Show top artists with flexible time range support.

**Purpose**: Analyze your listening patterns over different time periods.

**Options**:
- `--limit` / `-l` - Number of artists to show (default: 10)
- `--since` / `-s` - Start date/time for analysis period
- `--until` / `-u` - End date/time for analysis period
- `--period` - Predefined period: `week`, `month`, `quarter`, `year`, `all-time` (default: all-time)
- `--format` - Output format: `table` (default), `csv`, `json`, `jsonl`
- `--database` / `-d` - Database path

**Output Columns**:
- Rank
- Artist Name
- Play Count
- Percentage (of total plays in period)
- Avg Plays/Day

**Examples**:
```bash
# Top 10 artists all-time
scrobbledb artists top

# Top 20 artists this year
scrobbledb artists top --limit 20 --period year

# Top artists in last 30 days
scrobbledb artists top --since "30 days ago"

# Top artists in specific date range
scrobbledb artists top --since 2024-01-01 --until 2024-03-31
```

**Implementation Notes**:
- Parse period into since/until dates:
  - `week`: last 7 days
  - `month`: last 30 days
  - `quarter`: last 90 days
  - `year`: last 365 days
  - `all-time`: no date filter
- Calculate percentage: `(artist_plays / total_plays_in_period) * 100`
- Calculate avg plays/day: `artist_plays / days_in_period`
- Use rich Table with progress bar for percentage visualization
- Add summary footer showing total plays and date range analyzed

#### `scrobbledb artists show`

Display detailed information about a specific artist.

**Purpose**: Deep dive into a single artist's listening history.

**Arguments**:
- `ARTIST_NAME` - Artist name (case-insensitive partial match)

**Options**:
- `--artist-id` - Use artist ID instead of name
- `--format` - Output format: `table` (default), `json`, `jsonl`
- `--database` / `-d` - Database path

**Output**:

First, display artist summary:
- Artist Name
- Total Plays
- Unique Tracks
- Unique Albums
- First Played
- Last Played
- Listening Streak (if applicable)

Then, display top tracks table:
- Track Title
- Album
- Play Count
- Last Played

Then, display albums list:
- Album Title
- Track Count
- Play Count
- Last Played

**Examples**:
```bash
# Show artist details
scrobbledb artists show "Radiohead"

# Use artist ID
scrobbledb artists show --artist-id 123
```

**Implementation Notes**:
- Find artist by name (case-insensitive LIKE)
- If multiple matches, list candidates and ask for clarification
- Query all related tracks, albums, and plays
- Sort top tracks by play count (limit to 10)
- Sort albums by play count
- Use rich Panels for different sections
- Calculate listening streak (optional): longest consecutive days with plays

---

### 4. Tracks Commands (`scrobbledb tracks`)

#### `scrobbledb tracks search`

Search for tracks using fuzzy matching.

**Purpose**: Find tracks by partial title, useful for quick lookups.

**Arguments**:
- `QUERY` - Search query for track title (case-insensitive partial match)

**Options**:
- `--limit` / `-l` - Maximum results (default: 20)
- `--artist` - Filter by artist name
- `--album` - Filter by album title
- `--format` - Output format: `table` (default), `csv`, `json`, `jsonl`
- `--database` / `-d` - Database path

**Output Columns**:
- Track Title
- Artist
- Album
- Play Count
- Last Played

**Examples**:
```bash
# Search for tracks with "love" in title
scrobbledb tracks search "love"

# Search within specific artist
scrobbledb tracks search "love" --artist "The Beatles"

# Search within specific album
scrobbledb tracks search "love" --album "Sgt. Pepper"
```

**Implementation Notes**:
- Use SQL LIKE with wildcards: `WHERE tracks.title LIKE '%query%'`
- Join tracks → albums → artists for complete information
- Aggregate play counts per track
- Order by relevance (exact matches first) then by play count
- Consider using FTS5 index (tracks_fts) for better search performance

#### `scrobbledb tracks top`

Show top tracks with flexible time range support.

**Purpose**: Discover your most played tracks over various time periods.

**Options**:
- `--limit` / `-l` - Number of tracks to show (default: 10)
- `--since` / `-s` - Start date/time for analysis period
- `--until` / `-u` - End date/time for analysis period
- `--period` - Predefined period: `week`, `month`, `quarter`, `year`, `all-time` (default: all-time)
- `--artist` - Filter by artist name
- `--format` - Output format: `table` (default), `csv`, `json`, `jsonl`
- `--database` / `-d` - Database path

**Output Columns**:
- Rank
- Track Title
- Artist
- Album
- Play Count
- Percentage (of total plays in period)

**Examples**:
```bash
# Top 10 tracks all-time
scrobbledb tracks top

# Top 25 tracks this month
scrobbledb tracks top --limit 25 --period month

# Top tracks by specific artist in last year
scrobbledb tracks top --artist "Radiohead" --period year

# Top tracks in date range
scrobbledb tracks top --since 2024-01-01 --until 2024-12-31
```

**Implementation Notes**:
- Similar period parsing as `artists top`
- Join plays → tracks → albums → artists
- Calculate percentage of total plays
- Use rich Table with visual ranking
- Add summary showing total plays and date range

#### `scrobbledb tracks show`

Display detailed information about a specific track.

**Purpose**: View play history and statistics for a single track.

**Arguments**:
- `TRACK_TITLE` - Track title (case-insensitive partial match)

**Options**:
- `--track-id` - Use track ID instead of title
- `--artist` - Artist name (to disambiguate tracks with same title)
- `--album` - Album title (to disambiguate further)
- `--show-plays` - Show individual play timestamps (default: false)
- `--format` - Output format: `table` (default), `json`, `jsonl`
- `--database` / `-d` - Database path

**Output**:

First, display track summary:
- Track Title
- Artist
- Album
- Total Plays
- First Played
- Last Played
- Average Plays per Month (if >= 1 month of data)

Optionally (with `--show-plays`), display play history:
- Timestamp
- Days Since Previous Play

**Examples**:
```bash
# Show track details
scrobbledb tracks show "Bohemian Rhapsody"

# Disambiguate by artist
scrobbledb tracks show "Here Comes the Sun" --artist "The Beatles"

# Show with full play history
scrobbledb tracks show "Comfortably Numb" --show-plays

# Use track ID
scrobbledb tracks show --track-id 456
```

**Implementation Notes**:
- Find track by title (case-insensitive LIKE)
- Support disambiguation by artist and/or album if multiple matches
- If multiple matches remain, list candidates with artist/album
- Calculate time-based statistics (avg plays per month)
- When showing plays, calculate gaps between consecutive plays
- Use rich Panel for summary, Table for play history
- Limit play history display to reasonable number (e.g., 100 most recent)

---

## Shared Implementation Components

### Helper Functions

Create a new module `src/scrobbledb/domain_queries.py` with shared query functions:

```python
def get_plays_with_filters(
    db: Database,
    limit: int = 20,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    track: Optional[str] = None
) -> List[Dict]:
    """Query plays with various filters."""
    pass

def get_artists_with_stats(
    db: Database,
    limit: int = 50,
    sort_by: str = "plays",
    order: str = "desc",
    min_plays: int = 0,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None
) -> List[Dict]:
    """Query artists with aggregated statistics."""
    pass

def get_albums_by_search(
    db: Database,
    query: str,
    artist: Optional[str] = None,
    limit: int = 20
) -> List[Dict]:
    """Search albums by title with optional artist filter."""
    pass

def get_tracks_by_search(
    db: Database,
    query: str,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    limit: int = 20
) -> List[Dict]:
    """Search tracks by title with optional filters."""
    pass

def parse_relative_time(time_str: str) -> datetime:
    """Parse relative time expressions like '7 days ago'."""
    pass

def parse_period_to_dates(period: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Convert period string to since/until dates."""
    pass
```

### Output Formatting

Create shared rich formatting utilities:

```python
def format_timestamp(ts: datetime) -> str:
    """Format timestamp consistently across commands."""
    return ts.strftime("%Y-%m-%d %H:%M:%S")

def format_plays_table(plays: List[Dict], console: Console) -> None:
    """Format plays as rich table."""
    pass

def format_artist_summary(artist_data: Dict, console: Console) -> None:
    """Format artist summary in a rich Panel."""
    pass
```

### Database Path Handling

All commands will use the existing `get_default_db_path()` helper from `cli.py` and support `--database` override, maintaining consistency with existing commands.

### Output Format Support

Support four output formats consistently:
- **table** (default): Rich table output, human-readable
- **csv**: CSV format, suitable for Excel/spreadsheet import
- **json**: JSON object or array of objects, machine-readable
- **jsonl**: JSON Lines format (newline-delimited JSON), one object per line

## Command Module Structure

Organize commands in separate modules:

```
src/scrobbledb/
  ├── cli.py              # Main CLI entry point
  ├── domain_queries.py   # Shared query functions
  ├── domain_format.py    # Shared formatting utilities
  ├── commands/
  │   ├── __init__.py
  │   ├── plays.py        # Plays command group
  │   ├── albums.py       # Albums command group
  │   ├── artists.py      # Artists command group
  │   └── tracks.py       # Tracks command group
```

Register command groups in `cli.py`:

```python
from .commands import plays, albums, artists, tracks

cli.add_command(plays.plays)
cli.add_command(albums.albums)
cli.add_command(artists.artists)
cli.add_command(tracks.tracks)
```

## Testing Strategy

### Unit Tests

- Test query functions with mock database
- Test date parsing utilities
- Test filtering and sorting logic
- Test output formatting functions

### Integration Tests

- Test each command with test database
- Verify output formats (table, JSON, CSV)
- Test edge cases (empty results, invalid inputs)
- Test date range filtering

### Manual Testing

- Test with real scrobbledb database
- Verify rich table rendering in terminal
- Test various date/time input formats
- Verify performance with large datasets

## Documentation Updates

### CLI Help Text

Each command must have:
- Clear description of purpose
- Comprehensive examples
- Option descriptions with defaults
- Reference to related commands

### README Updates

Add new section: "Exploring Your Music"

```markdown
## Exploring Your Music

Scrobbledb provides intuitive commands for investigating your listening history:

### Recent Plays
# View your recent listening history
scrobbledb plays list --limit 50

### Top Artists
# See your top artists this month
scrobbledb artists top --period month

### Search Albums
# Find albums containing "dark"
scrobbledb albums search "dark"

### Track Statistics
# View stats for a specific track
scrobbledb tracks show "Bohemian Rhapsody"
```

## Performance Considerations

### Database Indexes

Ensure appropriate indexes exist:
- `plays(timestamp)` - For time-range queries
- `plays(track_id, timestamp)` - For track play history
- `tracks(album_id)` - For album lookups
- `albums(artist_id)` - For artist lookups

These indexes should be created during `scrobbledb config init` if they don't exist.

### Query Optimization

- Use COUNT(*) with LIMIT for large result sets
- Avoid SELECT * when only specific columns needed
- Use EXPLAIN QUERY PLAN to verify index usage
- Consider caching for expensive aggregations

### Progress Indicators

For potentially slow operations (large date ranges, complex aggregations):
- Show spinner during query execution
- Display row count as data streams
- Use rich Progress for multi-step operations

## Error Handling

### Common Error Scenarios

1. **Database not found**
   - Message: "Database not found. Run 'scrobbledb config init' to create one."
   - Exit code: 1

2. **Invalid date format**
   - Message: "Invalid date format: {input}. Use ISO 8601 (YYYY-MM-DD) or relative time (7 days ago)"
   - Show example of correct format
   - Exit code: 1

3. **No results found**
   - Don't error, show friendly message
   - Suggest alternative searches or broader criteria
   - Exit code: 0

4. **Ambiguous match**
   - Show all matching candidates
   - Suggest using --artist or --album to narrow
   - Provide --id option for exact selection
   - Exit code: 1

5. **Empty database**
   - Message: "Database has no plays. Run 'scrobbledb ingest' to import your listening history."
   - Exit code: 1

### Input Validation

- Validate date formats before query execution
- Check for reasonable limit values (1-10000)
- Validate period values against allowed list
- Sanitize search inputs (though SQL parameterization handles injection)

## Migration Path

### Phase 1: Core Commands (MVP)
- `plays list`
- `artists list` and `artists top`
- `tracks search` and `tracks top`

### Phase 2: Detail Commands
- `albums search` and `albums show`
- `artists show`
- `tracks show`

### Phase 3: Enhancements
- Advanced filtering options
- Export capabilities
- Statistics and visualizations
- Integration with `browse` TUI

## Future Enhancements (Out of Scope)

These features are not part of the initial implementation but could be added later:

### Visualization
- Listening history charts over time
- Genre distribution (if genre data available)
- Listening heatmaps (day/hour patterns)

### Recommendations
- Similar artists based on listening patterns
- Deep cuts (tracks you might have forgotten)
- Discovery suggestions (artists similar to your favorites)

### Playlists
- Generate playlists from top tracks
- Export to Spotify/Apple Music formats
- Create themed playlists by era/mood

### Social Features
- Compare with friends (if applicable)
- Listening milestones and achievements
- Sharing formatted statistics

### Advanced Analytics
- Listening velocity (plays per period over time)
- Artist/genre diversity metrics
- Prediction of future listening patterns

## Success Criteria

✅ **Usability**
- Non-technical users can explore their music without SQL knowledge
- Commands are intuitive and self-documenting
- Error messages are helpful and actionable

✅ **Functionality**
- All specified commands implemented and tested
- Time range filtering works correctly
- Sorting and filtering produce expected results
- Output formats (table/JSON/CSV) work consistently

✅ **Performance**
- Commands respond quickly (<2s for typical queries)
- Large result sets are handled efficiently
- Appropriate progress indicators for slow operations

✅ **Consistency**
- Commands follow scrobbledb conventions
- Help text is comprehensive and accurate
- Output formatting is polished and readable
- Integration with existing commands is seamless

✅ **Documentation**
- README includes usage examples
- CLI help is comprehensive
- Code is well-commented
- Tests provide usage examples

## Open Questions

### 1. Output Format Default

Should we default to rich tables or JSON for programmatic use?

**Recommendation**: Default to rich tables (human-readable). Users can opt into JSON/CSV with `--format` flag.

### 2. FTS5 Search vs SQL LIKE

Should search commands use FTS5 full-text search when available?

**Recommendation**: Use FTS5 when available (check `tracks_fts` table existence), fallback to SQL LIKE. FTS5 provides better relevance ranking.

### 3. Artist/Album/Track Disambiguation

How to handle multiple matches when user provides partial names?

**Recommendation**: 
- If 1 match: proceed automatically
- If 2-5 matches: list all and error with suggestion to use `--artist` or `--id`
- If 6+ matches: show count and error, suggest narrowing search

### 4. Relative Time Parsing

What relative time expressions should be supported?

**Recommendation**: Support common expressions:
- "N days/weeks/months/years ago"
- "yesterday", "today"
- "last week/month/year"
- Use existing dateutil.parser for absolute dates

### 5. Default Limits

What should default limits be for each command?

**Recommendation**:
- `plays list`: 20 (fit typical terminal height)
- `artists/tracks list`: 50 (reasonable overview)
- `artists/tracks top`: 10 (focused view)
- `search commands`: 20 (manageable results)
- All overridable with `--limit`

---

## Implementation Checklist

- [ ] Create `src/scrobbledb/domain_queries.py` with shared query functions
- [ ] Create `src/scrobbledb/domain_format.py` with formatting utilities
- [ ] Create `src/scrobbledb/commands/` directory
- [ ] Implement `plays.py` command group with `list` subcommand
- [ ] Implement `albums.py` command group with `search` and `show` subcommands
- [ ] Implement `artists.py` command group with `list`, `top`, and `show` subcommands
- [ ] Implement `tracks.py` command group with `search`, `top`, and `show` subcommands
- [ ] Register command groups in `cli.py`
- [ ] Write unit tests for query functions
- [ ] Write integration tests for each command
- [ ] Add database indexes if needed (during init)
- [ ] Update README with new commands section
- [ ] Update CLI help text with examples
- [ ] Manual testing with real database
- [ ] Performance testing with large datasets
- [ ] Documentation review and polish

---

This design provides a comprehensive, user-friendly interface for exploring scrobble data while maintaining consistency with scrobbledb's existing architecture and conventions.
