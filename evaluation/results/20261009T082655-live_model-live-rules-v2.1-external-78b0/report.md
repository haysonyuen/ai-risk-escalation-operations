# Evaluation run 20261009T082655-live_model-live-rules-v2.1-external-78b0

* Kind: **live_model** — Live model outputs, scored against provisional labels.
* Rule version: `rules-v2.1`; controls: `controls-v1.2`; prompt: `prompt-v3`; model: `claude-opus-5`
* Split: `external`; cases: 20
* Held-out integrity: matches freeze = True, status = untouched
* Labels are provisional author-generated judgments on synthetic cases, not independently validated ground truth.

## Severity

| Metric | Before controls (valid assessments) | After deterministic controls (all cases) |
| --- | --- | --- |
| exact_match | 60.0% (12/20) | 60.0% (12/20) |
| within_acceptable_range | 100.0% (20/20) | 100.0% (20/20) |
| p0p1_precision | 69.2% (9/13) | 69.2% (9/13) |
| p0p1_recall | 100.0% (9/9) | 100.0% (9/9) |
| under-severity outside range (count) | 0 | 0 |
| over-severity outside range (count) | 0 | 0 |

### Confusion matrix after controls (rows = expected, cols = predicted)

| expected \ predicted | P0 | P1 | P2 | P3 | none |
| --- | --- | --- | --- | --- | --- |
| P0 | 1 | 1 | 0 | 0 | 0 |
| P1 | 0 | 7 | 0 | 0 | 0 |
| P2 | 0 | 4 | 2 | 0 | 0 |
| P3 | 0 | 0 | 3 | 2 | 0 |

## Routing, review and schema

* Primary route exact: 80.0% (16/20)
* Primary route within acceptable routes: 95.0% (19/20)
* Mandatory review flagged when required: 100.0% (15/15)
* Review flagged when not required (over-flagging): 100.0% (5/5)
* Schema-valid assessments: 100.0% (20/20)
* Failed assessments routed to manual review: undefined (no failures; 0/0)
* Facts with invalid evidence references: 0.0% (0/72)
* Claim-support accuracy: not reported — No human claim-support reviews recorded for this run (see claim_review_worksheet.csv).
* Latency ms (mean / p95, n): 42100.33854364992 / 57872.46779099951 (n=20)
* Estimated cost USD: 2.17445
* Category recall (labeled categories all predicted): 100.0% (18/18)
* C7 automatic pause: fired 1, expected 1; precision 100.0% (1/1); recall 100.0% (1/1); unwarranted none; missed none

## By scenario category (after controls)

| category | n | severity in range | route acceptable | review flagged when required |
| --- | --- | --- | --- | --- |
| EXTERNAL | 20 | 100.0% (20/20) | 95.0% (19/20) | 100.0% (15/15) |

## Failures (1)

| case | family | expected (acceptable) | rec. | after controls | route | problems | rules |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EXT-014 | X-EXTERNAL | P3 (P3) | P3 | P3 | model_behavior | route_not_acceptable | ROUTE-P3 |
