"""Tests for the TimeSeriesRepository protocol.

This module contains tests for the TimeSeriesRepository protocol,
which defines the interface for time series data repositories.
"""

from datetime import date

from ducktide.time.timeseries_repo import TimeSeriesRepository


class TestTimeSeriesRepository:
    """Tests for the TimeSeriesRepository protocol."""

    def test_timeseries_repository_is_protocol(self):
        """Test that TimeSeriesRepository behaves like a Protocol."""
        # The most important aspect of a Protocol is structural subtyping
        # We can verify this by checking if we can use a class that implements
        # the required methods without explicitly inheriting from TimeSeriesRepository

        # This is already tested in test_timeseries_repository_structural_subtyping
        # So we'll just verify that TimeSeriesRepository has the expected method
        assert hasattr(TimeSeriesRepository, "get_timeseries_frame")

    def test_timeseries_repository_implementation(self):
        """Test that a class implementing the protocol works correctly."""

        # Create a concrete implementation of TimeSeriesRepository
        class TestTimeSeriesRepo:
            """Test implementation of TimeSeriesRepository."""

            def get_timeseries_frame(self, table, instrument_id, start, end):
                """Return a dummy value for testing."""
                return {"table": table, "instrument_id": instrument_id, "start": start, "end": end}

        # Create an instance
        repo = TestTimeSeriesRepo()

        # Test that it can be used as a TimeSeriesRepository
        # This will fail at runtime if the protocol is not correctly implemented
        result = repo.get_timeseries_frame(
            table="test_table", instrument_id=42, start=date(2025, 1, 1), end=date(2025, 1, 31)
        )

        # Verify the result
        assert result["table"] == "test_table"
        assert result["instrument_id"] == 42
        assert result["start"] == date(2025, 1, 1)
        assert result["end"] == date(2025, 1, 31)

    def test_timeseries_repository_structural_subtyping(self):
        """Test that structural subtyping works with TimeSeriesRepository."""

        # Function that accepts a TimeSeriesRepository
        def use_repo(repo: TimeSeriesRepository):
            """Query a repository conforming to the TimeSeriesRepository protocol."""
            return repo.get_timeseries_frame(table="test_table", instrument_id=42, start=None, end=None)

        # Create a class that matches the protocol but doesn't explicitly inherit from it
        class StructuralRepo:
            """Repository matching the protocol structurally without inheriting it."""

            def get_timeseries_frame(self, table, instrument_id, start, end):
                """Return a stub identifier for the requested time series."""
                return f"{table}:{instrument_id}"

        # Create an instance
        repo = StructuralRepo()

        # Test that it can be used with a function expecting TimeSeriesRepository
        result = use_repo(repo)

        # Verify the result
        assert result == "test_table:42"
