"""Canonical spec views — requirements.md / entities.md / entry-points.md.

Derived DETERMINISTICALLY from a validated TechDesign (never from raw text),
so the three canonical files always agree with TECH_DESIGN.yaml. Written into
the spec-pack alongside the per-source conversions.
"""
from __future__ import annotations

import os

from .model import TechDesign


def render_requirements(design: TechDesign) -> str:
    out = [f"# Requirements — mesh `{design.mesh_name}`", ""]
    out.append(f"Sources: {', '.join(design.source_docs) or '(none)'}")
    out.append("")
    for a in design.agents:
        out.append(f"## Agent: {a.name}")
        out.append(f"- role: {a.role}")
        out.append(f"- tier: {a.tier}")
        if a.objective:
            out.append(f"- objective: {a.objective}")
        if a.delegates_to:
            out.append(f"- delegates_to: {', '.join(a.delegates_to)}")
        if a.hitl_threshold_eur is not None:
            out.append(f"- hitl_threshold_eur: {a.hitl_threshold_eur}")
        if a.allowed_egress:
            out.append(f"- egress: {', '.join(a.allowed_egress)}")
        if a.states:
            out.append("")
            out.append("### States")
            for s in a.states:
                line = f"- {s.id} {s.name}"
                if s.hold:
                    line += " [HOLD]"
                if s.description:
                    line += f" — {s.description}"
                if s.invariant:
                    line += f" (invariant: {s.invariant})"
                out.append(line)
        if a.tools:
            out.append("")
            out.append("### Tools")
            for t in a.tools:
                line = f"- {t.name}"
                if t.description:
                    line += f" — {t.description}"
                if t.mutating:
                    line += " (mutating)"
                out.append(line)
        if a.invariants:
            out.append("")
            out.append("### Invariants")
            for inv in a.invariants:
                out.append(f"- {inv}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def render_entities(design: TechDesign) -> str:
    out = [f"# Entities — mesh `{design.mesh_name}`", ""]
    any_ent = False
    for a in design.agents:
        if not a.entities:
            continue
        any_ent = True
        out.append(f"## {a.name}")
        for e in a.entities:
            fields = ", ".join(e.fields) if e.fields else "(no fields declared)"
            out.append(f"- {e.name}  →  table `{e.table}`")
            out.append(f"    - fields: {fields}")
        out.append("")
    if not any_ent:
        out.append("_(no entities declared in any agent spec)_")
    return "\n".join(out).rstrip() + "\n"


def render_entry_points(design: TechDesign) -> str:
    out = [f"# Entry Points — mesh `{design.mesh_name}`", ""]
    any_ep = False
    for a in design.agents:
        if not a.entry_points:
            continue
        any_ep = True
        out.append(f"## {a.name}")
        for ep in a.entry_points:
            line = f"- {ep.id} [{ep.kind}]"
            if ep.description:
                line += f" — {ep.description}"
            if ep.target_state:
                line += f" → {ep.target_state}"
            out.append(line)
        out.append("")
    if not any_ep:
        out.append("_(no entry points declared in any agent spec)_")
    return "\n".join(out).rstrip() + "\n"


def write_canonical(design: TechDesign, spec_pack: str) -> list[str]:
    os.makedirs(spec_pack, exist_ok=True)
    files = {
        "requirements.md": render_requirements(design),
        "entities.md": render_entities(design),
        "entry-points.md": render_entry_points(design),
    }
    written: list[str] = []
    for fname, text in files.items():
        path = os.path.join(spec_pack, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        written.append(path)
    return written
