"""Streamlit dashboard for the live paper trading state."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, cast

import pandas as pd

from core.config import get_settings


def load_state(path: Path) -> dict[str, Any]:
    """Load persisted paper-trader state."""

    if not path.exists():
        return {}
    return cast(dict[str, Any], json.loads(path.read_text()))


def load_audit(path: Path, *, limit: int = 200) -> pd.DataFrame:
    """Load recent JSONL audit records."""

    if not path.exists():
        return pd.DataFrame()
    lines = path.read_text().splitlines()[-limit:]
    rows = [json.loads(line) for line in lines if line.strip()]
    return pd.DataFrame(rows)


def main() -> None:
    """Run Streamlit dashboard."""

    st = importlib.import_module("streamlit")

    settings = get_settings()
    state_path = settings.paper_trader_state_path
    audit_path = settings.paper_trader_audit_log_path

    st.set_page_config(page_title="pm-edge Paper Trading", layout="wide")
    st.title("pm-edge Live Paper Trading")
    st.caption("Paper-only monitoring. No live-money execution is wired in this phase.")

    state = load_state(state_path)
    audit = load_audit(audit_path)
    equity = state.get("equity", settings.paper_trader_virtual_capital_usd)
    cash = state.get("cash", settings.paper_trader_virtual_capital_usd)
    positions = pd.DataFrame(state.get("positions", {}).values())

    metric_cols = st.columns(4)
    metric_cols[0].metric("Equity", f"${equity:,.2f}")
    metric_cols[1].metric("Cash", f"${cash:,.2f}")
    metric_cols[2].metric("Open Positions", str(len(positions)))
    metric_cols[3].metric("Mode", "Paper")

    st.subheader("Current Portfolio")
    if positions.empty:
        st.info("No open paper positions.")
    else:
        st.dataframe(positions, use_container_width=True)

    st.subheader("Live Equity Curve")
    if not audit.empty and "equity" in audit:
        curve = audit.dropna(subset=["equity"])[["as_of", "equity"]]
        if not curve.empty:
            st.line_chart(curve.set_index("as_of"))
        else:
            st.info("No equity observations in audit log yet.")
    else:
        st.info("No audit log found yet.")

    st.subheader("Top Opportunities")
    signal_rows = [row for row in state.get("last_signals", []) if isinstance(row, dict)]
    if signal_rows:
        top = pd.DataFrame(signal_rows).sort_values("edge_abs", ascending=False).head(10)
        st.dataframe(top, use_container_width=True)
    else:
        st.info("No scored opportunities yet.")

    st.subheader("Recent Trade Decisions")
    if audit.empty:
        st.info("No decisions logged yet.")
    else:
        st.dataframe(audit.tail(50), use_container_width=True)

    st.subheader("Rubric Status")
    performance = state.get("latest_performance", {})
    rubric = performance.get("rubric", {})
    st.write(rubric.get("grade", "Unavailable"))
    if rubric.get("reasons"):
        st.write(rubric["reasons"])


if __name__ == "__main__":
    main()
