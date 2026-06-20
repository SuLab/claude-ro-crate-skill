from __future__ import annotations

import json as _json
from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.validation.context import build_context
from ro_crate_run.validation.journal import check_journal
from ro_crate_run.validation.privacy import check_privacy
from ro_crate_run.validation.profiles import check_profile
from ro_crate_run.validation.reproducibility import check_reproducibility
from ro_crate_run.validation.rocrate import check_rocrate
from ro_crate_run.validation.shacl import check_shacl
from ro_crate_run.validation.state import check_state
from ro_crate_run.validation.validator import validate_run


def _start(tmp_path: Path, monkeypatch) -> Path:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Ctx demo", "--no-checkpoint"]) == 0
    return tmp_path / ".ro-crate-run"


# --- ValidationContext tests ---


def test_context_is_active_before_finalize(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    ctx = build_context(state_dir, strict=False, public=False)
    assert ctx.active_run is True
    assert ctx.events  # run.started present
    assert ctx.metadata is None  # no checkpoint yet


def test_context_inactive_after_finalize(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["checkpoint"]) == 0
    assert main(["finalize"]) == 0
    ctx = build_context(state_dir, strict=False, public=False)
    assert ctx.active_run is False
    assert ctx.metadata is not None


# --- Level 0: journal tests ---


def _corrupt_last_event(state_dir: Path, mutate) -> None:  # type: ignore[no-untyped-def]
    path = state_dir / "events.ndjson"
    lines = [line for line in path.read_text().splitlines() if line.strip()]
    obj = _json.loads(lines[-1])
    mutate(obj)
    lines[-1] = _json.dumps(obj)
    path.write_text("\n".join(lines) + "\n")


def test_journal_clean_run_has_no_errors(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    findings = check_journal(build_context(state_dir, strict=False, public=False))
    assert [f for f in findings if f.code != "open"] == []


def test_journal_flags_unregistered_event_type(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # L0 now enforces the central EVENT_TYPES vocabulary: an event whose type is not
    # registered is flagged (the registry is no longer decorative).
    from ro_crate_run.journal import EventWriter

    state_dir = _start(tmp_path, monkeypatch)
    EventWriter(state_dir).append("totally.bogus.type", {"x": 1}, source_kind="human_cli")
    findings = check_journal(build_context(state_dir, strict=False, public=False))
    assert any(f.code == "unknown_event_type" for f in findings), \
        "L0 did not flag an unregistered event type"


def test_journal_detects_hash_tamper(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    _corrupt_last_event(state_dir, lambda o: o["payload"].__setitem__("x", "tampered"))
    findings = check_journal(build_context(state_dir, strict=False, public=False))
    assert any(f.code == "event_hash_mismatch" for f in findings)


def test_journal_detects_bad_timestamp(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    _corrupt_last_event(state_dir, lambda o: o.__setitem__("timestamp", "not-a-date"))
    findings = check_journal(build_context(state_dir, strict=False, public=False))
    assert any(f.code in {"invalid_timestamp", "event_hash_mismatch"} for f in findings)


def test_journal_unterminated_command_ok_while_active(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    path = state_dir / "events.ndjson"
    last = _json.loads([line for line in path.read_text().splitlines() if line.strip()][-1])
    started = dict(last)
    started.update(
        event_type="execution.command.started",
        sequence=last["sequence"] + 1,
        payload={"command_id": "cmd_999"},
        previous_event_hash=last["event_hash"],
    )
    from ro_crate_run.events import compute_event_hash
    started["event_hash"] = compute_event_hash(started)
    with path.open("a") as fh:
        fh.write(_json.dumps(started) + "\n")
    import json as j
    state_data = j.loads((state_dir / "state.json").read_text())
    state_data["sequence"] = started["sequence"]
    state_data["last_event_hash"] = started["event_hash"]
    (state_dir / "state.json").write_text(j.dumps(state_data))
    ctx = build_context(state_dir, strict=False, public=False)
    assert ctx.active_run is True
    assert not any(f.code == "unterminated_command" for f in check_journal(ctx))


# --- Level 1: state tests ---


def test_state_clean_after_checkpoint(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["checkpoint"]) == 0
    findings = [f for f in check_state(build_context(state_dir, strict=False, public=False)) if f.level == "state"]
    assert [f for f in findings if f.code not in {"open_phase", "open_step"}] == []


def test_state_detects_dirty_mismatch(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["checkpoint"]) == 0
    # Add a post-checkpoint output declaration to make the run dirty again
    assert main(["output", "extra.txt"]) == 0
    # Now force dirty=False
    s = _json.loads((state_dir / "state.json").read_text())
    s["dirty"] = False
    (state_dir / "state.json").write_text(_json.dumps(s))
    findings = check_state(build_context(state_dir, strict=False, public=False))
    assert any(f.code == "dirty_flag_inaccurate" for f in findings)


def test_state_detects_idmap_inconsistency(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    (state_dir / "id-map.json").write_text('{"event_to_entity": "not-a-dict"}')
    findings = check_state(build_context(state_dir, strict=False, public=False))
    assert any(f.code == "id_map_invalid" for f in findings)


# --- Level 2: rocrate tests ---


def test_rocrate_clean_checkpoint(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["checkpoint"]) == 0
    findings = check_rocrate(build_context(state_dir, strict=False, public=False))
    assert [f for f in findings if f.level == "ro_crate"] == []


def test_rocrate_declared_absent_file_not_flagged_missing(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # A file declared with a non-present existence (e.g. "expected") is legitimately
    # absent on disk and must not be reported as referenced_file_missing.
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["output", "future.txt", "--existence", "expected"]) == 0
    assert main(["run", "--", "python3", "-c", "print('x')"]) == 0
    assert main(["checkpoint"]) == 0
    findings = check_rocrate(build_context(state_dir, strict=False, public=False))
    assert not any(
        f.code == "referenced_file_missing" and f.path == "future.txt" for f in findings
    )


def test_rocrate_missing_metadata(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)  # no checkpoint -> no metadata
    findings = check_rocrate(build_context(state_dir, strict=False, public=False))
    assert any(f.code == "metadata_missing" for f in findings)


def test_rocrate_missing_referenced_file(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["checkpoint"]) == 0
    meta = state_dir / "ro-crate" / "ro-crate-metadata.json"
    data = _json.loads(meta.read_text())
    data["@graph"].append({"@id": "ghost.txt", "@type": "File", "name": "ghost.txt"})
    for e in data["@graph"]:
        if e["@id"] == "./":
            e.setdefault("hasPart", []).append({"@id": "ghost.txt"})
    meta.write_text(_json.dumps(data))
    findings = check_rocrate(build_context(state_dir, strict=False, public=False))
    assert any(f.code == "referenced_file_missing" for f in findings)


# --- Level 3: profile tests ---


def test_profile_process_requires_action_under_strict(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["checkpoint"]) == 0  # no commands -> no action
    findings = check_profile(build_context(state_dir, strict=True, public=False))
    assert any(f.code == "process_no_action" for f in findings)


def test_profile_missing_required_output(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["output", "results/final.txt", "--required"]) == 0
    main(["checkpoint"])  # may return 1 due to missing output — that's expected
    findings = check_profile(build_context(state_dir, strict=False, public=False))
    assert any(f.code == "missing_required_output" for f in findings)


def test_profile_workflow_synthesizes_agent_workflow(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The agent's own actions ARE the workflow (SPEC §16): forcing the workflow profile
    # with no external definition file synthesizes a ComputationalWorkflow + mainEntity,
    # so there are no missing-entity findings.
    state_dir = _start(tmp_path, monkeypatch)
    main(["run", "--", "python3", "-c", "print('hi')"])
    main(["checkpoint", "--profile", "workflow"])
    findings = check_profile(build_context(state_dir, strict=False, public=False))
    assert not any(f.code == "workflow_missing_main_entity" for f in findings)
    assert not any(f.code == "workflow_missing_entity" for f in findings)
    meta = _json.loads((state_dir / "ro-crate" / "ro-crate-metadata.json").read_text())
    ids = {e.get("@id") for e in meta["@graph"]}
    assert "#workflow/agent-actions" in ids
    root = next(e for e in meta["@graph"] if e.get("@id") == "./")
    assert root.get("mainEntity", {}).get("@id") == "#workflow/agent-actions"


# --- Level 4: reproducibility tests ---


def test_repro_warns_missing_software(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    findings = check_reproducibility(build_context(state_dir, strict=False, public=False))
    assert any(f.code == "missing_software_versions" and f.level == "reproducibility" for f in findings)


def test_repro_require_software_escalates_to_error(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    cfg = _json.loads((state_dir / "config.json").read_text())
    cfg["validation"]["require_software_versions"] = True
    cfg["validation"]["require_git_commit"] = True
    (state_dir / "config.json").write_text(_json.dumps(cfg))
    # Per SPEC §17.1 L4, missing software versions is a warning by default;
    # require_software_versions (SPEC §19, default true) escalates to an error only under --strict (§18.3).
    ctx_warn = build_context(state_dir, strict=False, public=False)
    warns = [f for f in check_reproducibility(ctx_warn) if f.code == "missing_software_versions"]
    assert warns and warns[0].level == "reproducibility"
    ctx_err = build_context(state_dir, strict=True, public=False)
    errs = [f for f in check_reproducibility(ctx_err) if f.code == "missing_software_versions_required"]
    assert errs and errs[0].level == "reproducibility"


# --- Level 5: privacy tests ---


def test_privacy_seam_noop_when_not_public(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["checkpoint"]) == 0
    assert check_privacy(build_context(state_dir, strict=False, public=False)) == []


def test_privacy_seam_scans_files_when_public(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["checkpoint"]) == 0
    (state_dir / "ro-crate" / "leak.txt").write_text("AKIAIOSFODNN7EXAMPLE aws key")
    findings = check_privacy(build_context(state_dir, strict=False, public=True))
    assert any(f.code == "secret_pattern" for f in findings)


# --- SHACL tests ---


def test_shacl_skips_when_not_strict(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["checkpoint"]) == 0
    assert check_shacl(build_context(state_dir, strict=False, public=False)) == []


# --- validate_run orchestrator tests ---


def test_validate_run_populates_recommendations(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["checkpoint"]) == 0
    report = validate_run(state_dir, strict=False, public=False, append_event=False)
    assert report.recommendations  # at least the missing-software recommendation
    assert report.status in {"passed", "warning", "failed"}
    assert set(report.levels) == {"journal", "state", "ro_crate", "profile", "reproducibility", "privacy"}


def test_standalone_validate_does_not_mark_stale_crate_clean(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    state_dir = _start(tmp_path, monkeypatch)
    assert main(["checkpoint"]) == 0
    assert main(["note", "post-checkpoint note", "--public"]) == 0

    from ro_crate_run.state import load_state

    assert load_state(state_dir).dirty is True
    assert main(["validate"]) == 0

    state = load_state(state_dir)
    assert state.dirty is True
    assert state.last_checkpoint is not None
    assert state.last_checkpoint.materialized_through_sequence < state.sequence


def test_validate_run_strict_from_config(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # config.validation.strict must genuinely ESCALATE: an empty run (no actions) validates
    # without errors normally, but strict mode promotes the no_actions profile finding to an
    # error -> status failed. Asserting the actual divergence (not the whole status universe)
    # is what catches a regression that silently disables config-strict.
    state_dir = _start(tmp_path, monkeypatch)
    main(["checkpoint"])
    lenient = validate_run(state_dir, strict=False, public=False, append_event=False)
    assert lenient.status != "failed", f"empty run should not fail leniently: {lenient.errors}"

    cfg = _json.loads((state_dir / "config.json").read_text())
    cfg["validation"]["strict"] = True
    (state_dir / "config.json").write_text(_json.dumps(cfg))
    strict = validate_run(state_dir, strict=False, public=False, append_event=False)
    assert strict.status == "failed", "config strict=True did not escalate the empty-run findings"
    assert strict.status != lenient.status, "config-strict produced the same status as lenient"
    assert set(strict.levels) == {
        "journal", "state", "ro_crate", "profile", "reproducibility", "privacy"
    }
