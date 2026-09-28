# Five-minute demo walkthrough

Setup (about 30 seconds):

```bash
python -m riskops.cli seed
streamlit run app/streamlit_app.py
```

Keep **Demo settings → AI assessment provider** on *Offline*. Every AI output in this demo carries a badge: **"Offline fixture · not a model"** or **"Offline simulation · not a model"**. No model is called. Containment is marked **SIMULATED** and drafts are marked **NOT SENT**. With `ANTHROPIC_API_KEY` set and *Live model* selected, the badge reads **"Live model"**.

The same steps are automated in `scripts/ui_walkthrough.py`, which produced the screenshots in `docs/screenshots/`.

---

### 0. The queue (20 s): `01_queue.png`
* The **Needs action** view lists the most urgent cases first. Point out the overdue P0 (INC-1002) that is still waiting for a human decision.
* The **Severity** column shows where each severity comes from: `P0 · AI` means an unconfirmed recommendation, and `P2 ✓` means a human confirmed it.
* **Next action** says what each case needs.
* INC-1009 shows `P1 · rules` and "AI failed". The provider failed (a labeled fault-injection timeout), so a manual review is required.
* Click any row to open the case.

### 1. Intake of an ambiguous but potentially urgent incident (40 s): `02_case_after_import.png`
Go to *New report* → **Import JSON** → **Load the walkthrough example** → **Import**. The case opens automatically.
* DEMO-2001: an enterprise admin sees a share link on a customer renewals spreadsheet and can't tell who can open it.
* Unknown fields (scope, recurrence, reversibility, external action) show as **Unknown** in red.
* The **Next** panel says: *Decide severity and routing — you can do this*.

### 2. AI assessment with evidence and unknowns (60 s): `03_ai_assessment_facts.png`
Stay on *Overview* and scroll to **AI assessment**.
* **AI recommends P2 → Product/UX.** **After safety controls: P1 → Legal/Privacy.** The page explains why: the recommendation was raised to the rules minimum, and the specialist route was kept.
* Impact, evidence and confidence are shown separately from severity: *Potential impact: high*, *Evidence: partial*, *Confidence: low*.
* **Why a human must review this** lists the reasons, including a cited evidence ID that doesn't exist.
* Each extracted fact appears **next to the evidence text it cites**. Fact 3 cites **E5, which does not exist in this case**, and is marked in red. One click records whether each fact is supported.

### 3. Human correction with a recorded reason (40 s): `04_decision_recorded.png`
As *Alex (Risk Ops)*, in the **Severity & routing decision** card:
1. Choose **P0**.
2. Select evidence E2, E3 and E4.

The button changes to **Record override** and asks for an override reason. Choose **AI under-estimated severity**, write a rationale, and record it. Then assign the owner *Jordan — Legal/Privacy*.
* The header now reads **P0 · confirmed**. The AI's P1 recommendation stays on record.
* Without a reason code, a written rationale, or (for P0/P1) the evidence-reviewed list, the service rejects the decision.

### 4. Specialist routing and simulated containment approval (50 s): `05_…`, `06_…`
Open **Containment** → **＋ Propose containment** → **Propose this** (the AI-suggested `restrict tool action`).
* As Alex, **Approve is disabled**. The card explains: *Approval at P0 (confirmed) requires Incident Lead*. The service layer enforces the same rule; see the tests.
* Switch *Working as* to **Sam (Incident Lead)**, give a reason, and click **Approve**. The action becomes **ACTIVE · simulated**, with a review time (24 h) and an expiry (72 h).

### 5. Executive brief (40 s): `07_executive_brief_dialog.png`
**Communications** → **＋ New draft** → *Executive incident brief* → **Open draft**. The brief contains:
* severity (human-confirmed);
* impact;
* facts with evidence IDs and their verification status;
* uncertainty;
* actions (simulated) and owners;
* the next decision needed.

It is flagged **Legal/Privacy review needed** and **NOT SENT**. As Sam, **Approve is disabled** ("Needs review by Legal/Privacy"). Switch to **Jordan (Legal/Privacy)**, open the draft and approve it.

### 6. Human-approved closure (50 s): `08_case_closed.png`, `09_activity_feed.png`
As Sam:
1. Click **Start investigation**, then add a note under *Activity*.
2. Under *Evidence*, click **＋ Add evidence** and add E5, a synthetic access log showing no external views.
3. Click **Move to response**.
4. **Reverse containment**, giving a reason.
5. Click **Close case…**. The *Closure* card lists any blockers first (undecided proposals, pending specialist reviews). The dialog pre-fills the evidence and teams; enter the root cause, impact, actions and sign-off, then submit.

*Activity* shows every event as a sentence: who, what, when, with the reason. It also marks seeded history versus demo actions. The raw append-only audit log is available below the feed.

### 7. Rule change followed by regression evaluation (50 s): `10_regression_alert.png`, `11_dashboard.png`, `12_quality.png`
*Rules & playbooks* → **Change rules + regression check**.
1. As Sam, switch the active version to **rules-v1.1** with a rationale. The change is logged and does not touch existing assessments or decisions.
2. Click **Run regression check** (baseline v1.0 against v1.1 on the **frozen held-out** split).
* Result: **QUALITY ALERT — P0/P1 recall 92.9% → 85.7%**. v1.1 fits more cases into the acceptable severity range but newly misses EVAL-048. This is a real regression in the author's own revision, observed on synthetic data. It is not production drift.
* The **Dashboard** now shows the alert at the top.
* For a **simulated degradation** demo, choose `rules-v1.1-fault-demo` as the candidate. In the CLI fault run on all 80 cases, mandatory-review compliance falls to 30/45.
* Finish on *Quality & evaluation*: runs with denominators, confusion matrices, the category breakdown, the failure list, and the limitations banner. Live-model evaluation is shown as **pending**.
