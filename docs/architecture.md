# Architecture and data model

## Design goals

* **Business logic is separate from the interface.** The `riskops/` package contains every rule, control, permission check and state transition. `app/` only calls those services. The tests call the same services directly, so no rule depends on the UI.
* **Simple, local, inspectable.** Python, Pydantic, SQLite and Streamlit. There is no agent framework, queue, server process or external service. The rules are JSON files that a reviewer can read.
* **Honest provenance.** Every assessment records where it came from (`live_model`, `offline_fixture`, `offline_simulation`, `fault_injection`) and which rule, prompt and control versions produced it. Every event records whether it came from `seed` history or a `demo` action.

## Component view

```text
             ┌───────────────────────── app/ (Streamlit) ─────────────────────────┐
             │ queue · workspace · intake · quality · rules · monitoring           │
             │ simulated identity selector (NOT authentication)                    │
             └───────────────┬──────────────────────────────────────────────────────┘
                             │ service calls only
┌────────────────────────────▼──────────────────────────────────────────────────────┐
│ riskops/workflow.py   state machine · permissions · decisions · containment ·    │
│                       closure · reopen · QA · links · claim reviews · rule change │
│ riskops/assessment.py provider → schema validation → evidence-ref check →         │
│                       deterministic controls C1–C6                                │
│ riskops/rules.py      versioned rules engine (playbooks/rules_*.json)            │
│ riskops/injection.py  embedded-instruction detection (flag, never obey)           │
│ riskops/providers/    OfflineFixture · OfflineSimulation · Anthropic · FaultInj.  │
│ riskops/communications.py  evidence-referenced drafts (never sent)                │
│ riskops/dedup.py      related-report suggestions with explanations                │
│ riskops/monitoring.py queue/SLA/override/failure metrics · regression gate        │
│ riskops/evaluation.py harness · metrics with denominators · reports               │
└────────────────────────────┬──────────────────────────────────────────────────────┘
                             │
                  SQLite data/riskops.db (events append-only via triggers)
```

## Assessment pipeline

```text
IncidentIntake ──► rules.evaluate(version) ──► RuleResult (signals, severity, floors,
      │                                         impact, evidence quality, confidence,
      │                                         categories, route, review reasons)
      └──────► provider.assess() ──► candidate JSON ──► AssessmentOutput (Pydantic, extra=forbid)
                                                         │ fail → C1 (no assessment, manual review)
                                                         ▼
                                        evidence-ID check (C2) → rule floor (C3) →
                                        injection flag (C4) → low-confidence/high-impact (C5) →
                                        specialist-route protection (C6)
                                                         ▼
                        assessment record: model_severity | controlled_severity | review reasons
```

Providers receive the incident inside `<incident_data>` delimiters. The prompts tell the model to treat that content as data. The output schema has no field that can approve, close, contain or send anything, and `extra="forbid"` rejects any output that adds one (fault test: `schema_violation`).

## State machine

| From | To | How |
| --- | --- | --- |
| NEW | ASSESSED / ASSESSMENT_FAILED | assessment (system or triage role) |
| ASSESSED, ASSESSMENT_FAILED | same / each other | reassessment (history kept) |
| NEW, ASSESSED, ASSESSMENT_FAILED, REOPENED | TRIAGED | human severity decision |
| TRIAGED | INVESTIGATING, RESPONSE | manual (requires human severity) |
| INVESTIGATING | CONTAINMENT, RESPONSE | manual |
| CONTAINMENT | INVESTIGATING, RESPONSE | manual |
| RESPONSE | INVESTIGATING | manual |
| RESPONSE | CLOSED | closure with sign-off only |
| CLOSED | QA_REVIEWED | QA review |
| CLOSED, QA_REVIEWED | REOPENED | reopen, or new evidence added |

Closure guards: a human-confirmed severity must exist and match `final_severity`. All required closure fields must be present, and the evidence-reviewed IDs must exist. No containment proposal can be left undecided. Any active simulated containment must be acknowledged. Drafts flagged for specialist review cannot be left pending. P0/P1 closures need the Incident Lead.

