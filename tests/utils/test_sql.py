"""Tests for the jqr.database.utils.sql SQL statement builders.

The SQL builder helpers in ``jqr.database.utils.sql`` are pure string factories
that are exercised end-to-end through the table and time-series database tests
(every generated statement is executed there against DuckDB). This mirror module
exists to satisfy the 1:1 test/source layout; the behavioural coverage lives in
the callers' tests.
"""
