from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

from ro_crate_run.cli import main
from ro_crate_run.context import ProjectContext

# ---------------------------------------------------------------------------
# Config-flag coverage: CLAUDE.md requires that *every* config.json flag changes
# behavior and is backed by a test proving it. This module pins the previously
# untested flags by setting each to a non-default value and asserting the
# materialized crate / validation report differs from the default.
# ---------------------------------------------------------------------------


def _state_dir() -> Path:
    return ProjectContext.from_cwd().state_dir


def _graph() -> list[dict]:
    crate = _state_dir() / "ro-crate" / "ro-crate-metadata.json"
    return json.loads(crate.read_text())["@graph"]


def _by_id(graph: list[dict]) -> dict[str, dict]:
    return {e["@id"]: e for e in graph if "@id" in e}


def _props(entity: dict) -> list[dict]:
    ap = entity.get("additionalProperty")
    if ap is None:
        return []
    return ap if isinstance(ap, list) else [ap]


def _validate_codes() -> tuple[set[str], set[str]]:
    """Run `rcr validate --json` in-process; return (error_codes, warning_codes)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["validate", "--json"])
    report = json.loads(buf.getvalue())
    errors = {f["code"] for f in report["errors"]}
    warnings = {f["code"] for f in report["warnings"]}
    return errors, warnings


def _write_config(mutate) -> None:
    """Read config.json, apply mutate(dict), write it back.

    Used for list-valued flags (ignore_patterns) and nested numeric flags where
    `rcr config a.b N` is awkward; the `config` CLI command only round-trips
    scalar leaves cleanly.
    """
    cfg_path = _state_dir() / "config.json"
    cfg = json.loads(cfg_path.read_text())
    mutate(cfg)
    cfg_path.write_text(json.dumps(cfg))


# ---------------------------------------------------------------------------
# file_policy.ignore_patterns — a file matching the pattern is EXCLUDED entirely
# ---------------------------------------------------------------------------


def test_ignore_patterns_excludes_matching_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    (tmp_path / "result.csv").write_text("a,b\n1,2\n")
    assert main(["output", "result.csv", "--copy"]) == 0

    # Default: the declared output is materialized as a graph entity.
    assert main(["checkpoint"]) == 0
    assert "result.csv" in _by_id(_graph())

    # Non-default ignore_patterns: the same file is dropped before it ever
    # reaches the graph (plan_file_inclusion skips ignored ids entirely).
    _write_config(lambda c: c.__setitem__("ignore_patterns", ["*.csv"]))
    assert main(["checkpoint"]) == 0
    assert "result.csv" not in _by_id(_graph())


# ---------------------------------------------------------------------------
# privacy.public_by_default — an UNFLAGGED finalize defaults to a public export
# (runs the Level-5 public gate) instead of a private one.
# ---------------------------------------------------------------------------


def test_public_by_default_changes_unflagged_finalize(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0

    # Default (public_by_default=False): an unflagged finalize is PRIVATE, so the
    # embedded event journal is allowed and ends up inside the zip.
    assert main(["finalize", "--zip", "--include-event-journal"]) == 0
    zips = list((_state_dir()).glob("*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as archive:
        assert any(name.endswith("events.ndjson") for name in archive.namelist())

    # Fresh run with public_by_default=True: the same unflagged finalize now runs
    # the public gate, which blocks an embedded journal that was not explicitly
    # opted into — rc=1 and no zip is produced.
    (tmp_path / "pub").mkdir()
    monkeypatch.chdir(tmp_path / "pub")
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    assert main(["config", "privacy.public_by_default", "true"]) == 0
    assert main(["finalize", "--zip", "--include-event-journal"]) == 1
    assert list((_state_dir()).glob("*.zip")) == []


# ---------------------------------------------------------------------------
# validation.require_clean_git — a dirty tree (no diff captured) is a warning by
# default and an ERROR when this flag is set.
#
# NOTE: observe_git_state() records `status` (porcelain) but never a `dirty`
# observe_git_state now emits a real `dirty` boolean (from the porcelain status), so the
# dirty_tree_no_diff finding is reachable from a genuinely dirty working tree.
# ---------------------------------------------------------------------------


def _git(d: Path, *args: str) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", *args], cwd=d, env=env, check=True, capture_output=True)


def test_require_clean_git_promotes_dirty_warning_to_error(tmp_path: Path, monkeypatch) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "init")
    (tmp_path / "dirty.txt").write_text("uncommitted\n")  # genuinely dirty working tree
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--mode", "advisory", "--profile", "process",
                 "--no-checkpoint"]) == 0
    assert main(["run", "--", "python3", "-c", "print('x')"]) == 0
    assert main(["checkpoint"]) == 0

    # Default (require_clean_git=False): dirty tree is a non-required warning.
    assert main(["config", "validation.require_clean_git", "false"]) == 0
    errors, warnings = _validate_codes()
    assert "dirty_tree_no_diff" in warnings
    assert "dirty_tree_no_diff_required" not in errors

    # Required: the same condition is promoted to an error (the _required suffix makes
    # _is_error treat the reproducibility finding as blocking).
    assert main(["config", "validation.require_clean_git", "true"]) == 0
    errors, warnings = _validate_codes()
    assert "dirty_tree_no_diff_required" in errors
    assert "dirty_tree_no_diff" not in warnings


# ---------------------------------------------------------------------------
# validation.require_date_published — toggling the flag adds/removes the
# root_missing_datePublished finding when the root lacks datePublished.
# ---------------------------------------------------------------------------


def test_require_date_published_toggles_finding(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    assert main(["checkpoint"]) == 0

    # Strip datePublished from the on-disk crate the validator reads.
    crate = _state_dir() / "ro-crate" / "ro-crate-metadata.json"
    doc = json.loads(crate.read_text())
    for entity in doc["@graph"]:
        if entity.get("@id") == "./":
            entity.pop("datePublished", None)
    crate.write_text(json.dumps(doc))

    # Required (default True): missing datePublished is reported.
    assert main(["config", "validation.require_date_published", "true"]) == 0
    errors, warnings = _validate_codes()
    assert "root_missing_datePublished" in (errors | warnings)

    # Not required: the same crate produces no such finding.
    assert main(["config", "validation.require_date_published", "false"]) == 0
    errors, warnings = _validate_codes()
    assert "root_missing_datePublished" not in (errors | warnings)


# ---------------------------------------------------------------------------
# hash_policy.max_file_size_mb — a file larger than the limit gets a
# hash-status=not-hashed additionalProperty instead of an sha256 identifier.
#
# (hash_policy.hash_large_files is asserted dead in test_dead_flags; the live
# hashing gate is purely max_file_size_mb.)
# ---------------------------------------------------------------------------


def test_max_file_size_mb_gates_hashing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    (tmp_path / "big.bin").write_bytes(b"x" * 200_000)
    assert main(["output", "big.bin", "--copy"]) == 0

    # Default (100 MB): the small file is hashed → sha256 identifier present.
    assert main(["checkpoint"]) == 0
    entity = _by_id(_graph())["big.bin"]
    assert isinstance(entity.get("identifier"), dict)
    assert entity["identifier"].get("propertyID") == "sha256"

    # max_file_size_mb=0: the file now exceeds the limit → no hash, a
    # hash-status=not-hashed additionalProperty is recorded instead.
    _write_config(lambda c: c["hash_policy"].__setitem__("max_file_size_mb", 0))
    assert main(["checkpoint"]) == 0
    entity = _by_id(_graph())["big.bin"]
    assert "identifier" not in entity
    assert any(
        p.get("propertyID") == "hash-status" and p.get("value") == "not-hashed"
        for p in _props(entity)
    )


# ---------------------------------------------------------------------------
# copy_mode (global) — copy vs reference: a declared output with no per-file
# policy is physically copied into the crate dir under "mixed"/"copy" but only
# referenced under "reference".
#
# We use an inferred command output (copy_policy unset) so the GLOBAL copy_mode
# is the deciding factor; `rcr output` always pins a per-file copy_policy.
# ---------------------------------------------------------------------------


def _run_with_output(tmp_path: Path) -> None:
    # The file must exist at materialization time to be copyable.
    (tmp_path / "out.txt").write_text("hi\n")
    assert (
        main(["run", "--outputs", "out.txt", "--", "python3", "-c", "print(1)"]) == 0
    )


def test_copy_mode_mixed_copies_output_into_crate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    _run_with_output(tmp_path)
    # Default copy_mode="mixed": the output is physically copied into the crate.
    assert main(["checkpoint"]) == 0
    assert (_state_dir() / "ro-crate" / "out.txt").exists()


def test_copy_mode_reference_does_not_copy_output(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    assert main(["config", "copy_mode", "reference"]) == 0
    _run_with_output(tmp_path)
    assert main(["checkpoint"]) == 0
    # Non-default copy_mode="reference": no physical copy, only a reference.
    assert not (_state_dir() / "ro-crate" / "out.txt").exists()


# ---------------------------------------------------------------------------
# file_policy.include_source_code — the workflow-definition source file's bytes
# are captured (physically copied into the crate) under the default
# "private-only" but withheld under "never".
#
# The entity itself always exists (it is the workflow mainEntity, so the builder
# keeps it in hasPart regardless); the policy-controlled difference is whether
# its content is included (copied), which is the leak-relevant behavior.
# ---------------------------------------------------------------------------


def _declare_source(tmp_path: Path) -> None:
    (tmp_path / "analyze.py").write_text("print(1)\n")
    assert main(["input", "analyze.py", "--role", "workflow-definition"]) == 0


def test_include_source_code_private_only_includes_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--profile", "workflow", "--no-checkpoint"]) == 0
    _declare_source(tmp_path)
    # Default "private-only": the SoftwareSourceCode file's bytes are copied in.
    assert main(["checkpoint", "--profile", "workflow"]) == 0
    entity = _by_id(_graph())["analyze.py"]
    assert "SoftwareSourceCode" in entity["@type"]
    assert (_state_dir() / "ro-crate" / "analyze.py").exists()


def test_include_source_code_never_excludes_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--profile", "workflow", "--no-checkpoint"]) == 0
    _declare_source(tmp_path)
    assert main(["config", "file_policy.include_source_code", "never"]) == 0
    assert main(["checkpoint", "--profile", "workflow"]) == 0
    # Non-default "never": the source content is withheld — its bytes are not
    # copied into the crate (it remains described as the abstract mainEntity).
    assert not (_state_dir() / "ro-crate" / "analyze.py").exists()


# ---------------------------------------------------------------------------
# hash_policy.hash_large_files — overrides the max_file_size_mb hash gate: a file
# that would be skipped for size is hashed anyway when this flag is set.
# ---------------------------------------------------------------------------


def test_hash_large_files_overrides_size_gate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["start", "Demo", "--no-checkpoint"]) == 0
    (tmp_path / "big.bin").write_bytes(b"x" * 200_000)
    assert main(["output", "big.bin", "--copy"]) == 0
    # Size gate makes the file unhashable...
    _write_config(lambda c: c["hash_policy"].__setitem__("max_file_size_mb", 0))
    assert main(["checkpoint"]) == 0
    assert "identifier" not in _by_id(_graph())["big.bin"], "expected size-gated (no hash)"
    # ...but hash_large_files=True overrides the gate and hashes it anyway.
    _write_config(lambda c: c["hash_policy"].__setitem__("hash_large_files", True))
    assert main(["checkpoint"]) == 0
    entity = _by_id(_graph())["big.bin"]
    assert (entity.get("identifier") or {}).get("propertyID") == "sha256", \
        f"hash_large_files did not override the size gate: {entity}"
