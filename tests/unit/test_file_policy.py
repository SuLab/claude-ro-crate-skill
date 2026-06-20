from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from filelock import FileLock, Timeout

from ro_crate_run.cli import main
from ro_crate_run.config import default_config
from ro_crate_run.materialize.builder import checkpoint
from ro_crate_run.materialize.files import FilePlan, plan_file_inclusion
from ro_crate_run.models import RunModel
from tests.graph_helpers import resolve_ref

# ---------------------------------------------------------------------------
# Task 1: FilePlan + inclusion by include_declared_inputs/outputs
# ---------------------------------------------------------------------------


def _model(tmp_path: Path) -> RunModel:
    (tmp_path / "in.csv").write_text("a,b\n")
    (tmp_path / "out.txt").write_text("ok\n")
    return RunModel(
        run_id="run_x",
        title="t",
        description="d",
        created_at="2026-06-17T00:00:00Z",
        updated_at="2026-06-17T00:00:00Z",
        selected_profile="process",
        requested_profile="process",
        profile_uri="https://w3id.org/ro/wfrun/process/0.5",
        mode="monitored",
        inputs=[{"path": "in.csv", "copy_policy": "reference"}],
        outputs=[{"path": "out.txt", "copy_policy": "reference"}],
    )


def test_inputs_referenced_outputs_included_by_default(tmp_path: Path) -> None:
    cfg = default_config()
    plans = {p.file_id: p for p in plan_file_inclusion(_model(tmp_path), cfg, tmp_path)}
    assert isinstance(plans["in.csv"], FilePlan)
    assert plans["in.csv"].included is False  # include_declared_inputs defaults False
    assert plans["out.txt"].included is True  # include_declared_outputs defaults True


def test_include_declared_inputs_flag_includes_input(tmp_path: Path) -> None:
    cfg = default_config()
    cfg.file_policy.include_declared_inputs = True
    plans = {p.file_id: p for p in plan_file_inclusion(_model(tmp_path), cfg, tmp_path)}
    assert plans["in.csv"].included is True


# ---------------------------------------------------------------------------
# Task 2: Ignore patterns, symlink & out-of-root safety
# ---------------------------------------------------------------------------


def test_ignored_paths_are_dropped(tmp_path: Path) -> None:
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_text("nope")
    cfg = default_config()
    model = RunModel(
        run_id="r",
        title="t",
        description="d",
        created_at="2026-06-17T00:00:00Z",
        updated_at="2026-06-17T00:00:00Z",
        selected_profile="process",
        requested_profile="process",
        profile_uri="https://w3id.org/ro/wfrun/process/0.5",
        mode="monitored",
        outputs=[{"path": "__pycache__/x.pyc"}],
    )
    plans = {p.file_id: p for p in plan_file_inclusion(model, cfg, tmp_path)}
    assert "__pycache__/x.pyc" not in plans


def test_symlink_escaping_root_is_referenced_not_copied(tmp_path: Path) -> None:
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("secret\n")
    link = tmp_path / "link.txt"
    os.symlink(outside, link)
    cfg = default_config()
    cfg.file_policy.include_declared_outputs = True
    model = RunModel(
        run_id="r",
        title="t",
        description="d",
        created_at="2026-06-17T00:00:00Z",
        updated_at="2026-06-17T00:00:00Z",
        selected_profile="process",
        requested_profile="process",
        profile_uri="https://w3id.org/ro/wfrun/process/0.5",
        mode="monitored",
        outputs=[{"path": "link.txt"}],
    )
    plans = {p.file_id: p for p in plan_file_inclusion(model, cfg, tmp_path)}
    assert plans["link.txt"].copy is False
    assert plans["link.txt"].reason == "outside-project-root"


# ---------------------------------------------------------------------------
# Task 3: Copy decision — copy_mode, per-declaration policy, size gating
# ---------------------------------------------------------------------------


def _single_output_model(tmp_path: Path, copy_policy=None) -> RunModel:
    (tmp_path / "out.bin").write_text("x" * 2048)
    out: dict = {"path": "out.bin"}
    if copy_policy:
        out["copy_policy"] = copy_policy
    return RunModel(
        run_id="r",
        title="t",
        description="d",
        created_at="2026-06-17T00:00:00Z",
        updated_at="2026-06-17T00:00:00Z",
        selected_profile="process",
        requested_profile="process",
        profile_uri="https://w3id.org/ro/wfrun/process/0.5",
        mode="monitored",
        outputs=[out],
    )


def test_copy_mode_mixed_copies_small_output(tmp_path: Path) -> None:
    cfg = default_config()  # copy_mode="mixed", include_declared_outputs=True
    plans = {p.file_id: p for p in plan_file_inclusion(_single_output_model(tmp_path), cfg, tmp_path)}
    assert plans["out.bin"].copy is True