## Permissions (simulated roles)

| Action | Allowed roles |
| --- | --- |
| Create incident, add evidence, add note | any human role |
| Run assessment | system, Risk Ops, Incident Lead |
| Decide severity/route, assign owner, transitions, link decisions, QA, reopen | Risk Ops, Incident Lead |
| Propose containment | any human role, system (source recorded as `ai`) |
| Approve/reject containment | P2/P3: Risk Ops or Incident Lead. P0/P1: Incident Lead. Account lockout: Incident Lead and human-confirmed P0 |
| Draft communications | any human role, system |
| Approve flagged drafts | the flagged specialist (Legal/Privacy → `legal_privacy`, Safety → `safety_specialist`) |
| Close | P2/P3: Risk Ops or Incident Lead. P0/P1: Incident Lead |
| Change active rule version | Incident Lead |

The UI role selector exists for demonstration. It is not authentication, and the prototype has no real access control.

## Data model (SQLite)

| Table | Purpose | Key columns |
| --- | --- | --- |
| `incidents` | current state per case | `incident_id`, `intake_json`, `status`, `owner`, `current_assessment_id`, `human_severity`, `human_route`, `human_teams_json`, `severity_decided_by/at`, `first_human_review_at`, `closure_json`, `origin` |
| `evidence` | evidence records with stable IDs | (`incident_id`, `evidence_id`) PK, `source_type`, `source_description`, `content`, `added_by`, `origin` |
| `assessments` | every assessment ever run (never overwritten) | `provider_kind`, `model_name`, `prompt_version`, `rule_version`, `status`, `error_kind`, `output_json`, `rule_result_json`, `controls_json` (incl. `controls_version`), `model_severity`, `controlled_severity`, `controlled_route`, `mandatory_review`, latency/tokens/cost |
| `events` | append-only audit trail | `ts`, `actor_id`, `actor_role`, `event_type`, `field`, `previous_value`, `new_value`, `reason`, `origin`, `details_json` |
| `containment_actions` | simulated containment lifecycle | `status` (proposed/rejected/active/reversed/expired), `proposed_source`, `decided_by`, `review_by`, `expires_at`, `simulated=1` |
| `communications` | draft versions | (`comm_id`, `version`) PK, `comm_type`, `body`, `evidence_refs_json`, `specialist_review_json`, `status`, `generator` |
| `links` | related/duplicate suggestions and decisions | `incident_a/b`, `link_type`, `status`, `score`, `explanation`, `decided_by`, `reason` |
| `claim_reviews` | human claim-support verdicts per fact | `assessment_id`, `fact_index`, `verdict`, `reviewer` |
| `settings` | active rule/prompt version, provider mode | key/value |
| `eval_runs` | evaluation summaries shown in the UI | `run_id`, `summary_json`, `artifact_dir`, `origin` |

SQLite triggers reject `UPDATE` and `DELETE` on `events`. This is a local integrity guard. It is **not tamper-proof**: anyone with file access can alter or replace the database.

## Timestamps and provenance

* The seed script freezes the clock (`db.clock`) so seeded history has historical timestamps. Seeded rows carry `origin='seed'`.
* Actions taken in the app carry `origin='demo'`. JSON imports carry `origin='import'`.
* Monitoring reports seeded and demo timings in separate columns.

## Live provider

`riskops/providers/anthropic_live.py` uses the official `anthropic` SDK (`messages.create`). The model comes from `RISKOPS_LIVE_MODEL` (default `claude-opus-5`) and the key from `ANTHROPIC_API_KEY`. The provider handles timeouts, authentication, rate-limit, connection and HTTP errors, `stop_reason=refusal`, truncation at `max_tokens`, and non-JSON output. Each of these becomes a labeled failure that routes the case to manual review. Cost is an estimate based on list prices in the module. The key is never logged or stored.
