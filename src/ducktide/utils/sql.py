"""Centralized SQL-string composition for pre-validated identifiers.

Every helper in this module assembles a SQL statement (or fragment) by textually
interpolating **only** SQL identifiers — table, schema and column names — plus
already-escaped path literals and caller-built fragments (WHERE conditions,
option lists). DuckDB, like most engines, does not accept bound parameters for
identifiers, so these names must be interpolated as text rather than passed as
query parameters.

The safety contract is therefore pushed to the callers: every ``source`` /
``table`` / ``schema`` / ``column`` argument must already be code-derived or
validated (see :class:`ducktide.time._base.TimeSeriesBase` — ``_validate_table_name``
and ``_quote_identifier`` — and :func:`ducktide.utils.path_validation.escape_path_for_sql`)
and never raw user data. All row *values* continue to be bound via ``?``
placeholders by the callers.

Concentrating the interpolation here keeps the Bandit ``B608`` (and Ruff
``S608``) audit surface to this single, reviewed module instead of ~20 call
sites scattered across the database layer.

The "caller validated it" contract is enforced *in code*, not merely asserted
in docstrings:

* Bare identifiers are produced through :func:`quote_identifier` /
  :func:`validate_identifier`, which reject anything that is not a plain SQL
  identifier (optionally ``schema.table`` qualified). Callers that build table
  names route through these (see
  :class:`ducktide.time._base.TimeSeriesBase`).
* :func:`create_schema_if_not_exists` interpolates a *raw* schema identifier and
  calls :func:`validate_identifier` on it itself, so the suppression on that
  line is guarded by a demonstrable, test-covered validation step.
* :func:`merge_upsert` takes column names straight from a DataFrame and quotes
  each with :func:`quote_column`, which escapes embedded quotes, so any column
  name is safe to interpolate.

Suppression comments are kept minimal and load-bearing: ``# nosec B608`` appears
only on the builders Bandit actually flags, and ``# noqa: S608`` only where Ruff
flags. Do not add either pre-emptively — Bandit reports a marker that suppresses
nothing as "nosec encountered, but no failed test", so a redundant one shows up as
gate noise rather than staying silent.

When pruning these, validate against ``make fmt`` and not only ``make security``.
The two invoke Bandit differently (the pre-commit hook passes ``--ini .bandit``
with its own exclude list) and they *disagree* about which lines trigger B608:
``make security`` reports some of the markers below as redundant while the
``make fmt`` hook fails without them.
* Path literals are pre-escaped via
  :func:`~ducktide.utils.path_validation.escape_path_for_sql`; option lists
  and query fragments are code-built, never raw user data. Row *values* are
  always bound via ``?`` placeholders by the callers.
"""

import re
from collections.abc import Collection, Mapping, Sequence

from ducktide.exceptions import ValidationError

# Valid SQL identifier (no quoting tricks, no injection); optionally qualified
# as ``schema.table`` (at most two dot-separated parts).
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_identifier(ident: str, kind: str = "SQL identifier") -> str:
    """Validate a bare SQL identifier, optionally schema-qualified.

    Accepts a single identifier (``table``) or a two-part ``schema.table``
    reference, where each part matches ``[A-Za-z_][A-Za-z0-9_]*``. This is the
    in-code enforcement of the "caller validated it" contract: any identifier
    interpolated into a builder must pass through here (or through
    :func:`quote_identifier`) first.

    Args:
        ident: The identifier to validate.
        kind: Human-readable noun used in the error message (e.g. ``"table
            name"``); lets callers surface a domain-specific message.

    Returns:
        The identifier, unchanged.

    Raises:
        ValidationError: If ``ident`` is not a valid (optionally qualified) SQL
            identifier.
    """
    parts = ident.split(".")
    if len(parts) > 2 or not all(_IDENTIFIER_RE.match(part) for part in parts):
        raise ValidationError(  # noqa: TRY003
            f"Invalid {kind} '{ident}': expected an identifier matching "
            f"[A-Za-z_][A-Za-z0-9_]*, optionally qualified as 'schema.table'"
        )
    return ident


def quote_identifier(ident: str) -> str:
    """Validate then DuckDB-quote a table or schema identifier.

    The single audited way to turn an identifier into an interpolation-safe,
    double-quoted SQL fragment. Validation happens first (:func:`validate_identifier`),
    so a quoted identifier can never carry an unvalidated name.

    Args:
        ident: The identifier to quote, optionally schema-qualified
            (e.g. ``"schema.table"``).

    Returns:
        The double-quoted identifier (e.g. ``'"schema"."table"'``).

    Raises:
        ValidationError: If ``ident`` is not a valid identifier.
    """
    validate_identifier(ident)
    if "." in ident:
        schema, name = ident.split(".", 1)
        return f'"{schema}"."{name}"'
    return f'"{ident}"'


def count_all(source: str) -> str:
    """Return ``SELECT COUNT(*) FROM <source>``.

    Args:
        source: A validated table name or table-valued expression.

    Returns:
        The SQL count statement.
    """
    return f"SELECT COUNT(*) FROM {source}"  # nosec B608  # noqa: S608


