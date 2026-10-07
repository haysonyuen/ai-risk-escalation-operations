# First-time operator review

**Reviewer stance:** a Risk Ops analyst using the tool for the first time, on fresh demo data.
**Scope:** Queue, Case (several kinds), New report, Dashboard, Quality & evaluation, Rules & playbooks.
**Method:** I clicked through each page and checked anything suspicious against the code.

Findings are grouped by impact:
- **High:** could lead to a wrong or unsafe decision, or wrong reporting.
- **Medium:** slows the operator down or causes confusion.
- **Low:** polish.

**Status: all 18 findings are fixed** (high, medium and low). For H4, the rule adopted is:
- **Severe-harm areas:** the Safety & Child Safety Specialist may decide severity and policy in severe-harm policy areas (CS, WP, SH, VE, NC), but not in other areas.
- **P0 in those areas:** needs the Specialist or the Incident Lead. A Risk Ops analyst can't confirm it alone.

Each finding below is kept as written; the fix is summarised in the section at the end.

---

## High: logic gaps that could lead to wrong decisions or reports

### H1. Unassessed cases default to "No policy issue"
- **Where:** Case → decision panel, e.g. INC-1010, *Non-consensual intimate deepfake of a coworker*.
- **What I saw:** the AI hasn't assessed the case yet. The decision form is pre-filled with **P1 → Risk Ops** and **Policy violated: NP-00 · No policy issue**. One click on "Record decision" records that an NCII case violates no policy.
- **Why it matters:** a pre-filled "no violation" on a severe-harm report invites rubber-stamping. It is the most damaging wrong default the tool can make.
- **Suggested change:**
  - With no AI or rules suggestion, leave Policy and Severity **empty** ("Choose…") and require a choice.
  - Never default to NP-00.

### H2. "Confirm AI recommendation" appears when the AI failed
- **Where:** Case → decision panel, e.g. INC-1009, *AI failed · needs manual triage*.
- **What I saw:**
  - The button says **Confirm AI recommendation**, but there is no AI recommendation, only the rules' placeholder estimate.
  - The form is pre-filled with that estimate (P0, Legal/Privacy, six teams, DL-01 plus PR-01).
  - Changing any field is recorded as an **override of the AI**.
- **Why it matters:**
  - The button invites an operator to "confirm" something the AI never said.
  - Manual triage is counted as an AI override, which inflates the override metrics on the Dashboard and Quality pages.
- **Suggested change:**
  - **Button:** label it **Record decision** when the AI failed.
  - **Pre-fill:** keep the placeholder but mark it "pre-filled from the rules estimate".
  - **Metrics:** don't classify decisions on failed assessments as overrides; count them as "manual triage".

### H3. A false positive is recorded as a confirmed CBRN violation
- **Where:** Case INC-1014, *CBRN classifier alert on a school chemistry session*. It was closed as **classifier false positive**.
- **What I saw:**
  - The header says **Policy: WP-01 · CBRN weapons uplift · ✓ confirmed**.
  - Dashboard → *By policy* counts it as a CBRN case.
- **Why it matters:** the record says "confirmed CBRN violation" for something the team decided was not a violation. Policy reporting (and any regulator-facing count) would be wrong.
- **Suggested change:** separate the **policy area investigated** from the **outcome**:
  - Add **Violation confirmed? Yes / No / Can't determine** to the decision and the closure.
  - Closure categories such as *classifier false positive* or *user misunderstanding* should require "No".
  - Policy charts should split confirmed violations from cleared cases.

### H4. Child-safety and CBRN cases can be confirmed without a specialist
- **Where:** Case INC-1002 (P0 child safety), working as **Alex, Risk Ops Analyst**.
- **What I saw:**
  - Alex can confirm P0 and the child-safety policy alone.
  - The **Safety & Child Safety Specialist** (Priya, who owns the case) **can't** record the severity decision at all. Only Risk Ops and the Incident Lead hold that permission.
- **Why it matters:**
  - The case page itself says "a specialist must look", yet the person who must look can't record the decision.
  - The analyst can decide without them.
  - This inverts the accountability the framework describes.
- **Suggested change:**
  - Let the Safety specialist decide severity and policy on severe-harm policy areas (CS, WP, SH, VE, NC).
  - For P0 in those areas, require either the specialist's decision or the Incident Lead's.

