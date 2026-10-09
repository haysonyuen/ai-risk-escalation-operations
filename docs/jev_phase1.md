# Phase 1: Jev in shadow mode

**Goal:** measure how accurately TypeSafe's Jev (a decision model that answers typed questions
with a probability per option) judges **policy** and **severity** on our cases, independently of
the LLM, without affecting any decision. Then decide, against criteria fixed in advance, whether
Jev may become a reference for the LLM (Phase 2).

## Status

| Step | State |
|---|---|
| 0. Access | Done 2026-10-09, locally: both keys from `.env`, `api.typesafe.ai` reachable. (Cloud sessions withhold `ANTHROPIC_API_KEY`; see `docs/jev_phase1_handover.md`) |
| 1. Labels and new cases | Done: 20 external-source cases, Phase 1 labels on all 100 cases, conventions in `docs/policy_conventions.md` |
| 2. Question design | Done: `config/jev_questions.json` (`jev-questions-v1`) |
| 3. Build | Done: Jev client, shadow store, `jev-eval`, admin role and admin-only views, tests |
| 4. Tune on dev | Done 2026-10-09: Jev format fixed and model pinned (`jev-1.13.0`); chose variant A, severity approach B, `jev-questions-v1` with no revisions |
| 5. Final run and go/no-go | Done 2026-10-09, once: **NO-GO** (external split fails severity within range: 65% vs ≥ 80%) |

## Results (2026-10-09)

Synthetic, author-labelled cases (dev 44, held_out 36, external 20). These numbers say how Jev
agrees with the author's labels on these cases; they are not a measure of real-world performance.

**Choice made on dev, before the final run:** variant A (one 19-option policy choice), severity
approach B (Jev answers the six factors on the masked state; the rules engine computes severity),
questions `jev-questions-v1` unchanged. On dev, variants A and B scored identically on every
criterion; A was chosen because its answers did not change across 3 repeats (B changed one
severity answer) and it uses fewer questions. Severity approach B was chosen because on dev it
was within range on 93% vs 86% for A, with 1 vs 4 P0/P1 under-calls. The final run fixed this
choice with `--severity-approach B_factors_rules`.

### Pass criteria (Jev, variant A, severity approach B, 3 repeats)

| Criterion | Target | dev (tuning) | held_out (final) | external (final) |
|---|---|---|---|---|
| Severe-harm cases where Jev gives the severe policy < 20% | 0 | 0 of 11 | 0 of 11 ✅ | 0 of 6 ✅ |
| P0 cases called P2 or lower | 0 | 0 | 0 ✅ | 0 ✅ |
| Severity within the acceptable range | ≥ 80% | 93% (41/44) | 81% (29/36) ✅ | **65% (13/20) ❌** |
| Correct policy in the top 2 | ≥ 85% | 98% (43/44) | 97% (35/36) ✅ | 95% (19/20) ✅ |

**Decision: NO-GO.** The external split fails "severity within the acceptable range" (65% vs
≥ 80%). Held_out passes, with severity at 81%, one case above the threshold.

