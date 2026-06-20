from __future__ import annotations

import json

from tests.e2e.assertions import by_type, entities_by_id
from tests.e2e.scenarios._common import (
    PROCESS_URI,
    STRICT_PREAMBLE,
    WORKFLOW_URI,
    prescriptive_prompt,
)
from tests.e2e.spec import ScenarioSpec, SeedFile


def _has_prop_value(graph: list, name: str) -> bool:
    for e in graph:
        t = e.get("@type")
        if "PropertyValue" in ([t] if isinstance(t, str) else (t or [])) and e.get("name") == name:
            return True
    return False


def _types(entity: dict) -> list:
    t = entity.get("@type")
    return t if isinstance(t, list) else [t]


def _existence_values(graph: list) -> set:
    # Per RO-Crate 1.2 (no anonymous inlining) additionalProperty PropertyValues are
    # top-level #embedded/* nodes referenced via {"@id": ...}; resolve the references.
    by_id = {e.get("@id"): e for e in graph}
    vals: set = set()
    for e in graph:
        if not ({"File", "Dataset"} & set(_types(e))):
            continue
        ap = e.get("additionalProperty")
        ap = ap if isinstance(ap, list) else ([ap] if ap else [])
        for p in ap:
            if isinstance(p, dict) and set(p.keys()) == {"@id"}:
                p = by_id.get(p["@id"], p)
            if isinstance(p, dict) and p.get("propertyID") == "existence":
                vals.add(p.get("value"))
    return vals


def _check_io_flags(graph: list, result) -> None:
    assert len(by_type(graph, "File")) >= 4, "expected several File entities"
    # Every declared existence class must be MATERIALIZED into the crate (not just stored
    # in state.json), so a consumer can distinguish an observed input from an
    # expected-but-absent output.
    present = _existence_values(graph)
    expected = {"observed local", "observed remote", "generated",
                "expected", "missing", "declared-only"}
    assert expected <= present, f"existence values not materialized: {expected - present}"
    ids = entities_by_id(graph)
    haspart = {r.get("@id") for r in (ids.get("./", {}).get("hasPart") or [])}
    # policy:copy — the --copy output is a navigable data part.
    assert "out.txt" in haspart, f"copied output out.txt not in root hasPart: {sorted(haspart)}"
    # policy:out-of-root-reference — an out-of-root input is a file: reference, never a part.
    host = [e["@id"] for e in graph if str(e.get("@id", "")).startswith("file:")]
    assert host, "no out-of-root file: reference entity"
    assert not (set(host) & haspart), "out-of-root reference was copied into hasPart"


def _check_notes_decisions(graph: list, result) -> None:
    # A public note (#note/*) is a distinct CreativeWork from any decision (#decision/*).
    notes = [
        e for e in graph
        if str(e.get("@id", "")).startswith("#note/") and "CreativeWork" in _types(e)
    ]
    assert notes, "no public #note/* CreativeWork entity"
    decisions = [
        e for e in graph
        if str(e.get("@id", "")).startswith("#decision/") and "CreativeWork" in _types(e)
    ]
    assert any(e.get("description") for e in decisions), \
        "no decision entity with rationale description"
    note_ids = {n["@id"] for n in notes}
    decision_ids = {d["@id"] for d in decisions}
    assert note_ids and not (note_ids & decision_ids), \
        "public note is not distinct from the decision entities"
    # The PRIVATE note/decision text must never leak into the graph (redaction happens before
    # persistence, so --private content stays out of the crate entirely).
    blob = json.dumps(graph)
    for secret in ("Private internal note", "Internal tradeoff", "kept for the record"):
        assert secret not in blob, f"private text leaked into the graph: {secret!r}"
    # The scenario runs `rcr reject`, which must surface as a failed AssessAction carrying an
    # error (a FailedActionStatus action without an error would violate the L3 profile rule).
    rejected = [
        e for e in by_type(graph, "AssessAction")
        if (e.get("actionStatus") or {}).get("@id", "").endswith("FailedActionStatus")
    ]
    assert rejected, "rcr reject did not produce a FailedActionStatus AssessAction"
    assert all(e.get("error") for e in rejected), \
        f"rejected AssessAction missing error: {rejected}"


def _check_phase_open_warning(graph: list, result) -> None:
    warnings = (result.validate_json or {}).get("warnings", [])
    assert any(w.get("code", "").startswith("open_phase") for w in warnings), \
        f"expected an open_phase warning; got {[w.get('code') for w in warnings]}"


