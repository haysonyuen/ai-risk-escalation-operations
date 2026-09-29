"""Command-line entry points.

  python -m riskops.cli seed [--reset]            reset/seed the local demo database
  python -m riskops.cli eval --system rules --rules rules-v2.0 --split dev
  python -m riskops.cli eval --system live --rules rules-v2.1 --prompt prompt-v3 --split dev
  python -m riskops.cli eval --system fault:under_severity --rules rules-v2.1 --split all
  python -m riskops.cli compare <run_dir> <run_dir> ...
  python -m riskops.cli claims <run_dir>/claim_review_worksheet.csv
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, evaluation


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="riskops")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("seed", help="reset and seed the local demo database")
    s.add_argument("--db", default=None)

    e = sub.add_parser("eval", help="run an evaluation")
    e.add_argument("--system", default="rules", help="rules | live | fault:<mode>")
    e.add_argument("--rules", default=config.BASELINE_RULE_VERSION)
    e.add_argument("--prompt", default="prompt-v3")
    e.add_argument("--split", default="dev", choices=["dev", "held_out", "all"])
    e.add_argument("--label", default=None)
    e.add_argument("--record-in-db", action="store_true", help="also record the run summary in the app database")

    c = sub.add_parser("compare", help="compare run directories")
    c.add_argument("runs", nargs="+")

    cl = sub.add_parser("claims", help="summarize a filled claim-support worksheet")
    cl.add_argument("worksheet")

    args = ap.parse_args(argv)
    if args.cmd == "seed":
        from .seed import seed
        path = seed(args.db)
        print(f"Seeded demo database at {path}")
        return 0
    if args.cmd == "eval":
        try:
            summary = evaluation.run_eval(args.system, args.rules, args.prompt, args.split, args.label)
        except evaluation.LiveEvaluationUnavailable as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.record_in_db:
            from .db import connect
            from .workflow import record_eval_run
            record_eval_run(connect(), summary, origin="cli")
        m = summary["metrics"]["after_deterministic_controls"]
        print(f"run: {summary['run_id']}")
        print(f"artifacts: {summary.get('artifact_dir')}")
        print(f"within range {evaluation._fmt(m['within_acceptable_range'])}; P0/P1 recall {evaluation._fmt(m['p0p1_recall'])}; "
              f"P0/P1 precision {evaluation._fmt(m['p0p1_precision'])}; review compliance "
              f"{evaluation._fmt(summary['metrics']['mandatory_review']['compliance_flagged_when_required'])}; "
              f"failures {len(summary['failures'])}")
        return 0
    if args.cmd == "compare":
        sums = [json.loads((Path(r) / "summary.json").read_text()) for r in args.runs]
        print(evaluation.compare(sums))
        return 0
    if args.cmd == "claims":
        print(json.dumps(evaluation.summarize_claim_worksheet(Path(args.worksheet)), indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
