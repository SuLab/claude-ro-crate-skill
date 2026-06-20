from __future__ import annotations

import json
import subprocess

from tests.e2e.harness import RCR, build_env
from tests.e2e.scenarios._common import PROCESS_URI, STRICT_PREAMBLE, prescriptive_prompt
from tests.e2e.spec import ScenarioSpec, SeedFile

MIN_CRATE = json.dumps({
    "@context": "https://w3id.org/ro/crate/1.2/context",
    "@graph": [
        {"@id": "ro-crate-metadata.json", "@type": "CreativeWork",
         "about": {"@id": "./"}, "conformsTo": {"@id": "https://w3id.org/ro/crate/1.2"}},
        {"@id": "./", "@type": "Dataset", "name": "Imported run",
         "description": "An external crate to import", "datePublished": "2026-01-01",
         "license": {"@id": "https://creativecommons.org/licenses/by/4.0/"},
         "conformsTo": {"@id": "https://w3id.org/ro/wfrun/process/0.5"},
         "hasPart": [{"@id": "input.csv"}]},
        {"@id": "input.csv", "@type": "File", "name": "input.csv"},
    ],
}, indent=2)


def _journal(result) -> list[dict]:
    p = result.workdir / ".ro-crate-run" / "events.ndjson"
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def _has_event(result, etype: str) -> bool:
    return any(e.get("event_type") == etype for e in _journal(result))


def _glob(result, pattern: str) -> list:
    return list(result.workdir.rglob(pattern))


def _check_public_export(graph: list, result) -> None:
    assert _has_event(result, "crate.finalized"), "no crate.finalized event"
    assert _glob(result, "*.zip"), "finalize --zip produced no zip archive"


def _check_sign(graph: list, result) -> None:
    assert _glob(result, "*.sig"), "no .sig signature file produced"
    assert _has_event(result, "crate.signed"), "no crate.signed event"
    # Verify the real sign+verify roundtrip on the actual crate: re-sign the current manifest
    # (deterministic regardless of any post-sign manifest change the agent/finalize made),
    # then `rcr verify` must accept it — and a one-byte tamper must make it fail.
    env = build_env(result.workdir)
    subprocess.run([str(RCR), "sign"], cwd=result.workdir, env=env, capture_output=True)
    ok = subprocess.run(
        [str(RCR), "verify"], cwd=result.workdir, env=env, capture_output=True, text=True,
    )
    assert ok.returncode == 0, f"rcr verify rejected a freshly-signed crate: {ok.stderr}"
    manifest = result.workdir / ".ro-crate-run" / "ro-crate" / "ro-crate-metadata.json"
    manifest.write_text(manifest.read_text() + " ")  # tamper
    bad = subprocess.run(
        [str(RCR), "verify"], cwd=result.workdir, env=env, capture_output=True, text=True,
    )
    assert bad.returncode != 0, "rcr verify accepted a tampered manifest"


def _check_export_blocked(graph: list, result) -> None:
    # Claude produced a crate whose output contains a secret; a safety-conscious agent
    # declines to publicly export it, so the harness triggers the export to verify the
    # gate fails closed.
    env = build_env(result.workdir)
    proc = subprocess.run(
        [str(RCR), "finalize", "--public", "--zip"],
        cwd=result.workdir, env=env, capture_output=True, text=True,
    )
    assert proc.returncode != 0, f"public export was not blocked (rc={proc.returncode})"
    assert _has_event(result, "run.export.blocked"), "no run.export.blocked event after gate"
    assert not _glob(result, "*.zip"), "a release zip was shipped despite the gate block"


def _check_redact_applied(graph: list, result) -> None:
    # Asserting the bookkeeping (backup + event) is not enough — prove the redaction actually
    # rewrote the captured text: the token must be gone from every live published surface (the
    # projected crate @graph and the live event journal) and the placeholder must be present.
    # The pre-redaction-* backup is excluded from the scrub check (it is the retained original).
    backups = _glob(result, "events.ndjson.pre-redaction-*")
    assert backups, "redact --apply did not preserve a pre-redaction journal backup"
    assert _has_event(result, "redaction.applied"), "no redaction.applied event"

    token = "ACME-9999"          # the exact id journaled by the scenario prompt
    placeholder = "[REDACTED:secret]"

    graph_blob = json.dumps(graph)
    assert token not in graph_blob, (
        f"redacted token {token!r} still present in the projected crate @graph; "
        "redaction did not modify the published text"
    )
    assert placeholder in graph_blob, (
        f"redaction placeholder {placeholder!r} not found in the crate @graph"
    )
    journal_blob = json.dumps(_journal(result))
    assert token not in journal_blob, f"redacted token {token!r} still present in the live journal"
    assert placeholder in journal_blob, (
        f"redaction placeholder {placeholder!r} not found in the live event journal"
    )


