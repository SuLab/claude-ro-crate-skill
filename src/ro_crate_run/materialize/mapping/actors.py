"""Actor and software entity builders.

``build_actors`` emits the stable identity roster (human, rcr, claude-code, the
Python/ro-crate-py/shell/model SoftwareApplications, and the workflow engine);
``build_software`` emits one SoftwareApplication per declared software entry and
per command instrument basename.
"""
from __future__ import annotations

import os
from typing import Any

from ro_crate_run import __version__
from ro_crate_run.events import ACTOR_NAMES, ACTOR_TYPES, crate_actor_id, engine_actor_id
from ro_crate_run.ids import software_entity_id
from ro_crate_run.models import RunModel

from ._helpers import strip_none


def build_actors(model: RunModel) -> list[dict[str, Any]]:
    """Emit stable actor entities for everyone involved in this run."""
    from ro_crate_run import adapters

    env = model.environment or {}
    actors: list[dict[str, Any]] = [
        {
            "@id": crate_actor_id("human"),
            "@type": ACTOR_TYPES["human"],
            "name": ACTOR_NAMES["human"],
        },
        {
            "@id": crate_actor_id("rcr"),
            "@type": ACTOR_TYPES["rcr"],
            "name": ACTOR_NAMES["rcr"],
            "softwareVersion": __version__,
        },
        {
            "@id": crate_actor_id("claude-code"),
            "@type": ACTOR_TYPES["claude-code"],
            "name": ACTOR_NAMES["claude-code"],
        },
        {
            "@id": crate_actor_id("ro-crate-py"),
            "@type": "SoftwareApplication",
            "name": "ro-crate-py",
            "softwareVersion": env.get("rocrate_package_version"),
        },
        {
            "@id": crate_actor_id("python"),
            "@type": "SoftwareApplication",
            "name": "Python",
            "softwareVersion": env.get("python"),
        },
    ]
    if env.get("claude_model"):
        actors.append(
            {
                "@id": crate_actor_id("claude-model"),
                # A model maps to SoftwareApplication (AIModel is not a context term).
                "@type": "SoftwareApplication",
                "name": str(env["claude_model"]),
            }
        )
    if env.get("shell"):
        actors.append(
            {
                "@id": crate_actor_id("shell"),
                "@type": "SoftwareApplication",
                "name": str(env["shell"]),
            }
        )
    if model.workflow and model.workflow.get("engine") and model.workflow["engine"] != "unknown":
        engine = str(model.workflow["engine"])
        # The base workflows.html MUST: a language/engine SoftwareApplication entity carries
        # name + url + version. Take the engine homepage from the adapter registry and the
        # observed engine version when the model carries one, else the placeholder "unknown".
        actors.append(
            {
                "@id": engine_actor_id(engine),
                "@type": "SoftwareApplication",
                "name": engine,
                "url": adapters.engine_homepage(engine.lower()),
                "softwareVersion": str(
                    model.workflow.get("version") or model.workflow.get("engine_version") or "unknown"
                ),
            }
        )
    # Strip None-valued fields before returning.
    return [strip_none(actor) for actor in actors]


def build_software(model: RunModel) -> list[dict[str, Any]]:
    """Emit a SoftwareApplication entity for every declared software entry and
    every command instrument basename, deduped by @id."""
    entities: dict[str, dict[str, Any]] = {}
    for sw in model.software:
        name = str(sw.get("name") or sw.get("command") or "software")
        sid = software_entity_id(name)
        entities[sid] = {
            "@id": sid,
            "@type": "SoftwareApplication",
            "name": name,
            "softwareVersion": sw.get("version", "unknown"),
        }
    for cmd in model.commands:
        if not cmd.argv:
            continue
        tool = os.path.basename(cmd.argv[0])
        sid = software_entity_id(tool)
        entities.setdefault(sid, {"@id": sid, "@type": "SoftwareApplication", "name": tool})
    return list(entities.values())
