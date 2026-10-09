# Phase 1: Jev in shadow mode

**Goal:** measure how accurately TypeSafe's Jev (a decision model that answers typed questions
with a probability per option) judges **policy** and **severity** on our cases, independently of
the LLM, without affecting any decision. Then decide, against criteria fixed in advance, whether
Jev may become a reference for the LLM (Phase 2).

## Status

| Step | State |
|---|---|
| 0. Access | Anthropic API reachable. **Jev API not reachable from this environment** (`api.typesafe.ai` blocked by the network policy); no keys stored as secrets yet |
| 1. Labels and new cases | Done: 20 external-source cases, Phase 1 labels on all 100 cases, conventions in `docs/policy_conventions.md` |
| 2. Question design | Done: `config/jev_questions.json` (`jev-questions-v1`) |
| 3. Build | Done: Jev client, shadow store, `jev-eval`, admin role and admin-only views, tests |
| 4. Tune on dev | **Waiting for Jev access** |
| 5. Final run and go/no-go | **Waiting for Jev access** (and the LLM baseline, which needs `ANTHROPIC_API_KEY` as a secret) |

No Jev or LLM results exist yet. Nothing in the app or this document reports any.

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

## Known limitations

- Jev's request/response format comes from third-party guides; it is isolated in
  `riskops/providers/jev.py` and will be confirmed by the first live call. Unreadable answers are
  recorded as errors with the raw response, never guessed.
- Price per token is the reported list price; verify in the TypeSafe console.
- 100 synthetic, author-labelled cases: overall numbers are indicative; per-policy and
  per-confidence-band numbers are rough.
- A test call to the live LLM (Claude Opus 5, `prompt-v3`) returned malformed JSON. The live
  provider now requests structured output; this is untested against the live API.
