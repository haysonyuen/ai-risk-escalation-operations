# Optional timed-review procedure (future user study, not yet run)

No time-savings claim is made for this prototype. This is how one could be measured.

**Question.** Does AI-assisted triage change time-to-decision and decision quality compared with triage from raw evidence alone?

**Design.** Within-subjects, counterbalanced.
* Participants: at least 6 people with Trust & Safety or incident-triage experience, none involved in writing the labels.
* Materials: 20 cases from a **fresh** labeled set (not the existing held-out set), matched across two blocks by severity mix and difficulty.
* Conditions:
  * **A.** Raw report and evidence only; the AI assessment is hidden.
  * **B.** The same, plus the AI assessment after controls (live model, fixed version).
* Each participant does one block in each condition. Block order and condition order are counterbalanced.

**Procedure.**
1. Five minutes of training on the severity framework using practice cases that are not in the study set.
2. For each case, the participant records severity, route, whether mandatory review is needed, and one sentence of rationale. The timer starts when the case opens and stops on "Record decision".
3. After each block, participants complete a short NASA-TLX, plus a question on trust in the AI summary (condition B).

**Measures.**
* Primary: median time per case.
* Decision quality:
  * severity within the acceptable range;
  * P0/P1 recall and precision;
  * route acceptability.
* Secondary:
  * automation bias: how often participants agree with a *wrong* AI recommendation;
  * evidence inspection: whether they opened the raw evidence.

**Analysis.**
* Paired comparison per participant. Report medians, interquartile ranges and all denominators.
* Do not claim a speed benefit if decision quality or P0/P1 recall is worse.
* Report automation-bias cases individually.

**Instrumentation needed.** Per-case timestamps for open and decide (the `events` table already records decision times; add a `case_opened` event) and a hidden-assessment mode for condition A.