### H5. QA review is not independent
- **Where:** Case → Closure & quality review → *QA review*.
- **What I saw:** whoever closed the case can also record its QA review. The code has no check.
- **Why it matters:** QA is meant to be a second pair of eyes. Self-review defeats it and makes the "QA reviewed" status misleading.
- **Suggested change:** block QA by the person who signed off the closure, and show "needs a different reviewer".

---

## Medium: clarity and flow

### M1. The most useful queue columns are off-screen
- **Where:** Queue.
- **What I saw:** on a 1440-pixel-wide screen, the columns in view are Severity, ID, Title, Code, Policy, Policy status and Status. **Alerts, Next action, First review and Owner** need horizontal scrolling.
- **Why it matters:** an operator scans the queue to decide *what to do next*. That is Alerts plus Next action, which are exactly the hidden columns.
- **Suggested change:**
  - **New order:** Severity · ID · Title · **Alerts** · **Next action** · First review · Owner · Status · Policy · Code · Policy status.
  - **Alternatively:** merge Code and Policy status into the Policy cell, e.g. "CS-01 Child safety (AI)".

### M2. "Actions I can take: 16" next to "11 cases"
- **Where:** Queue headline numbers.
- **What I saw:** *Actions I can take* counts **actions**, while the list shows **cases**.
- **Why it matters:** two numbers that look comparable but don't match make the operator distrust the counts.
- **Suggested change:** show **Cases I can act on**, counting cases. If useful, add "(16 actions)" as hover text.

### M3. Internal tokens still leak into operator text
- **What I saw:**
  - **Activity feed:** "ran the AI assessment (offline fixture, rules rules-v2.0)".
  - **AI analysis → Why it matched:** "matched: policy_area=self_harm, self_harm_policy".
  - **Summary "In short":** "harm areas: benign noise".
  - **New report → Evidence → Type:** `reporter_statement`.
- **Why it matters:** this is the same readability issue fixed elsewhere, and it is inconsistent now that most of the app uses plain words.
- **Suggested change:**
  - Activity: "ran the AI assessment (Demo AI, Rules v2.0)".
  - Why it matched: show only the plain-language signal, with the raw terms in *How this was produced*.
  - Use policy names instead of category keys.
  - Use readable evidence types, e.g. "Reporter statement".

### M4. Is QA optional or a required stage?
- **Where:** Closed case, e.g. INC-1014.
- **What I saw:**
  - The stage line says "Stage 7 of 8 · **next: QA review**".
  - The Next panel says "Quality review (sampling) — **Optional**".
  - The dashboard counts "Closed · QA pending" as a backlog.
- **Why it matters:** operators can't tell whether a closed case is finished.
- **Suggested change:** pick one rule. I'd suggest:
  - **QA is sampled:** the stage line says "Closed (QA optional)" and the dashboard shows "Closed · sampled for QA".
  - **Mandatory QA where it matters:** for P0/P1, QA is required and the Next panel says so.

### M5. The decision form pre-selects six teams
- **Where:** Case INC-1009 decision panel.
- **What I saw:** "Teams involved" is pre-filled with six teams: Incident Lead, Legal/Privacy, Enterprise/CS, Product Security, Engineering, Risk Ops.
- **Why it matters:** a long pre-selected list gets accepted unread, and "everyone is involved" means nobody owns it.
- **Suggested change:** pre-select only the owning team plus the Incident Lead for P0/P1, and show the others as suggestions.

### M6. Dashboard "By policy" is dominated by "No policy issue" and "Not assessed"
- **Where:** Dashboard → Workload → *By policy*.
- **What I saw:** the largest bar is *NP-00 · No policy issue*, and *Not assessed* appears as a policy.
- **Why it matters:** the chart is meant to show where policy risk sits. Noise categories push the real policies down.
- **Suggested change:** show violations and suspected violations only, with a separate count of "No policy issue · N" and "Not assessed · N" under the chart.

### M7. Auto-generated incident IDs look like existing ones
- **Where:** New report → Incident ID, e.g. **INC-1007184148**.
- **What I saw:** the ID is a timestamp (MMDDhhmmss), so it reads like "INC-1007" plus noise.
- **Why it matters:** IDs are quoted in conversations and tickets, and an ID that looks like a different case causes mix-ups.
- **Suggested change:** use the next sequential number (e.g. **INC-1017**) and keep the ID read-only by default.

