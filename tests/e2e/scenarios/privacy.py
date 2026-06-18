from __future__ import annotations

from tests.e2e.assertions import by_type
from tests.e2e.scenarios._common import PROCESS_URI, STRICT_PREAMBLE, prescriptive_prompt
from tests.e2e.spec import ScenarioSpec, SeedFile


def _crate_contains(result, text: str) -> bool:
    if result.crate_path is None:
        return False
    for p in result.crate_path.parent.rglob("*"):
        if p.is_file():
            try:
                if text in p.read_text(errors="ignore"):
                    return True
            except OSError:
                continue
    return False


def _check_custom_redaction(graph: list, result) -> None:
    assert not _crate_contains(result, "ACME-9999"), "custom secret pattern leaked into crate"
    assert by_type(graph, "CreativeWork"), "expected the public note as a CreativeWork"


def _check_env_excluded(graph: list, result) -> None:
    assert not _crate_contains(result, "supersecretenvvalue"), \
        "non-allowlisted env var value leaked into crate"


def _check_never_capture(graph: list, result) -> None:
    assert not _crate_contains(result, "topsecretpassword"), "sensitive file content leaked"
    assert result.crate_path is not None
    crate_dir = result.crate_path.parent
    assert not (crate_dir / "secret.env").exists(), "secret.env was copied into the crate"
    assert not (crate_dir / "deploy.pem").exists(), "deploy.pem was copied into the crate"


SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        name="priv-custom-redaction",
        area="privacy",
        expected_profile_uri=PROCESS_URI,
        public=True,
        needles=("ACME-9999",),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({"feature:custom-redaction"}),
        check=_check_custom_redaction,
        prompt=prescriptive_prompt(
            "Configure a custom redaction pattern, then record a public note that contains "
            "a matching secret. The secret must be redacted before it is persisted.",
            [
                'rcr start "Custom redaction" --mode advisory --profile process',
                'Create the file .ro-crate-run/secrets-redaction.json with exactly this content: '
                '{"patterns": ["ACME-[0-9]+"]}',
                'rcr note "Resolved ticket ACME-9999 during the analysis" --public',
                "rcr run -- python3 -c \"print('work')\"",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="priv-env-exclude",
        area="privacy",
        expected_profile_uri=PROCESS_URI,
        env={"RCR_FAKE_SECRET": "supersecretenvvalue"},
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({"feature:env-allowlist"}),
        check=_check_env_excluded,
        prompt=prescriptive_prompt(
            "Capture a run; a non-allowlisted environment variable must not be recorded.",
            [
                'rcr start "Env allowlist" --mode advisory --profile process',
                'rcr software python3 --version "3.12.3"',
                "rcr run --outputs out.txt -- python3 -c \"open('out.txt','w').write('x\\n')\"",
                "rcr output out.txt --role result",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="priv-never-capture",
        area="privacy",
        expected_profile_uri=PROCESS_URI,
        seed_files=(
            SeedFile("secret.env", "API_KEY=topsecretpassword\n"),
            SeedFile("deploy.pem", "-----BEGIN KEY-----\ntopsecretpassword\n-----END KEY-----\n"),
        ),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({"feature:never-capture"}),
        check=_check_never_capture,
        prompt=prescriptive_prompt(
            "Declare sensitive files as inputs even with copying enabled; they must never "
            "be read or copied into the crate.",
            [
                'rcr start "Never capture" --mode advisory --profile process',
                "rcr config file_policy.include_declared_inputs true",
                "rcr input secret.env --role config --copy",
                "rcr input deploy.pem --role key --copy",
                "rcr run -- python3 -c \"print('work')\"",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
]
