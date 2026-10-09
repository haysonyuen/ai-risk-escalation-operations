# Jev shadow evaluation: 20261009T071739-jev_shadow-A-dev-ca53

Split **dev**, variant **A**, questions `jev-questions-v1`, model `jev-latest`, 44 cases × 1 repeats. Errors: 44.

**Overall: NOT PASSED** (severity criteria use approach A_direct)

| Criterion | Target | Result | |
|---|---|---|---|
| Severe-harm cases where Jev gives the severe policy < 20% | 0 | 0 | ✅ |
| P0 cases called P2 or lower | 0 | 0 | ✅ |
| Severity within the acceptable range | ≥ 80% | None | ❌ |
| Correct policy in the top 2 | ≥ 85% | None | ❌ |

## Policy
- Top policy correct: n/a
- Correct policy in top 2: n/a
- Severe-harm misses (< 20%): 0 of 0 

| Jev confidence | Cases | Top policy correct |
|---|---|---|
| below 0.5 | 0 | n/a |
| 0.5–0.8 | 0 | n/a |
| 0.8 and above | 0 | n/a |

## Severity
| Approach | Within range | P0/P1 under-calls | P0 called P2 or lower | Over-calls |
|---|---|---|---|---|
| A_direct | n/a | n/a  | 0 | n/a |
| B_factors_rules | n/a | n/a  | 0 | n/a |

## Other questions
- Case type: n/a
- What happened: n/a
- Evidence supports claim: n/a

## Stability across repeats
- {"repeats": 1}

Input tokens: 46933; estimated cost $0.002 (reported list price; verify in the console).

Author labels, not reviewed by the project owner; see docs/jev_phase1.md.