def select_all(source: str) -> str:
    """Return ``SELECT * FROM <source>``.

    Args:
        source: A validated table name or table-valued expression.

    Returns:
        The SQL select statement.
    """
    return f"SELECT * FROM {source}"  # nosec B608  # noqa: S608


def select_ordered(table: str, where: str = "", order_by: str = "") -> str:
    """Return ``SELECT * FROM <table> [WHERE <where>] [ORDER BY <order_by>]``.

    Args:
        table: A validated (optionally quoted) table name.
        where: A pre-built condition fragment *without* the leading ``WHERE``
            keyword. Empty string omits the clause.
        order_by: A pre-built ordering fragment *without* the leading
            ``ORDER BY`` keyword (e.g. ``"timestamp ASC"``). Empty string omits
            the clause.

    Returns:
        The composed SQL select statement.
    """
    sql = f"SELECT * FROM {table}"  # nosec B608  # noqa: S608
    if where:
        sql += f" WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    return sql


def insert_row(table: str, columns: str, placeholders: str) -> str:
    """Return ``INSERT INTO <table> (<columns>) VALUES (<placeholders>)``.

    Args:
        table: A validated table name.
        columns: A comma-separated list of validated column names.
        placeholders: A comma-separated list of ``?`` placeholders bound by the
            caller.

    Returns:
        The parameterized insert statement.
    """
    return f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"  # nosec B608  # noqa: S608


def insert_from_query(table: str, query: str) -> str:
    """Return ``INSERT INTO <table> <query>``.

    Args:
        table: A validated (optionally quoted) destination table name.
        query: A SQL ``SELECT`` sourcing the rows to insert.

    Returns:
        The insert-from-select statement.
    """
    return f"INSERT INTO {table} {query}"


def insert_columns_from(table: str, columns: str, source: str) -> str:
    """Return ``INSERT INTO <table> (<columns>) SELECT <columns> FROM <source>``.

    Args:
        table: A validated table name.
        columns: A comma-separated list of validated column names.
        source: A registered relation name (code-derived, not user data).

    Returns:
        The insert-from-select statement, matching columns by name.
    """
    return f"INSERT INTO {table} ({columns}) SELECT {columns} FROM {source}"  # nosec B608  # noqa: S608


def quote_column(name: str) -> str:
    """Quote a column name as a DuckDB identifier, escaping embedded quotes.

    Unlike :func:`quote_identifier` this accepts any string, since DataFrame
    columns may legitimately hold spaces or punctuation; doubling ``"`` makes
    the result a single identifier whatever the input.

    Args:
        name: A column name.

    Returns:
        The double-quoted identifier.
    """
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def merge_upsert(
    table: str,
    source: str,
    key: Sequence[str],
    columns: Sequence[str],
    *,
    update: bool,
    null_safe: Collection[str] = (),
) -> str:
    """Return a ``MERGE INTO`` that upserts ``source`` into ``table`` on ``key``.

    Every column is named explicitly: DuckDB's bare ``UPDATE``/``INSERT``
    actions match columns by position, which would silently shuffle values
    when the source's column order differs from the table's.

    Key columns in ``null_safe`` compare with ``IS NOT DISTINCT FROM`` so a
    NULL key matches a stored NULL; the others compare with ``=``. For a
    source column with no NULLs the two match exactly the same rows, but only
    ``=`` lets DuckDB skip stored row groups during the join: on a 10M-row
    table ``IS NOT DISTINCT FROM`` scans all of it, ~3.5x slower per upsert.

    Args:
        table: A validated (optionally quoted) destination table name.
        source: A registered relation name (code-derived, not user data).
        key: The key columns; must be a subset of ``columns``.
        columns: The source's columns, quoted here via :func:`quote_column`.
        update: Whether a matched row is overwritten (``True``) or left as is.
        null_safe: Key columns whose source values include NULLs.

    Returns:
        The merge statement.
    """
    on = " AND ".join(
        f"t.{quote_column(c)} {'IS NOT DISTINCT FROM' if c in null_safe else '='} s.{quote_column(c)}" for c in key
    )
    names = ", ".join(quote_column(c) for c in columns)
    values = ", ".join(f"s.{quote_column(c)}" for c in columns)
    statement = f"MERGE INTO {table} AS t USING {source} AS s ON ({on})"
    assignments = ", ".join(f"{quote_column(c)} = s.{quote_column(c)}" for c in columns if c not in key)
    if update and assignments:
        statement += f" WHEN MATCHED THEN UPDATE SET {assignments}"  # nosec B608 - columns quoted by quote_column
    return statement + f" WHEN NOT MATCHED THEN INSERT ({names}) VALUES ({values})"  # noqa: S608 - columns quoted by quote_column


# Existence of one table or view, matched on (schema, name) across every
# attached catalog. Both values are bound parameters, so nothing is interpolated.
TABLE_EXISTS = (
    "SELECT 1 FROM ("
    "SELECT schema_name, table_name FROM duckdb_tables() "
    "UNION ALL "
    "SELECT schema_name, view_name FROM duckdb_views() WHERE NOT internal"
    ") WHERE schema_name = ? AND table_name = ? LIMIT 1"
)


