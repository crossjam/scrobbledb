"""
SQLite database query and inspection commands.

This module provides a wrapper around sqlite-utils CLI commands,
automatically defaulting to the scrobbledb database in the XDG data directory.
"""

import click
import sys
from pathlib import Path

# Import sqlite-utils CLI commands
from sqlite_utils.cli import (
    query as sqlite_query,
    tables as sqlite_tables,
    views as sqlite_views,
    schema as sqlite_schema,
    rows as sqlite_rows,
    indexes as sqlite_indexes,
    triggers as sqlite_triggers,
    search as sqlite_search,
    dump as sqlite_dump,
    analyze_tables as sqlite_analyze_tables,
    memory as sqlite_memory,
    plugins_list as sqlite_plugins,
)


class SqlGroup(click.Group):
    """Custom Group class that provides dynamic help text."""

    def format_help(self, ctx, formatter):
        """Format help text with actual database path."""
        # Import here to avoid circular import
        from .cli import get_default_db_path

        db_path = get_default_db_path()

        # Write usage
        self.format_usage(ctx, formatter)

        # Create and write dynamic help text
        help_text = f"""SQLite database query and inspection commands.

These commands provide read-only access to your scrobbledb database
using the sqlite-utils CLI. The database path defaults to your
scrobbledb database in the XDG data directory.

Default Database Location:
  {db_path}

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
"""

        formatter.write_paragraph()
        for line in help_text.strip().splitlines():
            if line.strip():
                formatter.write_text(line)
            else:
                formatter.write_paragraph()

        # Format options (this also calls format_commands for Groups)
        self.format_options(ctx, formatter)


@click.group(cls=SqlGroup)
@click.option(
    "--database",
    "-d",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    default=None,
    help="Database path (default: scrobbledb database in XDG data dir)",
)
@click.pass_context
def sql(ctx, database):
    """
    SQLite database query and inspection commands.

    Execute SQL queries, list tables, view schemas, and more using sqlite-utils.
    All commands default to the scrobbledb database in your XDG data directory.
    """
    # Import here to avoid circular import
    from .cli import get_default_db_path

    ctx.ensure_object(dict)
    if database is None:
        database = get_default_db_path()
    ctx.obj['database'] = database


@sql.command()
@click.argument("sql_query")
@click.option(
    "--attach",
    type=(str, click.Path(file_okay=True, dir_okay=False, allow_dash=False)),
    multiple=True,
    help="Additional databases to attach - specify alias and filepath",
)
@click.option(
    "--nl",
    help="Output newline-delimited JSON",
    is_flag=True,
    default=False,
)
@click.option(
    "--arrays",
    help="Output rows as arrays instead of objects",
    is_flag=True,
    default=False,
)
@click.option("--csv", is_flag=True, help="Output CSV")
@click.option("--tsv", is_flag=True, help="Output TSV")
@click.option("--no-headers", is_flag=True, help="Omit CSV headers")
@click.option(
    "-t", "--table", is_flag=True, help="Output as a formatted table"
)
@click.option(
    "--fmt",
    help="Table format - see tabulate documentation for available formats",
)
@click.option(
    "--json-cols",
    help="Detect JSON cols and output them as JSON, not escaped strings",
    is_flag=True,
    default=False,
)
@click.option("-r", "--raw", is_flag=True, help="Raw output, first column of first row")
@click.option("--raw-lines", is_flag=True, help="Raw output, first column of each row")
@click.option(
    "-p",
    "--param",
    multiple=True,
    type=(str, str),
    help="Named :parameters for SQL query",
)
@click.option(
    "--functions", help="Python code defining one or more custom SQL functions"
)
@click.option(
    "--load-extension",
    multiple=True,
    help="Path to SQLite extension, with optional :entrypoint",
)
@click.pass_context
def query(ctx, sql_query, **kwargs):
    """
    Execute SQL query and return the results as JSON.

    Example:

        \b
        scrobbledb sql query "SELECT * FROM tracks WHERE artist_id = :id LIMIT 10" -p id 123
    """
    path = ctx.obj['database']
    ctx.invoke(sqlite_query, path=path, sql=sql_query, **kwargs)


