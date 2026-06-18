#!/usr/bin/env python3
import sys

import _bootstrap  # noqa: F401  (sets sys.path before ro_crate_run import)

from ro_crate_run.cli import main

raise SystemExit(main(["validate", *sys.argv[1:]]))
