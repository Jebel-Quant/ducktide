# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "futures",
#     "duckdb",
#     "polars",
# ]
#
# [tool.uv.sources]
# futures = { path = "../../.." }
# ///

"""Marimo notebook demonstrating the jqr.database system.

This notebook demonstrates:
- Database initialization with DuckDB (jqr.database.DB)
- Creating custom model classes for use with the Table interface
- Repository pattern operations (insert, select, get, delete)
- Bulk data ingestion and export (CSV/Parquet)
- Low-level SQL execution
- Time series data management with TimeSeriesDB
"""

import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


with app.setup:
    from dataclasses import dataclass
    from datetime import date, datetime
    from typing import ClassVar

    import polars as pl

    from jqr.database.db import DB
    from jqr.database.table import Table
    from jqr.database.time import TimeSeriesDB


@app.cell(hide_code=True)
def cell_intro_header():
    """Render the notebook title and introduction."""
    import marimo as mo

    mo.md(
        """
        # 🗄️ jqr.database System Demo

        This notebook demonstrates the core database infrastructure in `jqr.database`.
        Unlike the ORM layer, this layer provides more direct control over table definitions
        and database operations while still following the Repository pattern.

        We will cover:
        1. **Core DB & Table**: Defining models and managing tables.
        2. **Data Operations**: CRUD, bulk inserts, and filtering.
        3. **Persistence**: Exporting and importing CSV/Parquet.
        4. **Time Series**: Using `TimeSeriesDB` for high-volume data.
        """
    )
    return (mo,)


@app.cell(hide_code=True)
def cell_section1_header(mo):
    """Render section 1 header."""
    mo.md("## 1. Defining a Custom Model")
    return


@app.cell
def cell_define_model():
    """Define the Trade model and TradeTable class."""

    @dataclass
    class Trade:
        trade_id: int
        symbol: str
        price: float
        quantity: int
        timestamp: datetime

        # Required metadata for jqr.database.Table
        _table_name = "trades"
        _primary_key = "trade_id"
        _columns: ClassVar[list[str]] = ["trade_id", "symbol", "price", "quantity", "timestamp"]
        _schema: ClassVar[dict[str, str]] = {
            "trade_id": "INTEGER PRIMARY KEY",
            "symbol": "TEXT NOT NULL",
            "price": "DOUBLE",
            "quantity": "INTEGER",
            "timestamp": "TIMESTAMP",
        }

        @classmethod
        def generate_create_table_sql(cls):
            """Generate SQL for table creation."""
            fields = ",\n    ".join([f"{k} {v}" for k, v in cls._schema.items()])
            return f"CREATE TABLE IF NOT EXISTS {cls._table_name} (\n    {fields}\n);"

        @classmethod
        def from_row(cls, row):
            """Create instance from database row."""
            return cls(*row)

    # Create a specialized Table class for our model to use with DB class
    class TradeTable(Table):
        def __init__(self, connection, read_only=False):
            super().__init__(connection, model_class=Trade, read_only=read_only)

    print("✓ Trade model and TradeTable defined.")
    return Trade, TradeTable


@app.cell(hide_code=True)
def cell_section2_header(mo):
    """Render section 2 header."""
    mo.md("## 2. Database Initialization")
    return


@app.cell
def cell_init_db(Trade, TradeTable):
    """Initialize the database with the custom table."""
    # jqr.database.DB takes a map of {attribute_name: table_cls}
    # where table_cls is a class that can be initialized with (connection, read_only=...)
    db = DB(tables_map={"trades": TradeTable}, db_path=":memory:")
    print("✓ Database initialized with custom table mapping.")
    return (db,)


@app.cell
def cell_demonstrate_db_methods(db):
    """Demonstrate low-level SQL execution via DB."""
    # Low-level SQL execution via DB
    db.execute_query("CREATE TABLE raw_data (id INTEGER, val TEXT)")
    db.execute_query("INSERT INTO raw_data VALUES (1, 'Hello'), (2, 'World')")

    result = db.execute_query("SELECT * FROM raw_data").fetchall()
    print(f"Raw query result: {result}")
    return (result,)


