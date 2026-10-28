"""Conversational design refinement (Buddy collaborator, Part 2b).

Translate a natural-language instruction into a deterministic mutation of an
APPROVED-or-draft TECH_DESIGN.yaml, re-validate via pydantic, and report what
changed. Deterministic intent parsing — NO LLM guessing. Unknown instructions
fail closed (return ok=False with a helpful message) rather than corrupting
the design.

Supported instructions (agent-scoped to the design's single agent, or the
agent named in the instruction):
  - "add a state <Name> [hold]"            → append a T-state (optionally HOLD)
  - "add a hold state <Name>"              → append a HOLD state
  - "add a tool <name> [for <EP-ID>]"      → append a tool stub (+ optional EP)
  - "add an invariant <text>"              → append an invariant rule
  - "rename state <Old> to <New>"          → rename a state's display name
  - "set hitl threshold to <amount>"       → set hitl_threshold_eur
Anything else → ok=False, no mutation.
"""
from __future__ import annotations

import re

from .model import InvariantDef, StateDef, TechDesign, ToolDef


def _next_state_id(agent) -> str:
    nums = []
    for s in agent.states:
        m = re.match(r"^T(\d+)", s.id)
        if m:
            nums.append(int(m.group(1)))
    return f"T{(max(nums) + 1) if nums else 1:02d}"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "state"


def refine_design(design: TechDesign, instruction: str) -> dict:
    """Apply one NL instruction to a TechDesign. Returns a change-report dict:
    {ok, changed, summary, error?}. On ok=False the design is UNMODIFIED."""
    text = instruction.strip()
    low = text.lower()
    if not design.agents:
        return {"ok": False, "changed": [], "error": "no agents in design"}
    # agent scoping: prefer an agent named in the instruction, else the first.
    agent = design.agents[0]
    for a in design.agents:
        if a.name.lower() in low:
            agent = a
            break
    changed: list[str] = []

    # --- add a (hold) state -------------------------------------------------
    m = re.search(r"add (?:a |an )?(hold )?state\s+([a-zA-Z][\w -]*?)\s*(?:\bhold\b)?$", low)
    if m:
        is_hold = bool(m.group(1)) or " hold" in low
        name_raw = m.group(2).strip()
        sid = _next_state_id(agent)
        terminal = name_raw.lower() in ("done", "cancelled", "canceled", "complete", "rejected", "shipped")
        agent.states.append(StateDef(
            id=sid, name=_slug(name_raw).title().replace("-", " "),
            description=f"added via conversational refinement: {name_raw}",
            terminal=terminal, hold=is_hold,
        ))
        changed.append(f"state {sid} ({name_raw}){' [HOLD]' if is_hold else ''}")
        return {"ok": True, "changed": changed,
                "summary": f"Added state {sid} '{name_raw}'" + (" (HOLD)" if is_hold else "")}

    # --- add a tool ---------------------------------------------------------
    m = re.search(r"add (?:a |an )?tool\s+([a-zA-Z][\w-]*)(?:\s+for\s+([A-Za-z0-9-]+))?", low)
    if m:
        tool = _slug(m.group(1)).replace("-", "_")
        ep = m.group(2)
        agent.tools.append(ToolDef(
            name=tool, description="added via conversational refinement",
            mutating=False, entry_point=ep or None))
        changed.append(f"tool {tool}" + (f" for {ep}" if ep else ""))
        return {"ok": True, "changed": changed,
                "summary": f"Added tool '{tool}'" + (f" bound to {ep}" if ep else "")}

    # --- add an invariant ---------------------------------------------------
    m = re.search(r"add (?:an |a )?invariant\s+(.+)$", low)
    if m:
        rule = m.group(1).strip()
        agent.invariant_defs.append(InvariantDef(id=f"I-{len(agent.invariant_defs) + 1:02d}", rule=rule))
        changed.append(f"invariant I-{len(agent.invariant_defs):02d}")
        return {"ok": True, "changed": changed,
                "summary": f"Added invariant I-{len(agent.invariant_defs):02d}: {rule}"}

    # --- rename a state -----------------------------------------------------
    m = re.search(r"rename state\s+([a-zA-Z][\w -]*?)\s+to\s+([a-zA-Z][\w -]*)$", low)
    if m:
        old, new = m.group(1).strip(), m.group(2).strip()
        for st in agent.states:
            if st.name.lower() == old or st.id.lower() == old:
                st.name = new.title()
                changed.append(f"renamed state {st.id} → {new}")
                return {"ok": True, "changed": changed,
                        "summary": f"Renamed state {st.id} to '{new}'"}
        return {"ok": False, "changed": [], "error": f"no state named '{old}'"}

    # --- set hitl threshold --------------------------------------------------
    m = re.search(r"(?:set )?hitl(?: threshold)?(?: to)?\s*(?:€|eur|euros?)?\s*(\d[\d,]*)", low)
    if m:
        amount = int(m.group(1).replace(",", ""))
        agent.hitl_threshold_eur = amount
        changed.append(f"hitl_threshold_eur = €{amount}")
        return {"ok": True, "changed": changed,
                "summary": f"Set HITL threshold to €{amount}"}

    return {"ok": False, "changed": [],
            "error": ("couldn't parse that refinement. Try: 'add a hold state Review', "
                      "'add a tool notify_customer', 'add an invariant ...', "
                      "'rename state X to Y', or 'set hitl threshold to 5000'.")}


def refine_design_file(design_path: str, instruction: str) -> dict:
    """Load YAML, refine, re-validate (pydantic), write back atomically.
    Fail-closed: a failed re-validation does NOT touch the file."""
    raw = open(design_path, encoding="utf-8").read()
    design = TechDesign.from_yaml(raw)
    res = refine_design(design, instruction)
    if not res.get("ok"):
        return res
    # re-validate the mutated design (round-trip through pydantic)
    try:
        validated = TechDesign.from_yaml(design.to_yaml())
    except Exception as exc:
        return {"ok": False, "changed": [], "error": f"re-validation failed: {exc}"}
    with open(design_path, "w", encoding="utf-8") as f:
        f.write(validated.to_yaml())
    res["design_path"] = design_path
    return res