@sql.command()
@click.option(
    "--fts4", help="Just show FTS4 enabled tables", default=False, is_flag=True
)
@click.option(
    "--fts5", help="Just show FTS5 enabled tables", default=False, is_flag=True
)
@click.option(
    "--counts", help="Include row counts per table", default=False, is_flag=True
)
@click.option(
    "--nl",
    help="Output newline-delimited JSON",
    is_flag=True,
    default=False,
)
@click.option(
    "--arrays",
    help="Output rows as arrays instead of objects",
    is_flag=True,
    default=False,
)
@click.option("--csv", is_flag=True, help="Output CSV")
@click.option("--tsv", is_flag=True, help="Output TSV")
@click.option("--no-headers", is_flag=True, help="Omit CSV headers")
@click.option(
    "-t", "--table", is_flag=True, help="Output as a formatted table"
)
@click.option(
    "--fmt",
    help="Table format - see tabulate documentation for available formats",
)
@click.option(
    "--json-cols",
    help="Detect JSON cols and output them as JSON, not escaped strings",
    is_flag=True,
    default=False,
)
@click.option(
    "--columns",
    help="Include list of columns for each table",
    is_flag=True,
    default=False,
)
@click.option(
    "--schema",
    help="Include schema for each table",
    is_flag=True,
    default=False,
)
@click.option(
    "--load-extension",
    multiple=True,
    help="Path to SQLite extension, with optional :entrypoint",
)
@click.pass_context
def tables(ctx, **kwargs):
    """
    List the tables in the database.

    Example:

        \b
        scrobbledb sql tables --counts --columns
    """
    path = ctx.obj['database']
    ctx.invoke(sqlite_tables, path=path, **kwargs)


@sql.command()
@click.option(
    "--counts", help="Include row counts per view", default=False, is_flag=True
)
@click.option(
    "--nl",
    help="Output newline-delimited JSON",
    is_flag=True,
    default=False,
)
@click.option(
    "--arrays",
    help="Output rows as arrays instead of objects",
    is_flag=True,
    default=False,
)
@click.option("--csv", is_flag=True, help="Output CSV")
@click.option("--tsv", is_flag=True, help="Output TSV")
@click.option("--no-headers", is_flag=True, help="Omit CSV headers")
@click.option(
    "-t", "--table", is_flag=True, help="Output as a formatted table"
)
@click.option(
    "--fmt",
    help="Table format - see tabulate documentation for available formats",
)
@click.option(
    "--json-cols",
    help="Detect JSON cols and output them as JSON, not escaped strings",
    is_flag=True,
    default=False,
)
@click.option(
    "--columns",
    help="Include list of columns for each view",
    is_flag=True,
    default=False,
)
@click.option(
    "--schema",
    help="Include schema for each view",
    is_flag=True,
    default=False,
)
@click.option(
    "--load-extension",
    multiple=True,
    help="Path to SQLite extension, with optional :entrypoint",
)
@click.pass_context
def views(ctx, **kwargs):
    """
    List the views in the database.

    Example:

        \b
        scrobbledb sql views --counts
    """
    path = ctx.obj['database']
    ctx.invoke(sqlite_views, path=path, **kwargs)


@sql.command()
@click.argument("tables", nargs=-1)
@click.option(
    "--load-extension",
    multiple=True,
    help="Path to SQLite extension, with optional :entrypoint",
)
@click.pass_context
def schema(ctx, tables, **kwargs):
    """
    Show full schema for this database or for specified tables.

    Example:

        \b
        scrobbledb sql schema
        scrobbledb sql schema tracks plays
    """
    path = ctx.obj['database']
    ctx.invoke(sqlite_schema, path=path, tables=tables, **kwargs)


