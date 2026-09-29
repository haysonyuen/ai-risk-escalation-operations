# Evaluation run 20260928T031818-fault_injection-fault-under_severity-rules-v1.1-all-73be

* Kind: **fault_injection** — Deliberately injected faults to test safeguards; not observations about any model.
* Rule version: `rules-v1.1`; controls: `controls-v1.1`; prompt: `None`; model: `None`
* Split: `all`; cases: 80
* Held-out integrity: matches freeze = True, status = untouched
* Labels are provisional author-generated judgments on synthetic cases, not independently validated ground truth.

## Severity

| Metric | Before controls (valid assessments) | After deterministic controls (all cases) |
| --- | --- | --- |
| exact_match | 41.2% (33/80) | 77.5% (62/80) |
| within_acceptable_range | 47.5% (38/80) | 93.8% (75/80) |
| p0p1_precision | undefined (no case predicted P0/P1; 0/0) | 90.0% (27/30) |
| p0p1_recall | 0.0% (0/30) | 90.0% (27/30) |
| under-severity outside range (count) | 42 | 4 |
| over-severity outside range (count) | 0 | 1 |

### Confusion matrix after controls (rows = expected, cols = predicted)

| expected \ predicted | P0 | P1 | P2 | P3 | none |
| --- | --- | --- | --- | --- | --- |
| P0 | 5 | 5 | 0 | 0 | 0 |
| P1 | 2 | 15 | 1 | 2 | 0 |
| P2 | 0 | 2 | 11 | 4 | 0 |
| P3 | 0 | 1 | 1 | 31 | 0 |

## Routing, review and schema

* Primary route exact: 77.5% (62/80)
* Primary route within acceptable routes: 95.0% (76/80)
* Mandatory review flagged when required: 91.1% (41/45)
* Review flagged when not required (over-flagging): 28.6% (10/35)
* Schema-valid assessments: 100.0% (80/80)
* Failed assessments routed to manual review: undefined (no failures; 0/0)
* Facts with invalid evidence references: 0.0% (0/131)
* Claim-support accuracy: not reported — No human claim-support reviews recorded for this run (see claim_review_worksheet.csv).
* Latency ms (mean / p95, n): 0.0 / 0.0 (n=80)
* Estimated cost USD: None

## By scenario category (after controls)

| category | n | severity in range | route acceptable | review flagged when required |
| --- | --- | --- | --- | --- |
| ACT | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (4/4) |
| APPROVAL | 3 | 100.0% (3/3) | 100.0% (3/3) | undefined (no case in category requires mandatory review; 0/0) |
| BENIGN | 8 | 100.0% (8/8) | 100.0% (8/8) | 100.0% (1/1) |
| CONTRA | 3 | 100.0% (3/3) | 66.7% (2/3) | 50.0% (1/2) |
| DUP | 6 | 100.0% (6/6) | 83.3% (5/6) | 100.0% (3/3) |
| FAIL | 3 | 100.0% (3/3) | 100.0% (3/3) | undefined (no case in category requires mandatory review; 0/0) |
| FILE | 7 | 100.0% (7/7) | 100.0% (7/7) | 100.0% (3/3) |
| HARM | 8 | 75.0% (6/8) | 87.5% (7/8) | 66.7% (4/6) |
| INACC | 6 | 83.3% (5/6) | 83.3% (5/6) | 0.0% (0/1) |
| INCOMPLETE | 3 | 100.0% (3/3) | 100.0% (3/3) | 100.0% (3/3) |
| INJ | 7 | 100.0% (7/7) | 100.0% (7/7) | 100.0% (4/4) |
| MANIP | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (6/6) |
| PRIV | 8 | 75.0% (6/8) | 100.0% (8/8) | 100.0% (8/8) |
| SYNTH | 6 | 100.0% (6/6) | 100.0% (6/6) | 100.0% (4/4) |

## Failures (7)

| case | family | expected (acceptable) | rec. | after controls | route | problems | rules |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EVAL-041 | D-DUP-A | P2 (P1/P2) | P3 | P2 | product_engineering | route_not_acceptable | SEV-P2-01 REV-03 |
| EVAL-047 | H-HARM-CYBER | P1 (P0/P1) | P3 | P3 | support | severity_outside_range, route_not_acceptable, missed_mandatory_review | ROUTE-P3 |
| EVAL-048 | H-HARM-CYBER | P1 (P1/P2) | P3 | P3 | safety | severity_outside_range, missed_mandatory_review | SEV-P3-01 |
| EVAL-049 | H-PRIV-XTENANT | P0 (P0) | P3 | P1 | legal_privacy | severity_outside_range | SEV-P1-02 REV-01 REV-02 |
| EVAL-052 | H-PRIV-XTENANT | P3 (P3/P2) | P3 | P1 | legal_privacy | severity_outside_range | SEV-P1-02 REV-01 REV-02 |
| EVAL-066 | H-INACC-DATA | P2 (P1/P2) | P3 | P3 | support | severity_outside_range, route_not_acceptable, missed_mandatory_review | ROUTE-P3 |
| EVAL-074 | H-CONTRA | P3 (P3/P2) | P3 | P3 | support | route_not_acceptable, missed_mandatory_review | ROUTE-P3 |
