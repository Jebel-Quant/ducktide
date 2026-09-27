"""Tests for the TimeSeriesModel class.

This module contains tests for the TimeSeriesModel abstract base class,
which provides time series data access functionality to domain models.

These tests exercise the model against a real in-memory
:class:`~ducktide.time.TimeSeriesDB` (the concrete
:class:`~ducktide.time.timeseries_repo.TimeSeriesRepository`) and assert on
observable behaviour — the frames returned and the rows persisted — rather than
on the internal sequence of repository calls. The model's own guard clauses
(missing ``instrument_id`` / ``table_name``) are exercised directly.
"""

from datetime import UTC, date, datetime
from typing import ClassVar

import polars as pl
import pytest

from ducktide.exceptions import ValidationError
from ducktide.model import DomainModel
from ducktide.time import TimeSeriesDB
from ducktide.time.timeseries_model import TimeSeriesModel


# Create a concrete implementation of TimeSeriesModel for testing
class MockTimeSeriesModel(DomainModel, TimeSeriesModel):
    """Concrete implementation of TimeSeriesModel for testing."""

    table_name: ClassVar[str] = "test_table"
    id: int

    @property
    def instrument_id(self) -> int:
        """Return the instrument ID for time series data.

        Returns:
            int: The ID used to identify this test instrument.
        """
        return self.id


@pytest.fixture
def repo() -> TimeSeriesDB:
    """Return a real, empty in-memory time series repository.

    Returns:
        An in-memory :class:`~ducktide.time.TimeSeriesDB` instance.
    """
    return TimeSeriesDB()


def _seed(repo: TimeSeriesDB, rows: list[dict]) -> None:
    """Persist rows directly into the repository, bypassing the model.

    Lets the query tests assert on data they seeded without depending on the
    model's ingest transformation (which has its own tests).

    Args:
        repo: The repository to seed.
        rows: Row dicts, each with ``timestamp`` (aware datetime),
            ``instrument_id`` and ``value``.
    """
    repo.ingest("test_table", pl.DataFrame(rows))


