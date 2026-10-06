## Purpose

Adds secondary indexes on the foreign-key columns that join plays to tracks to albums to
artists.
The database currently has no indexes other than the implicit primary-key ones, so a
lookup that starts from the parent side — the plays of a track, the tracks of an album —
scans the child table.
Full-history rollups read every play whatever indexes exist, so they are not what these
indexes are for.

## ADDED Requirements

### Requirement: Analytics indexes can be created on demand

The system SHALL provide an opt-in way to create secondary indexes on the foreign-key
columns joining plays to tracks, tracks to albums, and albums to artists, so that
lookups starting from the parent side can use them.

#### Scenario: Indexes are created

- **WHEN** a user runs `scrobbledb index --analytics` against a populated database
- **THEN** the analytics indexes are created and the system reports each one it created

#### Scenario: Indexed queries return the same results

- **WHEN** a top-artists or monthly-rollup query is run before and after the analytics
  indexes are created
- **THEN** both return identical results, and the top-artists query plan after creation
  uses an analytics index

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

#### Scenario: An equivalent index already exists

- **WHEN** `scrobbledb index --analytics` is run against a database that already has a
  usable index on one of those columns under a different name
- **THEN** the command creates no second index for that column and reports it as already
  in place

#### Scenario: A name is taken by an index on something else

- **WHEN** an index already carries the name the command would use but is not on the
  needed column
- **THEN** the command reports the conflict, still creates the others, and exits with a
  non-zero status rather than reporting success

#### Scenario: Row data is untouched

- **WHEN** the analytics indexes are created
- **THEN** the contents of the `artists`, `albums`, `tracks` and `plays` tables are
  unchanged

#### Scenario: Empty or unpopulated database

- **WHEN** `scrobbledb index --analytics` is run against a database whose scrobble
  tables, or the columns the indexes sit on, do not yet exist
- **THEN** the command reports that there is nothing to index and exits without error

### Requirement: Missing analytics indexes are surfaced, not silently created

`scrobbledb serve` SHALL detect the absence of these indexes and tell the user how to
create them; no command SHALL create them as a side effect.

#### Scenario: Warning at server startup

- **WHEN** `scrobbledb serve` starts against a populated database that lacks the
  analytics indexes
- **THEN** it prints a warning that lookups by track, album or artist may be slow, names
  `scrobbledb index --analytics` as the remedy, and starts the server anyway

#### Scenario: No warning when indexes are present

- **WHEN** `scrobbledb serve` starts against a database that already has the analytics
  indexes
- **THEN** no index warning is printed

#### Scenario: Serving does not create indexes

- **WHEN** a server session runs against a database lacking the analytics indexes
- **THEN** the indexes are still absent after the session ends
