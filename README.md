# ducktide

[![Release](https://img.shields.io/github/v/release/Jebel-Quant/ducktide?sort=semver)](https://github.com/Jebel-Quant/ducktide/releases)

[![rhiza v1.8.0](https://img.shields.io/badge/rhiza-v1.8.0-blue)](https://github.com/jebel-quant/rhiza/releases/tag/v1.8.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python versions](https://img.shields.io/badge/Python-3.11 • 3.12 • 3.13 • 3.14-blue?logo=python)](https://www.python.org/)
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

Run `make help` to see all available targets:

```text
 task                section         needs                 does
 book                Book            test benchmark        build the companion
                                     stress                book
                                     hypothesis-test
                                     paper
 book-nav            Book                                  check that every
                                                           mkdocs nav entry
                                                           resolves in the
                                                           built book
 marimo              Book            install               start the Marimo
                                                           editor
 marimo-validate     Book            install               check that every
                                                           Marimo notebook runs
 serve               Book            book                  build the book and
                                                           serve it on port
                                                           8000
 clean               Dev                                   remove build
                                                           artifacts and stale
                                                           local branches
 doctor              Dev                                   check local
                                                           prerequisites
 setup               Dev                                   run the repository's
                                                           own environment
                                                           setup hook
 docker-build        Docker                                build the Docker
                                                           image
 docker-clean        Docker                                remove the Docker
                                                           image
 docker-run          Docker          docker-build          run the Docker
                                                           container
 lfs-install         Git LFS                               configure git-lfs
                                                           for this repository
 lfs-pull            Git LFS                               download the LFS
                                                           files for the
                                                           current branch
 lfs-status          Git LFS                               show the status of
                                                           LFS files
 lfs-track           Git LFS                               list the patterns
                                                           tracked by git-lfs
 failed-workflows    GitHub Helpers                        list recent failing
                                                           workflow runs
 latest-release      GitHub Helpers                        show information
                                                           about the latest
                                                           GitHub release
 view-issues         GitHub Helpers                        list open issues
 view-prs            GitHub Helpers                        list open pull
                                                           requests
 whoami              GitHub Helpers                        check github auth
                                                           status
 workflow-status     GitHub Helpers                        show recent runs for
                                                           the release workflow
 paper               Paper                                 compile the LaTeX
                                                           paper to PDF
 paper-clean         Paper                                 remove the LaTeX
                                                           build artifacts
 presentation        Presentation                          generate the HTML
                                                           slides with Marp
 presentation-pdf    Presentation                          generate the PDF
                                                           slides with Marp
 presentation-serve  Presentation                          serve the slides
                                                           with Marp's live
                                                           preview
 all                 Python          fmt deps test         run every gate, as
                                     docs-coverage         CI does
                                     security license
                                     typecheck rhiza-test
 coverage            Python          install               measure coverage and
                                                           write
                                                           _tests/coverage.xml
 deps                Python          install               run deptry over the
                                                           contributed folders
 docs-coverage       Python          install               check docstring
                                                           coverage with
                                                           interrogate
 install             Python          setup                 create the venv and
                                                           sync dependencies
 license             Python          install               scan for copyleft
                                                           licences
 security            Python          install               run the bandit
                                                           security scan
 test                Python          install               run all tests
 test-lowest         Python          install               run the tests
                                                           against the oldest
                                                           dependencies the
                                                           manifest allows
 typecheck           Python          install               run ty and/or mypy
                                                           (typechecker = ty |
                                                           mypy | both)
 docs-examples       Quality         install               check the fenced
                                                           examples in the docs
                                                           tree
 fmt                 Quality                               run the pre-commit
                                                           hooks over all files
 complexity          Quality                               fail on a block
                                                           above the
                                                           cyclomatic-complexi…
                                                           ceiling
 test-pyproject      Quality         install               run the
                                                           pyproject.toml
                                                           structure checks,
                                                           verbosely
 rhiza-test          Quality         install               run the rhiza
                                                           repository checks
 semgrep             Quality                               run the semgrep
                                                           static analysis
                                                           rules
 todos               Quality                               list every TODO,
                                                           FIXME and HACK
                                                           comment
 update              Template                              sync the rhiza
                                                           template into this
                                                           repository
 benchmark           Testing extras  install               run the performance
                                                           benchmarks
 hypothesis-test     Testing extras  install               run the
                                                           property-based tests
 stress              Testing extras  install               run the stress and
                                                           load tests
```

## License

MIT
