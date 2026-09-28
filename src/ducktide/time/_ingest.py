"""Ingestion (upsert on a series key) for the time-series interface.

This module defines :class:`TimeSeriesIngestMixin`, which creates tables on
first write and afterwards upserts: an incoming row whose key (the series
columns plus the timestamp) is already stored replaces it, and any other row is
inserted, whatever its timestamp. Re-ingesting an overlapping frame is safe,
and late-arriving rows and corrections land instead of being dropped.
"""

import logging
from collections.abc import Sequence
from typing import Literal

import polars as pl

from ..exceptions import ValidationError
from ..utils import sql
from ._base import TimeSeriesBase

logger = logging.getLogger(__name__)

# The series column used when ``ingest`` is not given a key and the frame has it.
_DEFAULT_SERIES_COL = "instrument_id"
# Name under which the incoming batch is registered for one MERGE.
_INGEST_SOURCE = "__ducktide_ingest"


class TimeSeriesIngestMixin(TimeSeriesBase):
    """Table creation and keyed upsert ingestion for time-series data."""

    def ingest(
        self,
        table: str,
        frame: pl.DataFrame,
        *,
        key: Sequence[str] | None = None,
        on_conflict: Literal["update", "ignore"] = "update",
    ) -> None:
        """Ingest time series data from a Polars DataFrame into a table.

        Creates the table from the frame's schema if it doesn't exist.
        Otherwise the frame is upserted on its key: the series columns plus the
        timestamp column. A row whose key is already stored replaces the stored
        row (or is skipped, with ``on_conflict="ignore"``); every other row is
        inserted, including rows older than what is already stored.

        Args:
            table: Name of the destination table. May be schema-qualified as
                "schema.table". If a schema is specified and doesn't exist, it
                will be created automatically.
            frame: Polars DataFrame containing the data to ingest. Must include
                the timestamp column (default name: "timestamp") and the key
                columns. Columns are matched to the table by name.
            key: Columns identifying one series, e.g. ``["instrument_id"]`` or
                ``["base", "quote"]``; the timestamp column is added
                automatically. Defaults to ``["instrument_id"]`` when the frame
                has that column, else to no series columns (one series).
            on_conflict: ``"update"`` (default) overwrites a stored row with the
                incoming one, so corrections land; ``"ignore"`` keeps the stored
                row and only inserts rows with new keys.

        Examples:
            >>> import polars as pl
            >>> from ducktide.time import TimeSeriesDB
            >>> from datetime import datetime
            >>>
            >>> ts_db = TimeSeriesDB()
            >>> bar = {"timestamp": [datetime(2025, 1, 1, 9, 0)], "instrument_id": [100]}
            >>>
            >>> ts_db.ingest("future", pl.DataFrame({**bar, "close": [103.0]}))
            >>> ts_db.ingest("future", pl.DataFrame({**bar, "close": [104.0]}))  # a correction
            >>> ts_db.get_timeseries_frame("future")["close"].to_list()
            [104.0]
            >>>
            >>> # Schema-qualified tables and custom keys work the same way
            >>> fx = pl.DataFrame(
            ...     {"timestamp": [datetime(2025, 1, 1)], "base": ["EUR"], "quote": ["USD"], "rate": [1.1]}
            ... )
            >>> ts_db.ingest("market_data.fx", fx, key=["base", "quote"])

        Raises:
            ValidationError: If the table name is not a valid SQL identifier, a
                key or timestamp column is missing from the frame, or
                ``on_conflict`` is not ``"update"`` or ``"ignore"``.

        Note:
            Within one frame, the last row for a key wins. A NULL key value
            matches a stored NULL instead of inserting a duplicate.
        """
        self._validate_table_name(table)
        if on_conflict not in ("update", "ignore"):
            raise ValidationError(f"on_conflict must be 'update' or 'ignore', got {on_conflict!r}")  # noqa: TRY003
        # A frame assembled with pl.concat keeps one chunk per piece, and DuckDB
        # pays per chunk: a 500-row frame from 500 one-row frames ingests ~20x
        # slower. Rechunking costs ~1 ms then and nothing for a contiguous frame.
        frame = frame.rechunk()
        key_cols = self._key_columns(frame, key)
        # Checking for duplicate keys costs a fifth of removing them, and most
        # frames have none, so only pay for the order-preserving unique() then.
        if frame.select(key_cols).is_duplicated().any():
            frame = frame.unique(subset=key_cols, keep="last", maintain_order=True)
        self._ensure_schema(table)

        if not self.has_table(table):
            self._create_table_from_frame(table, frame)
            return
        if frame.height == 0:
            return

        logger.info("Upserting %d rows into '%s' on %s...", frame.height, table, key_cols)
        statement = sql.merge_upsert(
            self._quote_identifier(table),
            _INGEST_SOURCE,
            key_cols,
            frame.columns,
            update=on_conflict == "update",
            null_safe=[col for col in key_cols if frame[col].null_count()],
        )
        self.con.register(_INGEST_SOURCE, frame)
        try:
            self.con.execute(statement)
        finally:
            self.con.unregister(_INGEST_SOURCE)

    def _key_columns(self, frame: pl.DataFrame, key: Sequence[str] | None) -> list[str]:
        """Resolve the full upsert key: the series columns plus the timestamp column.

        Args:
            frame: The incoming DataFrame.
            key: The caller's series columns, or None for the default.

        Returns:
            The key columns, series columns first, timestamp last.

        Raises:
            ValidationError: If the timestamp column or a key column is missing
                from the frame, or ``key`` repeats a column.
        """
        if key is None:
            series = [_DEFAULT_SERIES_COL] if _DEFAULT_SERIES_COL in frame.columns else []
        else:
            series = [col for col in key if col != self.time_col]
        key_cols = [*series, self.time_col]
        if len(set(key_cols)) != len(key_cols):
            raise ValidationError(f"key repeats a column: {list(key or [])}")  # noqa: TRY003
        missing = [col for col in key_cols if col not in frame.columns]
        if missing:
            raise ValidationError(f"frame is missing key column(s): {', '.join(missing)}")  # noqa: TRY003
        return key_cols

    def _ensure_schema(self, table: str) -> None:
        """Create the table's schema if the name is schema-qualified.

        Args:
            table: The (possibly schema-qualified) destination table name.

        Note:
            ``table`` is validated by :meth:`_validate_table_name`, and the
            schema part is further stripped of quote characters by
            ``_quote_unquoted``; not user data.
        """
        if "." in table:
            schema, _ = table.split(".", 1)
            self.con.execute(sql.create_schema_if_not_exists(self._quote_unquoted(schema)))

    def _create_table_from_frame(self, table: str, frame: pl.DataFrame) -> None:
        """Create a new table from a Polars DataFrame using DuckDB inference.

        Args:
            table: The destination table name.
            frame: The DataFrame whose schema and rows seed the new table.

        Note:
            ``quoted_table`` is produced by ``_quote_identifier``; data rows come
            from the registered ``temp_ingest`` relation, not string
            interpolation.
        """
        self.con.register("temp_ingest", frame)
        quoted_table = self._quote_identifier(table)
        self.con.execute(sql.create_table_as(quoted_table, sql.select_all("temp_ingest")))
        self.con.unregister("temp_ingest")
