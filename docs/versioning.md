# Rule, prompt and control versioning

Every assessment stores the **rule version**, **prompt version**, **controls version**, provider kind and model name that produced it. Reassessment adds a new record; earlier ones are kept. Evaluation summaries store the same identifiers.

## Rule versions (`playbooks/rules_*.json`)

| Version | Status | Origin |
| --- | --- | --- |
| `rules-v2.0` | baseline (active by default) | Taxonomy v2 (frontier-lab harm areas). Written from the framework's severity table plus lessons carried over from v1, before the v2 dataset existed. Severe-harm areas are detected from structured restricted-evidence fields (`policy_area=…`, `content_provided=…`). |
| `rules-v2.1` | revised candidate | Written only from the **development-split** failures of v2.0; each `changelog` entry cites the dev cases behind it. On held-out data it matched v2.0 exactly on severity (30/36), with slightly better category recall. The gate shows no regression, but also no evidence of improvement. |
| `rules-v2.1-fault-demo` | FAULT INJECTION | A deliberately broken copy (REV-01, FLOOR-01 and SEV-P0-CHILD removed). It exists only to demonstrate the regression gate, including the loss of automatic pauses. Its runs are labeled `fault_injection`. |
| `rules-v1.0`, `rules-v1.1`, `rules-v1.1-fault-demo` | archived (`playbooks/archive/`) | Taxonomy v1 (generic categories). They are not loaded by the app because their categories do not exist in taxonomy v2. They are kept for reproducibility of `evaluation/archive_v1/`. |

A rule file contains:
* `lexicons`: keyword signals.
* `derived_signals` (v2.0+): named combinations of other signals, e.g. `refused_not_provided`.
* `severity_rules`: ordered, first match wins.
* `severity_floors`: raise-only, evaluated after impact and evidence quality are known.
* `impact_rules`, `category_rules`, `route_priority`, `teams`, and optional `p3_routing`.
* `mandatory_review` conditions.
* `containment_options`: reversible options, each with an `offer_at_or_above` severity.

Conditions use `all` / `any` / `none` over named signals, so every rule can be read in the UI (Rules & playbooks → Readable rules).

### Changing rules (governed)

1. Create a new file with a new `rule_version`, a `parent_version` and a `changelog` that cites the evidence behind each change. Do not edit an evaluated version in place. For example, the v2 held-out misses (EVAL-052, EVAL-057…) are documented in evaluation.md, not patched into v2.1.
2. Run the regression gate against the baseline on the **held-out** split (UI: Rules & playbooks → Change rules + regression check, or `python -m riskops.cli eval ...` followed by `compare`). The gate flags any drop in P0/P1 recall, mandatory-review compliance, schema validity or C7 automatic-pause recall, and any drop of more than 5 percentage points in severity-range or route accuracy.
3. Only the Incident Lead role can switch the active version, and a rationale is required. The switch is logged as a `rule_version_changed` event. **It does not modify existing assessments or human decisions.** A case is re-scored only when someone re-runs its assessment, and the reassessment never changes the human decision (a disagreement is logged).
4. If held-out failures are used to motivate a change, record a disclosure in `data/eval/FREEZE.json`, set its status to `used-for-tuning`, and stop calling that set untouched.

## Prompt versions (`riskops/prompts/`)

| Version | Notes |
| --- | --- |
| `prompt-v3` | Current. Taxonomy v2 categories and routes; an explicit instruction never to reproduce harmful specifics; explains the C7 automatic pause so the model does not under-call to avoid it. **Not yet evaluated against a live model.** |
| `prompt-v1`, `prompt-v2` | Archived in `riskops/prompts/archive/` (taxonomy v1). |

Prompts matter only in live mode. Offline fixtures and the simulation do not read them, although the version is still recorded.

## Controls versions (`riskops/assessment.py: CONTROLS_VERSION`)

| Version | Change |
| --- | --- |
| `controls-v1.0` | Initial C1–C6. |
| `controls-v1.1` | Role labels inside `conversation_excerpt` evidence (for example "Assistant: …") no longer count as role impersonation (a false positive seen on a v1 demo case). |
| `controls-v1.2` | **C7 automatic pause** for P0 CBRN / child-safety recommendations, and C6 specialist routes extended to Child Safety and Threat Intel (taxonomy v2). |

Controls are applied after any provider and do not depend on the rule version. They can raise severity, add review requirements and (C7 only) apply one reversible, simulated session pause that a person must confirm or lift. They never lower severity.

## Taxonomy and demo data versions

* `taxonomy-v2` (`riskops/schemas.py: TAXONOMY_VERSION`): 19 risk categories, 10 routes, 13 containment types.
* The demo database stores `demo_data_version`. A local database built from older demo data is rebuilt automatically on first load, because its schema and categories no longer match.

## SLA configuration (`config/sla.json`)

The numeric targets (P0: 60 minutes to first human review, P1: 240 minutes, automatic-pause review within 60 minutes, and so on) are **prototype assumptions** chosen for the demo. They are not any company's policy, and the original framework does not specify them; it states only postures such as "same-hour" and "same-day". The file is versioned as `sla-demo-1`.
