"""Tests for the ducktide.utils.sql SQL statement builders.

Most SQL builder helpers in ``ducktide.utils.sql`` are pure string factories
exercised end-to-end through the table and time-series database tests (every
generated statement is executed there against DuckDB). The behavioural coverage
for those lives in the callers' tests.

This module covers the *identifier-validation* contract that guards the
interpolation sites: ``validate_identifier`` / ``quote_identifier`` and the three
builders that validate a raw column/schema identifier in code.

``sql`` exposes module-level functions and no classes, so these tests are
module-level functions too — grouping them under ``Test*`` classes would read as a
mirror of source classes that do not exist (see ``[tool.check_test_layout]``).
"""

import pytest

from ducktide.exceptions import ValidationError
from ducktide.utils import sql

# ── validate_identifier: the single audited identifier validator ──────────────


@pytest.mark.parametrize("ident", ["timestamp", "ts", "_x", "a1", "schema.table", "s._t2"])
def test_validate_identifier_accepts_valid_identifiers(ident: str) -> None:
    """Bare and two-part schema-qualified identifiers pass unchanged."""
    assert sql.validate_identifier(ident) == ident


@pytest.mark.parametrize(
    "ident",
    [
        "ts; DROP TABLE x",  # statement injection
        "1abc",  # leading digit
        "a.b.c",  # more than two parts
        "col--",  # comment injection
        "a b",  # whitespace
        'a"b',  # embedded quote
        "",  # empty
        "*",  # star is not an identifier
    ],
)
def test_validate_identifier_rejects_invalid_identifiers(ident: str) -> None:
    """Anything that is not a plain (optionally qualified) identifier raises."""
    with pytest.raises(ValidationError):
        sql.validate_identifier(ident)


# ── quote_identifier: validation-then-quoting, the only sanctioned path ───────


def test_quote_identifier_quotes_bare_identifier() -> None:
    """A bare identifier becomes a double-quoted fragment."""
    assert sql.quote_identifier("tbl") == '"tbl"'


def test_quote_identifier_quotes_schema_qualified_identifier() -> None:
    """A schema-qualified identifier quotes each part."""
    assert sql.quote_identifier("s.t") == '"s"."t"'


def test_quote_identifier_rejects_invalid_identifier_before_quoting() -> None:
    """An invalid identifier cannot be quoted — validation happens first."""
    with pytest.raises(ValidationError):
        sql.quote_identifier('t"; DROP TABLE x')


# ── the builders that interpolate a raw column/schema identifier ──────────────


def test_create_schema_rejects_bad_schema() -> None:
    """A malicious ``schema`` is rejected before interpolation."""
    with pytest.raises(ValidationError):
        sql.create_schema_if_not_exists("s; DROP SCHEMA y")


def test_valid_schema_builder_roundtrip() -> None:
    """Valid identifiers still produce the expected SQL text."""
    assert sql.create_schema_if_not_exists("analytics") == "CREATE SCHEMA IF NOT EXISTS analytics"


def test_create_table_if_not_exists_builds_columns_in_order() -> None:
    """Column definitions are emitted in mapping order."""
    statement = sql.create_table_if_not_exists("sensor", {"id": "BIGINT PRIMARY KEY", "name": "VARCHAR NOT NULL"})
    assert statement == "CREATE TABLE IF NOT EXISTS sensor (\n    id BIGINT PRIMARY KEY,\n    name VARCHAR NOT NULL\n)"


def test_create_table_if_not_exists_rejects_bad_identifiers() -> None:
    """Table and column names are validated, since they come from class and field names."""
    with pytest.raises(ValidationError, match="table name"):
        sql.create_table_if_not_exists("t; DROP TABLE x", {"id": "BIGINT"})
    with pytest.raises(ValidationError, match="column name"):
        sql.create_table_if_not_exists("t", {"id); DROP TABLE x; --": "BIGINT"})


def test_quote_column_escapes_embedded_quotes() -> None:
    """Any column name becomes exactly one quoted identifier."""
    assert sql.quote_column("close") == '"close"'
    assert sql.quote_column('a"; DROP TABLE x --') == '"a""; DROP TABLE x --"'


def test_merge_upsert_names_every_column() -> None:
    """Matched rows update the non-key columns; unmatched rows insert all columns by name."""
    statement = sql.merge_upsert('"prices"', "src", ["id", "ts"], ["close", "ts", "id"], update=True)
    assert statement == (
        'MERGE INTO "prices" AS t USING src AS s ON (t."id" = s."id" AND t."ts" = s."ts") '
        'WHEN MATCHED THEN UPDATE SET "close" = s."close" '
        'WHEN NOT MATCHED THEN INSERT ("close", "ts", "id") VALUES (s."close", s."ts", s."id")'
    )


def test_merge_upsert_without_update_only_inserts() -> None:
    """With update=False, or no non-key columns, matched rows are left alone."""
    assert "WHEN MATCHED" not in sql.merge_upsert("t", "s", ["ts"], ["ts", "v"], update=False)
    assert "WHEN MATCHED" not in sql.merge_upsert("t", "s", ["ts"], ["ts"], update=True)


def test_merge_upsert_null_safe_keys() -> None:
    """Only the key columns named in null_safe compare with IS NOT DISTINCT FROM."""
    statement = sql.merge_upsert("t", "s", ["id", "ts"], ["id", "ts", "v"], update=True, null_safe=["id"])
    assert 'ON (t."id" IS NOT DISTINCT FROM s."id" AND t."ts" = s."ts")' in statement


def test_ordered_by_quotes_columns_and_puts_nulls_first() -> None:
    """Each sort column is quoted and ascending with NULLs first, matching get_timeseries_frame."""
    assert (
        sql.ordered_by(["instrument_id", 'odd"name']) == '"instrument_id" ASC NULLS FIRST, "odd""name" ASC NULLS FIRST'
    )
