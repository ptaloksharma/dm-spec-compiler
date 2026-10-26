"""Module 3 — Architect-in-the-Loop review & approval hook.

Emission is BLOCKED until the human architect approves the compiled
TECH_DESIGN.yaml. Two modes:

  interactive  (TTY): print a rendered review summary, then prompt
                      [a]pprove / [e]dit / [q]uit. Edit drops the file into
                      $EDITOR and re-validates on save.
  non-interactive   : require a signed approval file
                      ``<design>.approved`` whose first line is
                      ``APPROVED <sha256-of-design-yaml>``.

The approval is bound to the EXACT bytes of the design file — editing the
YAML after approval invalidates it (fail-closed).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

from .model import TechDesign


def design_sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def approval_path(design_path: str) -> str:
    return design_path + ".approved"


def is_approved(design_path: str) -> bool:
    ap = approval_path(design_path)
    if not (os.path.exists(design_path) and os.path.exists(ap)):
        return False
    current = design_sha(open(design_path, encoding="utf-8").read())
    first = open(ap, encoding="utf-8").read().splitlines()[0].strip()
    return first == f"APPROVED {current}"


def render_summary(design: TechDesign) -> str:
    lines = [f"TECH_DESIGN review — mesh '{design.mesh_name}' "
             f"({len(design.agents)} agents, sources: {len(design.source_docs)})"]
    for a in design.agents:
        lines.append(
            f"  • {a.name}  [{a.role}/{a.tier}]  states={len(a.states)} "
            f"eps={len(a.entry_points)} tools={len(a.tools)} "
            f"entities={len(a.entities)} invariants={len(a.invariants)}"
            + (f" hitl€{a.hitl_threshold_eur}" if a.hitl_threshold_eur else ""))
        if a.delegates_to:
            lines.append(f"      delegates → {', '.join(a.delegates_to)}")
    return "\n".join(lines)


def approve(design_path: str) -> None:
    sha = design_sha(open(design_path, encoding="utf-8").read())
    with open(approval_path(design_path), "w", encoding="utf-8") as f:
        f.write(f"APPROVED {sha}\n")


def review_gate(design_path: str, *, assume_yes: bool = False,
                dashboard_path: str | None = None) -> bool:
    """Run the checkpoint. Returns True iff approved (side effect: writes stamp).

    On a TTY this is a loop: show summary + dashboard location, then
    [a]pprove / [e]dit / [q]uit. Edit re-validates AND re-renders the
    dashboard so the architect always sees design & diagram in sync.
    """
    text = open(design_path, encoding="utf-8").read()
    design = TechDesign.from_yaml(text)  # re-validate whatever is on disk

    if is_approved(design_path):
        return True
    if assume_yes:
        approve(design_path)
        return True
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False  # non-interactive, no stamp → blocked

    while True:
        print(render_summary(design))
        if dashboard_path:
            print(f"\n  🗺  Archify diagram (open in browser): file://{os.path.abspath(dashboard_path)}")
        choice = input("\nArchitect review — [a]pprove / [e]dit / [q]uit: ").strip().lower()
        if choice in ("a", "approve", ""):
            approve(design_path)
            return True
        if choice in ("q", "quit"):
            return False
        if choice in ("e", "edit"):
            editor = os.environ.get("EDITOR", "vi")
            subprocess.call([editor, design_path])
            try:
                design = TechDesign.from_yaml(open(design_path, encoding="utf-8").read())
            except Exception as exc:  # validation failure → stay in loop
                print(f"  ✗ edited design failed validation: {exc}")
                continue
            if dashboard_path:  # keep diagram in sync with the edit
                from .archify_bridge import render_dashboard
                seal = render_dashboard(design, dashboard_path)
                print(f"  ↻ diagram re-rendered (spec {seal['spec_hash'][:12]})")