@app.cell(hide_code=True)
def cell_section3_header(mo):
    """Render section 3 header."""
    mo.md("## 3. Data Operations (CRUD)")
    return


@app.cell
def cell_insert_data(db, Trade):
    """Insert sample data into the database."""
    t1 = Trade(1, "AAPL", 150.0, 10, datetime(2023, 1, 1, 10, 0))
    t2 = Trade(2, "MSFT", 250.0, 5, datetime(2023, 1, 1, 10, 5))

    # Insert via table interface
    db.trades.insert(t1, t2)

    print(f"✓ Inserted {len(db.trades)} trades.")
    return t1, t2


@app.cell
def cell_query_data(db):
    """Query data from the database."""
    # Select all
    all_trades = db.trades.select()

    # Select with filter
    msft_trades = db.trades.select("symbol = ?", ["MSFT"])

    return all_trades, msft_trades


@app.cell
def cell_display_trades(mo, all_trades):
    """Display the queried trades."""
    print(all_trades)
    return


@app.cell(hide_code=True)
def cell_section4_header(mo):
    """Render section 4 header."""
    mo.md("## 4. Bulk Operations and DataFrames")
    return


@app.cell
def cell_bulk_insert(db, Trade):
    """Perform bulk insert of many records."""
    many_trades = [Trade(i, "GOOG", 2800.0 + i, 1, datetime(2023, 1, 1, 11, i)) for i in range(10, 20)]
    db.trades.bulk_insert(many_trades)
    print(f"✓ Bulk inserted {len(many_trades)} trades. Total: {len(db.trades)}")
    return (many_trades,)


@app.cell
def cell_to_dataframe(db):
    """Export the table to a Polars DataFrame."""
    # Export table to Polars DataFrame
    df = db.trades.to_frame()
    return (df,)


@app.cell
def cell_display_df(mo, df):
    """Display the Polars DataFrame."""
    mo.md(f"### Trades DataFrame (Total: {len(df)})")
    return mo.ui.table(df)


@app.cell(hide_code=True)
def cell_section5_header(mo):
    """Render section 5 header."""
    mo.md("## 5. Time Series Database")
    return


@app.cell
def cell_init_ts_db():
    """Initialize the TimeSeriesDB and ingest sample data."""
    ts_db = TimeSeriesDB(":memory:")

    # Generate some sample time series data
    import numpy as np

    dates = pl.date_range(date(2023, 1, 1), date(2023, 1, 10), "1d", eager=True)
    ts_data = pl.DataFrame(
        {"timestamp": dates, "instrument_id": [101] * len(dates), "price": np.random.randn(len(dates)).cumsum() + 100}
    )

    # Ingest into TS database
    ts_db.ingest("equity_prices", ts_data)

    print("✓ TimeSeriesDB initialized and data ingested.")
    return ts_db, ts_data


@app.cell
def cell_query_ts(ts_db):
    """Query the TimeSeriesDB."""
    # Retrieve time series frame
    retrieved_df = ts_db.get_timeseries_frame(
        "equity_prices", instrument_id=101, start=date(2023, 1, 3), end=date(2023, 1, 7)
    )
    return (retrieved_df,)


@app.cell
def cell_display_ts(mo, retrieved_df):
    """Display the retrieved time series data."""
    return mo.vstack([mo.md("### Retrieved Time Series Data (Filtered)"), mo.ui.table(retrieved_df)])


@app.cell(hide_code=True)
def cell_summary(mo, db):
    """Render the notebook summary."""
    mo.md(
        f"""
        ## Summary

        - **Total Trades**: {len(db.trades)}
        - **Models used**: `Trade` (Custom)
        - **Storage**: DuckDB (In-memory)

        This demonstrates how `jqr.database` provides a robust foundation for both relational
        metadata and high-volume time series data without the overhead of a full ORM.
        """
    )
    return


if __name__ == "__main__":
    app.run()