def ordered_by(columns: Sequence[str]) -> str:
    """Return an ``ORDER BY`` fragment sorting ascending on ``columns``, NULLs first.

    NULLs first matches Polars' sort order and ``get_timeseries_frame``.

    Args:
        columns: The columns to sort by, quoted here via :func:`quote_column`.

    Returns:
        The fragment, without the ``ORDER BY`` keyword.
    """
    return ", ".join(f"{quote_column(c)} ASC NULLS FIRST" for c in columns)


def create_temp_table_as(table: str, query: str) -> str:
    """Return ``CREATE TEMP TABLE <table> AS <query>``.

    Args:
        table: A code-derived temporary table name.
        query: A SQL ``SELECT`` producing the table's contents.

    Returns:
        The create-temp-table-as-select statement.
    """
    return f"CREATE TEMP TABLE {table} AS {query}"


def delete_all(table: str) -> str:
    """Return ``DELETE FROM <table>``.

    Args:
        table: A validated (optionally quoted) table name.

    Returns:
        The delete statement, removing every row.
    """
    return f"DELETE FROM {table}"  # nosec B608  # noqa: S608 - table is validated and quoted by the caller


def create_table_as(table: str, query: str) -> str:
    """Return ``CREATE TABLE <table> AS <query>``.

    Args:
        table: A validated (optionally quoted) table name.
        query: A SQL ``SELECT`` producing the new table's contents.

    Returns:
        The create-table-as-select statement.
    """
    return f"CREATE TABLE {table} AS {query}"


def create_table_if_not_exists(table: str, columns: Mapping[str, str]) -> str:
    """Return ``CREATE TABLE IF NOT EXISTS <table> (<column> <definition>, ...)``.

    Table and column names are validated here, because they are derived from a
    model's class and field names rather than written out by hand. The column
    definitions are SQL type and constraint text supplied by code.

    Args:
        table: The table name.
        columns: Column definitions keyed by column name, in column order.

    Returns:
        The create-table statement.

    Raises:
        ValidationError: If the table or any column name is not a valid SQL identifier.
    """
    validate_identifier(table, "table name")
    for column in columns:
        validate_identifier(column, "column name")
    body = ",\n    ".join(f"{column} {definition}" for column, definition in columns.items())
    return f"CREATE TABLE IF NOT EXISTS {table} (\n    {body}\n)"


def create_schema_if_not_exists(schema: str) -> str:
    """Return ``CREATE SCHEMA IF NOT EXISTS <schema>``.

    Args:
        schema: A validated, quote-stripped schema name.

    Returns:
        The create-schema statement.

    Raises:
        ValidationError: If ``schema`` is not a valid SQL identifier.
    """
    validate_identifier(schema)
    return f"CREATE SCHEMA IF NOT EXISTS {schema}"  # schema validated above


def drop_table_if_exists(table: str) -> str:
    """Return ``DROP TABLE IF EXISTS <table>``.

    Args:
        table: A validated (optionally quoted) table name, or a catalog-derived
            identifier.

    Returns:
        The drop-table statement.
    """
    return f"DROP TABLE IF EXISTS {table}"


def copy_select_to(columns: str, source: str, escaped_path: str, options: str) -> str:
    """Return ``COPY (SELECT <columns> FROM <source>) TO '<path>' (<options>)``.

    Args:
        columns: A comma-separated select list (``"*"`` or validated columns
            with optional casts).
        source: A validated (optionally quoted) table name.
        escaped_path: A path already escaped via
            :func:`~ducktide.utils.path_validation.escape_path_for_sql`.
        options: A comma-separated list of literal ``COPY`` options.

    Returns:
        The COPY export statement.
    """
    return f"COPY (SELECT {columns} FROM {source}) TO '{escaped_path}' ({options})"  # nosec B608  # noqa: S608


def read_csv_expr(escaped_path: str, options: str = "") -> str:
    """Return a ``read_csv_auto(...)`` table expression.

    Args:
        escaped_path: A path already escaped via
            :func:`~ducktide.utils.path_validation.escape_path_for_sql`.
        options: A comma-separated list of literal ``read_csv_auto`` options
            (``KEY=VALUE`` form). Empty string omits options.

    Returns:
        The ``read_csv_auto`` table-valued expression usable in a ``FROM``
        clause.
    """
    if options:
        return f"read_csv_auto('{escaped_path}', {options})"
    return f"read_csv_auto('{escaped_path}')"


def read_parquet_expr(escaped_path: str) -> str:
    """Return a ``read_parquet(...)`` table expression.

    Args:
        escaped_path: A path already escaped via
            :func:`~ducktide.utils.path_validation.escape_path_for_sql`.

    Returns:
        The ``read_parquet`` table-valued expression usable in a ``FROM`` clause.
    """
    return f"read_parquet('{escaped_path}')"
