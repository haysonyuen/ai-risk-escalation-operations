# AI Risk & Escalation Operations

A locally runnable **prototype** of an AI-assisted incident triage and escalation workflow for early harm signals from an AI work assistant. It implements the conceptual operating framework in [`docs/framework.md`](docs/framework.md): an eight-stage process, P0–P3 severity, proportional containment, and clear human accountability.

It shows how Trust & Safety incident-response judgment can become working software: evidence-linked AI assessments, explicit deterministic controls, human decisions and overrides with recorded reasons, governed rule versions, and a repeatable evaluation harness with a frozen held-out set.

> **What this is not.** This is a portfolio prototype that uses **synthetic incidents**. Containment and communications are **simulated**; nothing is sent or enforced. Roles are **simulated identities**, not authentication. No real organisation uses it, and it makes no claims about production reliability, harm reduction or business impact. Offline "AI" outputs are hand-written fixtures or a deterministic simulation, **not measured model performance**. No live-model evaluation has been run yet (details below).

---

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m riskops.cli seed                 # create data/riskops.db with 12 synthetic incidents
streamlit run app/streamlit_app.py         # http://localhost:8501
```

Everything runs offline. For the optional live model mode, copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY` (and optionally `RISKOPS_LIVE_MODEL`). If the key is missing, live mode **fails visibly**: cases go to manual review, and live evaluation refuses to run. It never falls back to offline results silently.

| Task | Command |
| --- | --- |
| Reset and seed the demo database | `python -m riskops.cli seed` (or **Reset demo data** in the sidebar) |
| Run the tests | `python -m pytest -q` |
| Reproduce every evaluation artifact | `./scripts/run_all_evals.sh` |
| Run one evaluation | `python -m riskops.cli eval --system rules --rules rules-v1.1 --split held_out` |
| Compare runs | `python -m riskops.cli compare evaluation/results/<run> evaluation/results/<run>` |
| Live-model evaluation (pending, needs a key) | `python -m riskops.cli eval --system live --rules rules-v1.1 --prompt prompt-v2 --split dev` |
| Regenerate the dataset / fixtures | `python scripts/generate_eval_dataset.py` · `PYTHONPATH=. python scripts/build_fixtures.py` |
| Browser smoke test / scripted demo (app running) | `python scripts/ui_smoke.py` · `python scripts/ui_walkthrough.py docs/screenshots` |

The five-minute demo script is in [`docs/demo_walkthrough.md`](docs/demo_walkthrough.md).

---

## What is implemented

**The eight-stage workflow** is an explicit state machine (`riskops/workflow.py`). Every transition is validated, and every state change is written as an append-only event:

`NEW` (1 Intake) → `ASSESSED` / `ASSESSMENT_FAILED` (2 AI enrichment) → `TRIAGED` (3 Human severity triage) → `INVESTIGATING` (4) → `CONTAINMENT` (5) → `RESPONSE` (6) → `CLOSED` (7, human sign-off) → `QA_REVIEWED` (8). New evidence on a closed case moves it to `REOPENED`.

**Separation of concerns on every case**
* *Potential impact* and *evidence quality / confidence* are assessed separately from severity.
* The *provider recommendation* (from a model, fixture or simulation) is stored separately from the *recommendation after deterministic controls*.
* The *human-confirmed severity* lives only on the incident and is never overwritten by reassessment or rule changes.

**Always-on deterministic controls (`controls-v1.1`)**

| ID | Control |
| --- | --- |
| C1 | A provider failure, malformed output or schema-invalid output means no assessment is invented. The case goes to manual review, and the labeled rules recommendation is shown. |
| C2 | Every cited evidence ID must exist in the case. Invalid references are flagged. A valid reference is not treated as proof: claim support is reviewed separately. |
| C3 | Controls never lower severity. A provider recommendation below the rules recommendation is raised to it. |
| C4 | Instructions embedded in report text are flagged for review and never followed. |
| C5 | Low confidence on a potentially high- or critical-impact case triggers mandatory review. Low confidence does not mean low severity. |
| C6 | If the suggested route differs from a specialist route (Safety, Legal/Privacy, Product Security), the specialist route is kept and the case is flagged. |

**Human accountability is enforced in the service layer, not the UI:**
* Only Risk Ops or the Incident Lead can decide severity.
* Overrides need a reason code and a written rationale.
* P0/P1 decisions must list the source evidence that was reviewed.
* P0/P1 containment and closure need the Incident Lead. Account lockout is allowed only for human-confirmed P0.
* Drafts flagged for Legal/Privacy or Safety need that specialist's approval.
* The AI/system actor can only assess, propose and draft.

Tests call the services directly to confirm these checks can't be bypassed.

**Other capabilities**
* Manual and JSON intake, with explicit unknowns.
* Related-report suggestions with explanations. A reviewer confirms each link; evidence is never merged or suppressed.
* Evidence-referenced communication drafts: executive brief, cross-functional handoff, user acknowledgment and closure summary. All are marked NOT SENT and keep version history.
* Simulated containment with review and expiry times, reversal, and automatic expiry.
* Operational monitoring that keeps seeded history separate from demo actions, reports repeat issues as counts only, and uses configurable prototype SLA targets (`config/sla.json`).
* A regression gate and quality alert that compares rule versions on the frozen held-out split.

