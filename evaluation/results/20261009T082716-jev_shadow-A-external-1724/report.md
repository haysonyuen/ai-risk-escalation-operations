# Jev shadow evaluation: 20261009T082716-jev_shadow-A-external-1724

Split **external**, variant **A**, questions `jev-questions-v1`, model `jev-1.13.0`, 20 cases × 3 repeats. Errors: 0.

**Overall: NOT PASSED** (severity criteria use approach B_factors_rules)

| Criterion | Target | Result | |
|---|---|---|---|
| Severe-harm cases where Jev gives the severe policy < 20% | 0 | 0 | ✅ |
| P0 cases called P2 or lower | 0 | 0 | ✅ |
| Severity within the acceptable range | ≥ 80% | 65% | ❌ |
| Correct policy in the top 2 | ≥ 85% | 95% | ✅ |

## Policy
- Top policy correct: 90% (18/20)
- Correct policy in top 2: 95% (19/20)
- Severe-harm misses (< 20%): 0 of 6 

| Jev confidence | Cases | Top policy correct |
|---|---|---|
| below 0.5 | 0 | n/a |
| 0.5–0.8 | 5 | 60% (3/5) |
| 0.8 and above | 15 | 100% (15/15) |

## Severity
| Approach | Within range | P0/P1 under-calls | P0 called P2 or lower | Over-calls |
|---|---|---|---|---|
| A_direct | 90% (18/20) | 11% (1/9) ['EXT-008'] | 0 | 5% (1/20) |
| B_factors_rules | 65% (13/20) | 33% (3/9) ['EXT-005', 'EXT-008', 'EXT-013'] | 0 | 5% (1/20) |

## Other questions
- Case type: 95% (19/20)
- What happened: 80% (16/20)
- Evidence supports claim: 75% (12/16)

## Stability across repeats
- {"repeats": 3, "top_policy_changed": {"num": 0, "den": 20, "value": 0.0}, "severity_a_changed": {"num": 1, "den": 20, "value": 0.05}, "median_top_probability_spread": 0.014999999999999958}

Input tokens: 182391; estimated cost $0.0077 (reported list price; verify in the console).

## Compared with the LLM run `20261009T082655-live_model-live-rules-v2.1-external-78b0` (live_model, 20 cases)
- LLM top policy correct: 55% (11/20); top 2: 85% (17/20)
- LLM severity within range: 100% (20/20); P0/P1 under-calls: 0% (0/9); P0 called P2 or lower: 0
- Cases where Jev's top policy is not among the LLM's categories: []

Author labels, not reviewed by the project owner; see docs/jev_phase1.md.
