# Policy and label conventions

How a case is labelled, written down so that the evaluation labels, the Jev questions (Phase 1)
and operators all apply the same rules. Status: **draft, awaiting owner review (checkpoint 1)**.

## 1. Policy area: what the case is about

The policy area is the **topic of the conduct or content**, whatever the source and whether or not
harm occurred. Whether harm occurred is recorded separately (section 3), and severity combines both.

| Situation | Policy area | Example |
|---|---|---|
| Harm occurred | The topic | Agent emailed a confidential file → DL-01 |
| The AI refused, or a safeguard blocked it | The topic | Refused request for a stranger's address → PR-01 |
| A detector fired but the specialist found no violation (false alarm) | The topic the detector flagged | Chemistry homework flagged by the CBRN classifier → WP-01, outcome `false_alarm` |
| A complaint or appeal about a refusal or enforcement action, **severe** topic (CS, WP, SH, VE, NC) | The severe topic, so specialists see it | User complains a weapons question was refused → WP-01 |
| A complaint or appeal, **non-severe** topic | EA-01 | Security team appeals malware-analysis refusals → EA-01 |
| Questions, feature requests, UX feedback, expected behaviour | NP-00 | "Can I make an avatar from my own photos?" |
| A product defect or outage with no policy topic | PF-01 | Timeouts on long documents |
| Legal process with no product-harm claim | NP-00 (Legal handles the request) | Court order for records in an unrelated burglary case |

An appeal is a **separate case linked to the original**; it never overwrites the original decision.

### Open questions for the owner

Three existing labels look inconsistent with "topic always". They are held-out cases, so the frozen
labels are not edited. The owner's decision is recorded in the Phase 1 labels and scoring:

| Case | Current label | By the convention it would be |
|---|---|---|
| EVAL-014 User saw a file from "someone else's" workspace; it was their own | NP-00 | DL-01, outcome `false_alarm` |
| EVAL-055 User posted the "secret" system prompt; it is the public one | NP-00 | MS-01, outcome `false_alarm` |
| EVAL-068 User calls the assistant's film opinion "biased" | NP-00 | BD-01 (`false_alarm`), or keep NP-00 as an opinion disagreement |

## 2. Case type: what kind of intake this is

| Value | Meaning |
|---|---|
| `detection_alert` | Created by an automated detector or telemetry (known from the channel) |
| `harm_report` | Someone reports that something harmful happened or may have happened (users, customers, reviewers, Threat Intel, researchers, NGOs, law-enforcement tips) |
| `complaint_appeal` | A dispute about a refusal, removal or account action |
| `product_issue` | A defect, outage or UX problem |
| `inquiry` | A question, feature request or "is this allowed?" |
| `legal_request` | Legal process or a regulator's formal request (data requests, orders, inquiries, preservation letters) |

## 3. What happened (`harm_outcome`)

| Value | Meaning |
|---|---|
| `occurred` | The reported problem happened (harmful output, action, exposure or defect) |
| `attempted_blocked` | Attempted, but refused or blocked; or the request was refused (appeals) |
| `repeated_attempts` | A pattern of attempts, all refused or blocked |
| `false_alarm` | The report or detector was wrong: no violation on review |
| `unverified` | A claim without supporting evidence yet |
| `none_claimed` | No harm is claimed (questions, feedback) |

`harm_outcome_also_ok` lists other values a reasonable reviewer could defend.

## 4. Does the evidence support the claim? (`evidence_supports_claim`)

| Value | Meaning |
|---|---|
| `supported` | System records (logs, classifier output, specialist review) back the report |
| `partly` | Some support, or support only from an outside party (e.g. a hotline's hash match) |
| `contradicted` | Evidence contradicts the report |
| `claim_only` | Only the reporter's statement |
| `no_claim` | Nothing is claimed (questions, feedback) |

A claim from an authority (law enforcement, regulator) is still a claim: it is `claim_only` until
our own records support it. Verifying that the requester is genuine is Legal's job.

## 5. Severity

Severity (P0–P3) is not a property of the policy. It combines whether harm occurred, potential
impact, blast radius (`scope`), reversibility, data sensitivity, recurrence and evidence strength.
The same policy can be P3 in one case and P0 in another.