def _check_git(graph: list, result) -> None:
    git = entities_by_id(graph).get("#git/state")
    assert git is not None, "no #git/state entity"
    assert "Thing" in _types(git), f"#git/state is not a Thing: {_types(git)}"  # entity:Thing
    assert _has_prop_value(graph, "branch"), "no git branch PropertyValue"
    assert _has_prop_value(graph, "dirty"), "no git dirty PropertyValue"
    # The e2e harness seeds an `origin` remote, so the remote PropertyValue must appear.
    assert _has_prop_value(graph, "remote"), "no git remote PropertyValue"
    # The scanned dependency manifest is materialized with a verifiable sha256 digest.
    req = entities_by_id(graph).get("requirements.txt")
    assert req is not None, "requirements.txt dependency manifest not materialized"
    # identifier is a {"@id": "#embedded/..."} reference to a top-level sha256 PropertyValue.
    ident = req.get("identifier") or {}
    if set(ident.keys()) == {"@id"}:
        ident = entities_by_id(graph).get(ident["@id"], ident)
    digest = ident.get("value", "")
    assert len(str(digest)) == 64, f"dependency manifest missing sha256: {req}"
    # include_git_diff=always over a dirty tree must materialize the diff/patch as a File whose
    # `about` points back at the git state, so the captured patch is reachable provenance.
    diffs = [
        e for e in graph
        if "File" in _types(e) and (
            e.get("encodingFormat") == "text/x-patch"
            or (
                str(e.get("@id", "")).startswith(".ro-crate-run/")
                and str(e.get("@id", "")).endswith((".patch", ".diff"))
            )
        )
    ]
    assert diffs, "include_git_diff=always did not emit a git diff/patch File entity"
    assert any((d.get("about") or {}).get("@id") == "#git/state" for d in diffs), \
        f"git diff File does not point `about` at #git/state: {diffs}"


def _check_journal_embedded(graph: list, result) -> None:
    ids = {e.get("@id") for e in graph}
    assert "events.ndjson" in ids, "event journal File entity not embedded in crate"


def _check_params_container(graph: list, result) -> None:
    ids = entities_by_id(graph)
    containers = by_type(graph, "ContainerImage")
    assert containers, "no ContainerImage entity"
    # `rcr container docker.io/library/python:3.12 --digest sha256:deadbeef` must split into
    # registry/image/tag/sha256 with the EXACT expected values (the digest loses its algo prefix).
    img = next(
        (c for c in containers
         if c.get("registry") == "docker.io" and c.get("tag") == "3.12"), None)
    assert img is not None, \
        f"no ContainerImage with registry docker.io / tag 3.12: {containers}"
    assert img.get("name") == "library/python", \
        f"ContainerImage name(image) {img.get('name')!r} != library/python"
    assert img.get("sha256") == "deadbeef", \
        f"ContainerImage sha256 {img.get('sha256')!r} != deadbeef"
    # The connected parameter must produce a ParameterConnection whose source/target resolve
    # to the declared #param/* FormalParameter entities.
    conns = by_type(graph, "ParameterConnection")
    assert conns, "no ParameterConnection entity"
    conn = conns[0]
    src = (conn.get("sourceParameter") or {}).get("@id")
    tgt = (conn.get("targetParameter") or {}).get("@id")
    assert src == "#param/raw", f"connection sourceParameter {src!r} != #param/raw"
    assert tgt == "#param/clean", f"connection targetParameter {tgt!r} != #param/clean"
    for pid in (src, tgt):
        fp = ids.get(pid)
        assert fp is not None, f"connection endpoint {pid!r} resolves to no entity"
        assert "FormalParameter" in _types(fp), \
            f"connection endpoint {pid!r} is not a FormalParameter: {_types(fp)}"


