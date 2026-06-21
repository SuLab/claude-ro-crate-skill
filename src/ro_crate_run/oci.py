"""OCI image-reference parsing for ``rcr container``: split a reference into its
registry, image, tag, and digest components."""

from __future__ import annotations


def parse_image_ref(ref: str) -> tuple[str, str, str, str]:
    """Split an OCI image reference into (registry, image, tag, digest)."""
    registry = ""
    digest = ""
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    if "/" in ref:
        first, rest = ref.split("/", 1)
        # A leading segment with a dot, a port, or "localhost" is a registry host.
        if "." in first or ":" in first or first == "localhost":
            registry, ref = first, rest
    tag = ""
    if ":" in ref:
        ref, tag = ref.rsplit(":", 1)
    return registry, ref, tag, digest
