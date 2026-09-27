"""Tests for the ducktide exception hierarchy."""

import pytest

from ducktide.exceptions import (
    DatabaseConnectionError,
    DatabaseError,
    DataError,
    DucktideError,
    QueryError,
    ValidationError,
)


class TestDucktideError:
    """Tests for the DucktideError base exception."""

    def test_ducktide_error_is_base_exception(self):
        """Test that DucktideError inherits from Exception."""
        assert issubclass(DucktideError, Exception)

    def test_can_raise_and_catch_ducktide_error(self):
        """Test that DucktideError can be raised and caught."""
        with pytest.raises(DucktideError, match="test error"):
            raise DucktideError("test error")  # noqa: TRY003

    def test_exception_message_preservation(self):
        """Test that exception messages are preserved."""
        test_message = "This is a test error message"

        with pytest.raises(DucktideError, match=test_message):
            raise DucktideError(test_message)

        with pytest.raises(ValidationError, match=test_message):
            raise ValidationError(test_message)

        with pytest.raises(DatabaseError, match=test_message):
            raise DatabaseError(test_message)

        with pytest.raises(DatabaseConnectionError, match=test_message):
            raise DatabaseConnectionError(test_message)

        with pytest.raises(QueryError, match=test_message):
            raise QueryError(test_message)

        with pytest.raises(DataError, match=test_message):
            raise DataError(test_message)


class TestValidationError:
    """Tests for the ValidationError exception."""

    def test_validation_error_inherits_from_ducktide_error(self):
        """Test that ValidationError inherits from DucktideError."""
        assert issubclass(ValidationError, DucktideError)

    def test_can_catch_validation_error_as_ducktide_error(self):
        """Test that ValidationError can be caught as DucktideError."""
        with pytest.raises(DucktideError):
            raise ValidationError("validation failed")  # noqa: TRY003


class TestDatabaseError:
    """Tests for the DatabaseError exception."""

    def test_database_error_inherits_from_ducktide_error(self):
        """Test that DatabaseError inherits from DucktideError."""
        assert issubclass(DatabaseError, DucktideError)

    def test_can_catch_database_error_as_ducktide_error(self):
        """Test that DatabaseError can be caught as DucktideError."""
        with pytest.raises(DucktideError):
            raise DatabaseError("database error")  # noqa: TRY003


class TestDatabaseConnectionError:
    """Tests for the DatabaseConnectionError exception."""

    def test_database_connection_error_inherits_from_database_error(self):
        """Test that DatabaseConnectionError inherits from DatabaseError."""
        assert issubclass(DatabaseConnectionError, DatabaseError)
        assert issubclass(DatabaseConnectionError, DucktideError)

    def test_can_catch_database_connection_error_as_database_error(self):
        """Test that DatabaseConnectionError can be caught as DatabaseError."""
        with pytest.raises(DatabaseError):
            raise DatabaseConnectionError("connection failed")  # noqa: TRY003


class TestQueryError:
    """Tests for the QueryError exception."""

    def test_query_error_inherits_from_database_error(self):
        """Test that QueryError inherits from DatabaseError."""
        assert issubclass(QueryError, DatabaseError)
        assert issubclass(QueryError, DucktideError)

    def test_can_catch_query_error_as_database_error(self):
        """Test that QueryError can be caught as DatabaseError."""
        with pytest.raises(DatabaseError):
            raise QueryError("query failed")  # noqa: TRY003


class TestDataError:
    """Tests for the DataError exception."""

    def test_data_error_inherits_from_ducktide_error(self):
        """Test that DataError inherits from DucktideError."""
        assert issubclass(DataError, DucktideError)

    def test_can_catch_data_error_as_ducktide_error(self):
        """Test that DataError can be caught as DucktideError."""
        with pytest.raises(DucktideError):
            raise DataError("data error")  # noqa: TRY003
