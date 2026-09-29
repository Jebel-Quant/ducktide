# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com),
and entries are generated from [Conventional Commits](https://www.conventionalcommits.org).

## [0.1.2] - 2026-09-29

### Bug Fixes
- Honour TimeSeriesDB.time_col in TimeSeriesModel resampling (#42)

## [0.1.1] - 2026-09-29

### Bug Fixes
- Quote column names in entity-table SQL (#29) (#34)
- Raise DatabaseError on writes to a read-only store (#32) (#35)
- Create a missing parent folder on export (#33) (#36)
- Include the whole day for a date end bound (#31) (#38)
- Return timezone-aware timestamps in UTC (#30) (#37)

### Documentation
- Explain the two-database design, drop the README's Development section (#27)
- Add a LaTeX introduction to ducktide (#28)
- Update the introduction paper for the fixes in #34-#38 (#39)
- Link the introduction PDF from the book nav (#40)

## [0.1.0] - 2026-09-28

### New Features
- [**breaking**] Define a table from a single Pydantic model (#14)
- [**breaking**] Upsert time-series ingest on a configurable series key (#18)
- Add TimeSeriesModel.ingest_many for one write per table (#21)
- Add TimeSeriesDB.compact to regroup a table by series key (#22)

### Documentation
- URL-encode the Python versions badge so it renders (#23)
- Add a 'Why not DuckDB directly?' section to the README (#25)

### Performance
- Bulk-insert via one INSERT ... SELECT, look up single tables (#17)
- Send UUID columns to bulk_insert's frame path as text (#19)
- Faster time-series upserts on large tables and concatenated frames (#20)

### Maintenance
- Update rhiza to v1.9.0 (#24)

## [0.0.1] - 2026-09-27

### Bug Fixes
- Add missing type annotations to fix mypy errors
- *(tests)* Mirror test layout to source tree (closes #782) (#783)
- Close the four quality findings from the /rhiza:quality run (#820)
- Pass ruff and deptry under the synced template config
- Enforce the declared 100% coverage floor (#5)
- Point rhiza-task at book/marimo/notebooks (#4)
- Declare numpy in database_demo's script header (#4)
- Stop ducktide.orm eagerly importing the example model (#7)
- Link the exported notebooks from the book nav (#12)

### Documentation
- Achieve 100% documentation coverage
- Clarify dual ORM namespace (jqr.database.orm vs jqr.orm.models) (#771)
- Add badges, CLAUDE.md and mkdocs.yml

### Maintenance
- Decompose database/table.py into submodules (#754) (#756)
- Address quality-scorecard findings (#763-#767) (#768)
- Enforce layering and centralize SQL identifier validation (#786)
- Assert TimeSeriesModel behaviour against a real repo (closes #775) (#787)
- Point repo at jebel-quant/rhiza@v1.8.0
- Add project skeleton + license metadata
- Apply rhiza sync v1.8.0
- Relock after requires-python change
- Chore(deps)(deps): bump the github-actions group with 6 updates
- Declare the tag-derived version for /rhiza:release

### Other Changes
- 465 refactor (#466)
- Simplify ORMModel (#467)
- Table get (#470)
- Consolidate get_timeseries_frame into TimeSeriesModel base class (#469)
- Enhance documentation and docstrings across repository (#474)
- Remove fallback to pydantic model_fields in ORMModel
- Remove jqr.orm references from jqr.database and add comprehensive docstring examples (#476)
- Add read_only parameter to TimeSeriesDB (#479)
- Contracts (#480)
- Remove `table_name` property and refactor as class attribute in models (#482)
- [WIP] Investigate the role of the variable table_name (#488)
- Implement hedged VIX strategy: short front contract + long second contract (#492)
- Refactor contract and future models to enforce strict validation, rem… (#508)
- Weaknesses (#510)
- Sync (#514)
- Sync (#516)
- Experiments (#520)
- Sync (#536)
- Sync40 (#607)
- Address repo-review issues #710-#712, #720, #724 (#726)
- Standardize on Google-style docstrings across src/ (#733)
- Address open issues: typed filter API, API doc prose, 100% coverage gate (#738)
- Sync Rhiza template v0.18.8 → v0.19.3 (#742)
- Justify and narrow nosec B608 SQL suppressions (#755) (#757)
- Adopt PEP 639 license metadata, prune dead nosec markers, flatten test classes (#799)
- Extract ducktide from futures' jqr.database
- Merge pull request #1 from Jebel-Quant/rhiza_init_20260927
- Merge pull request #2 from Jebel-Quant/rhiza_v1.8.0_20260927
- Merge pull request #3 from Jebel-Quant/dependabot/github_actions/github-actions-804e4f0f0e
- Merge pull request #9 from Jebel-Quant/rhiza_fix_5_20260927
- Merge pull request #11 from Jebel-Quant/rhiza_fix_7_20260927
- Merge branch 'main' into rhiza_fix_4_20260927
- Merge pull request #10 from Jebel-Quant/rhiza_fix_4_20260927
- Merge pull request #13 from Jebel-Quant/rhiza_fix_12_20260927
- Merge pull request #15 from Jebel-Quant/rhiza_release_setup

