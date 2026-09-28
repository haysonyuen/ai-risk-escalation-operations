"""Streamlit entry point: `streamlit run app/streamlit_app.py`."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="AI Risk & Escalation Ops (prototype)", layout="wide")

import common  # noqa: E402  (adds repo root to sys.path)
import view_intake  # noqa: E402
import view_monitoring  # noqa: E402
import view_quality  # noqa: E402
import view_queue  # noqa: E402
import view_rules  # noqa: E402
import view_workspace  # noqa: E402
from riskops import config  # noqa: E402

if not config.db_path().exists():
    from riskops.seed import seed
    seed()

common.open_conn()
page = common.sidebar()
common.show_flash()
{
    "Incident queue": view_queue.render,
    "Incident workspace": view_workspace.render,
    "New intake": view_intake.render,
    "Quality & evaluation": view_quality.render,
    "Rules & playbooks": view_rules.render,
    "Monitoring": view_monitoring.render,
}[page]()