@sql.command()
@click.argument("table_name")
@click.option(
    "-c", "--column", multiple=True, help="Columns to return"
)
@click.option(
    "--where", help="SQL where clause to filter rows"
)
@click.option(
    "-o", "--order", help="Order by ('column' or 'column desc')"
)
@click.option(
    "--limit", type=int, help="Number of rows to return"
)
@click.option(
    "--offset", type=int, help="SQL offset to use"
)
@click.option(
    "--nl",
    help="Output newline-delimited JSON",
    is_flag=True,
    default=False,
)
@click.option(
    "--arrays",
    help="Output rows as arrays instead of objects",
    is_flag=True,
    default=False,
)
@click.option("--csv", is_flag=True, help="Output CSV")
@click.option("--tsv", is_flag=True, help="Output TSV")
@click.option("--no-headers", is_flag=True, help="Omit CSV headers")
@click.option(
    "-t", "--table-format", "table", is_flag=True, help="Output as a formatted table"
)
@click.option(
    "--fmt",
    help="Table format - see tabulate documentation for available formats",
)
@click.option(
    "--json-cols",
    help="Detect JSON cols and output them as JSON, not escaped strings",
    is_flag=True,
    default=False,
)
@click.option(
    "-p",
    "--param",
    multiple=True,
    type=(str, str),
    help="Named :parameters for SQL query",
)
@click.option(
    "--load-extension",
    multiple=True,
    help="Path to SQLite extension, with optional :entrypoint",
)
@click.pass_context
def rows(ctx, table_name, column, where, order, limit, offset, nl, arrays, csv, tsv, no_headers, table, fmt, json_cols, param, load_extension):
    """
    Output all rows in the specified table.

    Example:

        \b
        scrobbledb sql rows plays --limit 20
        scrobbledb sql rows tracks -c artist_name -c track_title --limit 10
    """
    path = ctx.obj['database']

    # Call sqlite_rows with all parameters explicitly set to avoid context pollution
    # Note: sqlite-utils uses 'dbtable' for the table name, 'table' for formatting flag
    ctx.invoke(
        sqlite_rows,
        path=path,
        dbtable=table_name,
        column=column,
        where=where,
        limit=limit,
        offset=offset,
        nl=nl,
        arrays=arrays,
        csv=csv,
        tsv=tsv,
        no_headers=no_headers,
        table=table,
        fmt=fmt,
        json_cols=json_cols,
        order=order,
        param=param,
        load_extension=load_extension,
    )


@sql.command()
@click.argument("tables", nargs=-1)
@click.option(
    "--aux", is_flag=True, help="Include auxiliary columns"
)
@click.option(
    "--nl",
    help="Output newline-delimited JSON",
    is_flag=True,
    default=False,
)
@click.option(
    "--arrays",
    help="Output rows as arrays instead of objects",
    is_flag=True,
    default=False,
)
@click.option("--csv", is_flag=True, help="Output CSV")
@click.option("--tsv", is_flag=True, help="Output TSV")
@click.option("--no-headers", is_flag=True, help="Omit CSV headers")
@click.option(
    "-t", "--table", is_flag=True, help="Output as a formatted table"
)
@click.option(
    "--fmt",
    help="Table format - see tabulate documentation for available formats",
)
@click.option(
    "--json-cols",
    help="Detect JSON cols and output them as JSON, not escaped strings",
    is_flag=True,
    default=False,
)
@click.option(
    "--load-extension",
    multiple=True,
    help="Path to SQLite extension, with optional :entrypoint",
)
@click.pass_context
def indexes(ctx, tables, aux, nl, arrays, csv, tsv, no_headers, table, fmt, json_cols, load_extension):
    """
    Show indexes for the whole database or specific tables.

    Example:

        \b
        scrobbledb sql indexes
        scrobbledb sql indexes tracks
    """
    import sqlite_utils

    path = ctx.obj['database']

    # Build the SQL query (copied from sqlite-utils indexes command)
    sql = """
    select
      sqlite_master.name as "table",
      indexes.name as index_name,
      xinfo.*
    from sqlite_master
      join pragma_index_list(sqlite_master.name) indexes
      join pragma_index_xinfo(index_name) xinfo
    where
      sqlite_master.type = 'table'
    """
    if tables:
        quote = sqlite_utils.Database(memory=True).quote
        sql += " and sqlite_master.name in ({})".format(
            ", ".join(quote(t) for t in tables)
        )
    if not aux:
        sql += " and xinfo.key = 1"

    # Call query directly with ALL parameters explicitly set
    ctx.invoke(
        sqlite_query,
        path=path,
        sql=sql,
        attach=(),
        nl=nl,
        arrays=arrays,
        csv=csv,
        tsv=tsv,
        no_headers=no_headers,
        table=table,
        fmt=fmt,
        json_cols=json_cols,
        raw=False,
        raw_lines=False,
        param=(),
        load_extension=load_extension,
        functions=None,
    )


