"""Conversational design refinement (Buddy collaborator).

Translate a natural-language instruction into a deterministic mutation of an
APPROVED-or-draft TECH_DESIGN.yaml, re-validate via pydantic, and report what
changed. Deterministic parsing is the PRIMARY path — fast, free, reproducible.
Unknown instructions fail closed (no mutation).

An OPTIONAL LLM harness (DeepSeek) can enrich the human-readable comment for an
already-applied, already-validated change. It is OFF by default, NEVER mutates
the design, and falls back to the deterministic summary on any error.

Supported instructions (agent-scoped to the named agent, else the first):
  - "add a state <Name> [hold]"        → append a T-state (optionally HOLD)
  - "add a hold state <Name>"          → append a HOLD state
  - "add a tool <name> [for <EP-ID>]"  → append a tool stub (+ optional EP)
  - "add an invariant <text>"          → append an invariant rule
  - "rename state <Old> to <New>"      → rename a state's display name
  - "set hitl threshold to <amount>"   → set hitl_threshold_eur
Anything else → ok=False, no mutation.
"""
from __future__ import annotations

import re

from .events import emit_event
from .model import InvariantDef, StateDef, TechDesign, ToolDef, TransitionDef


# --------------------------------------------------------------------------- #
# Optional LLM/DeepSeek comment harness (OFF by default).                       #
# --------------------------------------------------------------------------- #
def _llm_enabled() -> bool:
    import os
    return os.environ.get("DM_SPEC_LLM", "").lower() in ("deepseek", "1", "true") and bool(
        os.environ.get("DEEPSEEK_API_KEY"))


def _llm_comment(instruction: str, summary: str, agent_name: str) -> str:
    """Optional richer one-line comment for an ALREADY-applied, ALREADY-validated
    change. Never mutates the design; falls back to `summary` on any failure."""
    if not _llm_enabled():
        return summary
    import json
    import os
    import urllib.request
    base = os.environ.get("DEEPSEEK_BASE", "https://api.deepseek.com")
    prompt = (
        "In one warm, specific sentence, confirm this architecture refinement to "
        f"the architect of agent '{agent_name}'. Instruction: {instruction!r}. "
        f"Applied change: {summary}.")
    try:
        body = json.dumps({
            "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 60, "temperature": 0.2,
        }).encode()
        req = urllib.request.Request(
            f"{base}/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        return text or summary
    except Exception:
        return summary


def _next_state_id(agent) -> str:
    nums = []
    for s in agent.states:
        m = re.match(r"^T(\d+)", s.id)
        if m:
            nums.append(int(m.group(1)))
    return f"T{(max(nums) + 1) if nums else 1:02d}"


def _next_transition_id(agent) -> str:
    nums = []
    for t in agent.transitions:
        m = re.match(r"^T(\d+)", t.id)
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
            terminal=terminal, hold=is_hold))
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

    # --- add a transition <From> -> <To> [when <trigger>] --------------------
    m = re.search(
        r"add (?:a |an )?transition\s+([a-zA-Z][\w -]*?)\s*(?:->|to)\s*([a-zA-Z][\w -]*?)"
        r"(?:\s+(?:when|on|via|trigger(?:ed by)?)\s+([\w -]+))?$", low)
    if m:
        frm, to = m.group(1).strip(), m.group(2).strip()
        trig = (m.group(3) or "").strip()
        def _sid(name):
            for st in agent.states:
                if st.name.lower() == name or st.id.lower() == name:
                    return st.id
            return name.title()
        tid = _next_transition_id(agent)
        agent.transitions.append(TransitionDef(
            id=tid, from_state=_sid(frm), to_state=_sid(to),
            trigger=trig or "manual", guard="", effect="added via conversational refinement"))
        changed.append(f"transition {tid} {_sid(frm)}->{_sid(to)}")
        return {"ok": True, "changed": changed,
                "summary": f"Added transition {tid}: {_sid(frm)} → {_sid(to)}" + (f" on '{trig}'" if trig else "")}

    # --- remove/delete a state (and its transitions) -------------------------
    m = re.search(r"(?:remove|delete)\s+(?:the\s+)?state\s+([a-zA-Z][\w -]*?)$", low)
    if m:
        name = m.group(1).strip()
        target = None
        for st in agent.states:
            if st.name.lower() == name or st.id.lower() == name:
                target = st
                break
        if not target:
            return {"ok": False, "changed": [], "error": f"no state named '{name}'"}
        agent.states = [st for st in agent.states if st.id != target.id]
        before = len(agent.transitions)
        agent.transitions = [t for t in agent.transitions
                             if t.from_state != target.id and t.to_state != target.id]
        removed_edges = before - len(agent.transitions)
        changed.append(f"removed state {target.id} ({removed_edges} transition(s) dropped)")
        return {"ok": True, "changed": changed,
                "summary": f"Removed state {target.id} '{target.name}' + {removed_edges} transition(s)"}

    # --- remove/delete a tool -------------------------------------------------
    m = re.search(r"(?:remove|delete)\s+(?:the\s+)?tool\s+([a-zA-Z][\w-]*?)$", low)
    if m:
        name = _slug(m.group(1)).replace("-", "_")
        before = len(agent.tools)
        agent.tools = [t for t in agent.tools if t.name != name]
        if len(agent.tools) == before:
            return {"ok": False, "changed": [], "error": f"no tool named '{name}'"}
        changed.append(f"removed tool {name}")
        return {"ok": True, "changed": changed, "summary": f"Removed tool '{name}'"}

    return {"ok": False, "changed": [],
            "error": ("couldn't parse that refinement. Try: 'add a hold state Review', "
                      "'add a tool notify_customer', 'add a transition A -> B', "
                      "'remove state X', 'add an invariant ...', 'rename state X to Y', "
                      "or 'set hitl threshold to 5000'.")}


def refine_design_file(design_path: str, instruction: str) -> dict:
    """Load YAML, refine, re-validate (pydantic), write back atomically.
    Fail-closed: a failed re-validation does NOT touch the file."""
    from .review import is_approved
    was_approved = is_approved(design_path)
    raw = open(design_path, encoding="utf-8").read()
    design = TechDesign.from_yaml(raw)
    res = refine_design(design, instruction)
    if not res.get("ok"):
        emit_event("GUARDRAIL", f"refine blocked: {res.get('error', 'unparseable')}",
                   level="block", detail={"instruction": instruction})
        return res
    try:
        validated = TechDesign.from_yaml(design.to_yaml())
    except Exception as exc:
        emit_event("GUARDRAIL", f"refine re-validation failed: {exc}", level="block")
        return {"ok": False, "changed": [], "error": f"re-validation failed: {exc}"}
    with open(design_path, "w", encoding="utf-8") as f:
        f.write(validated.to_yaml())
    res["design_path"] = design_path
    agent_name = design.agents[0].name if design.agents else "agent"
    res["summary"] = _llm_comment(instruction, res.get("summary", ""), agent_name)
    emit_event("REFINE", res.get("summary", "design refined"),
               detail={"changed": res.get("changed", [])})
    if was_approved:
        # A design edit invalidates the prior SHA-256 stamp → notify.
        emit_event("STAMP", "prior SHA-256 approval invalidated by design edit — re-approve required",
                   level="warn", detail={"design": design_path})
        res["approval_invalidated"] = True
    return res
