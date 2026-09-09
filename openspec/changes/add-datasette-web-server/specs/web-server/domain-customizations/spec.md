## Purpose

Teaches the generic Datasette web server what a scrobbledb database means: the stored
queries that expose scrobbledb’s listening analytics as linkable URLs, the SQL functions
that make scrobbledb’s time and naming semantics expressible in SQL, and the metadata
that describes its tables.
Without this, the server shows four unlabelled tables and no analytics.

## ADDED Requirements

### Requirement: Stored queries expose scrobbledb’s analytics

The system SHALL make scrobbledb’s listening analytics available as named, linkable
stored queries on the served database, covering at minimum: a collection overview;
monthly, yearly and daily rollups; top artists, top albums and top tracks with play
counts and share-of-total percentages; per-artist, per-album and per-track detail with
first and last play; a denormalized play feed; and full-text search over artist, album
and track names.

#### Scenario: Stored queries are discoverable

- **WHEN** a client views the served database’s index page
- **THEN** the stored queries are listed by name, each with a human-readable description
  of what it returns

#### Scenario: Overview query

- **WHEN** a client runs the overview stored query against a populated database
- **THEN** the result contains the total play count, the distinct artist, album and
  track counts, and the earliest and latest play timestamps

#### Scenario: Top artists query

- **WHEN** a client runs the top-artists stored query with a limit
- **THEN** the result is ordered by play count descending, is capped at that limit, and
  each row carries the artist name, its play count, and its percentage of the plays in
  range

#### Scenario: Denormalized play feed

- **WHEN** a client runs the plays stored query
- **THEN** each row carries the play timestamp alongside the track title, album title
  and artist name, so no manual joining is required

#### Scenario: Results agree with the CLI

- **WHEN** a stored query and the corresponding scrobbledb CLI command are run against
  the same database with equivalent parameters
- **THEN** they return the same rows in the same order

### Requirement: Stored queries accept time-range and limit parameters

Stored queries that operate over a time range SHALL accept optional start and end
parameters and a result limit, and SHALL apply an inclusive range on both bounds.

#### Scenario: Bounded range

- **WHEN** a client supplies both a start and an end value to a time-ranged stored query
- **THEN** only plays at or after the start and at or before the end are counted

#### Scenario: Omitted range

- **WHEN** a client omits the start and end parameters
- **THEN** the query covers the database’s entire play history

#### Scenario: Human-readable time input

- **WHEN** a client supplies a relative or natural-language value such as `last march`
  or `30 days ago` as a range bound
- **THEN** it is interpreted the same way the scrobbledb CLI interprets `--since` and
  `--until`, and the query returns the corresponding range

### Requirement: Analytics not available in the CLI are provided

The system SHALL additionally expose stored queries for listening analytics that
scrobbledb does not currently compute anywhere: a daily rollup, an hour-of-day
distribution, a day-of-week distribution, consecutive-day listening streaks, and
per-artist first-play discovery dates.

#### Scenario: Daily rollup

- **WHEN** a client runs the daily rollup stored query over a range
- **THEN** the result has one row per calendar day in that range with plays present,
  each carrying the date and that day’s play count

#### Scenario: Hour-of-day distribution

- **WHEN** a client runs the listening-clock stored query
- **THEN** the result has at most 24 rows, each an hour of day with the number of plays
  recorded in it

#### Scenario: Listening streaks

- **WHEN** a client runs the streaks stored query
- **THEN** the result lists runs of consecutive calendar days with at least one play,
  each with its start date, end date and length, ordered longest first

#### Scenario: Artist discovery dates

- **WHEN** a client runs the discovery stored query
- **THEN** each row carries an artist and the timestamp of that artist’s earliest play

### Requirement: Custom SQL functions expose scrobbledb semantics

The system SHALL register SQL functions on the served database’s connections so that
scrobbledb’s time parsing, fuzzy name matching, and display formatting are usable from
stored queries and from ad hoc SQL.

#### Scenario: Time parsing function

- **WHEN** a query calls the time-parsing function with a relative or natural-language
  string
