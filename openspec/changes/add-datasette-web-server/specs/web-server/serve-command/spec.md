## Purpose

Provides an HTTP surface over a scrobbledb database so listening history can be browsed,
linked to, filtered and queried ad hoc in a web browser, using Datasette as the embedded
web server. Covers the command that starts the server, how it resolves and protects the
database, and how it behaves when its optional dependencies are missing.

## ADDED Requirements

### Requirement: Serve command starts an embedded web server

The system SHALL provide a `scrobbledb serve` command that starts a Datasette web server
in the current process and serves the scrobbledb database over HTTP until interrupted.

#### Scenario: Server starts against the default database

- **WHEN** a user runs `scrobbledb serve` with no options and the default database
  exists
- **THEN** the system starts an HTTP server, prints the URL it is listening on, and
  remains in the foreground serving requests

#### Scenario: Server serves the scrobbledb tables

- **WHEN** the server is running and a client requests the database index page
- **THEN** the response lists the `artists`, `albums`, `tracks` and `plays` tables and
  each is individually browsable

#### Scenario: Graceful shutdown

- **WHEN** the running server receives an interrupt signal
- **THEN** the system stops accepting connections and exits with status 0 without a
  traceback

### Requirement: Database resolution matches the rest of the CLI

The system SHALL resolve the database to serve using the same precedence as every other
scrobbledb command: an explicitly supplied `--database` path, otherwise the default
database in the platform data directory.

#### Scenario: Explicit database path

- **WHEN** a user runs `scrobbledb serve --database /path/to/other.db`
- **THEN** the system serves that database rather than the default one

#### Scenario: Missing database

- **WHEN** the resolved database file does not exist
- **THEN** the system prints an error naming the resolved path, points the user at
  `scrobbledb config init`, and exits with a non-zero status without starting a server

#### Scenario: Database present but not populated

- **WHEN** the resolved database exists but has no `plays` table
- **THEN** the system prints a warning that the database has not been ingested into and
  points the user at `scrobbledb ingest`, and still starts the server

#### Scenario: Stale search index

- **WHEN** the server starts against a database whose search index covers fewer tracks
  than the `tracks` table contains
- **THEN** it prints a warning naming the shortfall and the command that rebuilds the
  index, and starts the server anyway

#### Scenario: Database changes while being served

- **WHEN** another process writes to the database while a server session is running
- **THEN** the server continues to serve without erroring and without returning results
  from a stale snapshot

### Requirement: The served database is read-only

The system SHALL open the database in a mode that cannot modify it, and SHALL NOT expose
any endpoint that writes to it.

#### Scenario: Write statement is rejected

- **WHEN** a client submits an `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ATTACH` or
  `DETACH` statement through any query interface the server exposes
- **THEN** the statement is rejected with an error and the database file is unchanged

#### Scenario: Read-only cannot be switched off

- **WHEN** a client attempts to disable the connection’s read-only enforcement and then
  submits a write
- **THEN** the write is still rejected, and no other database file becomes reachable
  through the connection

#### Scenario: Serving never mutates the database

- **WHEN** a server session starts, handles requests, and shuts down
- **THEN** the database file’s contents are byte-identical to what they were before the
  session, including when analytics indexes are absent

### Requirement: Network exposure defaults to localhost

The system SHALL bind to `127.0.0.1` by default and SHALL require an explicit opt-in to
listen on any other interface.

#### Scenario: Default bind

- **WHEN** a user runs `scrobbledb serve` with no host option
- **THEN** the server accepts connections from the local machine only

#### Scenario: Explicit host and port

- **WHEN** a user runs `scrobbledb serve --host 0.0.0.0 --port 9000`
- **THEN** the server listens on that interface and port, and the printed URL reflects
  them

#### Scenario: Port already in use

- **WHEN** the requested port is already bound by another process
- **THEN** the system prints an actionable error naming the port and exits with a
  non-zero status

### Requirement: Web server dependencies are optional

The system SHALL keep the web server’s dependencies out of the base install, and the
rest of the CLI SHALL remain fully functional without them.

#### Scenario: Extra not installed

- **WHEN** a user runs `scrobbledb serve` in an environment without the web server
  dependencies
- **THEN** the system prints an actionable message naming the extra to install and exits
  with a non-zero status, rather than raising an import error traceback

#### Scenario: Help works without the extra

- **WHEN** a user runs `scrobbledb serve --help` or `scrobbledb --help` in an
  environment without the web server dependencies
- **THEN** the help text renders normally and the process exits with status 0

#### Scenario: Unrelated commands are unaffected

- **WHEN** the web server dependencies are absent
- **THEN** every other scrobbledb command behaves exactly as it did before this
  capability existed

### Requirement: Domain customizations are scoped to this server

The system SHALL apply its scrobbledb-specific customizations only to servers it starts,
and SHALL NOT alter the behavior of unrelated Datasette instances that happen to share
the same Python environment.

#### Scenario: Customizations present in the scrobbledb server

- **WHEN** a server started by `scrobbledb serve` is inspected for its loaded plugins
- **THEN** the scrobbledb domain plugin is listed among them

#### Scenario: Unrelated Datasette instance is untouched

- **WHEN** a separate Datasette process is started against an unrelated database in the
  same environment
- **THEN** the scrobbledb domain plugin is not loaded and no scrobbledb canned queries
  or functions are available to it
