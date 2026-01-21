# scrobbledb

[![QA](https://github.com/crossjam/scrobbledb/actions/workflows/qa.yml/badge.svg)](https://github.com/crossjam/scrobbledb/actions/workflows/qa.yml)

**Save your listening history from Last.fm or Libre.fm to a local SQLite database.**

scrobbledb is a Python command-line tool that downloads your scrobble data (listening history) from Last.fm or Libre.fm and stores it in a SQLite database for local analysis, backup, and exploration. Built with modern Python tooling, it offers rich terminal output, full-text search, interactive browsing, and comprehensive data export capabilities.

## About Last.fm and Scrobbling

[Last.fm](https://www.last.fm/) is a music discovery and tracking service that records what you listen to across different platforms and devices. This process of recording your listening history is called "scrobbling."

**Scrobbling** automatically logs each track you play—including the artist, album, track name, and timestamp—creating a detailed history of your music consumption over time. Last.fm aggregates this data to generate statistics, recommendations, and insights about your listening habits.

The **Last.fm API** provides programmatic access to this scrobble data, allowing applications like scrobbledb to retrieve and analyze your complete listening history. [Libre.fm](https://libre.fm/) is an open-source alternative that offers compatible scrobbling services.

## Why scrobbledb?

- **Local backup**: Keep your listening history in a local database you control
- **Advanced queries**: Use SQL to analyze your music habits in ways the web interface doesn't support
- **Data portability**: Export your data in multiple formats (JSON, CSV, TSV)
- **Full-text search**: Find tracks, albums, and artists instantly with SQLite FTS5
- **Interactive browsing**: Explore your library with a terminal UI
- **Privacy**: Your data stays on your machine

## Origin

scrobbledb is a modernization of [Jacob Kaplan-Moss's](https://github.com/jacobian/) [lastfm-to-sqlite](https://github.com/jacobian/lastfm-to-sqlite) project. This version has been significantly expanded with:

- Modern Python tooling (uv, ruff, type hints)
- Domain-specific commands for exploring artists, albums, tracks, and plays
- Interactive terminal UI for browsing
- Full-text search capabilities
- Comprehensive data export options
- Enhanced statistics and filtering
- Rich terminal output with tables and progress bars

Original concept and implementation by Jacob Kaplan-Moss. Current development by Brian M. Dennis.

## Installation

scrobbledb requires Python 3.11 or later and uses [uv](https://github.com/astral-sh/uv) for dependency management.

```bash
# Clone the repository
git clone https://github.com/crossjam/scrobbledb.git
cd scrobbledb

# Install dependencies
uv sync

# Run scrobbledb
uv run scrobbledb --help
```

## Quick Start

### 1. Save your Last.fm credentials

```bash
uv run scrobbledb auth
```

This prompts for your Last.fm username, API key, shared secret, and password, then saves them in `~/.local/share/dev.pirateninja.scrobbledb/auth.json`.

**Getting API credentials**: Visit [Last.fm API](https://www.last.fm/api/account/create) to create an API account and obtain your API key and shared secret.

### 2. Initialize the database

```bash
uv run scrobbledb config init
```

This creates the SQLite database and sets up the full-text search index.

### 3. Import your listening history

```bash
uv run scrobbledb ingest
```

This fetches your complete scrobble history from Last.fm and stores it locally. Depending on how many scrobbles you have, this may take several minutes.

### 4. Explore your data

```bash
# Search for tracks
uv run scrobbledb search "pink floyd"

# View recent plays
uv run scrobbledb plays list --limit 50

# Browse interactively
uv run scrobbledb browse

# See your top artists
uv run scrobbledb artists top --limit 20

# View statistics
uv run scrobbledb stats overview
```

## Command Overview

scrobbledb provides a comprehensive set of commands for managing and exploring your music data:

### Data Management

- **`auth`** - Configure Last.fm/Libre.fm API credentials ([docs](docs/commands/auth.md))
- **`config`** - Initialize database, reset data, or show configuration paths ([docs](docs/commands/config.md))
- **`ingest`** - Fetch listening history from Last.fm/Libre.fm ([docs](docs/commands/ingest.md))
- **`import`** - Import scrobbles from JSONL, CSV, or TSV files ([docs](docs/commands/import.md))
- **`index`** - Create or rebuild the full-text search index ([docs](docs/commands/index.md))
- **`export`** - Export data in various formats with presets or custom SQL ([docs](docs/commands/export.md))

### Data Exploration

- **`search`** - Full-text search across artists, albums, and tracks ([docs](docs/commands/search.md))
- **`browse`** - Interactive terminal UI for browsing tracks ([docs](docs/commands/browse.md))
- **`plays`** - View and filter listening history chronologically ([docs](docs/commands/plays.md))
- **`artists`** - Browse artists, view top artists, see detailed statistics ([docs](docs/commands/artists.md))
- **`albums`** - Search albums and view album details with tracks ([docs](docs/commands/albums.md))
- **`tracks`** - Search tracks, view top tracks, see play history ([docs](docs/commands/tracks.md))
- **`stats`** - Generate listening statistics (overview, monthly, yearly) ([docs](docs/commands/stats.md))

### Advanced

- **`sql`** - Direct access to sqlite-utils commands for power users ([docs](docs/commands/sql.md))
- **`version`** - Display the installed version ([docs](docs/commands/version.md))

See the [CLI overview](docs/cli.md) for a complete command reference and detailed documentation for each command.

## Database Schema

scrobbledb stores your data in a normalized SQLite database:

- **`artists`** - Artist information (id, name)
- **`albums`** - Album information (id, title, artist_id)
- **`tracks`** - Track information (id, title, album_id)
- **`plays`** - Play events (track_id, timestamp)
- **`tracks_fts`** - FTS5 full-text search index

This schema enables efficient queries, comprehensive searches, and detailed analysis of your listening history.

## Example Workflows

### Backup your data weekly

```bash
# Update with new scrobbles
uv run scrobbledb ingest --since-date "7 days ago"

# Export to JSON backup
uv run scrobbledb export plays --format json --output backup-$(date +%Y%m%d).json
```

### Find your most-played tracks from a specific year

```bash
uv run scrobbledb tracks top --since 2023-01-01 --until 2023-12-31 --limit 50
```

### Analyze your listening patterns

```bash
# Monthly breakdown
uv run scrobbledb stats monthly --year 2024

# Top artists in the last 30 days
uv run scrobbledb artists top --since "30 days ago"

# All plays for a specific artist
uv run scrobbledb plays list --artist "Radiohead" --limit 1000
```

### Export data for external analysis

```bash
# Export to CSV for Excel/pandas
uv run scrobbledb export plays --format csv --output plays.csv

# Custom SQL query
uv run scrobbledb export --sql "SELECT artist_name, COUNT(*) as plays FROM plays GROUP BY artist_name" --format csv
```

## Configuration

scrobbledb follows the XDG Base Directory specification. By default, data is stored in:

- **Linux/Unix**: `~/.local/share/dev.pirateninja.scrobbledb/`
- **macOS**: `~/Library/Application Support/dev.pirateninja.scrobbledb/`
- **Windows**: `%LOCALAPPDATA%\dev.pirateninja.scrobbledb\`

You can override the database and auth file locations using command-line options:

```bash
uv run scrobbledb --database /path/to/custom.db ingest --auth /path/to/auth.json
```

## Development

scrobbledb uses modern Python development tools:

- **uv** - Fast Python package manager
- **ruff** - Fast Python linter and formatter
- **pytest** - Testing framework
- **poe** - Task runner for common development tasks

```bash
# Run tests
poe test

# Lint code
poe lint

# Type check
poe type

# Run all quality checks
poe qa
```

See [AGENTS.md](AGENTS.md) for detailed development guidelines.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

scrobbledb is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for the full license text.

Original lastfm-to-sqlite project by Jacob Kaplan-Moss, also licensed under Apache License 2.0.

## Links

- **Repository**: https://github.com/crossjam/scrobbledb
- **Original Project**: https://github.com/jacobian/lastfm-to-sqlite
- **Last.fm API**: https://www.last.fm/api
- **Libre.fm**: https://libre.fm/
