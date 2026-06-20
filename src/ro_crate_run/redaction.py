"""Secret-redaction engine.

Detects and masks credentials in text, structured payloads, and captured
environment variables before any data is persisted to the event journal or a
crate. A `Redactor` carries a table of compiled credential patterns (built-in
plus optional user-supplied ones) and an environment-variable allowlist.

This module is also the home for the on-disk secret-scan helpers
(`iter_regular_files`, `scan_file_for_secrets`, `scan_tree`): they read each
file losslessly as latin-1 so an ASCII secret embedded in an otherwise-binary
blob is still caught, and skip a file only when it cannot be read at all
(OSError). `iter_regular_files` is the one canonical tree walk callers route
through.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .constants import DEFAULT_ENV_ALLOWLIST
from .models import RcrConfig, RedactionResult

REDACTION_TOKEN = "[REDACTED:secret]"

# Single source of truth for secret-bearing key/identifier names. Both the
# lowercase gate (`key_pattern`) and the uppercase KEY=VALUE assignment regex in
# `redact_text` are built from this tuple so the two can never drift apart — a
# divergence would let the gate scan-positive while the substitution misses (or
# vice versa), a real leak risk in a security-critical redactor.
_SECRET_KEYWORDS: tuple[str, ...] = (
    "token",
    "secret",
    "password",
    "passwd",
    "cookie",
    "credential",
    "private_key",
    "api_key",
    "access_key",
    "refresh_token",
)
_KEYWORD_ALTERNATION = "|".join(_SECRET_KEYWORDS)


class Redactor:
    def __init__(
        self,
        environment_allowlist: list[str] | None = None,
        *,
        enabled: bool = True,
    ) -> None:
        # When False the redactor is a no-op: redact_text/capture_environment/
        # redact_value short-circuit. This makes the "disabled means no
        # redaction" contract explicit instead of encoding it as a never-match
        # sentinel regex.
        self.enabled = enabled
        self.environment_allowlist = set(environment_allowlist or [])
        # Built-in credential patterns, each tagged with a category name so a
        # RedactionResult can report which kind(s) of secret were masked.
        self.patterns: list[tuple[str, re.Pattern[str]]] = [
            ("openai-key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
            ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}")),
            ("aws-key", re.compile(r"A[KS]IA[0-9A-Z]{16}")),
            ("slack-token", re.compile(r"xox[abp]-[A-Za-z0-9-]{10,}")),
            ("google-api-key", re.compile(r"AIza[0-9A-Za-z_-]{35}")),
            (
                "jwt",
                re.compile(
                    r"eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"
                ),
            ),
            ("bearer", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}")),
            (
                "private-key",
                re.compile(
                    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                    re.S,
                ),
            ),
        ]
        # Gate pattern (any sensitive keyword anywhere in a key/text) and the
        # KEY=VALUE assignment-redaction pattern are both derived from
        # `_SECRET_KEYWORDS` so they share one vocabulary.
        self.key_pattern = re.compile(rf"(?i)({_KEYWORD_ALTERNATION})")
        self._assignment_pattern = re.compile(
            rf"(?i)([A-Z0-9_]*(?:{_KEYWORD_ALTERNATION})[A-Z0-9_]*\s*=\s*)\S+"
        )

    @classmethod
    def load_patterns(cls, path: Path) -> list[tuple[str, re.Pattern[str]]]:
        """Compile user-supplied patterns from a JSON policy file.

        Returns ``(category, pattern)`` pairs tagged with the ``custom``
        category. Malformed or unreadable files, and individual regexes that
        fail to compile, contribute nothing.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw = data.get("patterns", []) if isinstance(data, dict) else []
        compiled: list[tuple[str, re.Pattern[str]]] = []
        for item in raw:
            try:
                compiled.append(("custom", re.compile(str(item))))
            except re.error:
                continue
        return compiled

    def add_patterns_from(self, path: Path) -> None:
        """Append user-supplied credential patterns from a JSON policy file.

        Each loaded pattern is tagged with the ``custom`` category (see
        `load_patterns`); malformed or unreadable files contribute nothing.
        """
        self.patterns = [*self.patterns, *self.load_patterns(path)]

    @classmethod
    def from_config(cls, cfg: RcrConfig, state_dir: Path | None = None) -> Redactor:
        redactor = cls.default(cfg.redaction.environment_allowlist)
        if not cfg.redaction.enabled:
            redactor.enabled = False
            return redactor
        patterns_file = cfg.redaction.patterns_file
        if patterns_file:
            candidate = Path(patterns_file)
            if not candidate.is_absolute() and state_dir is not None:
                candidate = state_dir.parent / patterns_file
            redactor.add_patterns_from(candidate)
        return redactor

    @classmethod
    def for_state_dir(cls, state_dir: Path) -> Redactor:
        """Build the redactor configured for a project state directory.

        Loads ``config.json`` from ``state_dir`` and resolves any relative
        custom-patterns file against it, so callers cannot accidentally
        mis-resolve patterns to the current working directory.
        """
        from .state import load_config

        return cls.from_config(load_config(state_dir), state_dir=state_dir)

    @classmethod
    def default(cls, environment_allowlist: list[str] | None = None) -> Redactor:
        return cls(
            environment_allowlist=environment_allowlist or list(DEFAULT_ENV_ALLOWLIST)
        )

    def redact_text(self, text: str) -> RedactionResult:
        applied = 0
        categories: list[str] = []
        redacted = text
        if not self.enabled:
            return RedactionResult(redacted, applied, ())
        if self.key_pattern.search(redacted):
            redacted = self._assignment_pattern.sub(r"\1" + REDACTION_TOKEN, redacted)
            if redacted != text:
                applied += 1
                categories.append("secret-assignment")
        for name, pattern in self.patterns:
            redacted, count = pattern.subn(REDACTION_TOKEN, redacted)
            if count:
                applied += count
                categories.append(name)
        return RedactionResult(redacted, applied, tuple(sorted(set(categories))))

    def capture_environment(self, env: dict[str, str]) -> dict[str, str]:
        captured: dict[str, str] = {}
        for key, value in env.items():
            if key not in self.environment_allowlist:
                continue
            # A disabled redactor keeps the historical no-op behavior: it neither
            # drops sensitive-named keys nor masks values (matching the former
            # never-match-key_pattern path).
            if self.enabled and self.key_pattern.search(key):
                continue
            captured[key] = self.redact_text(value).text
        return captured

    def redact_value(self, value: Any) -> tuple[Any, int]:
        if not self.enabled:
            return value, 0
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
                # Key-name redaction (mirrors capture_environment): when a key
                # names a credential, mask its scalar leaf value even if the
                # value itself matches no value pattern. Without this a payload
                # like {"password": "hunter2"} would be journaled in cleartext.
                if self.key_pattern.search(key) and self._is_scalar_leaf(item):
                    redacted_dict[key] = REDACTION_TOKEN
                    applied += 1
                    continue
                redacted, count = self.redact_value(item)
                redacted_dict[key] = redacted
                applied += count
            return redacted_dict, applied
        return value, 0

    @staticmethod
    def _is_scalar_leaf(value: Any) -> bool:
        """Whether a value is a non-container leaf eligible for key-name masking.

        Scoping key-name redaction to scalar leaves keeps `redaction.applied`
        counts meaningful and avoids clobbering nested structures whole — those
        recurse so their own scalars are still value- and key-name-redacted.
        """
        return value is not None and not isinstance(value, (dict, list))


