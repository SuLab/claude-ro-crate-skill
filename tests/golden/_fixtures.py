from __future__ import annotations

from pathlib import Path
from typing import Callable

from ro_crate_run.cli import main


def _crate_dir(tmp_path: Path) -> Path:
    return tmp_path / ".ro-crate-run" / "ro-crate"


def process_minimal(tmp_path: Path) -> Path:
    assert main(["start", "Minimal", "--mode", "monitored",
                 "--profile", "process", "--no-checkpoint"]) == 0
    assert main(["software", "python3", "--version", "Python 3.12.0"]) == 0
    assert main(["output", "out.txt", "--role", "result", "--required"]) == 0
    assert main(["run", "--outputs", "out.txt", "--",
                 "python3", "-c", "open('out.txt','w').write('result\\n')"]) == 0
    assert main(["checkpoint", "--profile", "process"]) == 0
    return _crate_dir(tmp_path)


def process_multi(tmp_path: Path) -> Path:
    assert main(["start", "Multi", "--mode", "monitored",
                 "--profile", "process", "--no-checkpoint"]) == 0
    assert main(["software", "python3", "--version", "Python 3.12.0"]) == 0
    assert main(["input", "in.txt", "--role", "dataset", "--required"]) == 0
    Path("in.txt").write_text("1\n2\n3\n")
    assert main(["run", "--inputs", "in.txt", "--outputs", "step1.txt", "--",
                 "python3", "-c",
                 "open('step1.txt','w').write(str(len(open('in.txt').read().split())))"]) == 0
    assert main(["run", "--inputs", "step1.txt", "--outputs", "final.txt", "--",
                 "python3", "-c",
                 "open('final.txt','w').write(open('step1.txt').read()+'!')"]) == 0
    assert main(["output", "final.txt", "--role", "result", "--required"]) == 0
    assert main(["checkpoint", "--profile", "process"]) == 0
    return _crate_dir(tmp_path)


def process_failed(tmp_path: Path) -> Path:
    assert main(["start", "Failed", "--mode", "monitored",
                 "--profile", "process", "--no-checkpoint"]) == 0
    assert main(["software", "python3", "--version", "Python 3.12.0"]) == 0
    # non-zero exit; rcr run returns the command's exit code (here 3)
    rc = main(["run", "--", "python3", "-c",
               "import sys; sys.stderr.write('boom\\n'); sys.exit(3)"])
    assert rc == 3
    assert main(["checkpoint", "--profile", "process"]) in {0, 1}
    return _crate_dir(tmp_path)


def workflow_snakemake(tmp_path: Path) -> Path:
    assert main(["start", "WF", "--mode", "monitored",
                 "--profile", "auto", "--no-checkpoint"]) == 0
    Path("Snakefile").write_text(
        "rule all:\n    input: 'out.txt'\nrule make:\n"
        "    output: 'out.txt'\n    shell: \"echo ok > out.txt\"\n"
    )
    assert main(["software", "snakemake", "--version", "7.0.0"]) == 0
    assert main(["input", "Snakefile", "--role", "workflow-definition", "--required"]) == 0
    assert main(["run", "--outputs", "out.txt", "--",
                 "python3", "-c", "open('out.txt','w').write('ok\\n')"]) == 0
    assert main(["output", "out.txt", "--role", "result", "--required"]) == 0
    assert main(["checkpoint", "--profile", "auto"]) == 0
    return _crate_dir(tmp_path)


def provenance_two_step(tmp_path: Path) -> Path:
    assert main(["start", "Prov", "--mode", "monitored",
                 "--profile", "auto", "--no-checkpoint"]) == 0
    Path("flow.cwl").write_text("cwlVersion: v1.2\nclass: Workflow\n")
    assert main(["software", "cwltool", "--version", "3.1"]) == 0
    assert main(["input", "flow.cwl", "--role", "workflow-definition", "--required"]) == 0
    # step 1 produces an intermediate output consumed by step 2
    assert main(["step", "start", "normalize"]) == 0
    assert main(["run", "--step", "normalize", "--outputs", "mid.txt", "--",
                 "python3", "-c", "open('mid.txt','w').write('mid\\n')"]) == 0
    assert main(["step", "end", "normalize"]) == 0
    assert main(["step", "start", "summarize"]) == 0
    assert main(["run", "--step", "summarize", "--inputs", "mid.txt",
                 "--outputs", "final.txt", "--",
                 "python3", "-c",
                 "open('final.txt','w').write(open('mid.txt').read()+'done')"]) == 0
    assert main(["step", "end", "summarize"]) == 0
    assert main(["output", "final.txt", "--role", "result", "--required"]) == 0
    assert main(["checkpoint", "--profile", "auto"]) == 0
    return _crate_dir(tmp_path)


def privacy_public(tmp_path: Path) -> Path:
    assert main(["start", "Public", "--mode", "monitored",
                 "--profile", "process", "--no-checkpoint"]) == 0
    assert main(["software", "python3", "--version", "Python 3.12.0"]) == 0
    assert main(["note", "Public summary note", "--public"]) == 0
    assert main(["note", "PRIVATE secret-prompt detail", "--private"]) == 0
    assert main(["output", "out.txt", "--role", "result", "--required"]) == 0
    assert main(["run", "--outputs", "out.txt", "--",
                 "python3", "-c", "open('out.txt','w').write('ok\\n')"]) == 0
    assert main(["finalize", "--public"]) == 0
    return _crate_dir(tmp_path)


FIXTURES: dict[str, Callable[[Path], Path]] = {
    "privacy_public": privacy_public,
    "process_failed": process_failed,
    "process_minimal": process_minimal,
    "process_multi": process_multi,
    "provenance_two_step": provenance_two_step,
    "workflow_snakemake": workflow_snakemake,
}
