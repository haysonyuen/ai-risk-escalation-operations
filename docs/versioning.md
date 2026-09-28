# Rule, prompt and control versioning

Every assessment stores the **rule version**, **prompt version**, **controls version**, provider kind and model name that produced it. Reassessment adds a new record; earlier ones are kept. Evaluation summaries store the same identifiers.

## Rule versions (`playbooks/rules_*.json`)

| Version | Status | Origin |
| --- | --- | --- |
| `rules-v1.0` | baseline (active by default) | Written directly from the framework's severity table before any evaluation. Keyword lexicons plus structured intake fields. |
| `rules-v1.1` | revised candidate | Written only from the **development-split** failures of v1.0. Each change in its `changelog` cites the dev cases behind it. It was evaluated on held-out data after being finalized and showed a P0/P1 recall regression (see evaluation.md), so it was not promoted. |
| `rules-v1.1-fault-demo` | FAULT INJECTION | A deliberately broken copy (REV-01, FLOOR-01 and SEV-P1-01 removed). It exists only to demonstrate the regression gate. Its runs are labeled `fault_injection`, and any alert it triggers is simulated degradation. |

A rule file contains:
* `lexicons`: keyword signals.
* `severity_rules`: ordered, first match wins.
* `severity_floors`: raise-only, evaluated after impact and evidence quality are known.
* `impact_rules`, `category_rules`, `route_priority`, `teams`, and optional `p3_routing`.
* `mandatory_review` conditions.
* `containment_options`: reversible options, each with an `offer_at_or_above` severity.

Conditions use `all` / `any` / `none` over named signals, so every rule can be read in the UI (Rules & playbooks → Readable rules).

### Changing rules (governed)

1. Create a new file with a new `rule_version`, a `parent_version` and a `changelog` that cites the evidence behind each change. Do not edit an evaluated version in place. For example, the reported-only refusal limitation in v1.1 is recorded as a strict `xfail` test instead of being patched into v1.1.
2. Run the regression gate against the baseline on the **held-out** split (UI: Rules & playbooks → Change rules + regression check, or `python -m riskops.cli eval ...` followed by `compare`). The gate flags any drop in P0/P1 recall, mandatory-review compliance or schema validity, and any drop of more than 5 percentage points in severity-range or route accuracy.
3. Only the Incident Lead role can switch the active version, and a rationale is required. The switch is logged as a `rule_version_changed` event. **It does not modify existing assessments or human decisions.** A case is re-scored only when someone re-runs its assessment, and the reassessment never changes the human decision (a disagreement is logged).
4. If held-out failures are used to motivate a change, record a disclosure in `data/eval/FREEZE.json`, set its status to `used-for-tuning`, and stop calling that set untouched.

## Prompt versions (`riskops/prompts/`)

| Version | Notes |
| --- | --- |
| `prompt-v1` | Baseline assessment prompt: the framework definitions, the untrusted-data instruction, and the JSON schema (generated from `AssessmentOutput`). |
| `prompt-v2` | Revision based on the v1.0 dev failures. It orders the assessment as impact, then evidence, then severity; states that low confidence must not lower severity; tells the model to treat refusals and benign words explicitly; and asks it to list contradictions. **It has not been evaluated against a live model.** |

Prompts matter only in live mode. Offline fixtures and the simulation do not read them, although the version is still recorded.

## Controls versions (`riskops/assessment.py: CONTROLS_VERSION`)

| Version | Change |
| --- | --- |
| `controls-v1.0` | Initial C1–C6. |
| `controls-v1.1` | Role labels inside `conversation_excerpt` evidence (for example "Assistant: …") no longer count as role impersonation. The false positive was observed on seeded demo case INC-1001. On held-out data, this fix showed that EVAL-066's earlier mandatory-review flag had been accidental (see evaluation.md). |

Controls are applied after any provider and do not depend on the rule version. They can raise severity and add review requirements. They never lower severity.

## SLA configuration (`config/sla.json`)

The numeric targets (P0: 60 minutes to first human review, P1: 240 minutes, and so on) are **prototype assumptions** chosen for the demo. They are not any company's policy, and the original framework does not specify them; it states only postures such as "same-hour" and "same-day". The file is versioned as `sla-demo-1`.
