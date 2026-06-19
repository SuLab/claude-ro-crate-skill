from __future__ import annotations

from tests.e2e.assertions import by_type, entities_by_id
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


def _additional_properties(entity: dict, by_id: dict) -> list:
    """Resolve an entity's additionalProperty into a flat list of PropertyValue dicts.

    The materializer emits additionalProperty as an inline dict, a list of dicts, or an
    {"@id": "#embedded/..."} reference into a separate graph entity. Normalize all three.
    """
    raw = entity.get("additionalProperty")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    resolved: list = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if set(item.keys()) == {"@id"}:
            target = by_id.get(item["@id"])
            if isinstance(target, dict):
                resolved.append(target)
        else:
            resolved.append(item)
    return resolved


def _has_not_captured_status(entity: dict, by_id: dict) -> bool:
    for prop in _additional_properties(entity, by_id):
        if prop.get("propertyID") == "capture-status" and prop.get("value") == "not-captured":
            return True
    return False


def _check_custom_redaction(graph: list, result) -> None:
    assert not _crate_contains(result, "ACME-9999"), "custom secret pattern leaked into crate"
    assert by_type(graph, "CreativeWork"), "expected the public note as a CreativeWork"


def _check_env_excluded(graph: list, result) -> None:
    # Negative (filesystem): the non-allowlisted env var value must not appear anywhere.
    assert not _crate_contains(result, "supersecretenvvalue"), \
        "non-allowlisted env var value leaked into crate"
    # Negative (graph): no #env/* PropertyValue may carry the non-allowlisted var's name/value.
    env_pvs = [e for e in graph if str(e.get("@id", "")).startswith("#env/")]
    for pv in env_pvs:
        assert pv.get("name") != "RCR_FAKE_SECRET", \
            "non-allowlisted env var name materialized as an #env/* PropertyValue"
        assert pv.get("value") != "supersecretenvvalue", \
            "non-allowlisted env var value materialized as an #env/* PropertyValue"
    assert "#env/RCR_FAKE_SECRET" not in {e.get("@id") for e in graph}, \
        "non-allowlisted env var captured as #env/RCR_FAKE_SECRET"


def _check_never_capture(graph: list, result) -> None:
    # Content must never appear in the crate tree, and the sensitive files must not be copied.
    assert not _crate_contains(result, "topsecretpassword"), "sensitive file content leaked"
    assert result.crate_path is not None
    crate_dir = result.crate_path.parent
    assert not (crate_dir / "secret.env").exists(), "secret.env was copied into the crate"
    assert not (crate_dir / "deploy.pem").exists(), "deploy.pem was copied into the crate"
    # Graph-level proof of the never-capture contract: each sensitive declared input is a File
    # entity carrying capture-status=not-captured AND never read (no sha256 identifier / size).
    by_id = entities_by_id(graph)
    files = {e["@id"]: e for e in by_type(graph, "File") if "@id" in e}
    for name in ("secret.env", "deploy.pem"):
        ent = files.get(name)
        assert ent is not None, f"missing sensitive File entity {name!r} in @graph"
        assert _has_not_captured_status(ent, by_id), \
            f"{name!r} missing capture-status=not-captured additionalProperty"
        assert "identifier" not in ent, f"{name!r} carries an identifier (sha256) — content hashed"
        assert "contentSize" not in ent, f"{name!r} carries contentSize — content was read"


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
