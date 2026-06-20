from __future__ import annotations

from ro_crate_run.redaction import REDACTION_TOKEN, Redactor


def test_redact_value_masks_secret_key_name() -> None:
    # FIX A1: a structured payload whose value matches no value-pattern must
    # still be masked when its KEY names a credential, mirroring
    # capture_environment's key-name protection.
    redacted, applied = Redactor.default().redact_value({"password": "plaintext"})
    assert redacted == {"password": REDACTION_TOKEN}
    assert applied > 0


def test_redact_value_passes_through_non_secret_key() -> None:
    redacted, applied = Redactor.default().redact_value({"name": "alice"})
    assert redacted == {"name": "alice"}
    assert applied == 0


def test_redact_value_masks_secret_key_in_nested_dict() -> None:
    payload = {"outer": {"api_key": "plainvalue123", "note": "ok"}}
    redacted, applied = Redactor.default().redact_value(payload)
    assert redacted == {"outer": {"api_key": REDACTION_TOKEN, "note": "ok"}}
    assert applied == 1


def test_redact_value_secret_key_with_container_value_recurses() -> None:
    # A secret-named key whose value is a container is not masked wholesale; the
    # container recurses so its own scalars are still value/key-name redacted and
    # the applied count stays meaningful.
    payload = {"credentials": {"password": "hunter2", "user": "alice"}}
    redacted, applied = Redactor.default().redact_value(payload)
    assert redacted == {"credentials": {"password": REDACTION_TOKEN, "user": "alice"}}
    assert applied == 1


def test_redact_value_counts_remain_accurate() -> None:
    payload = {"token": "x", "secret": "y", "plain": "z"}
    redacted, applied = Redactor.default().redact_value(payload)
    assert redacted == {"token": REDACTION_TOKEN, "secret": REDACTION_TOKEN, "plain": "z"}
    assert applied == 2


def test_disabled_redactor_does_not_redact_secret_key() -> None:
    # An explicitly-disabled redactor is a no-op even for secret-named keys.
    redactor = Redactor.default()
    redactor.enabled = False
    redacted, applied = redactor.redact_value({"password": "plaintext"})
    assert redacted == {"password": "plaintext"}
    assert applied == 0
