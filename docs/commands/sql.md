# `scrobbledb sql`

Read-only sqlite-utils commands against the scrobbledb database. Use these to inspect tables, run ad-hoc queries, or examine indexes and triggers. The default database path is the XDG data directory.

## Group usage

<!-- [[[cog
from click.testing import CliRunner
from scrobbledb.cli import cli
runner = CliRunner()
result = runner.invoke(cli, ["sql", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql [OPTIONS] COMMAND [ARGS]...

SQLite database query and inspection commands.

These commands provide read-only access to your scrobbledb database
using the sqlite-utils CLI. The database path defaults to
the scrobbledb database in your XDG data directory (e.g.,
$XDG_DATA_HOME/dev.pirateninja.scrobbledb/scrobbledb.db).

To check if your database is initialized:
  scrobbledb init --dry-run

Core Scrobble Data Tables:
  artists - Artist information (id, name)
  albums  - Album information (id, title, artist_id)
  tracks  - Track information (id, title, album_id)
  plays   - Play events (track_id, timestamp)

Examples:

  # Query the database
  scrobbledb sql query "SELECT * FROM tracks LIMIT 10"

  # List all tables with row counts
  scrobbledb sql tables --counts

  # View table schema
  scrobbledb sql schema tracks

  # Browse table data
  scrobbledb sql rows plays --limit 20

  # Use a different database
  scrobbledb sql query "SELECT * FROM users" --database /path/to/other.db

Options:
  -d, --database FILE  Database path (default: scrobbledb database in XDG data
                       dir)
  --help               Show this message and exit.

Commands:
  analyze-tables  Analyze the columns in one or more tables.
  dump            Output a SQL dump of the schema and full contents of the...
  indexes         Show indexes for the whole database or specific tables.
  memory          Execute SQL query against an in-memory database,...
  plugins         List installed sqlite-utils plugins.
  query           Execute SQL query and return the results as JSON.
  rows            Output all rows in the specified table.
  schema          Show full schema for this database or for specified tables.
  search          Execute a full-text search against this table.
  tables          List the tables in the database.
  triggers        Show triggers configured in this database.
  views           List the views in the database.
```
<!-- [[[end]]] -->

## Subcommands

### `query`
Execute SQL and return results as JSON.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "query", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql query [OPTIONS] SQL_QUERY

  Execute SQL query and return the results as JSON.

  Example:

          scrobbledb sql query "SELECT * FROM tracks WHERE artist_id = :id LIMIT 10" -p id 123

Options:
  --attach <TEXT FILE>...     Additional databases to attach - specify alias and
                              filepath
  --nl                        Output newline-delimited JSON
  --arrays                    Output rows as arrays instead of objects
  --csv                       Output CSV
  --tsv                       Output TSV
  --no-headers                Omit CSV headers
  -t, --table                 Output as a formatted table
  --fmt TEXT                  Table format - see tabulate documentation for
                              available formats
  --json-cols                 Detect JSON cols and output them as JSON, not
                              escaped strings
  -r, --raw                   Raw output, first column of first row
  --raw-lines                 Raw output, first column of each row
  -p, --param <TEXT TEXT>...  Named :parameters for SQL query
  --functions TEXT            Python code defining one or more custom SQL
                              functions
  --load-extension TEXT       Path to SQLite extension, with optional
                              :entrypoint
  --help                      Show this message and exit.
```
<!-- [[[end]]] -->

### `tables`
List database tables with optional counts and columns.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "tables", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql tables [OPTIONS]

  List the tables in the database.

  Example:

          scrobbledb sql tables --counts --columns

Options:
  --fts4                 Just show FTS4 enabled tables
  --fts5                 Just show FTS5 enabled tables
  --counts               Include row counts per table
  --nl                   Output newline-delimited JSON
  --arrays               Output rows as arrays instead of objects
  --csv                  Output CSV
  --tsv                  Output TSV
  --no-headers           Omit CSV headers
  -t, --table            Output as a formatted table
  --fmt TEXT             Table format - see tabulate documentation for available
                         formats
  --json-cols            Detect JSON cols and output them as JSON, not escaped
                         strings
  --columns              Include list of columns for each table
  --schema               Include schema for each table
  --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
  --help                 Show this message and exit.
```
<!-- [[[end]]] -->

### `schema`
Show the schema for the whole database or specific tables.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "schema", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql schema [OPTIONS] [TABLES]...

  Show full schema for this database or for specified tables.

  Example:

          scrobbledb sql schema
          scrobbledb sql schema tracks plays

Options:
  --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
  --help                 Show this message and exit.
```
<!-- [[[end]]] -->

### `views`
List views in the database.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "views", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql views [OPTIONS]

  List the views in the database.

  Example:

          scrobbledb sql views --counts

Options:
  --counts               Include row counts per view
  --nl                   Output newline-delimited JSON
  --arrays               Output rows as arrays instead of objects
  --csv                  Output CSV
  --tsv                  Output TSV
  --no-headers           Omit CSV headers
  -t, --table            Output as a formatted table
  --fmt TEXT             Table format - see tabulate documentation for available
                         formats
  --json-cols            Detect JSON cols and output them as JSON, not escaped
                         strings
  --columns              Include list of columns for each view
  --schema               Include schema for each view
  --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
  --help                 Show this message and exit.
```
<!-- [[[end]]] -->

### `search`
Run full-text search against a table.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "search", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql search [OPTIONS] DBTABLE Q

  Execute a full-text search against this table.

  Example:

          scrobbledb sql search tracks "rolling stones" --limit 10

Options:
  -o, --order [relevance|score]  Order by relevance or score (relevance is the
                                 default)
  -c, --column TEXT              Columns to return
  --limit INTEGER                Number of rows to return
  --sql                          Show SQL query that would be run
  --quote                        Apply FTS quoting rules to search term
  --nl                           Output newline-delimited JSON
  --arrays                       Output rows as arrays instead of objects
  --csv-output, --csv            Output CSV
  --tsv                          Output TSV
  --no-headers                   Omit CSV headers
  -t, --table                    Output as a formatted table
  --fmt TEXT                     Table format - see tabulate documentation for
                                 available formats
  --json-cols                    Detect JSON cols and output them as JSON, not
                                 escaped strings
  --load-extension TEXT          Path to SQLite extension, with optional
                                 :entrypoint
  --help                         Show this message and exit.
```
<!-- [[[end]]] -->

### `dump`
Output a SQL dump of the schema and contents.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "dump", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql dump [OPTIONS]

  Output a SQL dump of the schema and full contents of the database.

  Example:

          scrobbledb sql dump > backup.sql

Options:
  --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
  --help                 Show this message and exit.
```
<!-- [[[end]]] -->

### `analyze-tables`
Analyze columns in one or more tables.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "analyze-tables", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql analyze-tables [OPTIONS] [TABLES]...

  Analyze the columns in one or more tables.

  Example:

          scrobbledb sql analyze-tables tracks
          scrobbledb sql analyze-tables tracks -c artist_name

Options:
  -c, --column TEXT       Specific columns to analyze
  --save                  Save results to _analyze_tables table
  --common-limit INTEGER  How many common values to return for each column
                          (default 10)
  --no-most               Skip most common values
  --no-least              Skip least common values
  --load-extension TEXT   Path to SQLite extension, with optional :entrypoint
  --help                  Show this message and exit.
```
<!-- [[[end]]] -->

### `memory`
Execute SQL against an in-memory database created from CSV/TSV/JSON inputs.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "memory", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql memory [OPTIONS] [PATHS]... SQL_QUERY

  Execute SQL query against an in-memory database, optionally populated by
  imported data.

  Example:

          scrobbledb sql memory data.csv "SELECT * FROM data LIMIT 10"

Options:
  --functions TEXT            Python code defining one or more custom SQL
                              functions
  --attach <TEXT FILE>...     Additional databases to attach - specify alias and
                              filepath
  --flatten                   Flatten nested JSON objects, so {"foo": {"bar":
                              1}} becomes {"foo_bar": 1}
  --nl                        Output newline-delimited JSON
  --arrays                    Output rows as arrays instead of objects
  --csv                       Output CSV
  --tsv                       Output TSV
  --no-headers                Omit CSV headers
  -t, --table                 Output as a formatted table
  --fmt TEXT                  Table format - see tabulate documentation for
                              available formats
  --json-cols                 Detect JSON cols and output them as JSON, not
                              escaped strings
  -r, --raw                   Raw output, first column of first row
  --raw-lines                 Raw output, first column of each row
  -p, --param <TEXT TEXT>...  Named :parameters for SQL query
  --encoding TEXT             Character encoding for CSV files
  --no-detect-types           Treat all CSV columns as TEXT
  --schema                    Show SQL schema for in-memory database
  --dump                      Dump SQL for in-memory database
  --save FILE                 Save in-memory database to this file
  --analyze                   Analyze resulting tables
  --load-extension TEXT       Path to SQLite extension, with optional
                              :entrypoint
  --help                      Show this message and exit.
```
<!-- [[[end]]] -->

### `plugins`
List installed sqlite-utils plugins.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "plugins", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql plugins [OPTIONS]

  List installed sqlite-utils plugins.

  Example:

          scrobbledb sql plugins

Options:
  --help  Show this message and exit.
```
<!-- [[[end]]] -->

### `indexes`
Show indexes for the whole database or specific tables.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "indexes", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql indexes [OPTIONS] [TABLES]...

  Show indexes for the whole database or specific tables.

  Example:

          scrobbledb sql indexes
          scrobbledb sql indexes tracks

Options:
  --aux                  Include auxiliary columns
  --nl                   Output newline-delimited JSON
  --arrays               Output rows as arrays instead of objects
  --csv                  Output CSV
  --tsv                  Output TSV
  --no-headers           Omit CSV headers
  -t, --table            Output as a formatted table
  --fmt TEXT             Table format - see tabulate documentation for available
                         formats
  --json-cols            Detect JSON cols and output them as JSON, not escaped
                         strings
  --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
  --help                 Show this message and exit.
```
<!-- [[[end]]] -->

### `rows`
Output rows from a table with filtering options.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "rows", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql rows [OPTIONS] TABLE_NAME

  Output all rows in the specified table.

  Example:

          scrobbledb sql rows plays --limit 20
          scrobbledb sql rows tracks -c artist_name -c track_title --limit 10
          scrobbledb sql rows plays --where "timestamp > :date" -p date 2024-01-01

  Security Note:     The --where and --order options accept raw SQL. Use --param
  for untrusted user data     to prevent SQL injection. Column and table names
  are automatically quoted.

Options:
  -c, --column TEXT           Columns to return
  --where TEXT                SQL where clause to filter rows (use --param for
                              user data)
  -o, --order TEXT            Order by ('column' or 'column desc')
  --limit INTEGER             Number of rows to return
  --offset INTEGER            SQL offset to use
  --nl                        Output newline-delimited JSON
  --arrays                    Output rows as arrays instead of objects
  --csv                       Output CSV
  --tsv                       Output TSV
  --no-headers                Omit CSV headers
  -t, --table-format          Output as a formatted table
  --fmt TEXT                  Table format - see tabulate documentation for
                              available formats
  --json-cols                 Detect JSON cols and output them as JSON, not
                              escaped strings
  -p, --param <TEXT TEXT>...  Named :parameters for SQL query
  --load-extension TEXT       Path to SQLite extension, with optional
                              :entrypoint
  --help                      Show this message and exit.
```
<!-- [[[end]]] -->

### `triggers`
Show triggers configured in the database.

<!-- [[[cog
result = runner.invoke(cli, ["sql", "triggers", "--help"])
cog.out("```\n" + result.output + "```")
]]] -->
```
Usage: cli sql triggers [OPTIONS] [TABLES]...

  Show triggers configured in this database.

  Example:

          scrobbledb sql triggers

Options:
  --nl                   Output newline-delimited JSON
  --arrays               Output rows as arrays instead of objects
  --csv                  Output CSV
  --tsv                  Output TSV
  --no-headers           Omit CSV headers
  -t, --table            Output as a formatted table
  --fmt TEXT             Table format - see tabulate documentation for available
                         formats
  --json-cols            Detect JSON cols and output them as JSON, not escaped
                         strings
  --load-extension TEXT  Path to SQLite extension, with optional :entrypoint
  --help                 Show this message and exit.
```
<!-- [[[end]]] -->