@sql.command()
@click.argument("tables", nargs=-1)
@click.option(
    "--nl",
    help="Output newline-delimited JSON",
    is_flag=True,
    default=False,
)
@click.option(
    "--arrays",
    help="Output rows as arrays instead of objects",
    is_flag=True,
    default=False,
)
@click.option("--csv", is_flag=True, help="Output CSV")
@click.option("--tsv", is_flag=True, help="Output TSV")
@click.option("--no-headers", is_flag=True, help="Omit CSV headers")
@click.option(
    "-t", "--table", is_flag=True, help="Output as a formatted table"
)
@click.option(
    "--fmt",
    help="Table format - see tabulate documentation for available formats",
)
@click.option(
    "--json-cols",
    help="Detect JSON cols and output them as JSON, not escaped strings",
    is_flag=True,
    default=False,
)
@click.option(
    "--load-extension",
    multiple=True,
    help="Path to SQLite extension, with optional :entrypoint",
)
@click.pass_context
def triggers(ctx, tables, nl, arrays, csv, tsv, no_headers, table, fmt, json_cols, load_extension):
    """
    Show triggers configured in this database.

    Example:

        \b
        scrobbledb sql triggers
    """
    import sqlite_utils

    path = ctx.obj['database']

    # Build the SQL query (copied from sqlite-utils triggers command)
    sql = """
    select
      name,
      tbl_name as "table",
      sql
    from
      sqlite_master
    where
      type = 'trigger'
    """
    if tables:
        quote = sqlite_utils.Database(memory=True).quote
        sql += " and tbl_name in ({})".format(
            ", ".join(quote(t) for t in tables)
        )
    sql += " order by name"

    # Call query directly with ALL parameters explicitly set
    ctx.invoke(
        sqlite_query,
        path=path,
        sql=sql,
        attach=(),
        nl=nl,
        arrays=arrays,
        csv=csv,
        tsv=tsv,
        no_headers=no_headers,
        table=table,
        fmt=fmt,
        json_cols=json_cols,
        raw=False,
        raw_lines=False,
        param=(),
        load_extension=load_extension,
        functions=None,
    )


@sql.command()
@click.argument("dbtable")
@click.argument("q")
@click.option(
    "-o",
    "--order",
    type=click.Choice(["relevance", "score"], case_sensitive=False),
    default="relevance",
    help="Order by relevance or score (relevance is the default)",
)
@click.option(
    "-c", "--column", multiple=True, help="Columns to return"
)
@click.option(
    "--limit", type=int, help="Number of rows to return"
)
@click.option(
    "--sql", is_flag=True, help="Show SQL query that would be run"
)
@click.option(
    "--quote",
    is_flag=True,
    help="Apply FTS quoting rules to search term",
)
@click.option(
    "--nl",
    help="Output newline-delimited JSON",
    is_flag=True,
    default=False,
)
@click.option(
    "--arrays",
    help="Output rows as arrays instead of objects",
    is_flag=True,
    default=False,
)
@click.option("--csv-output", "--csv", "csv", is_flag=True, help="Output CSV")
@click.option("--tsv", is_flag=True, help="Output TSV")
@click.option("--no-headers", is_flag=True, help="Omit CSV headers")
@click.option(
    "-t", "--table", is_flag=True, help="Output as a formatted table"
)
@click.option(
    "--fmt",
    help="Table format - see tabulate documentation for available formats",
)
@click.option(
    "--json-cols",
    help="Detect JSON cols and output them as JSON, not escaped strings",
    is_flag=True,
    default=False,
)
@click.option(
    "--load-extension",
    multiple=True,
    help="Path to SQLite extension, with optional :entrypoint",
)
@click.pass_context
def search(ctx, dbtable, q, column, **kwargs):
    """
    Execute a full-text search against this table.

    Example:

        \b
        scrobbledb sql search tracks "rolling stones" --limit 10
    """
    path = ctx.obj['database']
    ctx.invoke(sqlite_search, path=path, dbtable=dbtable, q=q, column=column, **kwargs)


@sql.command()
@click.option(
    "--load-extension",
    multiple=True,
    help="Path to SQLite extension, with optional :entrypoint",
)
@click.pass_context
def dump(ctx, **kwargs):
    """
    Output a SQL dump of the schema and full contents of the database.

    Example:

        \b
        scrobbledb sql dump > backup.sql
    """
    path = ctx.obj['database']
    ctx.invoke(sqlite_dump, path=path, **kwargs)


