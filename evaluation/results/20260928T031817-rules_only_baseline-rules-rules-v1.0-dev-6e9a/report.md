# Evaluation run 20260928T031817-rules_only_baseline-rules-rules-v1.0-dev-6e9a

* Kind: **rules_only_baseline** — Deterministic rules; says nothing about model quality.
* Rule version: `rules-v1.0`; controls: `controls-v1.1`; prompt: `None`; model: `None`
* Split: `dev`; cases: 44
* Held-out integrity: matches freeze = True, status = untouched
* Labels are provisional author-generated judgments on synthetic cases, not independently validated ground truth.

## Severity

| Metric | Before controls (valid assessments) | After deterministic controls (all cases) |
| --- | --- | --- |
| exact_match | 63.6% (28/44) | 63.6% (28/44) |
| within_acceptable_range | 79.5% (35/44) | 79.5% (35/44) |
| p0p1_precision | 82.4% (14/17) | 82.4% (14/17) |
| p0p1_recall | 87.5% (14/16) | 87.5% (14/16) |
| under-severity outside range (count) | 1 | 1 |
| over-severity outside range (count) | 8 | 8 |

### Confusion matrix after controls (rows = expected, cols = predicted)

| expected \ predicted | P0 | P1 | P2 | P3 | none |
| --- | --- | --- | --- | --- | --- |
| P0 | 3 | 1 | 0 | 0 | 0 |
| P1 | 2 | 8 | 1 | 1 | 0 |
| P2 | 0 | 1 | 8 | 1 | 0 |
| P3 | 0 | 2 | 7 | 9 | 0 |

## Routing, review and schema

* Primary route exact: 63.6% (28/44)
* Primary route within acceptable routes: 81.8% (36/44)
* Mandatory review flagged when required: 81.8% (18/22)
* Review flagged when not required (over-flagging): 9.1% (2/22)
* Schema-valid assessments: 100.0% (44/44)
* Failed assessments routed to manual review: undefined (no failures; 0/0)
* Facts with invalid evidence references: 0.0% (0/74)
* Claim-support accuracy: not reported — No human claim-support reviews recorded for this run (see claim_review_worksheet.csv).
* Latency ms (mean / p95, n): 0.04157497725869193 / 0.07829100013623247 (n=44)
* Estimated cost USD: None

## By scenario category (after controls)

| category | n | severity in range | route acceptable | review flagged when required |
| --- | --- | --- | --- | --- |
| ACT | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (2/2) |
| APPROVAL | 3 | 66.7% (2/3) | 66.7% (2/3) | undefined (no case in category requires mandatory review; 0/0) |
| BENIGN | 4 | 50.0% (2/4) | 50.0% (2/4) | undefined (no case in category requires mandatory review; 0/0) |
| DUP | 3 | 100.0% (3/3) | 66.7% (2/3) | 50.0% (1/2) |
| FAIL | 3 | 66.7% (2/3) | 100.0% (3/3) | undefined (no case in category requires mandatory review; 0/0) |
| FILE | 4 | 75.0% (3/4) | 75.0% (3/4) | 0.0% (0/1) |
| HARM | 4 | 75.0% (3/4) | 100.0% (4/4) | 100.0% (3/3) |
| INACC | 3 | 100.0% (3/3) | 100.0% (3/3) | undefined (no case in category requires mandatory review; 0/0) |
| INCOMPLETE | 3 | 66.7% (2/3) | 66.7% (2/3) | 33.3% (1/3) |
| INJ | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (2/2) |
| MANIP | 3 | 66.7% (2/3) | 66.7% (2/3) | 100.0% (3/3) |
| PRIV | 4 | 100.0% (4/4) | 100.0% (4/4) | 100.0% (4/4) |
| SYNTH | 3 | 66.7% (2/3) | 66.7% (2/3) | 100.0% (2/2) |

## Failures (13)

| case | family | expected (acceptable) | rec. | after controls | route | problems | rules |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EVAL-002 | D-HARM-BIO | P3 (P3/P2) | P1 | P1 | safety | severity_outside_range | SEV-P1-01 REV-01 |
| EVAL-017 | D-FILE-EDIT | P3 (P3) | P2 | P2 | product_engineering | severity_outside_range, route_not_acceptable | SEV-P2-01 |
| EVAL-018 | D-FILE-EDIT | P1 (P1/P2) | P2 | P2 | product_engineering | missed_mandatory_review | SEV-P2-01 |
| EVAL-020 | D-APPROVAL | P2 (P2) | P2 | P2 | product_engineering | route_not_acceptable | SEV-P2-01 |
| EVAL-021 | D-APPROVAL | P3 (P3) | P2 | P2 | product_ux | severity_outside_range | SEV-P2-01 |
| EVAL-024 | D-SYNTH-VOICE | P3 (P3) | P2 | P2 | safety | severity_outside_range, route_not_acceptable | SEV-P2-01 |
| EVAL-030 | D-FAIL-SYNC | P3 (P3) | P2 | P2 | product_engineering | severity_outside_range | SEV-P2-01 |
| EVAL-032 | D-BENIGN-HOWTO | P3 (P3) | P2 | P2 | product_engineering | severity_outside_range, route_not_acceptable | SEV-P2-01 |
| EVAL-035 | D-BENIGN-HOWTO | P3 (P3) | P1 | P1 | safety | severity_outside_range, route_not_acceptable | SEV-P1-01 REV-01 |
| EVAL-036 | D-INCOMPLETE | P1 (P0/P1) | P3 | P3 | support | severity_outside_range, route_not_acceptable, missed_mandatory_review |  |
| EVAL-037 | D-INCOMPLETE | P2 (P1/P2/P3) | P3 | P3 | support | missed_mandatory_review |  |
| EVAL-041 | D-DUP-A | P2 (P1/P2) | P2 | P2 | product_engineering | route_not_acceptable, missed_mandatory_review | SEV-P2-01 |
| EVAL-044 | D-MANIP-A | P3 (P3) | P2 | P2 | product_engineering | severity_outside_range, route_not_acceptable | SEV-P2-01 |
