# Five-minute demo walkthrough

Setup (about 30 seconds):

```bash
python -m riskops.cli seed
streamlit run app/streamlit_app.py
```

Keep the sidebar provider on **Offline**. Every AI output in this demo is labeled either **"AI · offline fixture (hand-authored, not a model)"** or **"AI · offline simulation (deterministic, not a model)"**. No model is called. Containment is marked **SIMULATED** and drafts are marked **NOT SENT**. To show a live model call instead, set `ANTHROPIC_API_KEY` and choose *Live model*. The badge then reads **"AI · live model call"**.

The same steps are automated in `scripts/ui_walkthrough.py`, which produced the screenshots in `docs/screenshots/`.

---

### 0. The queue (20 s): `01_queue.png`
Point out:
* The separate columns for **AI recommendation after controls**, **AI source** (fixture, simulation or FAULT-INJ) and **human decision**.
* The overdue P0 (INC-1002) that is still awaiting a human decision.
* INC-1009, where the provider **failed** (a labeled fault-injection timeout) and the case shows "rules fallback; AI failed".
* The filters for severity, status, category, owner and review requirement.

### 1. Intake of an ambiguous but potentially urgent incident (40 s): `02_intake_imported_report.png`
Go to *New intake* → *JSON import* → **Load walkthrough example** → **Import**.
* DEMO-2001: an enterprise admin sees a share link on a customer renewals spreadsheet and can't tell who can open it.
* The unknown fields (scope, recurrence, reversibility, external action) stay **explicitly unknown**, shown in red.
* Related-report suggestions run automatically. Nothing is merged.

### 2. AI assessment with evidence and unknowns (60 s): `03_ai_assessment.png`
Open the *AI assessment* section.
* Source badge: **offline fixture**. Rules `rules-v1.0`, prompt `prompt-v1`, controls `controls-v1.1`.
* **Potential impact** high, **evidence quality** partial, **confidence** low. These are separate from severity.
* The provider recommends **P2 → product_ux**. After deterministic controls, the recommendation is **P1 → legal_privacy**:
  * **C3** raised it to the rules floor.
  * **C6** kept the specialist route.
  * **C5** flagged it because low confidence on a high-impact case must not become low severity.
* One fact cites evidence **E5, which does not exist**. **C2** marks it `INVALID REF`. Facts with valid references are marked "support unverified", with a form to record a human support review.
* Hypotheses are listed separately from facts, and missing information is listed explicitly.

### 3. Human correction with a recorded reason (40 s): `04_human_override.png`
Acting as *Alex (Risk Ops, simulated)*, open *Triage, routing & notes*. Choose **P0**, evidence reviewed E2/E3/E4, reason **AI under-estimated severity**, and a written rationale. Record the decision and assign the owner *jordan.legal*.
* The service layer rejects this decision without a reason code, without a written rationale, or (for P0/P1) without the evidence-reviewed list.
* The header now shows the human decision **P0** next to the AI's **P1** after controls. The AI recommendation is not overwritten.

### 4. Specialist routing and simulated containment approval (50 s): `05_…`, `06_…`
*Containment*: click **Propose** on the AI-suggested option (`restrict_tool_action`, reversible). The proposal is recorded with source `ai`.
* As Alex, click **Approve (simulated)**. The action is **blocked by the service-layer permission check**, because P0 containment needs the Incident Lead.
* Switch identity to *Sam (Incident Lead)* and approve. The action becomes **ACTIVE · SIMULATED**, with a review time (24 h) and an expiry (72 h).

### 5. Executive brief (40 s): `07_executive_brief.png`
*Communications*: **Draft: Executive incident brief**. The draft contains:
* severity (human-confirmed);
* impact;
* facts with evidence IDs and their verification status;
* uncertainty (unknowns and confidence);
* actions (simulated), owners;
* the next decision needed.

It is flagged **needs Legal/Privacy review** and **NOT SENT**. Sam's approval is refused, because the draft requires Legal/Privacy. Switch to *Jordan (Legal/Privacy)* and approve.

### 6. Human-approved closure (50 s): `08_closed.png`, `09_audit_timeline.png`
As Sam:
1. Move the case to INVESTIGATING and add a note.
2. Add evidence **E5** (a synthetic access log showing no external views).
3. Move the case to RESPONSE.
4. Reverse the containment with a reason.
5. Fill in the closure form: category, final severity (it must match the human decision), root cause, impact, evidence reviewed, teams, actions, response status, remaining mitigation, monitoring, and sign-off.

The service refuses closure if a containment proposal is undecided, if active containment has not been acknowledged, if a flagged draft is still pending, if the evidence IDs are unknown, or if the actor lacks the Incident Lead role for P0/P1. *Timeline & audit* shows every append-only event, with actor, role, previous value, new value, reason and origin (`demo` versus `seed`).

### 7. Rule change followed by regression evaluation (50 s): `10_regression_alert_v11.png`, `11_quality_page.png`
*Rules & playbooks* → *Change rules + regression check*. As Sam, switch the active version to **rules-v1.1** with a rationale. This is logged and does not touch existing assessments or decisions. Then run the regression check: baseline v1.0 against candidate v1.1 on the **frozen held-out** split.
* Result: **QUALITY ALERT — P0/P1 recall 92.9% → 85.7%**. v1.1 improved severity-range accuracy but newly misses EVAL-048. This is a real regression in the author's own revision, observed on synthetic data. It is not production drift.
* For a **simulated degradation** demo, choose `rules-v1.1-fault-demo` as the candidate. That fault-injection rule set drops a review condition; in the CLI fault run on all 80 cases, mandatory-review compliance falls to 30/45.
* Finish on *Quality & evaluation*: runs with denominators, confusion matrices, the category breakdown, the failure list, and the limitations banner. Live-model evaluation is shown as **pending**.

Close by pointing to `docs/evaluation.md` for the observed failures and fault-injection results.
