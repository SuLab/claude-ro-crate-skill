#!/usr/bin/env python3
import json
import sys

import _bootstrap  # noqa: F401  (sets sys.path before ro_crate_run import)

from ro_crate_run.context import ProjectContext
from ro_crate_run.journal import EventWriter

event_type = sys.argv[1]
payload = {}
if "--payload-json" in sys.argv:
    payload = json.loads(sys.argv[sys.argv.index("--payload-json") + 1])
raise SystemExit(
    0 if EventWriter(ProjectContext.from_cwd().state_dir).append(event_type, payload) else 1
)