def test_copy_mode_reference_disables_copy(tmp_path: Path) -> None:
    cfg = default_config()
    cfg.copy_mode = "reference"
    plans = {p.file_id: p for p in plan_file_inclusion(_single_output_model(tmp_path), cfg, tmp_path)}
    assert plans["out.bin"].copy is False


def test_explicit_reference_policy_disables_copy(tmp_path: Path) -> None:
    cfg = default_config()
    plans = {
        p.file_id: p
        for p in plan_file_inclusion(_single_output_model(tmp_path, "reference"), cfg, tmp_path)
    }
    assert plans["out.bin"].copy is False
    assert plans["out.bin"].reason == "explicit-reference"


def test_large_file_is_referenced_not_copied(tmp_path: Path) -> None:
    cfg = default_config()
    cfg.file_policy.max_file_size_mb = 0  # any non-empty file exceeds the limit
    plans = {p.file_id: p for p in plan_file_inclusion(_single_output_model(tmp_path), cfg, tmp_path)}
    assert plans["out.bin"].copy is False
    assert plans["out.bin"].reason == "larger-than-max-file-size"


# ---------------------------------------------------------------------------
# Task 4: Wire the planner into the builder (entities, hasPart, byte copy)
# ---------------------------------------------------------------------------


def test_checkpoint_copies_included_output_and_excludes_input_from_haspart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Policy crate", "--no-checkpoint"]) == 0
    (tmp_path / "in.csv").write_text("a\n")
    assert main(["input", "in.csv"]) == 0
    assert main(["run", "--outputs", "out.txt", "--", "python3", "-c", "open('out.txt','w').write('ok')"]) == 0
    assert main(["checkpoint"]) == 0

    crate = tmp_path / ".ro-crate-run/ro-crate"
    graph = json.loads((crate / "ro-crate-metadata.json").read_text())
    root = next(e for e in graph["@graph"] if e["@id"] == "./")
    haspart = {ref["@id"] for ref in root.get("hasPart", [])}

    assert "out.txt" in haspart  # output included by default
    # H2 (RO-Crate 1.2 MUST + ro-crate-py round-trip): every relative-@id File data entity is
    # linked from hasPart, so the by-reference input is linked too — but its bytes are still
    # NOT copied into the crate (the by-reference / not-included file policy is unchanged).
    assert "in.csv" in haspart
    assert any(e["@id"] == "in.csv" for e in graph["@graph"])  # entity present
    assert (crate / "out.txt").exists()  # included output bytes copied into the crate
    assert not (crate / "in.csv").exists()  # by-reference input bytes NOT copied


# ---------------------------------------------------------------------------
# Task 5: Log/sidecar inclusion gating
# ---------------------------------------------------------------------------


def test_oversized_logs_are_not_copied(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Log policy", "--no-checkpoint"]) == 0
    # shrink the log size limit to zero so any non-empty log is skipped
    cfg_path = tmp_path / ".ro-crate-run/config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["file_policy"]["max_log_size_mb"] = 0
    cfg_path.write_text(json.dumps(cfg))
    assert main(["run", "--", "python3", "-c", "print('hello stdout')"]) == 0
    assert main(["checkpoint"]) == 0

    crate = tmp_path / ".ro-crate-run/ro-crate"
    copied = list((crate / ".ro-crate-run/logs").glob("*.txt")) if (crate / ".ro-crate-run/logs").exists() else []
    assert copied == []


# ---------------------------------------------------------------------------
# Task 6: Materializer run lock
# ---------------------------------------------------------------------------


def test_checkpoint_blocks_on_held_lock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Lock test", "--no-checkpoint"]) == 0
    state_dir = tmp_path / ".ro-crate-run"
    with FileLock(str(state_dir / "checkpoint.lock")):
        with pytest.raises(Timeout):
            checkpoint(state_dir, "auto", lock_timeout=0.1)


# ---------------------------------------------------------------------------
# Task 9: Hash-skip marker on file entities
# ---------------------------------------------------------------------------


def test_large_output_entity_marked_not_hashed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Hash skip", "--no-checkpoint"]) == 0
    cfg_path = tmp_path / ".ro-crate-run/config.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["hash_policy"]["max_file_size_mb"] = 0  # force skip
    cfg_path.write_text(json.dumps(cfg))
    assert main(["run", "--outputs", "big.txt", "--", "python3", "-c", "open('big.txt','w').write('data')"]) == 0
    assert main(["checkpoint"]) == 0

    graph = json.loads((tmp_path / ".ro-crate-run/ro-crate/ro-crate-metadata.json").read_text())["@graph"]
    entity = next(e for e in graph if e["@id"] == "big.txt")
    assert "identifier" not in entity
    # The inline hash-status PropertyValue is node-ified into a top-level #embedded/* entity
    # (RO-Crate 1.2 MUST: no anonymous inlining); the File carries a reference to it.
    ap = resolve_ref(entity["additionalProperty"], graph)
    assert ap["propertyID"] == "hash-status"
    assert ap["value"] == "not-hashed"
