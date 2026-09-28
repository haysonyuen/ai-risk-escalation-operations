#!/usr/bin/env bash
# Reproduce every evaluation artifact in evaluation/results/.
# Offline runs need no credentials. The live run is attempted last and exits with code 2
# (and writes nothing) when ANTHROPIC_API_KEY is not set - it never substitutes offline results.
set -u
cd "$(dirname "$0")/.."
PY=${PYTHON:-python}
$PY -m riskops.cli eval --system rules --rules rules-v1.0 --split dev      --label "Baseline rules-v1.0 on dev"
$PY -m riskops.cli eval --system rules --rules rules-v1.1 --split dev      --label "Revised rules-v1.1 on dev (tuned on this split)"
$PY -m riskops.cli eval --system rules --rules rules-v1.0 --split held_out --label "Baseline rules-v1.0 on frozen held-out"
$PY -m riskops.cli eval --system rules --rules rules-v1.1 --split held_out --label "Revised rules-v1.1 on frozen held-out"
# Fault-injection tests of the safeguards (NOT model findings)
$PY -m riskops.cli eval --system rules --rules rules-v1.1-fault-demo --split all --label "FAULT INJECTION: broken rule set (regression-gate demo)"
for f in under_severity invalid_evidence_refs malformed_json schema_violation timeout obeys_embedded_instructions; do
  $PY -m riskops.cli eval --system "fault:$f" --rules rules-v1.1 --split all --label "FAULT INJECTION: provider $f"
done
# Live model evaluation (pending without credentials)
$PY -m riskops.cli eval --system live --rules rules-v1.1 --prompt prompt-v2 --split dev --label "Live model prompt-v2 + rules-v1.1 on dev" || echo "live evaluation not run (see message above)"