def _check_finalized(graph: list, result) -> None:
    assert _has_event(result, "crate.finalized"), "no crate.finalized event"


def _check_imported(graph: list, result) -> None:
    assert _has_event(result, "crate.finalized") or graph, "import produced nothing"


SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        name="admin-finalize-public",
        area="admin",
        expected_profile_uri=PROCESS_URI,
        public=True,
        needles=("Private internal",),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:finalize", "flag:finalize:--public", "flag:finalize:--zip",
            "feature:public-export",
        }),
        check=_check_public_export,
        prompt=prescriptive_prompt(
            "Produce a public release package.",
            [
                'rcr start "Public release" --mode advisory --profile process',
                'rcr software python3 --version "3.12.3"',
                'rcr note "Public summary of the analysis" --public',
                'rcr note "Private internal reasoning" --private',
                "rcr run --outputs out.txt -- python3 -c \"open('out.txt','w').write('result\\n')\"",
                "rcr output out.txt --role result --required",
                "rcr checkpoint",
                "rcr finalize --public --zip",
            ],
        ),
    ),
    ScenarioSpec(
        name="admin-finalize-journal",
        area="admin",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "flag:finalize:--private", "flag:finalize:--include-event-journal",
        }),
        check=_check_finalized,
        prompt=prescriptive_prompt(
            "Finalize privately with the event journal embedded.",
            [
                'rcr start "Private with journal" --mode advisory --profile process',
                "rcr run -- python3 -c \"print('work')\"",
                "rcr checkpoint",
                "rcr finalize --private --include-event-journal",
            ],
        ),
    ),
    ScenarioSpec(
        name="admin-sign",
        area="admin",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:sign", "cmd:verify", "feature:signing", "flag:finalize:--sign",
        }),
        check=_check_sign,
        prompt=prescriptive_prompt(
            "Sign the finalized crate with the project key and verify the signature.",
            [
                'rcr start "Signed release" --mode advisory --profile process',
                "rcr run --outputs out.txt -- python3 -c \"open('out.txt','w').write('x\\n')\"",
                "rcr output out.txt --role result",
                "rcr checkpoint",
                "rcr sign",
                "rcr verify",
                "rcr finalize --private --sign",
            ],
        ),
    ),
    ScenarioSpec(
        name="admin-export-blocked",
        area="admin",
        skip_crate_battery=True,
        allow_blocked=True,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({"feature:export-blocked"}),
        check=_check_export_blocked,
        prompt=prescriptive_prompt(
            "Record a run whose output file contains test secret material (a dummy key).",
            [
                'rcr start "Blocked export" --mode advisory --profile process',
                "rcr run --outputs leak.txt -- python3 -c "
                "\"open('leak.txt','w').write('-----BEGIN RSA PRIVATE KEY-----\\nAKIAIOSFODNN7EXAMPLE\\n')\"",
                "rcr output leak.txt --role result",
                "rcr checkpoint",
            ],
        ),
    ),
    ScenarioSpec(
        name="admin-redact",
        area="admin",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({"cmd:redact", "feature:redact-apply"}),
        check=_check_redact_applied,
        prompt=prescriptive_prompt(
            "Record a note containing a project-specific identifier, then add a custom "
            "redaction pattern and apply it to the journal in place.",
            [
                'rcr start "Redaction" --mode advisory --profile process',
                'rcr note "Resolved ticket ACME-9999 during the work" --public',
                'Create the file .ro-crate-run/secrets-redaction.json with exactly this content: '
                '{"patterns": ["ACME-[0-9]+"]}',
                "rcr run -- python3 -c \"print('work')\"",
                "rcr redact --apply",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="admin-import",
        area="admin",
        expected_profile_uri=PROCESS_URI,
        seed_files=(SeedFile("to-import/ro-crate-metadata.json", MIN_CRATE),),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({"cmd:import-ro-crate", "feature:import", "cmd:export"}),
        check=_check_imported,
        prompt=prescriptive_prompt(
            "Bootstrap a run by importing an existing RO-Crate, then export it.",
            [
                'rcr start "Import existing" --mode advisory --profile process',
                "rcr import-ro-crate to-import",
                "rcr run -- python3 -c \"print('post-import work')\"",
                "rcr checkpoint",
                "rcr export --out exported.zip",
            ],
        ),
    ),
]
