"""Tests for the TimeSeriesModel class.

This module contains tests for the TimeSeriesModel abstract base class,
which provides time series data access functionality to domain models.
"""

from datetime import date
from typing import ClassVar
from unittest.mock import MagicMock

import polars as pl
import pytest

from jqr.database.exceptions import ValidationError
from jqr.database.orm.base import DomainModel
from jqr.database.time.timeseries_model import TimeSeriesModel
from jqr.database.time.timeseries_repo import TimeSeriesRepository


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


class TestTimeSeriesModel:
    """Tests for the TimeSeriesModel abstract base class."""

    def test_timeseries_model_properties(self):
        """Test the properties of TimeSeriesModel."""
        # Create an instance
        model = MockTimeSeriesModel(id=42)

        # Test properties
        assert model.table_name == "test_table"
        assert model.instrument_id == 42

    def test_get_timeseries_frame(self):
        """Test the get_timeseries_frame method."""
        # Create a mock repository
        mock_repo = MagicMock(spec=TimeSeriesRepository)

        # Create test data
        test_data = pl.DataFrame({"timestamp": [date(2025, 1, 1), date(2025, 1, 2)], "value": [100.0, 101.0]})

        # Configure the mock to return test data
        mock_repo.get_timeseries_frame.return_value = test_data

        # Create a model instance
        model = MockTimeSeriesModel(id=42)

        # Test with default parameters
        result = model.get_timeseries_frame(mock_repo)

        # Verify the repository was called with correct parameters
        # Note: 'every' is handled locally in the model, not passed to repo
        mock_repo.get_timeseries_frame.assert_called_once_with(
            table="test_table", instrument_id=42, start=None, end=None, timezone=None
        )

        # Verify the result
        assert result is test_data

    def test_get_timeseries_frame_with_date_range(self):
        """Test the get_timeseries_frame method with date range parameters."""
        # Create a mock repository
        mock_repo = MagicMock(spec=TimeSeriesRepository)

        # Create test data
        test_data = pl.DataFrame({"timestamp": [date(2025, 1, 1), date(2025, 1, 2)], "value": [100.0, 101.0]})

        # Configure the mock to return test data
        mock_repo.get_timeseries_frame.return_value = test_data

        # Create a model instance
        model = MockTimeSeriesModel(id=42)

        # Test with date range
        start_date = date(2025, 1, 1)
        end_date = date(2025, 1, 31)

        result = model.get_timeseries_frame(mock_repo, start=start_date, end=end_date)

        # Verify the repository was called with correct parameters
        mock_repo.get_timeseries_frame.assert_called_once_with(
            table="test_table", instrument_id=42, start=start_date, end=end_date, timezone=None
        )

        # Verify the result
        assert result is test_data

    def test_get_timeseries_frame_missing_instrument_id(self):
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

        model = IncompleteModel()
        mock_repo = MagicMock(spec=TimeSeriesRepository)

        with pytest.raises(ValidationError, match="instrument_id is not set"):
            model.get_timeseries_frame(mock_repo)

    def test_get_timeseries_frame_missing_table_name(self):
        """Test get_timeseries_frame when table_name is not defined."""

        class NoTableNameModel(TimeSeriesModel):
            """Model lacking a table_name to exercise the error path."""

            @property
            def instrument_id(self):
                """Return the instrument id."""
                return 1

        model = NoTableNameModel()
        mock_repo = MagicMock(spec=TimeSeriesRepository)

        with pytest.raises(AttributeError, match="NoTableNameModel must define table_name"):
            model.get_timeseries_frame(mock_repo)

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

    def test_ingest(self):
        """Test the ingest method of TimeSeriesModel."""
        # Create a mock repository
        mock_repo = MagicMock(spec=TimeSeriesRepository)

        # Create a model instance
        model = MockTimeSeriesModel(id=42)

        # Create test data without instrument_id, using 'ts_event' as expected by ingest
        test_data = pl.DataFrame({"ts_event": ["2025-01-01T09:00:00.000000+0000"], "value": [100.0]})

        # Test ingestion
        model.ingest(mock_repo, test_data)

        # Verify the repository was called
        # The frame passed to repo.ingest should have instrument_id=42 added
        assert mock_repo.ingest.call_count == 1
        call_args = mock_repo.ingest.call_args
        assert call_args.kwargs["table"] == "test_table"
        ingested_frame = call_args.kwargs["frame"]

        assert "instrument_id" in ingested_frame.columns
        assert ingested_frame["instrument_id"][0] == 42
        assert "timestamp" in ingested_frame.columns
        assert ingested_frame["value"][0] == 100.0

    def test_ingest_missing_instrument_id(self):
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

        model = IncompleteModel()
        mock_repo = MagicMock(spec=TimeSeriesRepository)
        test_data = pl.DataFrame({"ts_event": ["2025-01-01T09:00:00.000000+0000"]})

        with pytest.raises(ValidationError, match="instrument_id is not set"):
            model.ingest(mock_repo, test_data)

    def test_ingest_missing_table_name(self):
        """Test ingest when table_name is not defined."""

        class NoTableNameModel(TimeSeriesModel):
            """Model lacking a table_name to exercise the error path."""

            @property
            def instrument_id(self):
                """Return the instrument id."""
                return 1

        model = NoTableNameModel()
        mock_repo = MagicMock(spec=TimeSeriesRepository)
        test_data = pl.DataFrame({"ts_event": ["2025-01-01T09:00:00.000000+0000"]})

        with pytest.raises(AttributeError, match="NoTableNameModel must define table_name"):
            model.ingest(mock_repo, test_data)

    def test_get_timeseries_frame_with_every_resampling(self):
        """Test get_timeseries_frame with the 'every' resampling parameter."""
        from datetime import datetime

        # Create a mock repository
        mock_repo = MagicMock(spec=TimeSeriesRepository)

        # Create test OHLCV data with datetime for group_by_dynamic
        test_data = pl.DataFrame(
            {
                "timestamp": [
                    datetime(2025, 1, 1, 9, 0),
                    datetime(2025, 1, 1, 9, 30),
                    datetime(2025, 1, 1, 10, 0),
                    datetime(2025, 1, 1, 10, 30),
                ],
                "open": [100.0, 101.0, 102.0, 103.0],
                "high": [101.0, 102.0, 103.0, 104.0],
                "low": [99.0, 100.0, 101.0, 102.0],
                "close": [100.5, 101.5, 102.5, 103.5],
                "volume": [1000, 1100, 1200, 1300],
            }
        )

        # Configure the mock to return test data
        mock_repo.get_timeseries_frame.return_value = test_data

        # Create a model instance
        model = MockTimeSeriesModel(id=42)

        # Test with 'every' parameter for resampling to 1-hour bars
        result = model.get_timeseries_frame(mock_repo, every="1h")

        # Verify the repository was called (without 'every' - it's handled locally)
        mock_repo.get_timeseries_frame.assert_called_once_with(
            table="test_table", instrument_id=42, start=None, end=None, timezone=None
        )

        # Verify the result is resampled (2 hourly bars from 4 30-min bars)
        assert result.height == 2
        # Verify OHLCV aggregation
        assert "open" in result.columns
        assert "high" in result.columns
        assert "low" in result.columns
        assert "close" in result.columns
        assert "volume" in result.columns
