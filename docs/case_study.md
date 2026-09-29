# Case study: turning an incident-response framework into a working AI-assisted workflow

## Problem

The source framework ([framework.md](framework.md)) describes how an operations team should handle early harm signals from an AI assistant. It covers eight stages, four severity tiers, proportional containment, and a firm line between AI assistance and human accountability. The aim of this prototype was to check whether those principles hold up as software, and whether the software can be evaluated honestly.

## Key decisions and tradeoffs

**1. Deterministic controls wrap any AI output.** Deterministic controls (C1–C7) run after the model, fixture or simulation and are independent of it:
* **Accepted cost:** a model that is right when the rules are wrong can still be overruled upward (C3). An inflated severity that comes from manipulated report text passes through; it is flagged (C4) rather than corrected, so specialists spend some time reviewing it.
* **What it buys:** the fault-injection runs show that a provider which calls everything P3 still ends with 35/36 P0/P1 cases escalated after controls. Every provider failure goes to manual review, and no assessment is invented.

**1b. One automatic action, for the worst harms only (C7).** For P0 CBRN and child-safety cases, the system pauses the reported session immediately and then asks a person to confirm or lift the pause. Everything else still waits for a human.
* **Why these two:** delay is most costly there, and the pause is the smallest reversible action (one session, not an account).
* **Either source can trigger it; neither can cancel it.** The rules *or* the AI can trigger it, following the same "controls only make things safer" principle as C3. So the pause still fires when the AI times out or under-calls: 6/6 in every fault run.
* **Fail closed:** an unreviewed pause never lifts itself; it escalates to the Incident Lead. Account suspension and the mandatory external report remain human decisions.
* **The cost is false alarms.** On dev, the keyword baseline paused a case where the classifier had *blocked* the request. That is exactly why a person confirms every pause, and why the dashboard tracks the share of pauses that people lift.

**1c. Severe content never appears in tickets.** CBRN, child-safety, self-harm and violent-extremism cases show only structured metadata (policy area, classifier score, specialist verdict) and a pointer to a restricted evidence store. That is how a real triage tool limits analyst exposure, and it keeps the prototype safe to publish. **The tradeoff is disclosed:** rules that match those structured fields have an easier job than rules reading free text, so severe-area results are flattering.

**2. Four quantities are kept separate:** potential impact, evidence quality and confidence, provider recommendation, and human decision. Keeping them apart is what enforces "low confidence must not mean low severity". A floor (FLOOR-01) and a review control (C5) act on high-impact cases with weak evidence. Human decisions live only on the incident, so reassessment and rule changes cannot overwrite them. A disagreement is logged instead.

**3. Authorization lives in services, not screens.** Every consequential action is checked in `riskops/workflow.py`, and the tests call those services directly. The role selector is labeled as a simulation because the prototype has no authentication. Presenting it otherwise would be misleading.

**4. Rules are readable data with versions.** JSON rule files let a Trust & Safety reviewer read and diff the logic without reading Python. Versions are immutable once evaluated, and held-out misses are documented rather than patched in place. Moving to a new harm taxonomy (v1 → v2) meant a new rule set, prompt and dataset; the v1 artifacts are archived, not rewritten.

**5. The evaluation is built to be hard to fool.**
* Labels are kept in a separate file that the pipeline never reads.
* Cases are split by scenario family, so near-duplicates cannot leak across splits.
* The held-out set was hashed before tuning, and one pre-run edit is disclosed.
* Every metric has a denominator, and undefined metrics are reported as undefined.
* Claim support is not reported when no human has reviewed claims. There is no model self-grading.

**6. Tuning that did not generalize.** Both taxonomy versions tell the same lesson:
* **v1:** rules-v1.1 fixed real dev failures but lost one held-out P0/P1 case, and the regression gate caught it.
* **v2:** rules-v2.1 fixed all six v2.0 dev failures (41/44 → 44/44) and made **no difference** on held-out severity (30/36 for both).

Neither was tuned on held-out data, which would have spent the only untouched test set. Better rules need new, independently labeled cases, not more passes over the same ones.

**7. Everything is simulated, and it says so everywhere.** Containment has review and expiry times but no effect. Drafts are marked NOT SENT and specialist review is enforced. Seeded history and demo actions are tracked separately in monitoring. Recurrence is reported as counts only, because there is no exposure denominator.

## What went wrong along the way (and what changed)

* **Leaky titles.** Case titles written like analyst summaries leaked the answers. They were rewritten before any held-out run, and the change is disclosed.
* **Transcript false positive.** The injection detector flagged the "Assistant:" label in transcripts as impersonation. Fixing it showed that one held-out case had only been flagged for review by accident.
* **Negated text in lexicons.** In v1, keyword matching read "no steps were provided" as facilitation. In v2 the same class of bug caused an unwarranted automatic pause ("no image was generated").
* **A safety filter stopped the first draft of the v2 dataset.** The case write-ups for severe harms were too descriptive, even with redactions. The fix was the restricted-evidence format described in 1c.
* **UI state bugs.** Browser testing found state bugs (a stale connection after re-seeding, section state lost on form submission, a future-dated demo timestamp that produced negative durations). Each was fixed and re-verified in the browser.

## What would come next

1. Run the live-model evaluation on dev with prompt-v3, then run held-out **once**, and complete the claim-support worksheet for a sample.
2. Build a new, independently labeled held-out set, with free-text severe-harm reports written by a specialist, before any rules-v2.2 work. Ideally, have a second labeler and measure agreement.
3. Address the documented gaps: P0 for credible threats to life and for broad internal exposure of sensitive data, a narrower secrets rule, and review for deepfakes of real people below P1.
4. Run the timed-review study ([timed_review_protocol.md](timed_review_protocol.md)) before claiming any efficiency benefit.
