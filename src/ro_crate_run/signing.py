from __future__ import annotations

import base64
from pathlib import Path


class SigningUnavailable(RuntimeError):
    """Raised when the optional `signing` extra (cryptography) is not installed."""


def signing_available() -> bool:
    try:
        import cryptography  # noqa: F401

        return True
    except ModuleNotFoundError:
        return False


def _require():  # type: ignore[no-untyped-def]
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
    except ModuleNotFoundError as exc:  # pragma: no cover
        raise SigningUnavailable(
            "Install the 'signing' extra: pip install 'ro-crate-run[signing]'"
        ) from exc
    return serialization, ed25519


def generate_keypair() -> tuple[str, str]:
    """Generate a new Ed25519 keypair. Returns (private_pem, public_pem)."""
    serialization, ed25519 = _require()  # type: ignore[no-untyped-call]
    private = ed25519.Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


def sign_manifest(path: Path, private_pem: str) -> str:
    """Sign the contents of a file with an Ed25519 private key. Returns base64 signature."""
    serialization, _ = _require()  # type: ignore[no-untyped-call]
    private = serialization.load_pem_private_key(private_pem.encode(), password=None)
    signature = private.sign(path.read_bytes())
    return base64.b64encode(signature).decode()


def verify_manifest_signature(path: Path, signature: str, public_pem: str) -> bool:
    """Verify an Ed25519 signature against a file's contents. Returns True if valid."""
    serialization, _ = _require()  # type: ignore[no-untyped-call]
    from cryptography.exceptions import InvalidSignature

    public = serialization.load_pem_public_key(public_pem.encode())
    try:
        public.verify(base64.b64decode(signature), path.read_bytes())
        return True
    except InvalidSignature:
        return False
