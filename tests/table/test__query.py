"""Tests for the QueryMixin class in jqr.database.table._query."""

from __future__ import annotations

from datetime import date

import pytest

from jqr.database.exceptions import ValidationError

from .conftest import MockModel


class TestQueryMixin:
    """Test Table query methods, keyword filters, and properties."""

    def test_select_no_where(self, table):
        """Test select without a where clause (should return all rows)."""
        table.insert(MockModel(1, "a"), MockModel(2, "b"))
        results = table.select()
        assert len(results) == 2

    def test_get_by_success(self, table):
        """Test get_by with a key/value pair that exists."""
        table.insert(MockModel(1, "target"))
        retrieved = table.get_by("name", "target")
        assert retrieved.id == 1
        assert retrieved.name == "target"

    def test_get_by_not_found(self, table):
        """Test get_by with a key/value pair that doesn't exist (should raise KeyError)."""
        with pytest.raises(KeyError, match="No row found for name = missing"):
            table.get_by("name", "missing")

    def test_get_by_unknown_column(self, table):
        """Test get_by with a column that is not part of the table (should raise ValidationError)."""
        with pytest.raises(ValidationError, match="Unknown column 'no_such_column'"):
            table.get_by("no_such_column", 1)

    def test_get_by_rejects_sql_injection_in_key(self, table):
        """Test that a malicious key is rejected before reaching SQL."""
        table.insert(MockModel(1, "target"))
        with pytest.raises(ValidationError, match="Unknown column"):
            table.get_by("1=1; DROP TABLE mock_table; --", "x")
        # Table must still be intact
        assert len(table.select()) == 1

    def test_get_none_id(self, table):
        """Test get with a None ID (should return None)."""
        assert table.get(None) is None

    def test_get_not_found(self, table):
        """Test get with an ID that doesn't exist (should raise KeyError)."""
        with pytest.raises(KeyError, match="No row found for id = 999"):
            table.get(999)

    def test_getitem_success(self, table):
        """Test __getitem__ with a key that exists."""
        table.insert(MockModel(1, "test"))
        retrieved = table[1]
        assert retrieved.id == 1
        assert retrieved.name == "test"

    def test_getitem_not_found(self, table):
        """Test __getitem__ with a key that doesn't exist (should raise KeyError)."""
        with pytest.raises(KeyError, match="No row found for id = 999"):
            _ = table[999]

    def test_select_equality_filter(self, table):
        """Test select with a simple equality keyword filter."""
        table.insert(MockModel(1, "apple"), MockModel(2, "banana"))
        results = table.select(name="apple")
        assert len(results) == 1
        assert results[0].id == 1

    def test_select_multiple_filters_combined_with_and(self, table):
        """Test that multiple keyword filters are ANDed together."""
        table.insert(MockModel(1, "apple"), MockModel(2, "apple"), MockModel(3, "banana"))
        results = table.select(name="apple", id=2)
        assert len(results) == 1
        assert results[0].id == 2

    def test_select_before_suffix(self, table):
        """Test the _before suffix translates to a < comparison."""
        table.insert(
            MockModel(1, "a", date(2025, 3, 20)),
            MockModel(2, "b", date(2026, 3, 20)),
        )
        results = table.select(expiry_before=date(2026, 1, 1))
        assert [r.id for r in results] == [1]

    def test_select_after_suffix(self, table):
        """Test the _after suffix translates to a > comparison."""
        table.insert(
            MockModel(1, "a", date(2025, 3, 20)),
            MockModel(2, "b", date(2026, 3, 20)),
        )
        results = table.select(expiry_after=date(2026, 1, 1))
        assert [r.id for r in results] == [2]

    def test_select_inclusive_suffixes(self, table):
        """Test the _at_or_before and _at_or_after suffixes include the boundary."""
        table.insert(
            MockModel(1, "a", date(2025, 3, 20)),
            MockModel(2, "b", date(2026, 3, 20)),
        )
        assert len(table.select(expiry_at_or_before=date(2025, 3, 20))) == 1
        assert len(table.select(expiry_at_or_after=date(2025, 3, 20))) == 2

    def test_select_none_filters_for_null(self, table):
        """Test that passing None for an equality filter matches SQL NULL."""
        table.insert(MockModel(1, "a", date(2025, 3, 20)), MockModel(2, "b", None))
        results = table.select(expiry=None)
        assert [r.id for r in results] == [2]

    def test_select_unknown_filter_raises(self, table):
        """Test that an unknown filter name raises ValidationError."""
        with pytest.raises(ValidationError, match="Unknown filter 'no_such_column'"):
            table.select(no_such_column=1)

    def test_select_unknown_suffix_base_raises(self, table):
        """Test that a comparison suffix on an unknown column raises ValidationError."""
        with pytest.raises(ValidationError, match="Unknown filter 'no_such_column_before'"):
            table.select(no_such_column_before=1)

    def test_select_rejects_sql_injection_in_filter_name(self, table):
        """Test that a malicious filter name is rejected before reaching SQL."""
        table.insert(MockModel(1, "target"))
        injection = {"name = name; DROP TABLE mock_table; --": "x"}
        with pytest.raises(ValidationError, match="Unknown filter"):
            table.select(**injection)
        assert len(table.select()) == 1

    def test_select_filters_combined_with_raw_clause(self, table):
        """Test combining keyword filters with a raw WHERE clause and ORDER BY."""
        table.insert(MockModel(1, "apple"), MockModel(2, "apple"), MockModel(3, "banana"))
        results = table.select("id > ? ORDER BY id DESC", [0], name="apple")
        assert [r.id for r in results] == [2, 1]

    def test_empty_len_bool(self, table):
        """Test empty property, __len__, and __bool__."""
        assert table.empty is True
        assert len(table) == 0
        assert bool(table) is False

        table.insert(MockModel(1, "test"))
        assert table.empty is False
        assert len(table) == 1
        assert bool(table) is True

    def test_exists_after_drop(self, table):
        """Test exists, empty, and __len__ after dropping the table."""
        assert table.exists is True
        table.connection.execute("DROP TABLE mock_table")
        assert table.exists is False
        assert table.empty is True
        assert len(table) == 0

    def test_iter(self, table):
        """Test iterating over the table."""
        objs = [MockModel(1, "a"), MockModel(2, "b")]
        table.insert(*objs)
        items = list(table)
        assert len(items) == 2
        assert items[0].id == 1
        assert items[1].id == 2
