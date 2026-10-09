# Handover: finish Phase 1 (steps 4–5) on a local machine

For the next Claude Code session. Read this, then `docs/jev_phase1.md` and
`docs/policy_conventions.md`, before doing anything.

## Why this must run locally

Cloud sessions cannot run the LLM steps. Three cloud sessions in a row received
`TYPESAFE_API_KEY` but **not** `ANTHROPIC_API_KEY`, although both were saved in the same
environment settings box. The cloud environment withholds that name and also sets its own
`ANTHROPIC_BASE_URL`, so the app's LLM calls could not reach Anthropic from there. A code
workaround (a second variable name plus a forced base URL) was rejected by the session's safety
check and is **not** wanted. Run in a Claude Code session on the owner's computer (CLI, Desktop
app, or `claude remote-control`) instead. No code change is needed for that.

## Before you start (owner)

1. Revoke the Anthropic key "Risk-Ops" and the TypeSafe key that were shown in screenshots, and
   create new ones. `sk-ant-usr-…` is the current Anthropic key format (user-linked); it is fine.
2. Clone and install:
   ```
   git clone https://github.com/haysonyuen/ai-risk-escalation-operations.git
   cd ai-risk-escalation-operations
   git checkout claude/youthful-davinci-5ac4bk
   pip install -r requirements.txt -r requirements-dev.txt
   ```
3. Put the **new** keys in `.env` in the repo root (copy `.env.example`; `.env` is git-ignored and
   loaded by `riskops/config.py`):
   ```
   ANTHROPIC_API_KEY=...
   TYPESAFE_API_KEY=...
   ```
   Use `.env`, not `export` in the shell: Claude Code itself may pick up a shell
   `ANTHROPIC_API_KEY` and bill its own calls to it.
4. Start Claude Code in that folder and tell it: *"Do the handover in
   docs/jev_phase1_handover.md."*

## Rules for the agent

- Never print, log, commit or paste key values. Only use keys from the environment / `.env`;
  never use a key value seen anywhere else (chat, screenshots, earlier transcripts).
- The pass criteria in `docs/jev_phase1.md` are fixed. Do not change them.
- Tune on `dev` only. At most two question revisions, each saved as a new question version in
  `config/jev_questions.json` (e.g. `jev-questions-v2`), never edited in place.
- The final run (step 5) happens once. No changes to questions, code or labels afterwards.
- Synthetic, author-labelled data only: never claim real-world performance.
- Work and push only on `claude/youthful-davinci-5ac4bk`. Do not open or merge a PR.

## Steps

1. **Check access.** Confirm both keys are set without printing them, e.g.
   `python -c "import os; from riskops import config; print({k: bool(os.environ.get(k)) for k in ['ANTHROPIC_API_KEY','TYPESAFE_API_KEY']})"`
   and that `https://api.typesafe.ai` is reachable. If a key is missing, stop and tell the owner.
2. **One Jev case.** `python -m riskops.cli jev-eval --split dev --variant A --repeats 1`.
   The request/response format in `riskops/providers/jev.py` (`build_request`, `parse_response`)
   came from third-party guides and is unconfirmed. If parsing fails, fix those two functions to
   match the real API, add a test in `tests/test_jev_shadow.py` using a recorded response with no
   secrets in it, and pin `JEV_MODEL` (default `jev-latest`, `riskops/providers/jev.py:35`) to the
   version the API reports.
3. **LLM baseline on dev.**
   `python -m riskops.cli eval --system live --rules rules-v2.1 --prompt prompt-v3 --split dev`.
   It uses structured output (`output_config` json_schema in
   `riskops/providers/anthropic_live.py`), untested against the live API. If the API rejects the
   schema, fix it and keep `tests/test_live_provider_schema.py` passing. The run directory lands in
   `evaluation/results/`.
4. **Tune on dev.** Variants A and B:
   `python -m riskops.cli jev-eval --split dev --variant A --repeats 3 --llm-run evaluation/results/<llm dev run>`
   and the same with `--variant B`. Pick a variant; at most two question revisions (see rules).
5. **Final run, once.** Chosen variant with `--split held_out` and `--split external`, plus the LLM
   (`eval --system live … --split held_out` and `--split external`) for comparison.
6. **Write up.** In `docs/jev_phase1.md`: update the Status table (steps 0, 4, 5), add results per
   pass criterion, Jev vs LLM, real cost (from the run outputs), and the go/no-go decision. Remove
   "No Jev or LLM results exist yet". Run `pytest`, commit, push.

## Report to the owner (plain language)

- Pass/fail for each of the four criteria, with the numbers.
- Jev vs LLM on the same splits.
- Real cost of all runs (Jev and LLM).
- Go/no-go, and anything decided without owner review.
