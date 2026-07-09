"""Centralized SQL-string composition for pre-validated identifiers.

Every helper in this module assembles a SQL statement (or fragment) by textually
interpolating **only** SQL identifiers — table, schema and column names — plus
already-escaped path literals and caller-built fragments (WHERE conditions,
option lists). DuckDB, like most engines, does not accept bound parameters for
identifiers, so these names must be interpolated as text rather than passed as
query parameters.

The safety contract is therefore pushed to the callers: every ``source`` /
``table`` / ``schema`` / ``column`` argument must already be code-derived or
validated (see :class:`jqr.database.time._base.TimeSeriesBase` — ``_validate_table_name``
and ``_quote_identifier`` — and :func:`jqr.database.utils.path_validation.escape_path_for_sql`)
and never raw user data. All row *values* continue to be bound via ``?``
placeholders by the callers.

Concentrating the interpolation here keeps the Bandit ``B608`` (and Ruff
``S608``) audit surface to this single, reviewed module instead of ~20 call
sites scattered across the database layer.
"""


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
    return f"INSERT INTO {table} {query}"  # nosec B608


def create_table_as(table: str, query: str) -> str:
    """Return ``CREATE TABLE <table> AS <query>``.

    Args:
        table: A validated (optionally quoted) table name.
        query: A SQL ``SELECT`` producing the new table's contents.

    Returns:
        The create-table-as-select statement.
    """
    return f"CREATE TABLE {table} AS {query}"  # nosec B608


def create_schema_if_not_exists(schema: str) -> str:
    """Return ``CREATE SCHEMA IF NOT EXISTS <schema>``.

    Args:
        schema: A validated, quote-stripped schema name.

    Returns:
        The create-schema statement.
    """
    return f"CREATE SCHEMA IF NOT EXISTS {schema}"  # nosec B608


def drop_table_if_exists(table: str) -> str:
    """Return ``DROP TABLE IF EXISTS <table>``.

    Args:
        table: A validated (optionally quoted) table name, or a catalog-derived
            identifier.

    Returns:
        The drop-table statement.
    """
    return f"DROP TABLE IF EXISTS {table}"  # nosec B608


def copy_select_to(columns: str, source: str, escaped_path: str, options: str) -> str:
    """Return ``COPY (SELECT <columns> FROM <source>) TO '<path>' (<options>)``.

    Args:
        columns: A comma-separated select list (``"*"`` or validated columns
            with optional casts).
        source: A validated (optionally quoted) table name.
        escaped_path: A path already escaped via
            :func:`~jqr.database.utils.path_validation.escape_path_for_sql`.
        options: A comma-separated list of literal ``COPY`` options.

    Returns:
        The COPY export statement.
    """
    return f"COPY (SELECT {columns} FROM {source}) TO '{escaped_path}' ({options})"  # nosec B608  # noqa: S608


def read_csv_expr(escaped_path: str, options: str = "") -> str:
    """Return a ``read_csv_auto(...)`` table expression.

    Args:
        escaped_path: A path already escaped via
            :func:`~jqr.database.utils.path_validation.escape_path_for_sql`.
        options: A comma-separated list of literal ``read_csv_auto`` options
            (``KEY=VALUE`` form). Empty string omits options.

    Returns:
        The ``read_csv_auto`` table-valued expression usable in a ``FROM``
        clause.
    """
    if options:
        return f"read_csv_auto('{escaped_path}', {options})"  # nosec B608
    return f"read_csv_auto('{escaped_path}')"  # nosec B608


def read_parquet_expr(escaped_path: str) -> str:
    """Return a ``read_parquet(...)`` table expression.

    Args:
        escaped_path: A path already escaped via
            :func:`~jqr.database.utils.path_validation.escape_path_for_sql`.

    Returns:
        The ``read_parquet`` table-valued expression usable in a ``FROM`` clause.
    """
    return f"read_parquet('{escaped_path}')"  # nosec B608


def select_max_per_instrument(table: str, time_col: str) -> str:
    """Return the per-instrument max-timestamp query used during ingestion.

    Produces ``SELECT instrument_id, MAX(<time_col>) as max_ts FROM <table>
    GROUP BY instrument_id``.

    Args:
        table: A validated (optionally quoted) table name.
        time_col: The configured timestamp column name.

    Returns:
        The grouped max-timestamp query.
    """
    return f"SELECT instrument_id, MAX({time_col}) as max_ts FROM {table} GROUP BY instrument_id"  # nosec B608  # noqa: S608


def select_coalesce_max(table: str, time_col: str, default: str = "1970-01-01") -> str:
    """Return the global max-timestamp query used during ingestion.

    Produces ``SELECT COALESCE(MAX(<time_col>),'<default>') FROM <table>``.

    Args:
        table: A validated (optionally quoted) table name.
        time_col: The configured timestamp column name.
        default: A fixed epoch literal used when the table is empty.

    Returns:
        The coalesced max-timestamp query.
    """
    return f"SELECT COALESCE(MAX({time_col}),'{default}') FROM {table}"  # nosec B608  # noqa: S608
