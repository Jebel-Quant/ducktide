# ducktide

Immutable Pydantic models and append-fast time series on DuckDB + Polars.

ducktide is a small persistence layer with two halves:

- **Entity tables**: frozen Pydantic models persisted through repositories
  (`DB` + `Table`). Models carry no `save()`/`find()`/`delete()` methods;
  all reads and writes go through the table, so domain objects stay plain values.
- **Time series**: `TimeSeriesDB`, an append-only store for high-volume
  numerical data (prices, volumes, sensor readings). Ingestion only appends rows
  newer than what is already stored, per instrument, so re-ingesting an
  overlapping frame is safe.

Both run on DuckDB (in-memory or a single file) and hand data back as Polars
DataFrames. There is no SQLAlchemy and no server.

## Install

```bash
pip install ducktide
```

Requires Python 3.11+.

## Entity tables

Define a domain model and its table mapping:

```python
from functools import partial
from typing import ClassVar

from ducktide import DB, Table
from ducktide.orm import DomainModel, ORMModel


class Sensor(DomainModel):
    table_name: ClassVar[str] = "sensor"

    id: int
    name: str
    site: str


class SensorORM(ORMModel, Sensor):
    _table_name: ClassVar[str] = "sensor"
    _domain_model: ClassVar[type] = Sensor
    _primary_key: ClassVar[str] = "id"
    _schema: ClassVar[dict[str, str]] = {
        "id": "INTEGER PRIMARY KEY",
        "name": "TEXT NOT NULL",
        "site": "TEXT NOT NULL",
    }


db = DB(tables_map={"sensor": partial(Table, model_class=SensorORM)})  # or db_path="sensors.duckdb"

db.sensor.bulk_insert(
    [
        Sensor(id=1, name="north", site="berlin"),
        Sensor(id=2, name="south", site="zurich"),
    ]
)

db.sensor.select(site="berlin")  # [SensorORM(id=1, name='north', site='berlin')]
db.sensor.get(2)  # SensorORM(id=2, name='south', site='zurich')
db.sensor.to_frame()  # polars.DataFrame
db.sensor.to_parquet("sensors.parquet")
```

## Time series

```python
from datetime import date, datetime

import polars as pl

from ducktide import TimeSeriesDB

ts = TimeSeriesDB()  # or TimeSeriesDB("prices.duckdb")

ts.ingest(
    "prices",
    pl.DataFrame(
        {
            "timestamp": [datetime(2025, 1, 1, 9, 0), datetime(2025, 1, 1, 9, 1)],
            "instrument_id": [1, 1],
            "close": [100.0, 100.5],
        }
    ),
)

ts.get_timeseries_frame("prices", instrument_id=1, start=date(2025, 1, 1))
```

The table is created on first ingest. The timestamp column defaults to
`timestamp`; pass `TimeSeriesDB(time_col="ts")` to change it.

## Default database context

For notebooks and tests you can scope a default database instead of passing it
around:

```python
from ducktide.context import use_db

with use_db(db):
    ...  # code that calls ducktide.context.get_default_db()
```

## Development

```bash
uv sync --group test
uv run pytest
```

## License

MIT