class TestTimeSeriesModel:
    """Tests for the TimeSeriesModel abstract base class."""

    def test_timeseries_model_properties(self):
        """Test the properties of TimeSeriesModel."""
        # Create an instance
        model = MockTimeSeriesModel(id=42)

        # Test properties
        assert model.table_name == "test_table"
        assert model.instrument_id == 42

    def test_get_timeseries_frame(self, repo: TimeSeriesDB):
        """Model returns the persisted rows for its own instrument only."""
        _seed(
            repo,
            [
                {"timestamp": datetime(2025, 1, 1, tzinfo=UTC), "instrument_id": 42, "value": 100.0},
                {"timestamp": datetime(2025, 1, 2, tzinfo=UTC), "instrument_id": 42, "value": 101.0},
                # A different instrument that must not leak into the result.
                {"timestamp": datetime(2025, 1, 1, tzinfo=UTC), "instrument_id": 99, "value": 999.0},
            ],
        )

        result = MockTimeSeriesModel(id=42).get_timeseries_frame(repo)

        assert result.height == 2
        assert result["instrument_id"].unique().to_list() == [42]
        assert sorted(result["value"].to_list()) == [100.0, 101.0]

    def test_get_timeseries_frame_with_date_range(self, repo: TimeSeriesDB):
        """A start/end range restricts the returned rows to that window."""
        _seed(
            repo,
            [
                {"timestamp": datetime(2025, 1, 1, tzinfo=UTC), "instrument_id": 42, "value": 1.0},
                {"timestamp": datetime(2025, 1, 15, tzinfo=UTC), "instrument_id": 42, "value": 2.0},
                {"timestamp": datetime(2025, 2, 10, tzinfo=UTC), "instrument_id": 42, "value": 3.0},
            ],
        )

        result = MockTimeSeriesModel(id=42).get_timeseries_frame(repo, start=date(2025, 1, 1), end=date(2025, 1, 31))

        # Only the two January rows fall inside the window.
        assert sorted(result["value"].to_list()) == [1.0, 2.0]

    def test_get_timeseries_frame_missing_instrument_id(self, repo: TimeSeriesDB):
        """Test get_timeseries_frame when instrument_id is None."""

        class IncompleteModel(TimeSeriesModel):
            """Model whose instrument_id is None to exercise validation."""

            @property
            def instrument_id(self):
                """Return None to simulate a missing instrument id."""
                return None

            @property
            def table_name(self):
                """Return the time series table name."""
                return "test"

        with pytest.raises(ValidationError, match="instrument_id is not set"):
            IncompleteModel().get_timeseries_frame(repo)

    def test_get_timeseries_frame_missing_table_name(self, repo: TimeSeriesDB):
        """Test get_timeseries_frame when table_name is not defined."""

        class NoTableNameModel(TimeSeriesModel):
            """Model lacking a table_name to exercise the error path."""

            @property
            def instrument_id(self):
                """Return the instrument id."""
                return 1

        with pytest.raises(AttributeError, match="NoTableNameModel must define table_name"):
            NoTableNameModel().get_timeseries_frame(repo)

    def test_table_name_attribute_error(self):
        """Test table_name property raises AttributeError if not defined."""

        class NoTableNameModel(TimeSeriesModel):
            """Model lacking a table_name to exercise the AttributeError path."""

            @property
            def instrument_id(self):
                """Return the instrument id."""
                return 1

        model = NoTableNameModel()
        with pytest.raises(AttributeError, match="'NoTableNameModel' object has no attribute 'table_name'"):
            _ = model.table_name

    def test_table_name_fallback(self):
        """Test table_name property when defined on the class."""

        class ExplicitTableNameModel(TimeSeriesModel):
            """Model that sets table_name as a class attribute."""

            table_name = "explicit_table"

            @property
            def instrument_id(self):
                """Return the instrument id."""
                return 1

        model = ExplicitTableNameModel()
        # Note: this might not even call the property if overridden by class attribute
        assert model.table_name == "explicit_table"

    def test_ingest(self, repo: TimeSeriesDB):
        """Ingesting through the model persists a row keyed by instrument_id.

        The model is expected to parse ``ts_event`` into a ``timestamp`` column
        and stamp the frame with its ``instrument_id`` before handing it to the
        repository; here we assert on what actually landed in storage.
        """
        model = MockTimeSeriesModel(id=42)

        # ts_event drives the model's timestamp parsing; no instrument_id yet.
        model.ingest(repo, pl.DataFrame({"ts_event": ["2025-01-01T09:00:00.000000+0000"], "value": [100.0]}))

        # Read the row back out of the real repository.
        stored = repo.get_timeseries_frame("test_table", instrument_id=42, start=None, end=None)

        assert stored.height == 1
        assert stored["instrument_id"][0] == 42
        assert stored["value"][0] == 100.0
        # The model added a proper datetime timestamp column.
        assert "timestamp" in stored.columns
        assert isinstance(stored.schema["timestamp"], pl.Datetime)

    def test_ingest_missing_instrument_id(self, repo: TimeSeriesDB):
        """Test ingest when instrument_id is None."""

        class IncompleteModel(TimeSeriesModel):
            """Model whose instrument_id is None to exercise validation."""

            @property
            def instrument_id(self):
                """Return None to simulate a missing instrument id."""
                return None

            @property
            def table_name(self):
                """Return the time series table name."""
                return "test"

        test_data = pl.DataFrame({"ts_event": ["2025-01-01T09:00:00.000000+0000"]})

        with pytest.raises(ValidationError, match="instrument_id is not set"):
            IncompleteModel().ingest(repo, test_data)

    def test_ingest_missing_table_name(self, repo: TimeSeriesDB):
        """Test ingest when table_name is not defined."""

        class NoTableNameModel(TimeSeriesModel):
            """Model lacking a table_name to exercise the error path."""

            @property
            def instrument_id(self):
                """Return the instrument id."""
                return 1

        test_data = pl.DataFrame({"ts_event": ["2025-01-01T09:00:00.000000+0000"]})

        with pytest.raises(AttributeError, match="NoTableNameModel must define table_name"):
            NoTableNameModel().ingest(repo, test_data)

    def test_get_timeseries_frame_with_every_resampling(self, repo: TimeSeriesDB):
        """The 'every' parameter resamples the returned frame with OHLCV aggregation."""
        # Four 30-minute OHLCV bars spanning two whole hours.
        _seed(
            repo,
            [
                {
                    "timestamp": datetime(2025, 1, 1, hour, minute, tzinfo=UTC),
                    "instrument_id": 42,
                    "open": o,
                    "high": h,
                    "low": low,
                    "close": c,
                    "volume": v,
                }
                for (hour, minute, o, h, low, c, v) in [
                    (9, 0, 100.0, 101.0, 99.0, 100.5, 1000),
                    (9, 30, 101.0, 102.0, 100.0, 101.5, 1100),
                    (10, 0, 102.0, 103.0, 101.0, 102.5, 1200),
                    (10, 30, 103.0, 104.0, 102.0, 103.5, 1300),
                ]
            ],
        )

        result = MockTimeSeriesModel(id=42).get_timeseries_frame(repo, every="1h").sort("timestamp")

        # Four 30-minute bars collapse into two hourly bars.
        assert result.height == 2
        # First hour: open of first bar, max high, min low, close of last bar, summed volume.
        assert result["open"].to_list() == [100.0, 102.0]
        assert result["high"].to_list() == [102.0, 104.0]
        assert result["low"].to_list() == [99.0, 101.0]
        assert result["close"].to_list() == [101.5, 103.5]
        assert result["volume"].to_list() == [2100, 2500]
