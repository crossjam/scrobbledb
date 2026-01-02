import marimo

__generated_with = "0.18.4"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _(df):
    import altair as alt
    import pandas as pd

    # Convert marimo dataframe `df` to a pandas DataFrame if necessary
    if hasattr(df, "to_pandas"):
        df_pandas = df.to_pandas()
    elif isinstance(df, pd.DataFrame):
        df_pandas = df
    else:
        df_pandas = pd.DataFrame(df)

    # Find a timestamp-like column (prefer exact "timestamp" if present)
    timestamp_col = "timestamp"

    # Ensure datetime dtype and extract year
    df_pandas["__parsed_timestamp"] = pd.to_datetime(df_pandas[timestamp_col], errors="coerce")
    df_pandas = df_pandas.dropna(subset=["__parsed_timestamp"])
    df_pandas["year"] = df_pandas["__parsed_timestamp"].dt.year

    # Group by year and count plays
    plays_by_year = df_pandas.groupby("year").size().reset_index(name="count").sort_values("year")

    # Create an interactive Altair bar chart
    chart = (
        alt.Chart(plays_by_year)
        .mark_bar(color="#4C78A8")
        .encode(
            x=alt.X("year:O", title="Year"),
            y=alt.Y("count:Q", title="Number of Plays"),
            tooltip=[alt.Tooltip("year:O", title="Year"), alt.Tooltip("count:Q", title="Plays")],
            color=alt.value("#4C78A8")
        )
        .properties(
            title="Plays by Year",
            width=700,
            height=420
        )
        .interactive()
    )

    chart
    return


@app.cell
def _():
    import marimo as mo
    import sqlalchemy
    from scrobbledb.config_utils import get_default_db_path
    return get_default_db_path, mo, sqlalchemy


@app.cell
def _(get_default_db_path):
    db_path = get_default_db_path()
    return (db_path,)


@app.cell
def _(db_path, sqlalchemy):
    DATABASE_URL = f"sqlite:///{db_path}"
    engine = sqlalchemy.create_engine(DATABASE_URL)
    return (engine,)


@app.cell
def _(engine, mo, plays):
    df = mo.sql(
        f"""
        SELECT * FROM plays order by timestamp desc;
        """,
        output=False,
        engine=engine
    )
    return (df,)


if __name__ == "__main__":
    app.run()
