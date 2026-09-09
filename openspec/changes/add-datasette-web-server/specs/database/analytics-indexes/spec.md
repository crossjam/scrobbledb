## Purpose

Adds the secondary indexes scrobbledb’s analytical queries need.
The database currently has no indexes other than the implicit primary-key ones, so every
top-N and rollup query scans and joins the full play history; this makes those queries
acceptable to run interactively from a web server.

## ADDED Requirements

### Requirement: Analytics indexes can be created on demand

The system SHALL provide an opt-in way to create the secondary indexes that scrobbledb’s
analytical queries depend on, covering at minimum the foreign-key columns joining plays
to tracks, tracks to albums, and albums to artists, plus an index supporting
month-grained grouping of plays.

#### Scenario: Indexes are created

- **WHEN** a user runs `scrobbledb index --analytics` against a populated database
- **THEN** the analytics indexes are created and the system reports each one it created

#### Scenario: Analytical queries get faster

- **WHEN** a top-artists or monthly-rollup query is run before and after the analytics
  indexes are created
- **THEN** both return identical results, and the query plan after creation uses the
  indexes rather than scanning the joined tables

#### Scenario: Existing index behavior is unchanged

- **WHEN** a user runs `scrobbledb index` without the analytics flag
- **THEN** the command behaves exactly as it did before this capability existed

### Requirement: Index creation is idempotent and safe

Creating the analytics indexes SHALL be repeatable without error and SHALL NOT alter any
row data.

#### Scenario: Repeated invocation

- **WHEN** `scrobbledb index --analytics` is run against a database that already has the
  analytics indexes
- **THEN** the command succeeds, reports that the indexes already exist, and creates
  nothing

#### Scenario: Row data is untouched

- **WHEN** the analytics indexes are created
- **THEN** the contents of the `artists`, `albums`, `tracks` and `plays` tables are
  unchanged

#### Scenario: Empty or unpopulated database

- **WHEN** `scrobbledb index --analytics` is run against a database whose scrobble
  tables do not yet exist
- **THEN** the command reports that there is nothing to index and exits without error

### Requirement: Missing analytics indexes are surfaced, not silently created

Commands that depend on these indexes for acceptable performance SHALL detect their
absence and tell the user how to create them, and SHALL NOT create them as a side
effect.

#### Scenario: Warning at server startup

- **WHEN** `scrobbledb serve` starts against a populated database that lacks the
  analytics indexes
- **THEN** it prints a warning that analytical queries may be slow, names
  `scrobbledb index --analytics` as the remedy, and starts the server anyway

#### Scenario: No warning when indexes are present

- **WHEN** `scrobbledb serve` starts against a database that already has the analytics
  indexes
- **THEN** no index warning is printed

#### Scenario: Serving does not create indexes

- **WHEN** a server session runs against a database lacking the analytics indexes
- **THEN** the indexes are still absent after the session ends
