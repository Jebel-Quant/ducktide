# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "ducktide",
#     "duckdb",
#     "polars",
#     "numpy",
# ]
#
# [tool.uv.sources]
# ducktide = { path = "../../.." }
# ///

"""Marimo notebook demonstrating the ducktide system.

This notebook demonstrates:
- Database initialization with DuckDB (ducktide.DB)
- Defining a table from a single Pydantic model
- Repository pattern operations (insert, select, get, delete)
- Bulk data ingestion and export (CSV/Parquet)
- Low-level SQL execution
- Time series data management with TimeSeriesDB
"""

import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


with app.setup:
    from datetime import date, datetime

    import polars as pl

    from ducktide import DomainModel
    from ducktide.db import DB
    from ducktide.table import Table
    from ducktide.time import TimeSeriesDB


@app.cell(hide_code=True)
def cell_intro_header():
    """Render the notebook title and introduction."""
    import marimo as mo

    mo.md(
        """
        # 🗄️ ducktide System Demo

        This notebook demonstrates the core database infrastructure in `ducktide`.
        A table is defined by one Pydantic model: its fields are the columns, and rows
        come back as instances of that model. All reads and writes go through the
        table, following the Repository pattern.

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
    """Define the Trade model and its table."""

    class Trade(DomainModel):
        trade_id: int
        symbol: str
        price: float
        quantity: int
        timestamp: datetime

    # The model is the whole definition: column names, types and NOT NULL are
    # derived from its fields. Only the table name and primary key are stated.
    trades_table = Table.of(Trade, name="trades", primary_key="trade_id")

    print("✓ Trade model and its table defined.")
    return Trade, trades_table


@app.cell(hide_code=True)
def cell_section2_header(mo):
    """Render section 2 header."""
    mo.md("## 2. Database Initialization")
    return


@app.cell
def cell_init_db(trades_table):
    """Initialize the database with the custom table."""
    # ducktide.DB takes a map of {attribute_name: table factory}
    db = DB(tables_map={"trades": trades_table}, db_path=":memory:")
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
    t1 = Trade(trade_id=1, symbol="AAPL", price=150.0, quantity=10, timestamp=datetime(2023, 1, 1, 10, 0))
    t2 = Trade(trade_id=2, symbol="MSFT", price=250.0, quantity=5, timestamp=datetime(2023, 1, 1, 10, 5))

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
def cell_display_trades(all_trades):
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
    many_trades = [
        Trade(trade_id=i, symbol="GOOG", price=2800.0 + i, quantity=1, timestamp=datetime(2023, 1, 1, 11, i))
        for i in range(10, 20)
    ]
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

        This demonstrates how `ducktide` provides a robust foundation for both relational
        metadata and high-volume time series data without the overhead of a full ORM.
        """
    )
    return


if __name__ == "__main__":
    app.run()