- **THEN** it returns a UTC ISO-8601 timestamp string directly comparable against
  `plays.timestamp`

#### Scenario: Time parsing function with unparseable input

- **WHEN** the time-parsing function is called with a string it cannot interpret
- **THEN** it returns NULL rather than raising, so the surrounding query still executes

#### Scenario: Fuzzy match function

- **WHEN** a query calls the fuzzy-match function with two strings
- **THEN** it returns a similarity score usable in `ORDER BY` and `WHERE`, matching the
  scoring the scrobbledb CLI uses for artist search

#### Scenario: Formatting functions

- **WHEN** a query calls the month-name or timestamp-formatting function
- **THEN** it returns the same display string the scrobbledb CLI would render for that
  value

#### Scenario: Functions are available to ad hoc SQL

- **WHEN** a client writes its own SQL in the server’s query interface using any of
  these functions
- **THEN** the functions resolve and the query executes

### Requirement: Full-text search is reachable

The system SHALL expose full-text search over artist, album and track names as a stored
query, because scrobbledb’s search index is not in a form the web server discovers
automatically.

#### Scenario: Search returns matches

- **WHEN** a client runs the search stored query with a term matching an indexed artist,
  album or track name
- **THEN** the matching rows are returned with artist, album and track identifiers and
  titles

#### Scenario: Search with no matches

- **WHEN** the search term matches nothing
- **THEN** an empty result set is returned without error

#### Scenario: Search index absent

- **WHEN** the database has no search index built
- **THEN** the search stored query fails with a message pointing the user at
  `scrobbledb index`, rather than an opaque SQL error

#### Scenario: Search index present but incomplete

- **WHEN** the search index covers fewer tracks than the `tracks` table contains
- **THEN** the system reports the shortfall rather than silently returning fewer
  results, and names the command that rebuilds the index

### Requirement: The served database is described to the reader

The system SHALL supply human-readable descriptions and sensible browsing defaults for
the scrobbledb database, and SHALL hide internal storage tables from the table listing.

#### Scenario: Table and column descriptions

- **WHEN** a client views any of the `artists`, `albums`, `tracks` or `plays` tables
- **THEN** a description of the table is shown, and columns whose meaning is not obvious
  from their name are described

#### Scenario: Internal search tables are hidden

- **WHEN** a client views the database index page
- **THEN** the internal storage tables backing the search index are not listed among the
  browsable tables

#### Scenario: Sensible default ordering

- **WHEN** a client browses the `plays` table without specifying a sort
- **THEN** rows are ordered most recent first

### Requirement: Album aggregates identify exactly one album

Because roughly half of all album identifiers are synthesized from the album title, the
same album can exist under several identifiers.
Aggregating by album SHALL collapse those duplicates without merging albums that merely
share a title, and every field reported for an aggregated album SHALL describe the same
album.

#### Scenario: Duplicate identifiers for one album collapse

- **WHEN** a stored query aggregates by album and an album exists under more than one
  synthesized identifier for the same artist
- **THEN** it appears as a single row whose counts cover all of its identifiers

#### Scenario: Albums sharing a title across artists stay separate

- **WHEN** two different artists each have an album with the same title
- **THEN** they appear as two rows, each attributed to its own artist

#### Scenario: Every album aggregate obeys this

- **WHEN** any stored query aggregates albums — the album listing, top albums, or any
  other
- **THEN** it collapses the same album’s duplicate identifiers and separates albums that
  merely share a title, rather than one query doing so and another not

#### Scenario: An aggregated album resolves to all of its tracks

- **WHEN** a caller takes an aggregated album row and asks for the tracks behind it
- **THEN** it receives the tracks of every identifier the row’s counts covered, so the
  track list never disagrees with the track count reported beside it

#### Scenario: Reported fields describe one album

- **WHEN** a stored query reports an album identifier alongside an artist name, track
  count, play count or last-played timestamp
- **THEN** every one of those fields belongs to the album identified, never to a
  different album that happened to share its title
