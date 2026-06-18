from __future__ import annotations

from typing import Any

from .models import PrivacyFinding
from .redaction import Redactor


def check_public_export_payload(
    payload: Any, include_prompts: bool = False
) -> list[PrivacyFinding]:
    findings: list[PrivacyFinding] = []
    _scan(payload, "", include_prompts, findings)
    return findings


def _scan(value: Any, path: str, include_prompts: bool, findings: list[PrivacyFinding]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if "prompt" in str(key).lower() and not include_prompts:
                findings.append(PrivacyFinding("error", "raw_prompt_in_public_export"))
            _scan(item, child, include_prompts, findings)
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            _scan(item, f"{path}[{idx}]", include_prompts, findings)
    elif isinstance(value, str):
        result = Redactor.default().redact_text(value)
        if result.applied:
            findings.append(PrivacyFinding("error", "secret_pattern", path))
