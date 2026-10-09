# Jev shadow evaluation: 20261009T074800-jev_shadow-A-dev-4344

Split **dev**, variant **A**, questions `jev-questions-v1`, model `jev-1.13.0`, 44 cases × 3 repeats. Errors: 0.

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
| 0.5–0.8 | 6 | 83% (5/6) |
| 0.8 and above | 38 | 95% (36/38) |

## Severity
| Approach | Within range | P0/P1 under-calls | P0 called P2 or lower | Over-calls |
|---|---|---|---|---|
| A_direct | 86% (38/44) | 20% (4/20) ['EVAL-001', 'EVAL-005', 'EVAL-008', 'EVAL-036'] | 0 | 5% (2/44) |
| B_factors_rules | 93% (41/44) | 5% (1/20) ['EVAL-023'] | 0 | 5% (2/44) |

## Other questions
- Case type: 84% (37/44)
- What happened: 86% (38/44)
- Evidence supports claim: 74% (29/39)

## Stability across repeats
- {"repeats": 3, "top_policy_changed": {"num": 0, "den": 44, "value": 0.0}, "severity_a_changed": {"num": 0, "den": 44, "value": 0.0}, "median_top_probability_spread": 0.0}

Input tokens: 404697; estimated cost $0.017 (reported list price; verify in the console).

## Compared with the LLM run `20261009T074704-live_model-live-rules-v2.1-dev-052e` (live_model, 43 cases)
- LLM top policy correct: 81% (35/43); top 2: 98% (42/43)
- LLM severity within range: 100% (43/43); P0/P1 under-calls: 0% (0/19); P0 called P2 or lower: 0
- Cases where Jev's top policy is not among the LLM's categories: []

Author labels, not reviewed by the project owner; see docs/jev_phase1.md.
