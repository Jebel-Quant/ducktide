"""Tests for the jqr.database.utils.sql SQL statement builders.

Most SQL builder helpers in ``jqr.database.utils.sql`` are pure string factories
exercised end-to-end through the table and time-series database tests (every
generated statement is executed there against DuckDB). The behavioural coverage
for those lives in the callers' tests.

This module covers the *identifier-validation* contract that guards the
``# nosec B608`` interpolation sites: ``validate_identifier`` / ``quote_identifier``
and the three builders that validate a raw column/schema identifier in code.
"""

import pytest

from jqr.database.exceptions import ValidationError
from jqr.database.utils import sql


class TestValidateIdentifier:
    """The single audited identifier validator."""

    @pytest.mark.parametrize("ident", ["timestamp", "ts", "_x", "a1", "schema.table", "s._t2"])
    def test_accepts_valid_identifiers(self, ident: str) -> None:
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
    def test_rejects_invalid_identifiers(self, ident: str) -> None:
        """Anything that is not a plain (optionally qualified) identifier raises."""
        with pytest.raises(ValidationError):
            sql.validate_identifier(ident)


class TestQuoteIdentifier:
    """Validation-then-quoting is the only sanctioned interpolation path."""

    def test_quotes_bare_identifier(self) -> None:
        """A bare identifier becomes a double-quoted fragment."""
        assert sql.quote_identifier("tbl") == '"tbl"'

    def test_quotes_schema_qualified_identifier(self) -> None:
        """A schema-qualified identifier quotes each part."""
        assert sql.quote_identifier("s.t") == '"s"."t"'

    def test_rejects_invalid_identifier_before_quoting(self) -> None:
        """An invalid identifier cannot be quoted — validation happens first."""
        with pytest.raises(ValidationError):
            sql.quote_identifier('t"; DROP TABLE x')


class TestBuilderIdentifierGuards:
    """The builders that interpolate a raw column/schema identifier validate it."""

    def test_select_max_per_instrument_rejects_bad_time_col(self) -> None:
        """A malicious ``time_col`` is rejected before interpolation."""
        with pytest.raises(ValidationError):
            sql.select_max_per_instrument("t", "ts) ; DROP TABLE x --")

    def test_select_coalesce_max_rejects_bad_time_col(self) -> None:
        """A malicious ``time_col`` is rejected before interpolation."""
        with pytest.raises(ValidationError):
            sql.select_coalesce_max("t", "ts) ; DROP TABLE x --")

    def test_create_schema_rejects_bad_schema(self) -> None:
        """A malicious ``schema`` is rejected before interpolation."""
        with pytest.raises(ValidationError):
            sql.create_schema_if_not_exists("s; DROP SCHEMA y")

    def test_valid_time_col_builders_roundtrip(self) -> None:
        """Valid identifiers still produce the expected SQL text."""
        assert sql.select_max_per_instrument("tbl", "ts").startswith("SELECT instrument_id, MAX(ts)")
        assert sql.select_coalesce_max("tbl", "ts").startswith("SELECT COALESCE(MAX(ts)")
        assert sql.create_schema_if_not_exists("analytics") == "CREATE SCHEMA IF NOT EXISTS analytics"
