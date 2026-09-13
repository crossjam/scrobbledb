## Purpose

Lets an LLM agent query a scrobbledb listening history over the Model Context Protocol,
both through generic schema-and-SQL tools and through scrobbledb-specific tools that
answer domain questions without the agent having to know the schema or the timestamp
encoding.

## ADDED Requirements

### Requirement: The server exposes an MCP endpoint

The system SHALL expose a Model Context Protocol endpoint on the same web server that
serves the database, reachable over MCP Streamable HTTP, so an MCP client can connect to
the running scrobbledb server.

#### Scenario: Endpoint is reachable

- **WHEN** an MCP client connects to the running server’s MCP endpoint
- **THEN** the connection is established and the client can complete an MCP
  initialization handshake

#### Scenario: Endpoint is advertised

- **WHEN** `scrobbledb serve` starts
- **THEN** it prints the MCP endpoint URL alongside the web UI URL

#### Scenario: Endpoint absent when MCP support is not installed

- **WHEN** the server is started in an environment where MCP support is not installed
- **THEN** the web server still starts and serves normally, and the startup output
  states that the MCP endpoint is unavailable and how to enable it

### Requirement: Generic database tools are available

The system SHALL make the generic Datasette MCP tools available unchanged: listing the
databases visible to the caller, returning a database’s complete SQL schema, and
executing a single read-only SQL statement.

#### Scenario: Schema retrieval

- **WHEN** an MCP client calls the schema tool for the scrobbledb database
- **THEN** it receives the full SQL schema including the `artists`, `albums`, `tracks`
  and `plays` tables

#### Scenario: Read-only SQL execution

- **WHEN** an MCP client calls the SQL tool with a `SELECT` statement
- **THEN** it receives the result columns, the rows keyed by column name, and an
  indication of whether the result was truncated

#### Scenario: Write statement via MCP is rejected

- **WHEN** an MCP client calls the SQL tool with a statement that would modify the
  database
- **THEN** the call fails with an error and the database is unchanged

### Requirement: Domain tools answer scrobbledb questions without SQL

The system SHALL register additional MCP tools that speak scrobbledb’s domain model, so
an agent can answer common listening-history questions without composing SQL or knowing
the schema. These SHALL cover at minimum: collection overview, top artists, top albums,
top tracks, recent plays, artist detail, album detail, track detail, search by name, and
time-based rollups.

#### Scenario: Top artists tool

- **WHEN** an MCP client calls the top-artists tool with a limit and an optional time
  range
- **THEN** it receives a structured list of artists with play counts, ordered by play
  count descending and capped at the limit

#### Scenario: Artist detail tool

- **WHEN** an MCP client calls the artist-detail tool with an artist name
- **THEN** it receives that artist’s play count, album count, track count, and first and
  last play timestamps

#### Scenario: Ambiguous artist name

- **WHEN** the artist-detail tool is called with a name matching more than one artist
- **THEN** the call returns an error naming the candidate matches rather than silently
  picking one

#### Scenario: Unknown artist name

- **WHEN** the artist-detail tool is called with a name matching no artist
- **THEN** the call returns a result indicating no match, not an unhandled failure

#### Scenario: Search tool

- **WHEN** an MCP client calls the search tool with a partial name
- **THEN** it receives matching artists, albums and tracks with enough identifying
  detail to pass into the detail tools

#### Scenario: Tools are self-describing

- **WHEN** an MCP client lists the available tools
- **THEN** each scrobbledb tool carries a description and a typed input schema stating
  its parameters and which are optional

### Requirement: Domain tools accept the same time vocabulary as the CLI

MCP tools that take a time range SHALL accept the same relative and natural-language
values the scrobbledb CLI accepts for `--since` and `--until`.

#### Scenario: Natural-language range

- **WHEN** an MCP client calls a time-ranged tool with a bound such as `6 months ago`
- **THEN** the tool interprets it as the CLI would and returns results for that range

#### Scenario: Unparseable range value

- **WHEN** a time bound cannot be interpreted
- **THEN** the call returns an error naming the offending value and giving an example of
  an accepted form

#### Scenario: Omitted range

- **WHEN** no time bounds are supplied
- **THEN** the tool covers the entire play history

### Requirement: MCP tools inherit the server’s read-only and permission guarantees

Every MCP tool SHALL be read-only and SHALL be subject to the same database visibility
and query permissions as the web interface.

#### Scenario: No write path

- **WHEN** the full set of registered MCP tools is examined
- **THEN** none of them can modify the database, and a full MCP session leaves the
  database file unchanged

#### Scenario: Permission enforcement

- **WHEN** the server is configured to deny SQL execution to a caller
- **THEN** MCP tool calls from that caller that would execute SQL are refused with a
  permission error

#### Scenario: Every tool is covered

- **WHEN** each registered scrobbledb MCP tool is invoked in turn by a caller who lacks
  permission to execute SQL
- **THEN** every one of them is refused, with no tool reaching the database

#### Scenario: Results are bounded

- **WHEN** a tool call would return an unbounded number of rows
- **THEN** the result is capped and the response indicates that it was truncated
