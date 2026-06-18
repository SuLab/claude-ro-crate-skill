from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .models import RedactionResult

if TYPE_CHECKING:
    from .models import RcrConfig


class Redactor:
    def __init__(self, environment_allowlist: list[str] | None = None) -> None:
        self.environment_allowlist = set(environment_allowlist or [])
        self.patterns = [
            re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
            re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
            re.compile(r"A[KS]IA[0-9A-Z]{16}"),
            re.compile(r"xox[abp]-[A-Za-z0-9-]{10,}"),
            re.compile(r"AIza[0-9A-Za-z_-]{35}"),
            re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
            re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
            re.compile(
                r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S
            ),
        ]
        self.key_pattern = re.compile(
            r"(?i)(token|secret|password|passwd|cookie|credential|private_key|api_key|access_key|refresh_token)"
        )

    @classmethod
    def load_patterns(cls, path: Path) -> list[re.Pattern[str]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw = data.get("patterns", []) if isinstance(data, dict) else []
        compiled: list[re.Pattern[str]] = []
        for item in raw:
            try:
                compiled.append(re.compile(str(item)))
            except re.error:
                continue
        return compiled

    @classmethod
    def from_policy(cls, path: Path) -> Redactor:
        redactor = cls.default()
        redactor.patterns = [*redactor.patterns, *cls.load_patterns(path)]
        return redactor

    @classmethod
    def from_config(cls, cfg: RcrConfig, state_dir: Path | None = None) -> Redactor:
        redactor = cls.default(cfg.redaction.environment_allowlist)
        if not cfg.redaction.enabled:
            redactor.patterns = []
            redactor.key_pattern = re.compile(r"(?!x)x")  # matches nothing
            return redactor
        patterns_file = cfg.redaction.patterns_file
        if patterns_file:
            candidate = Path(patterns_file)
            if not candidate.is_absolute() and state_dir is not None:
                candidate = state_dir.parent / patterns_file
            redactor.patterns = [*redactor.patterns, *cls.load_patterns(candidate)]
        return redactor

    @classmethod
    def default(cls, environment_allowlist: list[str] | None = None) -> Redactor:
        return cls(
            environment_allowlist=environment_allowlist
            or ["PATH", "LANG", "LC_ALL", "SHELL", "PYTHONPATH", "CONDA_DEFAULT_ENV", "VIRTUAL_ENV"]
        )

    def redact_text(self, text: str) -> RedactionResult:
        applied = 0
        categories: list[str] = []
        redacted = text
        if self.key_pattern.search(redacted):
            redacted = re.sub(
                r"(?i)([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|COOKIE|CREDENTIAL|PRIVATE_KEY|API_KEY|ACCESS_KEY|REFRESH_TOKEN)[A-Z0-9_]*\s*=\s*)\S+",
                r"\1[REDACTED:secret]",
                redacted,
            )
            if redacted != text:
                applied += 1
                categories.append("secret")
        for pattern in self.patterns:
            redacted, count = pattern.subn("[REDACTED:secret]", redacted)
            if count:
                applied += count
                categories.append("secret")
        return RedactionResult(redacted, applied, tuple(sorted(set(categories))))

    def capture_environment(self, env: dict[str, str]) -> dict[str, str]:
        captured: dict[str, str] = {}
        for key, value in env.items():
            if key not in self.environment_allowlist or self.key_pattern.search(key):
                continue
            captured[key] = self.redact_text(value).text
        return captured

    def redact_value(self, value: Any) -> tuple[Any, int]:
        if isinstance(value, str):
            result = self.redact_text(value)
            return result.text, result.applied
        if isinstance(value, list):
            redacted_items = []
            applied = 0
            for item in value:
                redacted, count = self.redact_value(item)
                redacted_items.append(redacted)
                applied += count
            return redacted_items, applied
        if isinstance(value, dict):
            redacted_dict: dict[str, Any] = {}
            applied = 0
            for key, item in value.items():
                redacted, count = self.redact_value(item)
                redacted_dict[key] = redacted
                applied += count
            return redacted_dict, applied
        return value, 0


def redaction_event_payload(context: str, result: RedactionResult) -> dict[str, Any]:
    return {
        "context": context,
        "applied": result.applied,
        "categories": list(result.categories),
    }
