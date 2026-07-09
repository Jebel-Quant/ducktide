"""Time series database for high-volume append-heavy numerical data.

This module provides a separate database layer optimized for time series data,
which is fundamentally different from entity data.

Key Differences from ORM Database:
- **Time series data**: Raw numerical observations, high-volume, append-heavy
- **Entity data (ORM)**: Static metadata with identity, relationships, infrequent updates

Architecture:
    - TimeSeriesDB: Optimized for time series ingestion and querying
    - Database (ORM): Optimized for entity relationships and metadata

The separation allows:
1. Different optimization strategies for each data type
2. Independent scaling of time series vs. metadata storage
3. Clean separation of concerns

:class:`TimeSeriesDB` composes three focused mixins over
:class:`~jqr.database.time._base.TimeSeriesBase`:

- :class:`~jqr.database.time._query.TimeSeriesQueryMixin` — time-ordered reads
- :class:`~jqr.database.time._ingest.TimeSeriesIngestMixin` — append-only ingestion
- :class:`~jqr.database.time._io.TimeSeriesIOMixin` — CSV/Parquet import & export
"""

from ._ingest import TimeSeriesIngestMixin
from ._io import TimeSeriesIOMixin
from ._query import TimeSeriesQueryMixin


class TimeSeriesDB(TimeSeriesQueryMixin, TimeSeriesIngestMixin, TimeSeriesIOMixin):
    """Database for time-series data (read, ingest & import/export layer).

    This class provides optimized operations for time series data, which is
    fundamentally different from entity data. Time series data is:
    - High-volume numerical observations
    - Append-heavy with frequent updates
    - Queried by time ranges and instrument IDs
    - Not entities with identity or relationships

    This implements the TimeSeriesRepository protocol for use with domain models.
    The connection ownership and shared helpers live in
    :class:`~jqr.database.time._base.TimeSeriesBase`; the read, ingest and
    import/export behaviours are contributed by the composed mixins.

    Example:
        # Separate databases for different concerns
        # metadata_db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})
        # ts_db = TimeSeriesDB()
        # ts_db.ingest(Foo.table_name, price_data)
        # df = foo.get_timeseries_frame(ts_db)
    """
