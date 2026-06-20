#!/usr/bin/env python3
import sys

import _bootstrap  # noqa: F401  (sets sys.path before ro_crate_run import)

from ro_crate_run.hooks import main

raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "SessionStart"))
