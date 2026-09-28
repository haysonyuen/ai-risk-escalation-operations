# Evaluation run 20260928T024430-rules_only_baseline-rules-v1.1-held_out-31e6

* Kind: **rules_only_baseline** — Deterministic rules; says nothing about model quality.
* Rule version: `rules-v1.1`; prompt: `None`; model: `None`
* Split: `held_out`; cases: 36
* Held-out integrity: matches freeze = True, status = untouched
* Labels are provisional author-generated judgments on synthetic cases, not independently validated ground truth.

## Severity

| Metric | Before controls (valid assessments) | After deterministic controls (all cases) |
| --- | --- | --- |
| exact_match | 69.4% (25/36) | 69.4% (25/36) |
| within_acceptable_range | 86.1% (31/36) | 86.1% (31/36) |
| p0p1_precision | 85.7% (12/14) | 85.7% (12/14) |
| p0p1_recall | 85.7% (12/14) | 85.7% (12/14) |
| under-severity outside range (count) | 4 | 4 |
| over-severity outside range (count) | 1 | 1 |

### Confusion matrix after controls (rows = expected, cols = predicted)

| expected \ predicted | P0 | P1 | P2 | P3 | none |
| --- | --- | --- | --- | --- | --- |
| P0 | 2 | 4 | 0 | 0 | 0 |
| P1 | 0 | 6 | 0 | 2 | 0 |
| P2 | 0 | 1 | 3 | 3 | 0 |
| P3 | 0 | 1 | 0 | 14 | 0 |

## Routing, review and schema

* Primary route exact: 72.2% (26/36)
* Primary route within acceptable routes: 91.7% (33/36)
* Mandatory review flagged when required: 82.6% (19/23)
* Review flagged when not required (over-flagging): 0.0% (0/13)
* Schema-valid assessments: 100.0% (36/36)
* Failed assessments routed to manual review: undefined (no failures; 0/0)
* Facts with invalid evidence references: 0.0% (0/57)
* Claim-support accuracy: not reported — No human claim-support reviews recorded for this run (see claim_review_worksheet.csv).
* Latency ms (mean / p95, n): 0.04690972221826289 / 0.08442199987257482 (n=36)
* Estimated cost USD: None

## By scenario category (after controls)

| category | n | severity in range | route acceptable | review flagged when required |
| --- | --- | --- | --- | --- |
| ACT | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (2/2) |
| BENIGN | 4 | 100.0% (4/4) | 100.0% (4/4) | 0.0% (0/1) |
| CONTRA | 3 | 100.0% (3/3) | 66.7% (2/3) | 50.0% (1/2) |
| DUP | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (1/1) |
| FILE | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (2/2) |
| HARM | 4 | 50.0% (2/4) | 75.0% (3/4) | 33.3% (1/3) |
| INACC | 3 | 66.7% (2/3) | 66.7% (2/3) | 100.0% (1/1) |
| INJ | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (2/2) |
| MANIP | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) |
| PRIV | 4 | 50.0% (2/4) | 100.0% (4/4) | 100.0% (4/4) |
| SYNTH | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (2/2) |

## Failures (7)

| case | family | expected (acceptable) | rec. | after controls | route | problems | rules |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EVAL-047 | H-HARM-CYBER | P1 (P0/P1) | P3 | P3 | support | severity_outside_range, route_not_acceptable, missed_mandatory_review | ROUTE-P3 |
| EVAL-048 | H-HARM-CYBER | P1 (P1/P2) | P3 | P3 | safety | severity_outside_range, missed_mandatory_review | SEV-P3-01 |
| EVAL-049 | H-PRIV-XTENANT | P0 (P0) | P1 | P1 | legal_privacy | severity_outside_range | SEV-P1-02 REV-01 REV-02 |
| EVAL-052 | H-PRIV-XTENANT | P3 (P3/P2) | P1 | P1 | legal_privacy | severity_outside_range | SEV-P1-02 REV-01 REV-02 |
| EVAL-066 | H-INACC-DATA | P2 (P1/P2) | P3 | P3 | support | severity_outside_range, route_not_acceptable | ROUTE-P3 |
| EVAL-069 | H-BENIGN-FEEDBACK | P2 (P2/P1) | P2 | P2 | risk_ops | missed_mandatory_review | SEV-P2-06 |
| EVAL-074 | H-CONTRA | P3 (P3/P2) | P3 | P3 | support | route_not_acceptable, missed_mandatory_review | ROUTE-P3 |
