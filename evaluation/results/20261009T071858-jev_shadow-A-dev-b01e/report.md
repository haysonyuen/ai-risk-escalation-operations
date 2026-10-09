# Jev shadow evaluation: 20261009T071858-jev_shadow-A-dev-b01e

Split **dev**, variant **A**, questions `jev-questions-v1`, model `jev-1.13.0`, 44 cases × 1 repeats. Errors: 0.

**Overall: PASS** (severity criteria use approach B_factors_rules)

| Criterion | Target | Result | |
|---|---|---|---|
| Severe-harm cases where Jev gives the severe policy < 20% | 0 | 0 | ✅ |
| P0 cases called P2 or lower | 0 | 0 | ✅ |
| Severity within the acceptable range | ≥ 80% | 93% | ✅ |
| Correct policy in the top 2 | ≥ 85% | 98% | ✅ |

## Policy
- Top policy correct: 93% (41/44)
- Correct policy in top 2: 98% (43/44)
- Severe-harm misses (< 20%): 0 of 11 

| Jev confidence | Cases | Top policy correct |
|---|---|---|
| below 0.5 | 0 | n/a |
| 0.5–0.8 | 5 | 80% (4/5) |
| 0.8 and above | 39 | 95% (37/39) |

## Severity
| Approach | Within range | P0/P1 under-calls | P0 called P2 or lower | Over-calls |
|---|---|---|---|---|
| A_direct | 86% (38/44) | 20% (4/20) ['EVAL-001', 'EVAL-005', 'EVAL-008', 'EVAL-036'] | 0 | 5% (2/44) |
| B_factors_rules | 93% (41/44) | 5% (1/20) ['EVAL-023'] | 0 | 5% (2/44) |

## Other questions
- Case type: 84% (37/44)
- What happened: 86% (38/44)
- Evidence supports claim: 72% (28/39)

## Stability across repeats
- {"repeats": 1}

Input tokens: 134899; estimated cost $0.0057 (reported list price; verify in the console).

Author labels, not reviewed by the project owner; see docs/jev_phase1.md.