SCENARIOS: list[ScenarioSpec] = [
    ScenarioSpec(
        name="field-io-flags",
        area="fields",
        expected_profile_uri=PROCESS_URI,
        seed_files=(
            SeedFile("local_in.txt", "local input\n"),
            SeedFile("copy_me.txt", "copy this\n"),
            SeedFile("ref_me.txt", "reference this\n"),
        ),
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "flag:input:--required", "flag:input:--public", "flag:input:--private",
            "flag:input:--existence", "flag:input:--copy", "flag:input:--reference",
            "flag:output:--description", "flag:output:--public", "flag:output:--private",
            "flag:output:--existence", "flag:output:--copy", "flag:output:--reference",
            "existence:observed local", "existence:observed remote", "existence:generated",
            "existence:expected", "existence:missing", "existence:declared-only",
            "policy:copy", "policy:reference", "policy:out-of-root-reference",
        }),
        check=_check_io_flags,
        prompt=prescriptive_prompt(
            "Declare inputs and outputs covering every flag and existence value.",
            [
                'rcr start "IO flags" --mode advisory --profile process',
                'rcr input local_in.txt --role dataset --existence "observed local" --required --private',
                "rcr input copy_me.txt --role aux --copy --public",
                "rcr input ref_me.txt --role aux --reference",
                'rcr input /etc/hostname --role host --reference --existence "observed local"',
                'rcr input remote_data.csv --role remote --existence "observed remote"',
                'rcr input maybe.txt --role optional --existence "declared-only"',
                'rcr output out.txt --role result --description "the result" --existence generated --required --copy',
                'rcr output future.txt --role pending --existence expected --private',
                'rcr output gone.txt --role gone --existence missing --reference',
                "rcr run --outputs out.txt -- python3 -c \"open('out.txt','w').write('done\\n')\"",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="field-notes-decisions",
        area="fields",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:note", "cmd:decision", "cmd:accept", "cmd:reject",
            "flag:note:--public", "flag:note:--private",
            "flag:decision:--rationale", "flag:decision:--public", "flag:decision:--private",
            "entity:CreativeWork", "prop:decision:rationale",
        }),
        check=_check_notes_decisions,
        prompt=prescriptive_prompt(
            "Record observations and decisions, public and private.",
            [
                'rcr start "Notes and decisions" --mode advisory --profile process',
                'rcr note "Public observation about the data" --public',
                'rcr note "Private internal note" --private',
                'rcr decision "Chose method A" --rationale "A is simpler and faster" --public',
                'rcr decision "Internal tradeoff" --rationale "kept for the record" --private',
                "rcr run -- python3 -c \"print('work')\"",
                'rcr accept "Result looks correct"',
                'rcr reject "Second attempt was wrong"',
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="field-phase",
        area="fields",
        expected_profile_uri=WORKFLOW_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:phase", "feature:open-phase-warning",
        }),
        expect_validation_status=("passed", "warning"),
        check=_check_phase_open_warning,
        prompt=prescriptive_prompt(
            "Structure work into phases and leave the last phase open.",
            [
                'rcr start "Phased work" --mode advisory --profile auto',
                "rcr phase setup",
                "rcr run -- python3 -c \"print('setup')\"",
                "rcr phase analysis --complete-current",
                "rcr run -- python3 -c \"print('analyze')\"",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="field-git-deps",
        area="fields",
        expected_profile_uri=PROCESS_URI,
        seed_files=(
            SeedFile("requirements.txt", "requests==2.31.0\nnumpy==1.26.0\n"),
            SeedFile("README.md", "# project\n"),
        ),
        git_commit=True,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "cmd:config", "policy:lockfile-scan", "policy:include_git_diff",
            "prop:git:branch", "prop:git:dirty", "prop:git:remote", "entity:Thing",
        }),
        check=_check_git,
        prompt=prescriptive_prompt(
            "Capture git state (with a dirty working tree) and dependency lockfiles.",
            [
                'rcr start "Git and deps" --mode advisory --profile process',
                "rcr config file_policy.include_git_diff always",
                'rcr software python3 --version "3.12.3"',
                "rcr run --outputs README.md -- python3 -c "
                "\"open('README.md','a').write('dirty change\\n')\"",
                "rcr output README.md --role doc",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="field-config-journal",
        area="fields",
        expected_profile_uri=PROCESS_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "policy:include_event_journal",
        }),
        check=_check_journal_embedded,
        prompt=prescriptive_prompt(
            "Enable embedding the event journal in the crate.",
            [
                'rcr start "Embedded journal" --mode advisory --profile process',
                "rcr config file_policy.include_event_journal true",
                "rcr run -- python3 -c \"print('hi')\"",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
    ScenarioSpec(
        name="field-params-container",
        area="fields",
        expected_profile_uri=WORKFLOW_URI,
        append_system_prompt=STRICT_PREAMBLE,
        coverage_tags=frozenset({
            "entity:ParameterConnection", "entity:ContainerImage",
        }),
        check=_check_params_container,
        prompt=prescriptive_prompt(
            "Declare a containerized step with connected parameters.",
            [
                'rcr start "Params and container" --mode advisory --profile workflow',
                'rcr software python3 --version "3.12.3"',
                "rcr container docker.io/library/python:3.12 --digest sha256:deadbeef",
                'rcr parameter raw raw.csv --formal-parameter "#param/raw" --type File',
                'rcr parameter clean clean.csv --formal-parameter "#param/clean" --type File --connect-from "#param/raw" --connect-to "#param/clean"',
                "rcr run --outputs clean.csv -- python3 -c \"open('clean.csv','w').write('ok\\n')\"",
                "rcr output clean.csv --role result --required",
                "rcr checkpoint",
                "rcr validate --json",
            ],
        ),
    ),
]
