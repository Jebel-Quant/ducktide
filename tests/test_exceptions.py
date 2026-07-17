"""Tests for custom JQR exceptions."""

import pytest

from jqr.database.exceptions import (
    DatabaseConnectionError,
    DatabaseError,
    DataError,
    # InvalidMonthError,
    JQRError,
    QueryError,
    ValidationError,
)


class TestJQRError:
    """Tests for the JQRError base exception."""

    def test_jqr_error_is_base_exception(self):
        """Test that JQRError inherits from Exception."""
        assert issubclass(JQRError, Exception)

    def test_can_raise_and_catch_jqr_error(self):
        """Test that JQRError can be raised and caught."""
        with pytest.raises(JQRError, match="test error"):
            raise JQRError("test error")  # noqa: TRY003

    def test_exception_message_preservation(self):
        """Test that exception messages are preserved."""
        test_message = "This is a test error message"

        with pytest.raises(JQRError, match=test_message):
            raise JQRError(test_message)

        with pytest.raises(ValidationError, match=test_message):
            raise ValidationError(test_message)

        # with pytest.raises(InvalidMonthError, match=test_message):
        #     raise InvalidMonthError(test_message)

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

    def test_validation_error_inherits_from_jqr_error(self):
        """Test that ValidationError inherits from JQRError."""
        assert issubclass(ValidationError, JQRError)

    # def test_invalid_month_error_inherits_from_validation_error(self):
    #     """Test that InvalidMonthError inherits from ValidationError."""
    #     assert issubclass(InvalidMonthError, ValidationError)
    #     assert issubclass(InvalidMonthError, JQRError)

    def test_can_catch_validation_error_as_jqr_error(self):
        """Test that ValidationError can be caught as JQRError."""
        with pytest.raises(JQRError):
            raise ValidationError("validation failed")  # noqa: TRY003

    # def test_can_catch_invalid_month_error_as_validation_error(self):
    #     """Test that InvalidMonthError can be caught as ValidationError."""
    #     with pytest.raises(ValidationError):
    #         raise InvalidMonthError("invalid month")


class TestDatabaseError:
    """Tests for the DatabaseError exception."""

    def test_database_error_inherits_from_jqr_error(self):
        """Test that DatabaseError inherits from JQRError."""
        assert issubclass(DatabaseError, JQRError)

    def test_can_catch_database_error_as_jqr_error(self):
        """Test that DatabaseError can be caught as JQRError."""
        with pytest.raises(JQRError):
            raise DatabaseError("database error")  # noqa: TRY003


class TestDatabaseConnectionError:
    """Tests for the DatabaseConnectionError exception."""

    def test_database_connection_error_inherits_from_database_error(self):
        """Test that DatabaseConnectionError inherits from DatabaseError."""
        assert issubclass(DatabaseConnectionError, DatabaseError)
        assert issubclass(DatabaseConnectionError, JQRError)

    def test_can_catch_database_connection_error_as_database_error(self):
        """Test that DatabaseConnectionError can be caught as DatabaseError."""
        with pytest.raises(DatabaseError):
            raise DatabaseConnectionError("connection failed")  # noqa: TRY003


class TestQueryError:
    """Tests for the QueryError exception."""

    def test_query_error_inherits_from_database_error(self):
        """Test that QueryError inherits from DatabaseError."""
        assert issubclass(QueryError, DatabaseError)
        assert issubclass(QueryError, JQRError)

    def test_can_catch_query_error_as_database_error(self):
        """Test that QueryError can be caught as DatabaseError."""
        with pytest.raises(DatabaseError):
            raise QueryError("query failed")  # noqa: TRY003


class TestDataError:
    """Tests for the DataError exception."""

    def test_data_error_inherits_from_jqr_error(self):
        """Test that DataError inherits from JQRError."""
        assert issubclass(DataError, JQRError)

    def test_can_catch_data_error_as_jqr_error(self):
        """Test that DataError can be caught as JQRError."""
        with pytest.raises(JQRError):
            raise DataError("data error")  # noqa: TRY003