Not used for the decision (it would be choosing after seeing the test data): severity approach A
(Jev's direct P3→P0 score) was within range on 89% of held_out and 90% of external, with 2/16
and 1/9 P0/P1 under-calls. On dev it was the weaker approach.

### Other measurements (final runs)

| | held_out | external |
|---|---|---|
| Top policy correct | 89% (32/36) | 90% (18/20) |
| Severity B: P0/P1 under-calls | 12% (2/16: EVAL-052, EVAL-057) | 33% (3/9: EXT-005, EXT-008, EXT-013) |
| Severity B: over-calls | 14% (5/36) | 5% (1/20) |
| Case type | 89% | 95% |
| What happened | 92% | 80% |
| Evidence supports claim | 61% (20/33) | 75% (12/16) |
| Top policy changed across repeats | 0/36 | 0/20 |
| Errors | 0 | 0 |

### Jev vs the LLM (Claude Opus 5, `prompt-v3`, `rules-v2.1`, same splits)

| | Jev held_out | LLM held_out | Jev external | LLM external |
|---|---|---|---|---|
| Top policy correct | 89% | 92% (33/36) | 90% | 55% (11/20) |
| Correct policy in top 2 | 97% | 97% (35/36) | 95% | 85% (17/20) |
| Severity within range (model, before controls) | 81% (B) | 92% (33/36) | 65% (B) | 100% (20/20) |
| Severity within range (after deterministic controls) | n/a | 81% (29/36) | n/a | 100% (20/20) |
| P0/P1 under-calls (model) | 2/16 | 1/16 | 3/9 | 0/9 |
| P0 called P2 or lower | 0 | 0 | 0 | 0 |
| Failed requests | 0 | 0 | 0 | 0 |

The LLM's structured output (`output_config` json_schema) worked: 99 of 100 assessments were
schema-valid; the one failure (EVAL-011, dev) was a timeout and went to manual review.

### Cost (all runs on 2026-10-09)

| | Runs | Cost |
|---|---|---|
| Jev | 6 runs, 1.54M input tokens | $0.07 (reported list price, $0.042/M input; verify in the TypeSafe console) |
| LLM | 3 runs (dev, held_out, external), 100 assessments | $10.00 (estimate from the run outputs) |
| **Total** | | **≈ $10.07** |

Run directories in `evaluation/results/` (2026-10-09): Jev dev `…071739-…-ca53` (all HTTP 422,
before the format fix), `…071858-…-b01e`, `…074800-…-A-dev-4344`, `…074846-…-B-dev-c45a`;
Jev final `…081253-…-held_out-a334`, `…082716-…-external-1724`; LLM `…074704-…-dev-052e`,
`…081215-…-held_out-f70c`, `…082655-…-external-78b0`.

## How it works

```
case ──► rules + AI assessment (unchanged) ──► operator
   └──► Jev questions ──► shadow_results (write-only) ──► admin-only report
```

- **Isolation:** rules, workflow decisions, assessment and monitoring never read shadow results
  (`tests/test_jev_shadow.py`). A Jev failure never affects case handling.
- **Who sees it:** only the admin role (*Hayson — Admin*): Quality → **Jev shadow**, and a collapsed
  box on the case page. The role picker is a demo simulation, not a login.
- **When it runs:** after each AI assessment, only when `TYPESAFE_API_KEY` is set (setting
  `jev_shadow`, default on; `jev_variant`, default A). Local only; the hosted app has no key.

## Questions (`jev-questions-v1`)

| Question | Type | Runs on |
|---|---|---|
| Case type | choice (6) | all channels except telemetry alerts (taken from the channel) |
| Policy, **variant A** | one 19-option choice | every case |
| Policy, **variant B** | five severe-area yes/no + one 14-option choice | every case |
| What happened | choice (6) | every case |
| Severity, **approach A** (direct) | score P3→P0 | every case |
| Severity factors → **approach B** | six choices (scope, reversibility, sensitive data, external action, approval, recurrence), asked on a state **without** those fields; the existing rules engine then computes severity from Jev's answers | every case |
| Does the evidence support the claim? | choice (5) | all except telemetry alerts |

Each case costs two requests: one on the full state, one on the masked state for the factors.

## Pass criteria (fixed 2026-10-09, before any results)

| Criterion | Target |
|---|---|
| Severe-harm cases where Jev gives the severe policy < 20% | 0 |
| P0 cases called P2 or lower | 0 |
| Severity within the acceptable range | ≥ 80% |
| Correct policy in the top 2 | ≥ 85% |

## Running it (once Jev is reachable)

1. Add `api.typesafe.ai` under Allowed domains, and `TYPESAFE_API_KEY` / `ANTHROPIC_API_KEY` as
   secrets, in the environment settings; start a new session.
2. Confirm the response format with one case, then pin the model version (`JEV_MODEL`):
   `python -m riskops.cli jev-eval --split dev --variant A --repeats 1`
3. LLM baseline: `python -m riskops.cli eval --system live --rules rules-v2.1 --prompt prompt-v3 --split dev`
4. Tune on dev (at most two question revisions, each a new question version):
   `python -m riskops.cli jev-eval --split dev --variant A --repeats 3 --llm-run evaluation/results/<llm dev run>`
   and the same with `--variant B`.
5. Final, once, no changes afterwards: the chosen variant on `--split held_out` and `--split external`.

## Decisions made without owner review

The owner asked for Phase 1 to proceed without checkpoints. These were decided by the author and
should be reviewed when the results are read:

- **Labels are author labels.** Case type, what happened and evidence support for all 100 cases,
  and full labels for the 20 external cases, were written by the person who designed the Jev
  questions, after reading every case including the held-out ones. They were derived from the
  case text and existing rationales and not tuned to any Jev output (none existed).
- **Three convention questions** (EVAL-014, EVAL-055, EVAL-068; see `docs/policy_conventions.md`):
  both the frozen label and the "topic always" reading are accepted when scoring.
- **Detector false alarms keep the flagged policy area**, matching the existing labels (EVAL-004,
  -047, -053); "what happened = false alarm" records that there was no violation.
- **Admin role** sees everything but has no extra case-decision permissions.
- **Step 4–5 choices (2026-10-09):** variant A and severity approach B were chosen on dev (see
  Results). No question revisions were made. Jev's score answer is read as the most likely level
  rather than the expected score truncated down. 3 repeats were used for the final runs.

## Known limitations

- Jev's request/response format was confirmed against the live API (`jev-1.13.0`) on
  2026-10-09; score questions needed their levels sent as a `criteria` list. Unreadable answers
  are recorded as errors with the raw response, never guessed.
- Price per token is the reported list price; verify in the TypeSafe console.
- 100 synthetic, author-labelled cases: overall numbers are indicative; per-policy and
  per-confidence-band numbers are rough.
- The live LLM provider requests structured output; it worked against the live API on
  2026-10-09 (99/100 schema-valid, 1 timeout).
