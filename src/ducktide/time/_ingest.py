"""Ingestion (upsert on a series key) and compaction for the time-series interface.

This module defines :class:`TimeSeriesIngestMixin`, which creates tables on
first write and afterwards upserts: an incoming row whose key (the series
columns plus the timestamp) is already stored replaces it, and any other row is
inserted, whatever its timestamp. Re-ingesting an overlapping frame is safe,
and late-arriving rows and corrections land instead of being dropped.
``compact`` rewrites a table grouped by the same key, which speeds up reads
for a single series.
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
# Temporary table holding the sorted copy during one compaction.
_COMPACT_SCRATCH = "__ducktide_compact"


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
        self._require_writable("ingest")
        if on_conflict not in ("update", "ignore"):
            raise ValidationError(f"on_conflict must be 'update' or 'ignore', got {on_conflict!r}")  # noqa: TRY003
        # A frame assembled with pl.concat keeps one chunk per piece, and DuckDB
        # pays per chunk: a 500-row frame from 500 one-row frames ingests ~20x
        # slower. Rechunking costs ~1 ms then and nothing for a contiguous frame.
        frame = frame.rechunk()
        key_cols = self._key_columns(frame.columns, key, source="frame")
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

    def compact(self, table: str, *, key: Sequence[str] | None = None) -> None:
        """Rewrite a table grouped by series, so reads for one series skip most of it.

        DuckDB skips blocks of rows whose min/max show they cannot match a
        filter. Ingestion appends in arrival order, typically time order, which
        spreads every series across the whole table, so a read for one
        instrument has to scan nearly all of it. Compacting stores the rows
        sorted by the series key, then the timestamp; on 1M daily bars for 500
        instruments a one-instrument, one-year read drops from about 1.1 ms to
        0.75 ms.

        It is a trade-off: reads across instruments get slower, because each
        day is now spread over the whole table. A one-day cross-section goes
        from 0.3 ms to 1.4 ms (about 15x slower at 10M rows), and full-table
        aggregates from 0.65 ms to 0.9 ms. Compact only if single-series reads
        dominate. A table ingested one series at a time (e.g. through
        :meth:`TimeSeriesModel.ingest`) is already grouped, so compacting it
        gains nothing. New ingests land unsorted again, so compact
        periodically (e.g. after a day's ingest), not after every write.

        The table is emptied and refilled inside one transaction, so its
        schema, constraints, defaults and dependent views are kept, and a
        failure leaves it exactly as it was.

        Args:
            table: The table to compact. May be schema-qualified as "schema.table".
            key: The series columns to group by, as for :meth:`ingest`; the
                timestamp column is added automatically. Defaults to
                ``["instrument_id"]`` when the table has that column.

        Examples:
            >>> import polars as pl
            >>> from datetime import date
            >>> from ducktide.time import TimeSeriesDB
            >>>
            >>> ts_db = TimeSeriesDB()
            >>> day = {"instrument_id": [2, 1], "close": [20.0, 10.0]}
            >>> ts_db.ingest("prices", pl.DataFrame({**day, "timestamp": [date(2025, 1, 1)] * 2}))
            >>> ts_db.ingest("prices", pl.DataFrame({**day, "timestamp": [date(2025, 1, 2)] * 2}))
            >>> ts_db.compact("prices")
            >>> ts_db.query("SELECT instrument_id FROM prices ORDER BY rowid")["instrument_id"].to_list()
            [1, 1, 2, 2]

        Raises:
            ValidationError: If the table name is not a valid SQL identifier or
                the table lacks a key column.

        Note:
            A missing table is a no-op, as for :meth:`get_timeseries_frame`.
            DuckDB reuses the space freed by a compaction for later writes but
            does not shrink the file, which settles at a few times the data
            size.
        """
        self._validate_table_name(table)
        self._require_writable("compact")
        if not self.has_table(table):
            return
        quoted_table = self._quote_identifier(table)
        key_cols = self._key_columns(self.con.table(quoted_table).columns, key, source=f"table '{table}'")

        logger.info("Compacting '%s' on %s...", table, key_cols)
        self.con.begin()
        try:
            self.con.execute(
                sql.create_temp_table_as(
                    _COMPACT_SCRATCH, sql.select_ordered(quoted_table, order_by=sql.ordered_by(key_cols))
                )
            )
            self.con.execute(sql.delete_all(quoted_table))
            self.con.execute(sql.insert_from_query(quoted_table, sql.select_all(_COMPACT_SCRATCH)))
            self.con.execute(sql.drop_table_if_exists(_COMPACT_SCRATCH))
        except Exception:
            self.con.rollback()
            raise
        self.con.commit()

    def _key_columns(self, columns: Sequence[str], key: Sequence[str] | None, *, source: str) -> list[str]:
        """Resolve the full series key: the series columns plus the timestamp column.

        Args:
            columns: The columns available (a frame's or a table's).
            key: The caller's series columns, or None for the default.
            source: What ``columns`` belong to, for the error message.

        Returns:
            The key columns, series columns first, timestamp last.

        Raises:
            ValidationError: If the timestamp column or a key column is not in
                ``columns``, or ``key`` repeats a column.
        """
        if key is None:
            series = [_DEFAULT_SERIES_COL] if _DEFAULT_SERIES_COL in columns else []
        else:
            series = [col for col in key if col != self.time_col]
        key_cols = [*series, self.time_col]
        _check_key_columns(key_cols, columns, key=key, source=source)
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


def _check_key_columns(key_cols: list[str], columns: Sequence[str], *, key: Sequence[str] | None, source: str) -> None:
    """Check that a resolved series key has no repeats and exists in ``columns``.

    Args:
        key_cols: The resolved key columns, timestamp last.
        columns: The columns available (a frame's or a table's).
        key: The caller's series columns, for the error message.
        source: What ``columns`` belong to, for the error message.

    Raises:
        ValidationError: If ``key_cols`` repeats a column, or a key column is
            not in ``columns``.
    """
    if len(set(key_cols)) != len(key_cols):
        raise ValidationError(f"key repeats a column: {list(key or [])}")  # noqa: TRY003
    missing = [col for col in key_cols if col not in columns]
    if missing:
        raise ValidationError(f"{source} is missing key column(s): {', '.join(missing)}")  # noqa: TRY003
