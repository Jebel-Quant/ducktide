# CLAUDE.md

Guidance for Claude Code sessions in this repository.

ducktide: immutable Pydantic models and append-fast time series on DuckDB + Polars.
Python >=3.11, managed with uv, tooling from the [rhiza](https://github.com/jebel-quant/rhiza)
template (`.rhiza/template.yml`).

## Commands

Prefer bare `make <target>`; never call `.venv/bin/…` directly. `make help` lists everything.

- `make all` — every gate, as CI runs them (`fmt deps test docs-coverage security license typecheck rhiza-test`)
- `make fmt` — pre-commit hooks (ruff, ruff format, markdownlint, …) over all files
- `make test` — the pytest suite with coverage
- `make typecheck` — ty and/or mypy
- `make docs-coverage` — docstring coverage with interrogate
- `make deps` — deptry over `src`
- `make security` — bandit
- `make license` — copyleft licence scan
- `make update` — sync the rhiza template (prefer `/rhiza:update`, which opens a PR)

## Architecture

`src/ducktide/`:

- `db.py` — `DB`, DuckDB connection management; tables are attached via `tables_map` (`Table.of(Model)`).
- `table/` — `Table`, the repository-pattern interface, composed from `_base` (state),
  `_query` (reads), `_write` (writes) and `_io` (Parquet/CSV import/export).
- `model.py` — `DomainModel` (optional frozen base) and `column_definitions`, which derives a table's
  columns and DuckDB types from a Pydantic model's fields. `example.py` holds the sample `Foo` model.
- `time/` — `TimeSeriesDB` (time series store; `ingest` upserts on a series key, `compact` regroups by it), `TimeSeriesModel`,
  `TimeSeriesRepository`, split into `_base`, `_ingest`, `_query`, `_io`.
- `context.py` — `use_db`/`get_default_db`, a ContextVar-scoped default database.
- `exceptions.py` — the exception hierarchy.
- `utils/` — `sql.py` (the only place SQL strings with identifiers are composed;
  identifiers go through `validate_identifier`/`quote_identifier`) and `path_validation.py`.

One Pydantic model defines a table and is what reads return; models carry no persistence methods —
all reads and writes go through a `Table`.

## Rhiza template split

- **Rhiza-owned:** every path in the `files:` list of `.rhiza/template.lock` (Makefile,
  `ruff.toml`, `pytest.ini`, `.gitignore`, `.pre-commit-config.yaml`, `.github/workflows/rhiza_*.yml`,
  `docs/mkdocs-base.yml`, `tests/test_rhiza_packaging.py`, …). Don't edit these here: the
  `check-managed-files` hook rejects it and the next sync overwrites it. Fix gaps upstream in the template.
- **Locally owned:** `src/`, `tests/` (apart from the synced file above), `pyproject.toml`,
  `uv.lock`, `README.md`, `CLAUDE.md`, `mkdocs.yml`, `book/`.
- Repo-specific lint exceptions go inline (`# noqa: RULE - reason`), not into `ruff.toml`.

## Conventions

- Tests mirror the source tree (`tests/table/test__io.py` ↔ `src/ducktide/table/_io.py`).
- Coverage must stay at 100% (`fail_under = 100` in `pyproject.toml`).
- Every public module, class and function has a docstring (interrogate gate).
- The README's code blocks are executed by the rhiza checks — keep them runnable, and
  don't let them write into the repo root.
- Dependencies carry lower bounds; `pyarrow` is runtime-only (DuckDB's `.pl()`), hence
  the deptry ignore.