## Evaluation status (what actually ran)

The evaluation uses 80 synthetic cases in 23 scenario families: 44 development cases and 36 held-out cases, split by family. The held-out set was frozen with a SHA-256 hash **before any tuning** (`data/eval/FREEZE.json`, which also records one disclosed title-neutrality edit made before any held-out run). Labels are **provisional author judgments**, not validated ground truth.

| Rules-only (deterministic) | v1.0 dev | v1.1 dev* | v1.0 held-out | v1.1 held-out |
| --- | --- | --- | --- | --- |
| Severity within acceptable range | 35/44 | 44/44 | 29/36 | 31/36 |
| P0/P1 recall | 14/16 | 15/16 | **13/14** | **12/14** |
| P0/P1 precision | 14/17 | 15/16 | 13/16 | 12/14 |
| Route acceptable | 36/44 | 43/44 | 32/36 | 33/36 |
| Mandatory-review compliance | 18/22 | 22/22 | 18/23 | 18/23 |

\*rules-v1.1 was written from the v1.0 dev failures, so its dev results are optimistic by construction. On held-out data, v1.1 put more cases in the acceptable severity range but **lost one P0/P1 case** (EVAL-048). The regression gate flags this, and it is documented rather than tuned away. The rules-v1.0 baseline remains the active default.

* **Live-model evaluation: pending.** No `ANTHROPIC_API_KEY` was available. The harness, prompts (`prompt-v1`, `prompt-v2`), schema validation, cost and latency capture, and refusal/timeout handling are implemented and tested with mocked clients. The exact command is in the table above.
* **Claim-support accuracy: not reported.** No human reviews were recorded. Blank worksheets are written with every run.
* **Fault-injection runs** (labeled as such) confirm the safeguards. With a provider that under-calls every case as P3, P0/P1 recall before controls is 0/30 and after controls is 27/30. Timeouts, malformed JSON and schema violations are all routed to manual review (80/80 each).

Full method, results, observed failures and limitations: [`docs/evaluation.md`](docs/evaluation.md).

## Documentation

| Document | Contents |
| --- | --- |
| [docs/framework.md](docs/framework.md) | Original conceptual framework (preserved source document) |
| [docs/architecture.md](docs/architecture.md) | Architecture, modules, data model, state machine, controls |
| [docs/versioning.md](docs/versioning.md) | Rule, prompt and control versioning; governance of rule changes |
| [docs/evaluation.md](docs/evaluation.md) | Evaluation methodology, results, observed failures, fault injection, limitations |
| [docs/demo_walkthrough.md](docs/demo_walkthrough.md) | Five-minute demo script with screenshots |
| [docs/case_study.md](docs/case_study.md) | Decisions and tradeoffs |
| [docs/requirements_traceability.md](docs/requirements_traceability.md) | Requirement → code / test / result table |
| [docs/timed_review_protocol.md](docs/timed_review_protocol.md) | Optional procedure for a future timed-review user study |

## Repository layout

```text
riskops/            business logic (no UI code)
  schemas.py        Pydantic intake and assessment contracts
  rules.py          versioned deterministic rules engine
  injection.py      embedded-instruction detection
  assessment.py     provider → schema → evidence refs → controls
  providers/        offline fixture/simulation, live Anthropic, fault injection
  prompts/          prompt-v1.md, prompt-v2.md
  workflow.py       state machine, decisions, containment, closure, links, permissions
  communications.py evidence-referenced drafts (never sent)
  monitoring.py     queue, ops metrics, regression gate
  evaluation.py     evaluation harness and metrics
  db.py, seed.py, cli.py
app/                Streamlit UI (views call riskops services only)
playbooks/          rules_v1.0.json, rules_v1.1.json, rules_v1.1-fault-demo.json
config/sla.json     prototype SLA assumptions
data/eval/          cases.jsonl, labels.jsonl, splits.json, FREEZE.json
data/demo/          seed incidents and the walkthrough intake example
fixtures/           hand-authored assessment fixtures (labeled, not model outputs)
evaluation/results/ evaluation artifacts from the runs listed above
tests/              pytest suite
docs/               documentation and screenshots
```

## Project status

* **Implemented and tested locally:** the full workflow, UI, rules v1.0/v1.1, controls, offline providers, the fault-injection harness, the evaluation harness, and the seed/reset command. There are 53 automated tests passing, plus 1 strict expected-failure that documents a known rules-v1.1 limitation. A browser smoke test covered every view, and the seven-step demo was driven end to end through the UI in headless Chromium.
* **Simulated:** containment, communications, identities and roles, historical timestamps (seeded), and offline AI outputs.
* **Unvalidated:** labels (single author), live-model quality (not run), claim-support accuracy (no reviews), and any time-savings claim (no study; see the protocol).
