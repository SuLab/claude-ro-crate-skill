"""Pure entity builders for RO-Crate graph assembly.

Each function accepts a ``RunModel`` (or closely related inputs) and returns
``list[dict]`` graph fragments.  ``builder.py`` concatenates them, dedupes,
strips nulls, and writes via ro-crate-py.

Action ``actionStatus`` URIs come from ``constants`` (never literal strings),
project-relative file ``@id``s come from ``ids.relative_file_id`` /
``ids.file_ref``, and the actor roster (names, ``@type``, ids) comes from
``events`` so the same identities are maintained in exactly one place.

This package re-exports every builder so callers can ``from ro_crate_run.materialize
import mapping`` and call ``mapping.build_X`` without knowing the submodule layout. The
builders are grouped into cohesive submodules
(``actors``/``actions``/``file_entities``/``parameters``/``workflow``/``provenance``)
with cross-domain helpers in ``_helpers``.
"""
from __future__ import annotations

from ._helpers import command_action_type
from .actions import (
    build_agent_actions,
    build_blocked_actions,
    build_command_action,
    build_file_actions,
    build_housekeeping,
    build_phase_actions,
    build_prompts,
    build_raw_command_actions,
    build_results,
    build_subagent_actions,
    build_tool_uses,
)
from .actors import build_actors, build_software
from .file_entities import build_file_entity
from .parameters import (
    build_parameter_connections,
    build_parameters,
    workflow_formal_parameters,
)
from .provenance import (
    build_containers,
    build_dependencies,
    build_environment,
    build_git,
    build_notes_decisions,
)
from .workflow import (
    build_steps,
    build_workflow,
    build_workflow_action,
    build_workflow_timeline,
)

__all__ = [
    "build_actors",
    "build_agent_actions",
    "build_blocked_actions",
    "build_command_action",
    "build_containers",
    "build_dependencies",
    "build_environment",
    "build_file_actions",
    "build_file_entity",
    "build_git",
    "build_housekeeping",
    "build_notes_decisions",
    "build_parameter_connections",
    "build_parameters",
    "build_phase_actions",
    "build_prompts",
    "build_raw_command_actions",
    "build_results",
    "build_software",
    "build_steps",
    "build_subagent_actions",
    "build_tool_uses",
    "build_workflow",
    "build_workflow_action",
    "build_workflow_timeline",
    "command_action_type",
    "workflow_formal_parameters",
]
