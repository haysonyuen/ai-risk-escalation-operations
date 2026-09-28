# Case study: turning an incident-response framework into a working AI-assisted workflow

## Problem

The source framework ([framework.md](framework.md)) describes how an operations team should handle early harm signals from an AI work assistant. It covers eight stages, four severity tiers, proportional containment, and a firm line between AI assistance and human accountability. The aim of this prototype was to check whether those principles hold up as software, and whether the software can be evaluated honestly.

## Key decisions and tradeoffs

**1. Deterministic controls wrap any AI output.** Deterministic controls (C1–C6) run after the model, fixture or simulation and are independent of it:
* **Accepted cost:** a model that is right when the rules are wrong can still be overruled upward (C3). An inflated severity that comes from manipulated report text passes through; it is flagged (C4) rather than corrected, so specialists spend some time reviewing it.
* **What it buys:** the fault-injection runs show that a provider which calls everything P3 still ends with 27/30 P0/P1 cases escalated after controls. Every provider failure goes to manual review, and no assessment is invented.

**2. Four quantities are kept separate:** potential impact, evidence quality and confidence, provider recommendation, and human decision. Keeping them apart is what enforces "low confidence must not mean low severity". A floor (FLOOR-01) and a review control (C5) act on high-impact cases with weak evidence. Human decisions live only on the incident, so reassessment and rule changes cannot overwrite them. A disagreement is logged instead.

**3. Authorization lives in services, not screens.** Every consequential action is checked in `riskops/workflow.py`, and the tests call those services directly. The role selector is labeled as a simulation because the prototype has no authentication. Presenting it otherwise would be misleading.

**4. Rules are readable data with versions.** JSON rule files let a Trust & Safety reviewer read and diff the logic without reading Python. Versions are immutable once evaluated: the known v1.1 limitation is recorded as a strict `xfail` test rather than patched in place.

**5. The evaluation is built to be hard to fool.**
* Labels are kept in a separate file that the pipeline never reads.
* Cases are split by scenario family, so near-duplicates cannot leak across splits.
* The held-out set was hashed before tuning, and one pre-run edit is disclosed.
* Every metric has a denominator, and undefined metrics are reported as undefined.
* Claim support is not reported when no human has reviewed claims. There is no model self-grading.

**6. The revision that did not ship.** rules-v1.1 fixed real dev failures and improved held-out severity-range accuracy (29/36 → 31/36). It also lost one P0/P1 case (13/14 → 12/14), and the regression gate caught it. Under this framework, missing a high-severity case costs more than over-escalating one, so the baseline stays active. The failure is documented and was not tuned away on held-out data, which would have spent the only untouched test set.

**7. Everything is simulated, and it says so everywhere.** Containment has review and expiry times but no effect. Drafts are marked NOT SENT and specialist review is enforced. Seeded history and demo actions are tracked separately in monitoring. Recurrence is reported as counts only, because there is no exposure denominator.

## What went wrong along the way (and what changed)

* **Leaky titles.** Case titles written like analyst summaries leaked the answers. They were rewritten before any held-out run, and the change is disclosed.
* **Transcript false positive.** The injection detector flagged the "Assistant:" label in transcripts as impersonation. Fixing it showed that one held-out case had only been flagged for review by accident.
* **Negated text in lexicons.** Keyword matching read "no steps were provided" as facilitation. Narrowing the lexicon created the new EVAL-048 miss.
* **UI state bugs.** Browser testing found state bugs (a stale connection after re-seeding, section state lost on form submission, a future-dated demo timestamp that produced negative durations). Each was fixed and re-verified in the browser.

## What would come next

1. Run the live-model evaluation on dev (prompt-v1 against prompt-v2), then run held-out **once**, and complete the claim-support worksheet for a sample.
2. Build a new, independently labeled held-out set before any rules-v1.2 work. Ideally, have a second labeler and measure agreement.
3. Address the documented gaps: a partial-assistance guard on the refusal carve-out, a P0 rule for confirmed cross-tenant exposure, security-control bypass terms, and health-context inaccuracy → Safety review.
4. Run the timed-review study ([timed_review_protocol.md](timed_review_protocol.md)) before claiming any efficiency benefit.
