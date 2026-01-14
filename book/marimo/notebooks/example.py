# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "marimo",
#     "futures",
# ]
#
# [tool.uv.sources]
# futures = { path = "../../.." }
# ///

"""Example Marimo notebook demonstrating the jqr.database system."""

import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")

with app.setup:
    from functools import partial

    from jqr.database import DB, Table
    from jqr.database.orm.example import Foo, FooORM

    db = DB(tables_map={"foo": partial(Table, model_class=FooORM)})


@app.cell
def _():
    foo1 = Foo(id=1, name="apple")
    foo2 = Foo(id=2, name="banana")
    foo3 = Foo(id=3, name="cherry")
    db.insert(foo1, foo2, foo3)


@app.cell
def _():
    table = db.table[Foo]
    for f in table:
        print(f.name)


if __name__ == "__main__":
    app.run()