### M8. Nothing tells the owner a case was assigned
- **Where:** Case → Owner & stage, and Queue → *My cases*.
- **What I saw:** assigning an owner changes the field but leaves no visible handoff. Priya owns INC-1002, but nothing on her queue marks it as new to her.
- **Why it matters:** in operations, handoff is where cases get dropped.
- **Suggested change:**
  - Show "Assigned to you · 5m ago" in *My cases*.
  - Add an "Assigned to me" count to the queue headline numbers.
  - Write the handoff note into the activity feed. (The prototype has no messaging, so this stays in-app.)

---

## Low: polish

| # | Where | What I saw | Suggested change | Why |
| --- | --- | --- | --- | --- |
| L1 | Queue table | An empty extra row at the bottom of the table | Size the table to its rows | Looks like a missing case |
| L2 | Case → Communications | The "Open dr…" button is cut off | Shorten the label to "Open" or widen the button | Truncated buttons look broken |
| L3 | Case → Containment (confirmed pause) | "review due in 18h 41m · no automatic expiry" on a pause that's already confirmed | After confirmation, show "Confirmed by Priya · next review in 18h" | "Due" reads as still pending |
| L4 | Case header | Up to 8 chips across two lines on some cases (e.g. INC-1009) | Put status, severity and alerts first; move AI source and demo data to a muted second line | Important chips get lost |
| L5 | Dashboard → Human oversight | "Lifted (false alarms): 0%" based on one review | Show "0 of 1" and hide the percentage below 5 reviews | Percentages from tiny samples mislead |

---

## Suggested order of work
1. **H1, H2, H3:** wrong defaults and wrong records. These are small, contained changes.
2. **H4, H5:** role and permission rules. They are small in code but change who can do what, so they need your decision on the exact rules.
3. **M1 to M4:** what the operator sees first.
4. **M5 to M8, then L1 to L5.**

No real-world claims are made here. These observations come from synthetic demo data and simulated roles.

---

## What was changed

**High**
- **H1, required choices:** with no suggestion, severity and policy start empty ("Choose…"). The service refuses a decision without a policy, and nothing defaults to NP-00.
- **H2, AI failure is manual triage:** when the AI failed, the button reads "Record decision" and a note says the fields come from the rules estimate.
  - The decision is logged as **manual triage**, with the rules estimate kept separately.
  - It is not counted as an AI override. The dashboard shows the manual-triage count next to overrides.
- **H3, violation outcome at closure:** closure asks **"Was a policy violation confirmed?"** (Yes / No / Can't determine), and the answer is checked against the closure category.
  - A *classifier false positive* cannot be "Yes", and a confirmed incident must be "Yes".
  - Cleared cases show **"cleared · no violation"** and are left out of the *By policy* chart, which now counts confirmed or suspected violations only.
- **H4, specialist decisions:** the rule above is enforced in the service and reflected in the Next panel and the decision form.
- **H5, independent QA:** QA by the person who signed off the closure is refused, the QA button is disabled for them, and the reason is shown.

**Medium**
- **M1, queue columns:** Severity · ID · Title · Alerts · Next action · First review · Owner come first. Policy code and name are merged into one column.
- **M2, case counts:** "Cases I can act on" counts cases, with the number of steps in the hover text.
- **M3, plain text:**
  - The activity feed reads e.g. "Demo AI (…), Rules v2.0".
  - "Why it matched" no longer prints raw matched terms.
  - The demo AI summary names policies.
  - New report shows readable evidence types.
- **M4, QA rule:** QA is required for P0/P1 and sampled for P2/P3. The Next panel, the stage line and a "QA required" alert all say so, and closed cases are labelled just "Closed".
- **M5, fewer pre-selected teams:** only the owning team is pre-selected, plus the Incident Lead for P0/P1.
- **M6, policy chart:** shows violations only, with a "Not shown" line for no policy issue, cleared and not assessed.
- **M7, incident IDs:** new reports get the next sequential ID (e.g. INC-1017).
- **M8, handoff:** an "Assigned to you" alert and header chip appear until the new owner acts on the case, and the queue has an "Assigned to me" count.

**Low**
- **L1:** the queue table is sized to its rows.
- **L2:** the "Open draft" button has room.
- **L3:** confirmed pauses say "next review in …".
- **L4:** the case header shows status, policy and alerts first, with AI source and demo-data on a quieter second line.
- **L5:** the lifted-pause rate shows "n of N" below five reviews.
