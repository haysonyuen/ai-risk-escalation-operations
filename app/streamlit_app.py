"""Streamlit entry point: `streamlit run app/streamlit_app.py`."""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Risk & Escalation Ops", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded")

_v = tuple(int(x) for x in st.__version__.split(".")[:2])
if _v < (1, 50):
    st.error(f"This app needs Streamlit 1.50 or newer, but it is running on Streamlit {st.__version__} "
             "(probably a global/Anaconda install). In the project folder run:\n\n"
             "`source .venv/bin/activate` then `pip install -r requirements.txt` then "
             "`python -m streamlit run app/streamlit_app.py`")
    st.stop()

import common  # noqa: E402  (adds repo root to sys.path)
import page_case  # noqa: E402
import page_dashboard  # noqa: E402
import page_intake  # noqa: E402
import page_queue  # noqa: E402
import view_quality  # noqa: E402
import view_rules  # noqa: E402
from riskops import config  # noqa: E402
from riskops import workflow as wf  # noqa: E402
from riskops.db import get_setting  # noqa: E402
from riskops.providers import FAULT_MODES  # noqa: E402

common.open_conn()
common.md(common.CSS)

pages = {
    "queue": st.Page(page_queue.render, title="Queue", icon=":material/inbox:", default=True),
    "case": st.Page(page_case.render, title="Case", icon=":material/folder_open:", url_path="case"),
    "intake": st.Page(page_intake.render, title="New report", icon=":material/add_circle:", url_path="new"),
    "dashboard": st.Page(page_dashboard.render, title="Dashboard", icon=":material/monitoring:", url_path="dashboard"),
    "quality": st.Page(view_quality.render, title="Quality & evaluation", icon=":material/fact_check:", url_path="quality"),
    "rules": st.Page(view_rules.render, title="Rules & playbooks", icon=":material/rule:", url_path="rules"),
}
st.session_state["_pages"] = pages
nav = st.navigation({"Operations": [pages["queue"], pages["case"], pages["intake"]],
                     "Oversight": [pages["dashboard"], pages["quality"], pages["rules"]]})

with st.sidebar:
    st.selectbox("Working as", list(common.ACTORS), key="actor_id",
                 format_func=lambda k: common.ACTORS[k].display.replace(" (simulated)", ""))
    st.caption(f"Role: **{wf.ROLE_LABELS[common.current_actor().role]}** · simulated identity for the demo — not a login")
    st.divider()
    c = common.conn()
    mode = get_setting(c, "provider_mode")
    if mode != "offline":
        st.warning("Assessment provider: " + ("live model" if mode == "live" else "FAULT INJECTION test"))
    with st.expander("Demo settings"):
        # Public demo: never offer live model calls, even if an API key is configured by mistake.
        modes = (["offline"] if common.public_demo() else ["offline", "live"]) + [f"fault:{m}" for m in FAULT_MODES]
        labels = {"offline": "Offline (fixtures / simulation)",
                  "live": "Live model" + ("" if config.live_credentials_available() else " — no API key set")}
        labels.update({f"fault:{m}": f"Fault test: {d}" for m, d in FAULT_MODES.items()})
        new = st.selectbox("AI assessment provider", modes, index=modes.index(mode) if mode in modes else 0, format_func=labels.get)
        if new != mode:
            wf.set_provider_mode(c, new, common.current_actor())
            st.rerun()
        if new == "live" and not config.live_credentials_available():
            st.caption("Without ANTHROPIC_API_KEY live assessments fail visibly and go to manual review — no silent fallback.")
        st.caption(f"Active rules `{get_setting(c, 'active_rule_version')}` · prompt `{get_setting(c, 'active_prompt_version')}`")
        if st.checkbox("Allow reset", key="confirm_reset"):
            if st.button("Reset demo data"):
                from riskops.seed import seed_atomic
                st.session_state.pop("_conn").close()
                seed_atomic(common.db_file())
                for k in [k for k in st.session_state if k not in ("actor_id", "_pages", "_db_file")]:
                    del st.session_state[k]
                st.rerun()
    st.caption("Prototype · synthetic incidents · all containment and messages are simulated")
    if common.public_demo():
        st.info("Public demo: you have your own private copy of the demo data. Changes you make are not seen by "
                "other visitors and are discarded when you leave. Please don't enter real personal data.")

common.feedback("global")
common.show_toasts()
nav.run()
