#!/usr/bin/env python3
import sys

import _bootstrap  # noqa: F401  (sets sys.path before ro_crate_run import)

from ro_crate_run.hooks import main

# Require the Claude event name as argv[1]: defaulting it would let a malformed
# hooks.json entry inject a fabricated event type into the append-only journal.
if len(sys.argv) < 2:
    print("rocrate_hook.py requires the Claude event name as argv[1]", file=sys.stderr)
    raise SystemExit(2)

raise SystemExit(main(sys.argv[1]))
