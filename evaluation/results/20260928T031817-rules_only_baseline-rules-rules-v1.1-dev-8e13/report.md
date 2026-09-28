# Evaluation run 20260928T031817-rules_only_baseline-rules-rules-v1.1-dev-8e13

* Kind: **rules_only_baseline** — Deterministic rules; says nothing about model quality.
* Rule version: `rules-v1.1`; controls: `controls-v1.1`; prompt: `None`; model: `None`
* Split: `dev`; cases: 44
* Held-out integrity: matches freeze = True, status = untouched
* Labels are provisional author-generated judgments on synthetic cases, not independently validated ground truth.

## Severity

| Metric | Before controls (valid assessments) | After deterministic controls (all cases) |
| --- | --- | --- |
| exact_match | 84.1% (37/44) | 84.1% (37/44) |
| within_acceptable_range | 100.0% (44/44) | 100.0% (44/44) |
| p0p1_precision | 93.8% (15/16) | 93.8% (15/16) |
| p0p1_recall | 93.8% (15/16) | 93.8% (15/16) |
| under-severity outside range (count) | 0 | 0 |
| over-severity outside range (count) | 0 | 0 |

### Confusion matrix after controls (rows = expected, cols = predicted)

| expected \ predicted | P0 | P1 | P2 | P3 | none |
| --- | --- | --- | --- | --- | --- |
| P0 | 3 | 1 | 0 | 0 | 0 |
| P1 | 2 | 9 | 1 | 0 | 0 |
| P2 | 0 | 1 | 8 | 1 | 0 |
| P3 | 0 | 0 | 1 | 17 | 0 |

## Routing, review and schema

* Primary route exact: 81.8% (36/44)
* Primary route within acceptable routes: 97.7% (43/44)
* Mandatory review flagged when required: 100.0% (22/22)
* Review flagged when not required (over-flagging): 9.1% (2/22)
* Schema-valid assessments: 100.0% (44/44)
* Failed assessments routed to manual review: undefined (no failures; 0/0)
* Facts with invalid evidence references: 0.0% (0/74)
* Claim-support accuracy: not reported — No human claim-support reviews recorded for this run (see claim_review_worksheet.csv).
* Latency ms (mean / p95, n): 0.03405515910385888 / 0.05426600000646431 (n=44)
* Estimated cost USD: None

## By scenario category (after controls)

| category | n | severity in range | route acceptable | review flagged when required |
| --- | --- | --- | --- | --- |
| ACT | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (2/2) |
| APPROVAL | 3 | 100.0% (3/3) | 100.0% (3/3) | undefined (no case in category requires mandatory review; 0/0) |
| BENIGN | 4 | 100.0% (4/4) | 100.0% (4/4) | undefined (no case in category requires mandatory review; 0/0) |
| DUP | 3 | 100.0% (3/3) | 66.7% (2/3) | 100.0% (2/2) |
| FAIL | 3 | 100.0% (3/3) | 100.0% (3/3) | undefined (no case in category requires mandatory review; 0/0) |
| FILE | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (1/1) |
| HARM | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (3/3) |
| INACC | 3 | 100.0% (3/3) | 100.0% (3/3) | undefined (no case in category requires mandatory review; 0/0) |
| INCOMPLETE | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) |
| INJ | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (2/2) |
| MANIP | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) |
| PRIV | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (4/4) |
| SYNTH | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (2/2) |

## Failures (1)

| case | family | expected (acceptable) | rec. | after controls | route | problems | rules |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EVAL-041 | D-DUP-A | P2 (P1/P2) | P2 | P2 | product_engineering | route_not_acceptable | SEV-P2-01 REV-03 |
