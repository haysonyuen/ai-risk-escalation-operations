"""Admin-only views of Jev shadow results (Phase 1). Operators never see these, so Jev's answers
cannot sway their decisions while Jev is being measured."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st
from common import conn, current_actor, md, policy_label

from riskops import config, shadow
from riskops import workflow as wf
from riskops.providers import jev


def allowed() -> bool:
    return wf.can(current_actor(), "view_shadow")


def _pct(m: dict | None) -> str:
    if not m or m.get("value") is None:
        return "n/a"
    return f"{m['value']:.0%} ({m['num']}/{m['den']})"


def _runs() -> list[dict]:
    out = []
    for f in sorted(config.RESULTS_DIR.glob("*jev_shadow*/summary.json"), reverse=True):
        s = json.loads(f.read_text())
        if s.get("kind") == "jev_shadow":
            out.append(s)
    return out


def report() -> None:
    """Quality → Jev shadow (admin only)."""
    st.caption("Measured against the evaluation labels. Pass criteria were fixed before any results existed.")
    runs = _runs()
    if not runs:
        status = "a TYPESAFE_API_KEY is set" if jev.credentials_available() else "no TYPESAFE_API_KEY is set"
        st.info("No Jev shadow runs yet. Running one needs a Jev API key and network access to the Jev API "
                f"(here, {status}). Then run:\n\n`python -m riskops.cli jev-eval --split dev --variant A --repeats 3`")
        return
    names = [f"{s['run_id']} · {s['split']} · variant {s['variant']}" for s in runs]
    s = runs[names.index(st.selectbox("Run", names))]
    verdict = "PASS" if s["passed"] else "NOT PASSED"
    md(f"<b>{verdict}</b> · questions <code>{s['question_version']}</code> · model <code>{s['model']}</code> · "
       f"{s['cases']} cases × {s['repeats']} repeats · {s['errors']} errors")
    st.markdown("**Pass criteria** (fixed in advance)")
    st.dataframe(pd.DataFrame([{"Criterion": c["label"], "Target": c["target"],
                                "Result": f"{c['value']:.0%}" if isinstance(c["value"], float) else c["value"],
                                "": "✅" if c["passed"] else "❌"} for c in s["criteria"]]), hide_index=True, use_container_width=True)
    p = s["policy"]
    a, b = st.columns(2)
    with a:
        st.markdown("**Policy**")
        st.markdown(f"- Top policy correct: {_pct(p['top1'])}\n- Correct in top 2: {_pct(p['top2'])}\n"
                    f"- Severe-harm misses: {p.get('severe_policy_miss')} of {p.get('severe_cases')}")
        st.dataframe(pd.DataFrame([{"Jev confidence": x["band"], "Cases": x["cases"], "Top policy correct": _pct(x["top1_correct"])}
                                   for x in p.get("top1_by_confidence", [])]), hide_index=True, use_container_width=True)
    with b:
        st.markdown("**Severity**")
        st.dataframe(pd.DataFrame([{"Approach": "Direct (A)" if k.startswith("A") else "Factors → rules (B)",
                                    "Within range": _pct(m["within_range"]), "P0/P1 under-calls": _pct(m["under_calls_p0p1"]),
                                    "P0 → P2 or lower": m["p0_called_p2_or_lower"]} for k, m in s["severity"].items()]),
                     hide_index=True, use_container_width=True)
        st.markdown(f"- Case type: {_pct(s['case_type'])}\n- What happened: {_pct(s['harm_outcome'])}\n"
                    f"- Evidence supports claim: {_pct(s['evidence_support'])}")
    if c := s.get("llm_comparison"):
        st.markdown(f"**Compared with the LLM** (`{c['run']}`, {c['cases_compared']} cases)")
        st.markdown(f"- LLM top policy correct {_pct(c['llm_policy']['top1'])}, top 2 {_pct(c['llm_policy']['top2'])}; "
                    f"severity within range {_pct(c['llm_severity']['within_range'])}\n"
                    f"- Policy disagreements with Jev: {', '.join(c['policy_disagreements']) or 'none'}")
    st.caption(f"Stability across repeats: {json.dumps(s['stability'])} · input tokens {s['input_tokens']} · "
               f"estimated cost ${s['cost_usd_estimate']} · {s['labels_note']}")


def case_box(incident_id: str) -> None:
    """Case page: collapsed, admin-only box with this case's shadow answers."""
    if not allowed():
        return
    results = shadow.results_for(conn(), incident_id)
    with st.expander(f"Jev (shadow) · not used in decisions · {len(results)} result(s)"):
        if not results:
            st.caption("No shadow answers for this case. They are recorded after an AI assessment when a Jev API key is set.")
            return
        r = results[0]
        if r["error_kind"]:
            st.warning(f"Jev call failed ({r['error_kind']}): {r['error']}")
            return
        res = r["result"]
        top = res["policy_ranking"][:3]
        st.markdown("**Policy likelihood:** " + " · ".join(f"{policy_label(k)} {res['policy_probs'][k]:.0%}" for k in top))
        st.markdown(f"**Severity:** direct {res.get('severity_a', '—')} · from factors via rules {res.get('severity_b', '—')}")
        st.markdown(f"**Case type:** {res.get('case_type', '—')} · **What happened:** {res.get('harm_outcome', '—')} · "
                    f"**Evidence supports claim:** {res.get('evidence_support', '—')}")
        st.caption(f"Variant {r['variant']} · questions {r['question_version']} · model {r['model']} · {r['created_at']}")
