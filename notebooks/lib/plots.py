"""Plotly helpers for pm-edge analysis notebooks."""

from __future__ import annotations

import duckdb
import pandas as pd
import plotly.express as px  # type: ignore[import-untyped]
import plotly.graph_objects as go  # type: ignore[import-untyped]
from plotly.subplots import make_subplots  # type: ignore[import-untyped]

from notebooks.lib.queries import multi_timescale_aggregation


def plot_hourly_volume(
    df: pd.DataFrame,
    title: str = "Hourly Snapshot Volume",
) -> go.Figure:
    """Stacked bar by venue over hours."""

    if df.empty:
        return _empty_figure(title)
    return px.bar(df, x="hour", y="snapshots", color="venue", title=title)


def plot_book_top_over_time(
    con: duckdb.DuckDBPyConnection,
    market_id: str,
    timescale: str = "5 minute",
) -> go.Figure:
    """Time series of top_bid, top_ask, mid for a single market."""

    aggs = multi_timescale_aggregation(con, market_id, [timescale])
    df = aggs[timescale]
    fig = go.Figure()
    fig.update_layout(title=f"{market_id} top book over time ({timescale})", xaxis_title="Time")
    if df.empty:
        return fig
    for metric in ("top_bid", "top_ask", "mid"):
        fig.add_trace(go.Scatter(x=df["bucket"], y=df[metric], mode="lines", name=metric))
    return fig


def plot_multi_timescale_overlay(
    aggs: dict[str, pd.DataFrame],
    metric: str = "mid",
) -> go.Figure:
    """Subplots, one per timescale, showing the same metric."""

    if not aggs:
        return _empty_figure(f"Multi-timescale {metric}")

    fig = make_subplots(rows=len(aggs), cols=1, shared_xaxes=False, subplot_titles=list(aggs))
    for row, (timescale, df) in enumerate(aggs.items(), start=1):
        if df.empty or metric not in df:
            continue
        fig.add_trace(
            go.Scatter(x=df["bucket"], y=df[metric], mode="lines", name=timescale),
            row=row,
            col=1,
        )
    fig.update_layout(title=f"Multi-timescale {metric}", height=max(320, 240 * len(aggs)))
    return fig


def plot_spread_distribution(df: pd.DataFrame) -> go.Figure:
    """Histogram of spreads, faceted by venue."""

    if df.empty:
        return _empty_figure("Spread distribution")
    return px.histogram(
        df,
        x="spread_mean",
        color="venue",
        facet_col="venue",
        title="Spread distribution",
    )


def plot_movement_distribution(df: pd.DataFrame) -> go.Figure:
    """Distribution of distinct_top_bids per market."""

    if df.empty:
        return _empty_figure("Market movement distribution")
    return px.histogram(
        df,
        x="distinct_top_bids",
        color="venue",
        title="Market movement distribution",
    )


def _empty_figure(title: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(title=title)
    fig.add_annotation(
        text="No data available",
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
    )
    return fig
