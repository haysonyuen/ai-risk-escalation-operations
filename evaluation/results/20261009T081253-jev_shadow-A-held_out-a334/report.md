# Jev shadow evaluation: 20261009T081253-jev_shadow-A-held_out-a334

Split **held_out**, variant **A**, questions `jev-questions-v1`, model `jev-1.13.0`, 36 cases × 3 repeats. Errors: 0.

**Overall: PASS** (severity criteria use approach B_factors_rules)

| Criterion | Target | Result | |
|---|---|---|---|
| Severe-harm cases where Jev gives the severe policy < 20% | 0 | 0 | ✅ |
| P0 cases called P2 or lower | 0 | 0 | ✅ |
| Severity within the acceptable range | ≥ 80% | 81% | ✅ |
| Correct policy in the top 2 | ≥ 85% | 97% | ✅ |

## Policy
- Top policy correct: 89% (32/36)
- Correct policy in top 2: 97% (35/36)
- Severe-harm misses (< 20%): 0 of 11 

| Jev confidence | Cases | Top policy correct |
|---|---|---|
| below 0.5 | 0 | n/a |
| 0.5–0.8 | 6 | 67% (4/6) |
| 0.8 and above | 30 | 93% (28/30) |

## Severity
| Approach | Within range | P0/P1 under-calls | P0 called P2 or lower | Over-calls |
|---|---|---|---|---|
| A_direct | 89% (32/36) | 12% (2/16) ['EVAL-045', 'EVAL-072'] | 0 | 6% (2/36) |
| B_factors_rules | 81% (29/36) | 12% (2/16) ['EVAL-052', 'EVAL-057'] | 0 | 14% (5/36) |

## Other questions
- Case type: 89% (32/36)
- What happened: 92% (33/36)
- Evidence supports claim: 61% (20/33)

## Stability across repeats
- {"repeats": 3, "top_policy_changed": {"num": 0, "den": 36, "value": 0.0}, "severity_a_changed": {"num": 0, "den": 36, "value": 0.0}, "median_top_probability_spread": 0.0}

Input tokens: 330393; estimated cost $0.0139 (reported list price; verify in the console).

## Compared with the LLM run `20261009T081215-live_model-live-rules-v2.1-held_out-f70c` (live_model, 36 cases)
- LLM top policy correct: 92% (33/36); top 2: 97% (35/36)
- LLM severity within range: 92% (33/36); P0/P1 under-calls: 6% (1/16); P0 called P2 or lower: 0
- Cases where Jev's top policy is not among the LLM's categories: ['EVAL-065']

Author labels, not reviewed by the project owner; see docs/jev_phase1.md.
