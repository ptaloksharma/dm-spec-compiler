#!/usr/bin/env python3
"""api_design_status.py — report Design & Refine readiness for an agent home.

Zero-dependency (stdlib only): the Buddy UI calls this to decide whether the
Design & Refine tab shows the "Generate Architecture Diagram" empty state or
the live dashboard iframe. Never touches the dm_spec_compiler package, so it
works with any python3 on PATH.

usage: api_design_status.py <pyroot> <agent_home>

prints JSON:
  {status, requirements, design, dashboard, approved, mesh, agents, design_sha12}
"""
import hashlib
import json
import os
import re
import sys


def main() -> None:
    if len(sys.argv) < 3:
        print(json.dumps({"status": "error",
                          "error": "usage: api_design_status.py <pyroot> <agent_home>"}))
        sys.exit(1)
    home = os.path.abspath(sys.argv[2])
    req = os.path.join(home, "REQUIREMENTS.md")
    design = os.path.join(home, "TECH_DESIGN.yaml")
    dash = os.path.join(home, "architecture-dashboard.html")
    approved_stamp = design + ".approved"

    has_req = os.path.isfile(req)
    has_design = os.path.isfile(design)
    has_dash = os.path.isfile(dash)

    approved = False
    mesh = ""
    agents = 0
    sha12 = ""
    if has_design:
        try:
            text = open(design, encoding="utf-8").read()
            sha = hashlib.sha256(text.encode()).hexdigest()
            sha12 = sha[:12]
            m = re.search(r"^mesh_name:\s*(.+)$", text, re.M)
            mesh = m.group(1).strip() if m else ""
            agents = len(re.findall(r"^\s{2}-\s*name:", text, re.M))
            if os.path.isfile(approved_stamp):
                first = open(approved_stamp, encoding="utf-8").read().splitlines()[0].strip()
                approved = first == f"APPROVED {sha}"
        except Exception:
            pass

    print(json.dumps({
        "status": "ok",
        "agent_home": home,
        "requirements": has_req,
        "design": has_design,
        "dashboard": has_dash,
        "approved": approved,
        "mesh": mesh,
        "agents": agents,
        "design_sha12": sha12,
        # needs_generate is the empty-state trigger: spec captured but no design
        "needs_generate": has_req and not has_design,
    }))


if __name__ == "__main__":
    main()