@sql.command(name="analyze-tables")
@click.argument("tables", nargs=-1, required=False)
@click.option(
    "-c",
    "--column",
    multiple=True,
    help="Specific columns to analyze",
)
@click.option(
    "--save",
    is_flag=True,
    help="Save results to _analyze_tables table",
)
@click.option(
    "--common-limit",
    type=int,
    default=10,
    help="How many common values to return for each column (default 10)",
)
@click.option(
    "--no-most",
    is_flag=True,
    help="Skip most common values",
)
@click.option(
    "--no-least",
    is_flag=True,
    help="Skip least common values",
)
@click.option(
    "--load-extension",
    multiple=True,
    help="Path to SQLite extension, with optional :entrypoint",
)
@click.pass_context
def analyze_tables(ctx, tables, column, **kwargs):
    """
    Analyze the columns in one or more tables.

    Example:

        \b
        scrobbledb sql analyze-tables tracks
        scrobbledb sql analyze-tables tracks -c artist_name
    """
    path = ctx.obj['database']
    ctx.invoke(sqlite_analyze_tables, path=path, tables=tables, column=column, **kwargs)


@sql.command()
@click.argument(
    "paths",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=True),
    required=False,
    nargs=-1,
)
@click.argument("sql_query")
@click.option(
    "--functions", help="Python code defining one or more custom SQL functions"
)
@click.option(
    "--attach",
    type=(str, click.Path(file_okay=True, dir_okay=False, allow_dash=False)),
    multiple=True,
    help="Additional databases to attach - specify alias and filepath",
)
@click.option(
    "--flatten",
    is_flag=True,
    help='Flatten nested JSON objects, so {"foo": {"bar": 1}} becomes {"foo_bar": 1}',
)
@click.option(
    "--nl",
    help="Output newline-delimited JSON",
    is_flag=True,
    default=False,
)
@click.option(
    "--arrays",
    help="Output rows as arrays instead of objects",
    is_flag=True,
    default=False,
)
@click.option("--csv", is_flag=True, help="Output CSV")
@click.option("--tsv", is_flag=True, help="Output TSV")
@click.option("--no-headers", is_flag=True, help="Omit CSV headers")
@click.option(
    "-t", "--table", is_flag=True, help="Output as a formatted table"
)
@click.option(
    "--fmt",
    help="Table format - see tabulate documentation for available formats",
)
@click.option(
    "--json-cols",
    help="Detect JSON cols and output them as JSON, not escaped strings",
    is_flag=True,
    default=False,
)
@click.option("-r", "--raw", is_flag=True, help="Raw output, first column of first row")
@click.option("--raw-lines", is_flag=True, help="Raw output, first column of each row")
@click.option(
    "-p",
    "--param",
    multiple=True,
    type=(str, str),
    help="Named :parameters for SQL query",
)
@click.option(
    "--encoding",
    help="Character encoding for CSV files",
)
@click.option(
    "--no-detect-types",
    is_flag=True,
    help="Treat all CSV columns as TEXT",
)
@click.option(
    "--schema",
    is_flag=True,
    help="Show SQL schema for in-memory database",
)
@click.option(
    "--dump",
    is_flag=True,
    help="Dump SQL for in-memory database",
)
@click.option(
    "--save",
    type=click.Path(file_okay=True, dir_okay=False, allow_dash=False),
    help="Save in-memory database to this file",
)
@click.option(
    "--analyze",
    is_flag=True,
    help="Analyze resulting tables",
)
@click.option(
    "--load-extension",
    multiple=True,
    help="Path to SQLite extension, with optional :entrypoint",
)
@click.pass_context
def memory(ctx, paths, sql_query, **kwargs):
    """
    Execute SQL query against an in-memory database, optionally populated by imported data.

    Example:

        \b
        scrobbledb sql memory data.csv "SELECT * FROM data LIMIT 10"
    """
    ctx.invoke(sqlite_memory, paths=paths, sql=sql_query, **kwargs)


@sql.command()
@click.pass_context
def plugins(ctx):
    """
    List installed sqlite-utils plugins.

    Example:

        \b
        scrobbledb sql plugins
    """
    ctx.invoke(sqlite_plugins)