def scan_file_for_secrets(path: Path, redactor: Redactor) -> list[str]:
    """Return the matched secret-category names for a single file.

    The file is decoded as latin-1 (a lossless byte->char mapping) rather than
    UTF-8: an ASCII secret embedded in an otherwise-binary blob must still be
    caught instead of skipped. Only a file that cannot be read at all (OSError)
    is skipped, yielding an empty list.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    text = raw.decode("latin-1")
    return list(redactor.redact_text(text).categories)


def iter_regular_files(root: Path) -> Iterator[Path]:
    """Yield every regular file under ``root`` in sorted path order.

    The single canonical tree walk for the on-disk secret scanners so the
    "sorted, regular files only" traversal policy lives in exactly one place.
    """
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def scan_tree(root: Path, redactor: Redactor) -> list[tuple[Path, list[str]]]:
    """Scan every regular file under ``root`` for secrets.

    Returns one ``(path, categories)`` entry per file in which at least one
    secret category matched, in sorted path order. Uses the same hardened
    latin-1 / OSError-only policy as `scan_file_for_secrets`.
    """
    hits: list[tuple[Path, list[str]]] = []
    for path in iter_regular_files(root):
        categories = scan_file_for_secrets(path, redactor)
        if categories:
            hits.append((path, categories))
    return hits


def redaction_categories(*results: RedactionResult) -> list[str]:
    """Union of category names across one or more redaction results, sorted."""
    merged: set[str] = set()
    for result in results:
        merged.update(result.categories)
    return sorted(merged)


def redaction_event_payload(context: str, *results: RedactionResult) -> dict[str, Any]:
    """Build a ``redaction.applied`` event payload from one or more results.

    Sums the per-field redaction counts and merges their categories so a field
    redacted across multiple text streams (e.g. a note plus a rationale)
    reports every matched category, not just the first.
    """
    return {
        "context": context,
        "applied": sum(result.applied for result in results),
        "categories": redaction_categories(*results),
    }
