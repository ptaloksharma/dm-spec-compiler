"""Resolve the dm-agent-kit governance library onto sys.path.

The kit is an EXTERNAL dependency — never vendored. It lives at
``$DM_AGENT_KIT_ROOT`` (default ``~/dm-agent-kit``) and exposes:

  - ``src/archify``         → as-built architecture-dashboard compiler
  - ``src/buddy``           → wizard/role_templates (scaffold conventions)
  - ``src/ingest``          → constraint_extractor (provenance spans)
  - ``python/dm_agent_governance`` → intent contract / lint-policy gates

Import this module FIRST (from ``dm_spec_compiler/__init__.py``) before any
``dm_spec_compiler`` module that touches kit APIs.
"""
from __future__ import annotations

import os
import sys


def kit_root() -> str:
    return os.path.abspath(
        os.path.expanduser(os.environ.get("DM_AGENT_KIT_ROOT", "~/dm-agent-kit"))
    )


def ensure_kit_path() -> str:
    root = kit_root()
    for sub in ("src", "python"):
        p = os.path.join(root, sub)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.insert(0, p)
    return root


ensure_kit_path()
