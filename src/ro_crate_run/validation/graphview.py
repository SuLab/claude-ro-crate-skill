"""Shared, dependency-free helpers for reading an RO-Crate ``@graph``: coercing
scalar-or-list JSON-LD values to lists, reading an entity's ``@type``, and
detecting Action entities. These views are consumed by every level-2/3/4 checker
so the normalization rules live in one place.

This module imports nothing from the rest of the validation package (or the
project), so it is a neutral utility any layer can import — the materializer,
the adapters, and ``inspect`` route their ``@type``/Action coercion through it
rather than re-implementing the same rules.
"""

from __future__ import annotations

from typing import Any


def as_list(value: Any) -> list[Any]:
    """Return ``value`` as a list: a list passes through, anything else (including
    a scalar or ``None``) is wrapped in a single-element list."""
    return value if isinstance(value, list) else [value]


def types_of(entity: dict[str, Any]) -> list[str]:
    """Return an entity's ``@type`` values as a list (an absent ``@type`` yields
    an empty list)."""
    return as_list(entity.get("@type", []))


def is_action_value(value: Any) -> bool:
    """True when a raw ``@type`` value (scalar or list) names any ``*Action`` type."""
    return any(str(item).endswith("Action") for item in as_list(value))


def is_action(entity: dict[str, Any]) -> bool:
    """True when an entity carries any ``*Action`` ``@type``."""
    return is_action_value(entity.get("@type", []))
