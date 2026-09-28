# ducktide

[![Release](https://img.shields.io/github/v/release/Jebel-Quant/ducktide?sort=semver)](https://github.com/Jebel-Quant/ducktide/releases)

[![rhiza v1.8.0](https://img.shields.io/badge/rhiza-v1.8.0-blue)](https://github.com/jebel-quant/rhiza/releases/tag/v1.8.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python versions](https://img.shields.io/badge/Python-3.11%20%E2%80%A2%203.12%20%E2%80%A2%203.13%20%E2%80%A2%203.14-blue?logo=python)](https://www.python.org/)
[![CI](https://github.com/Jebel-Quant/ducktide/actions/workflows/rhiza_ci.yml/badge.svg?event=push)](https://github.com/Jebel-Quant/ducktide/actions/workflows/rhiza_ci.yml)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg?logo=ruff)](https://github.com/astral-sh/ruff)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![CodeFactor](https://www.codefactor.io/repository/github/Jebel-Quant/ducktide/badge)](https://www.codefactor.io/repository/github/Jebel-Quant/ducktide)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/Jebel-Quant/ducktide/badge)](https://scorecard.dev/viewer/?uri=github.com/Jebel-Quant/ducktide)

Immutable Pydantic models and append-fast time series on DuckDB + Polars.

ducktide is a small persistence layer with two halves:

- **Entity tables**: frozen Pydantic models persisted through repositories
  (`DB` + `Table`). One model defines a table — its fields are the columns —
  and carries no `save()`/`find()`/`delete()` methods; all reads and writes go
  through the table, so domain objects stay plain values.
- **Time series**: `TimeSeriesDB`, a store for high-volume numerical data
  (prices, volumes, sensor readings). Ingestion upserts on a series key
  (`instrument_id` plus the timestamp by default), so re-ingesting an
  overlapping frame is safe, and late rows and corrections land instead of
  being dropped.

Both run on DuckDB (in-memory or a single file) and hand data back as Polars
DataFrames. There is no SQLAlchemy and no server.

## Why not DuckDB directly?

Fair question. DuckDB does the actual work here: storage, the query engine,
`MERGE`, Parquet and CSV, the zero-copy hand-off to Polars. ducktide is candy
on top of the DuckDB cake. You could write all of it yourself in an afternoon
of SQL strings. The candy is still worth having, because it spares you that
afternoon and the bugs that come with it:

- **One definition of a table.** The Pydantic model is the schema. Columns,
  DuckDB types and `NOT NULL` come from its fields, so there is no `CREATE
  TABLE` to keep in sync with a class by hand.
- **Typed rows back, not tuples.** Reads return validated, frozen model
  instances (or a Polars frame when you want one), so the code that uses the
  data gets type checking and never indexes `row[3]`.
- **Upserts that are easy to get wrong, done once.** `ingest` turns a frame into
  a `MERGE` on the series key. It drops duplicate keys inside the frame (last
  row wins), matches `NULL` keys to stored `NULL`s instead of duplicating them,
  creates the table on the first write and lets late rows and corrections land.
  Written by hand, each of those is a subtle bug waiting to happen.
- **The performance traps are already stepped around.** Frames built with
  `pl.concat` are rechunked before ingest (about 20x faster on fragmented
  frames), `bulk_insert` hands DuckDB one frame rather than running
  `executemany` row by row, and UUID columns are sent as text so they still
  take that fast path. `compact` regroups a table by key when single-series
  reads dominate.
- **No SQL injection through names.** Table and column names are validated and
  quoted in one module; values always travel as bound parameters.
- **Your domain objects stay plain values.** Models carry no `save()` or
  `find()`; persistence lives in `Table`, so the same model works in tests,
  in memory and on disk.

When you need something ducktide does not cover, the DuckDB connection is right
there (`db.connection`, `ts.con`), and plain SQL still works on the same tables.

## Install

```bash
pip install ducktide
```

Requires Python 3.11+.

## Entity tables

Define a domain model; the table is derived from it:

```python
import tempfile
from pathlib import Path

from ducktide import DB, DomainModel, Table


class Sensor(DomainModel):
    id: int
    name: str
    site: str


db = DB(tables_map={"sensor": Table.of(Sensor)})  # or db_path="sensors.duckdb"

db.sensor.bulk_insert(
    [
        Sensor(id=1, name="north", site="berlin"),
        Sensor(id=2, name="south", site="zurich"),
    ]
)

db.sensor.select(site="berlin")  # [Sensor(id=1, name='north', site='berlin')]
db.sensor.get(2)  # Sensor(id=2, name='south', site='zurich')
db.sensor.to_frame()  # polars.DataFrame
db.sensor.to_parquet(Path(tempfile.mkdtemp()) / "sensors.parquet")
```

The columns, their DuckDB types and `NOT NULL` come from the fields (`X | None`
fields are nullable), and rows come back as `Sensor` instances. `Table.of`
takes `name=` (default: the lower-cased class name), `primary_key=` (default
`"id"`) and `sql_types=` to override a column's definition, e.g.
`sql_types={"name": "VARCHAR NOT NULL UNIQUE"}`, or to store a type the mapping
does not cover.

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

# A correction for 9:01 and a late bar for 8:59: both land.
ts.ingest(
    "prices",
    pl.DataFrame(
        {
            "timestamp": [datetime(2025, 1, 1, 9, 1), datetime(2025, 1, 1, 8, 59)],
            "instrument_id": [1, 1],
            "close": [100.4, 99.9],
        }
    ),
)

ts.get_timeseries_frame("prices", instrument_id=1, start=date(2025, 1, 1))  # 3 rows, close 99.9, 100.0, 100.4
```

The table is created on first ingest. After that, a row whose key is already
stored replaces it, and every other row is inserted, whatever its timestamp.
Within one frame the last row for a key wins. Pass `on_conflict="ignore"` to
keep stored rows and only add new keys.

The key is the timestamp plus `instrument_id` when the frame has one; pass
`key=` for other series, e.g. `ts.ingest("fx", frame, key=["base", "quote"])`.
The timestamp column defaults to `timestamp`; pass `TimeSeriesDB(time_col="ts")`
to change it.

Ingestion stores rows in arrival order. When whole days arrive for every
instrument at once, that spreads each instrument across the whole table.
`compact` rewrites a table grouped by the same key, so a read for one
instrument can skip most of it. It is a trade-off, not a free speed-up:

| | 1M rows, time order | compacted |
|---|---|---|
| one instrument, one year | 1.1 ms | 0.75 ms |
| one day, all instruments | 0.3 ms | 1.4 ms (~15x slower at 10M rows) |
| mean per instrument, whole table | 0.65 ms | 0.9 ms |

Compact only if reads for single instruments dominate. It does nothing for a
table loaded one instrument at a time (e.g. through `TimeSeriesModel.ingest`),
whose rows are already grouped, and DuckDB does not shrink the file afterwards.
New ingests land unsorted again, so compact periodically, e.g. after each day's
ingest:

```python
ts.compact("prices")  # or ts.compact("fx", key=["base", "quote"])
```

## Why two databases?

Both halves run on DuckDB. They are split by the shape of the data and by how
it is read and written, not by engine.

**Reference data** (`DB` + `Table`) is instruments, exchanges, sensors: few
rows, one per entity, identified by a primary key, rarely changed. The schema
is declared up front by a Pydantic model that validates every row, and reads
return typed, frozen objects. For a few thousand rows that is cheap and
pleasant to work with.

**Time series** (`TimeSeriesDB`) is prices, volumes, readings: millions of
rows, identified by series key plus timestamp. The schema comes from the first
frame ingested. Writes are bulk upserts, because corrections and late rows are
routine. Reads return Polars frames, never objects, since building a million
Pydantic instances would take seconds and a lot of memory. Row order on disk
matters for speed, which is what `compact` is for.

Forcing both into one abstraction would hurt one of them: row objects make
time series slow, and bare frames cost reference data its validation and types.

Keeping them in separate files also pays off:

- **Writers don't block each other.** Only one process can write to a DuckDB
  file at a time, so a nightly price ingest doesn't lock the instrument table.
- **Different lifecycles.** Reference data is small and worth backing up or
  versioning. Time series are large, can usually be re-downloaded from the
  vendor, and can be rebuilt without touching the definitions.
- **Read-only fan-out.** Many processes can open the time-series file with
  `read_only=True` while the reference database stays writable.

`TimeSeriesModel` connects the two. A model loaded from `DB` knows its
time-series table and its `instrument_id`, and fetches its own frame:

```python
from datetime import datetime
from typing import ClassVar

import polars as pl

from ducktide import DB, DomainModel, Table, TimeSeriesDB
from ducktide.time import TimeSeriesModel


class Instrument(DomainModel, TimeSeriesModel):
    table_name: ClassVar[str] = "prices"

    id: int
    ticker: str
    exchange: str

    @property
    def instrument_id(self) -> int:
        return self.id


ref = DB(tables_map={"instrument": Table.of(Instrument)})  # e.g. db_path="reference.duckdb"
ts = TimeSeriesDB()  # e.g. TimeSeriesDB("prices.duckdb")

ref.instrument.insert(Instrument(id=1, ticker="ACME", exchange="XNYS"))
ts.ingest(
    "prices",
    pl.DataFrame({"timestamp": [datetime(2025, 1, 1, 9, 0)], "instrument_id": [1], "close": [100.0]}),
)

acme = ref.instrument.get(1)  # an Instrument, from the reference database
acme.get_timeseries_frame(ts)  # its prices, from the time-series database
```

The trade-off: a SQL join across the two, such as all prices for instruments
on one exchange, needs DuckDB's `ATTACH` or a Polars join. In practice you pick
the instruments in the reference database first, then read their series.

## Default database context

For notebooks and tests you can scope a default database instead of passing it
around:

```python
from ducktide.context import use_db

with use_db(db):
    ...  # code that calls ducktide.context.get_default_db()
```

## License

MIT
