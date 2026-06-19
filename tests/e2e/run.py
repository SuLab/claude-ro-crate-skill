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
import subprocess  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402

from tests.e2e import assertions as A  # noqa: E402
from tests.e2e import coverage  # noqa: E402
from tests.e2e.harness import (  # noqa: E402
    _PROTECT_PATHS,
    REPO_ROOT,
    protect_repo,
    repo_source_dirty,
    run_scenario,
)
from tests.e2e.scenarios import ALL_SCENARIOS, by_area, by_name  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
_INTEGRITY_LOCK = threading.Lock()


def _run_one(spec, model: str | None, keep: bool) -> dict:
    rec: dict = {"name": spec.name, "area": spec.area, "ok": False, "error": None,
                 "claude_exit": None, "validation_status": None}
    result = None
    try:
        result = run_scenario(spec, model=model)
        rec["claude_exit"] = result.claude_exit
        rec["validation_status"] = (result.validate_json or {}).get("status")
        rec["source_tampered"] = result.source_tampered
        # assert_crate fails the scenario if result.source_tampered — the per-scenario,
        # snapshot-local trust gate. Unlike the old global repo-dirty check it can't be
        # tripped by a *different* concurrent scenario's tampering (no cross-contamination).
        A.assert_crate(result)
        rec["ok"] = True
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
        rec["trace"] = traceback.format_exc()
    finally:
        # Defense in depth: each scenario ran against an isolated source snapshot
        # (PYTHONPATH), so editing the repo's src/ is inert — it's never imported. Revert
        # any stray repo edit anyway to keep the developer's tree clean, and record it for
        # the report. This does NOT fail the scenario; trust is gated on source_tampered.
        with _INTEGRITY_LOCK:
            dirty = repo_source_dirty()
            if dirty:
                rec["repo_touched"] = dirty
                subprocess.run(
                    ["git", "-C", str(REPO_ROOT), "checkout", "--", *_PROTECT_PATHS],
                    capture_output=True, text=True,
                )
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
    before = set(repo_source_dirty().splitlines())
    with protect_repo():
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
            futs = {ex.submit(_run_one, s, args.model, args.keep): s for s in specs}
            for fut in concurrent.futures.as_completed(futs):
                rec = fut.result()
                records.append(rec)
                mark = "PASS" if rec["ok"] else "FAIL"
                print(f"[{mark}] {rec['name']:24s} exit={rec['claude_exit']} "
                      f"valid={rec['validation_status']} {rec['error'] or ''}")

    # Per-scenario reverts keep the repo clean; this should be empty. A non-empty value
    # means a revert lost a race — surfaced, but agent edits to repo src are inert anyway
    # (each scenario imported its own isolated snapshot, not the repo).
    dirty = "\n".join(sorted(set(repo_source_dirty().splitlines()) - before))
    if dirty:
        print("\n*** REPO SOURCE STILL DIRTY AT SUITE END (reverting) ***")
        print(dirty)
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "checkout", "--", *_PROTECT_PATHS],
            capture_output=True, text=True,
        )
    touched = sorted(r["name"] for r in records if r.get("repo_touched"))
    if touched:
        print(f"\n*** {len(touched)} scenario(s) edited repo src (inert, reverted): {touched} ***")
    tampered = sorted(r["name"] for r in records if r.get("source_tampered"))
    if tampered:
        print(f"\n*** {len(tampered)} scenario(s) tampered with their source snapshot: {tampered} ***")

    passed = [r for r in records if r["ok"]]
    report: dict = {
        "total": len(records), "passed": len(passed), "failed": len(records) - len(passed),
        "records": sorted(records, key=lambda r: r["name"]),
        "repo_touched": touched,
        "snapshot_tampered": tampered,
    }
    coverage_gap: list = []
    if not args.name and not args.area and not args.no_coverage:
        passed_specs = [s for s in specs
                        if any(r["name"] == s.name and r["ok"] for r in records)]
        coverage_gap = sorted(coverage.missing_tags(passed_specs))
        report["coverage_missing"] = coverage_gap
        if coverage_gap:
            print(f"\nCOVERAGE GAP ({len(coverage_gap)}): {coverage_gap}")
    report["repo_source_dirty"] = dirty
    (RESULTS / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True))
    print(f"\n{len(passed)}/{len(records)} passed. Report: {RESULTS / 'report.json'}")
    ok = len(passed) == len(records) and not coverage_gap and not dirty
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
