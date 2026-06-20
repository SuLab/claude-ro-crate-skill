"""Ed25519 detached-signature helpers for crate manifests.

Generates keypairs and signs/verifies the canonical ``ro-crate-metadata.json``.
The underlying ``cryptography`` library ships only with the optional ``signing``
extra; every public function raises `SigningUnavailable` when it is absent, so
the rest of the package degrades gracefully without it.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import TYPE_CHECKING, cast

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    _CRYPTO_AVAILABLE = True
except ModuleNotFoundError:  # pragma: no cover - exercised only without the extra
    _CRYPTO_AVAILABLE = False

if TYPE_CHECKING:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519


class SigningUnavailable(RuntimeError):
    """Raised when the optional `signing` extra (cryptography) is not installed."""


_UNAVAILABLE_MESSAGE = "Install the 'signing' extra: pip install 'ro-crate-run[signing]'"


def signing_available() -> bool:
    """Return whether the optional cryptography-backed signing extra is installed."""
    return _CRYPTO_AVAILABLE


def generate_keypair() -> tuple[str, str]:
    """Generate a new Ed25519 keypair. Returns (private_pem, public_pem)."""
    if not _CRYPTO_AVAILABLE:
        raise SigningUnavailable(_UNAVAILABLE_MESSAGE)
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


def public_key_from_private(private_pem: str) -> str:
    """Derive the Ed25519 public-key PEM from a private-key PEM."""
    if not _CRYPTO_AVAILABLE:
        raise SigningUnavailable(_UNAVAILABLE_MESSAGE)
    private = serialization.load_pem_private_key(private_pem.encode(), password=None)
    pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return str(pem)


def sign_manifest(path: Path, private_pem: str) -> str:
    """Sign the contents of a file with an Ed25519 private key. Returns base64 signature."""
    if not _CRYPTO_AVAILABLE:
        raise SigningUnavailable(_UNAVAILABLE_MESSAGE)
    private = cast(
        "ed25519.Ed25519PrivateKey",
        serialization.load_pem_private_key(private_pem.encode(), password=None),
    )
    signature = private.sign(path.read_bytes())
    return base64.b64encode(signature).decode()


def verify_manifest_signature(path: Path, signature: str, public_pem: str) -> bool:
    """Verify an Ed25519 signature against a file's contents. Returns True if valid."""
    if not _CRYPTO_AVAILABLE:
        raise SigningUnavailable(_UNAVAILABLE_MESSAGE)
    from cryptography.exceptions import InvalidSignature

    public = cast(
        "ed25519.Ed25519PublicKey",
        serialization.load_pem_public_key(public_pem.encode()),
    )
    try:
        public.verify(base64.b64decode(signature), path.read_bytes())
        return True
    except InvalidSignature:
        return False
