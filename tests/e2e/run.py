"""Standalone driver for the real-world e2e scenarios + a coverage/validation report.

Usage (from repo root):
    .venv/bin/python -m tests.e2e.run --jobs 4
    .venv/bin/python tests/e2e/run.py --name proc-minimal --keep
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import argparse  # noqa: E402
import concurrent.futures  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import traceback  # noqa: E402

from tests.e2e import assertions as A  # noqa: E402
from tests.e2e import coverage  # noqa: E402
from tests.e2e.harness import run_scenario  # noqa: E402
from tests.e2e.scenarios import ALL_SCENARIOS, by_area, by_name  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"


def _run_one(spec, model: str | None, keep: bool) -> dict:
    rec: dict = {"name": spec.name, "area": spec.area, "ok": False, "error": None,
                 "claude_exit": None, "validation_status": None}
    result = None
    try:
        result = run_scenario(spec, model=model)
        rec["claude_exit"] = result.claude_exit
        rec["validation_status"] = (result.validate_json or {}).get("status")
        A.assert_crate(result)
        rec["ok"] = True
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["trace"] = traceback.format_exc()
    finally:
        if result is not None:
            if keep:
                rec["workdir"] = str(result.workdir)
            else:
                shutil.rmtree(result.workdir, ignore_errors=True)
    return rec


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name")
    ap.add_argument("--area")
    ap.add_argument("--model", default=None)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--no-coverage", action="store_true")
    args = ap.parse_args(argv)

    if args.name:
        specs = [by_name(args.name)]
    elif args.area:
        specs = by_area(args.area)
    else:
        specs = list(ALL_SCENARIOS)

    RESULTS.mkdir(parents=True, exist_ok=True)
    records: list = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(_run_one, s, args.model, args.keep): s for s in specs}
        for fut in concurrent.futures.as_completed(futs):
            rec = fut.result()
            records.append(rec)
            mark = "PASS" if rec["ok"] else "FAIL"
            print(f"[{mark}] {rec['name']:24s} exit={rec['claude_exit']} "
                  f"valid={rec['validation_status']} {rec['error'] or ''}")

    passed = [r for r in records if r["ok"]]
    report: dict = {
        "total": len(records), "passed": len(passed), "failed": len(records) - len(passed),
        "records": sorted(records, key=lambda r: r["name"]),
    }
    coverage_gap: list = []
    if not args.name and not args.area and not args.no_coverage:
        passed_specs = [s for s in specs
                        if any(r["name"] == s.name and r["ok"] for r in records)]
        coverage_gap = sorted(coverage.missing_tags(passed_specs))
        report["coverage_missing"] = coverage_gap
        if coverage_gap:
            print(f"\nCOVERAGE GAP ({len(coverage_gap)}): {coverage_gap}")
    (RESULTS / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"\n{len(passed)}/{len(records)} passed. Report: {RESULTS / 'report.json'}")
    return 0 if len(passed) == len(records) and not coverage_gap else 1


if __name__ == "__main__":
    sys.exit(main())
