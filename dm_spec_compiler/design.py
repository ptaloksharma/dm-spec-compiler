"""Module 2 — Spec → TECH_DESIGN.yaml engine (deterministic).

Parses the normalised markdown spec-pack and extracts agents, hierarchy,
state machines (T01..Tnn), entry points (EP-XXX), tools, entities, invariants
and cross-agent edges. Everything is regex/heading driven — NO LLM guessing.

Grammar recognised (all optional; missing sections simply yield empty lists):

  # Agent: <kebab-name>            → starts an AgentDef block
    role: ui-coordinator|domain-agent|sub-agent
    tier: fast-path|standard|deep
    objective: <text>
    delegates_to: a, b
    hitl_threshold_eur: 25000
    egress: host1, host2

  ## States
    - T01 intake — received            → StateDef(id=T01, name=intake, ...)
    - T07 match [HOLD] — awaiting approval  (invariant: 3-way match required)

  ## Entry Points
    - EP-INT ingress — message arrives → T01

  ## Tools
    - match_invoice — run the matcher (mutating)

  ## Entities
    - invoice(id, supplier_id, amount, status)

  ## Invariants
    - 3-way match required before posting

Cross-agent edges derive from ``delegates_to``.
"""
from __future__ import annotations

import re

from .model import (AgentDef, EdgeDef, EntityDef, EntryPoint, EarsRequirement,
                    HoldDef, InvariantDef, NfrRequirement, ProcessingStep,
                    StateDef, TechDesign, ToolDef, TransitionDef, TypedField)

_AGENT_HEAD_RE = re.compile(r"^#{1,3}\s*Agent:\s*(?P<name>[a-z0-9][a-z0-9-]+)\s*$", re.I | re.M)
_SECTION_RE = re.compile(r"^#{2,4}\s*(?P<sec>states?|entry[- ]points?|tools?|entities|invariants?)\s*$", re.I)
_STATE_RE = re.compile(
    r"^\s*[-*]\s*(?P<id>T\d{2})\s+(?P<name>[a-z0-9_ -]+?)"
    r"(?:\s*\[(?P<flags>[^\]]+)\])?"
    r"(?:\s*[—–-]\s*(?P<desc>.*?))?"
    r"(?:\s*\(invariant:\s*(?P<inv>[^)]+)\))?\s*$", re.I | re.M)
_EP_RE = re.compile(
    r"^\s*[-*]\s*(?P<id>EP-[A-Z0-9][A-Z0-9_-]*)\s+(?P<kind>[a-z_-]+?)"
    r"(?:\s*[—–-]\s*(?P<desc>.*?))?"
    r"(?:\s*→\s*(?P<target>T\d{2}))?\s*$", re.I | re.M)
_TOOL_RE = re.compile(
    r"^\s*[-*]\s*(?P<name>[a-z][a-z0-9_]+)\s*[—–-]\s*(?P<desc>.*?)"
    r"(?:\s*\((?P<flags>[^)]+)\))?\s*$", re.I | re.M)
_ENTITY_RE = re.compile(
    r"^\s*[-*]\s*(?P<name>[a-z][a-z0-9_]+)\s*"
    r"(?:\((?P<fields>[^)]*)\))?"
    r"(?:\s*[—–-]\s*(?P<desc>.*?))?\s*$", re.I | re.M)
_INV_RE = re.compile(r"^\s*[-*]\s*(?P<txt>.+?)\s*$", re.M)
_KV_RE = re.compile(r"^\s*(?P<k>[a-z_]+):\s*(?P<v>.+?)\s*$", re.I)


def _snake(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    return s


def _split_sections(md: str) -> list[tuple[str, str]]:
    """Return [(agent_name, block_text)] — one per '# Agent:' heading."""
    matches = list(_AGENT_HEAD_RE.finditer(md))
    if not matches:
        return []
    blocks: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        blocks.append((m.group("name"), md[m.start():end]))
    return blocks


def _section_slice(block: str, kind: str) -> str:
    """Extract the body of a ## <kind> section within an agent block."""
    lines = block.splitlines()
    out: list[str] = []
    active = False
    for ln in lines:
        m = _SECTION_RE.match(ln)
        if m:
            active = m.group("sec").lower().startswith(kind)
            continue
        if ln.startswith("#") and not _SECTION_RE.match(ln):
            active = False
        if active:
            out.append(ln)
    return "\n".join(out)


def _parse_agent(name: str, block: str) -> AgentDef:
    agent = AgentDef(name=name)

    # top-of-block scalar keys
    header = block.split("\n## ")[0]
    for ln in header.splitlines():
        kv = _KV_RE.match(ln)
        if not kv:
            continue
        k, v = kv.group("k").lower(), kv.group("v").strip()
        if k == "role":
            agent.role = v if v in {"ui-coordinator", "domain-agent", "sub-agent"} else "domain-agent"
        elif k == "tier":
            agent.tier = v
        elif k == "objective":
            agent.objective = v
        elif k == "use_case":
            agent.use_case = v
        elif k == "delegates_to":
            agent.delegates_to = [x.strip() for x in v.split(",") if x.strip()]
        elif k == "hitl_threshold_eur":
            try:
                agent.hitl_threshold_eur = int(float(v.replace(",", "")))
            except ValueError:
                pass
        elif k == "egress":
            agent.allowed_egress = [x.strip() for x in v.split(",") if x.strip()]

    # states
    for m in _STATE_RE.finditer(_section_slice(block, "state")):
        flags = (m.group("flags") or "").lower()
        agent.states.append(StateDef(
            id=m.group("id"),
            name=_snake(m.group("name")),
            description=(m.group("desc") or "").strip(),
            invariant=(m.group("inv") or None),
            hold="hold" in flags,
        ))

    # entry points
    for m in _EP_RE.finditer(_section_slice(block, "entry")):
        agent.entry_points.append(EntryPoint(
            id=m.group("id"),
            kind=m.group("kind").lower(),
            description=(m.group("desc") or "").strip(),
            target_state=m.group("target"),
        ))

    # tools
    for m in _TOOL_RE.finditer(_section_slice(block, "tool")):
        flags = (m.group("flags") or "").lower()
        agent.tools.append(ToolDef(
            name=_snake(m.group("name")),
            description=(m.group("desc") or "").strip(),
            mutating="mutating" in flags or "write" in flags,
        ))

    # entities
    for m in _ENTITY_RE.finditer(_section_slice(block, "entit")):
        fields = [f.strip() for f in (m.group("fields") or "").split(",") if f.strip()]
        agent.entities.append(EntityDef(
            name=_snake(m.group("name")),
            table=_snake(m.group("name")) + "s",
            fields=fields,
        ))

    # invariants (plain bullets)
    for m in _INV_RE.finditer(_section_slice(block, "invariant")):
        agent.invariants.append(m.group("txt").strip())

    return agent


def compile_design(spec_texts: dict[str, str], mesh_name: str = "spec-mesh") -> TechDesign:
    """spec_texts: {filename: markdown}. Returns a validated TechDesign."""
    combined = "\n\n".join(t for t in spec_texts.values())
    blocks = _split_sections(combined)
    if not blocks:
        raise ValueError(
            "no '# Agent:' blocks found — spec pack must declare at least one agent")

    agents = [_parse_agent(name, block) for name, block in blocks]

    # de-duplicate repeated agent declarations by merging
    merged: dict[str, AgentDef] = {}
    for a in agents:
        if a.name in merged:
            m = merged[a.name]
            m.states.extend(s for s in a.states if s.id not in {x.id for x in m.states})
            m.entry_points.extend(e for e in a.entry_points if e.id not in {x.id for x in m.entry_points})
            m.tools.extend(t for t in a.tools if t.name not in {x.name for x in m.tools})
            m.entities.extend(e for e in a.entities if e.name not in {x.name for x in m.entities})
            m.invariants.extend(i for i in a.invariants if i not in m.invariants)
        else:
            merged[a.name] = a
    agents = list(merged.values())

    # cross-agent edges from delegates_to (and coordinator→all fallback)
    known = {a.name for a in agents}
    for a in agents:
        for target in a.delegates_to:
            if target in known and a.states:
                src = a.states[-1].id
                tgt_agent = merged[target]
                dst = tgt_agent.states[0].id if tgt_agent.states else src
                a.edges.append(EdgeDef(from_state=src, to_state=dst,
                                       condition=f"handoff:{target}"))

    return TechDesign(
        mesh_name=mesh_name,
        agents=agents,
        source_docs=sorted(spec_texts.keys()),
    )


# --------------------------------------------------------------------------- #
# Rich HTML merge (πd Genius spec packs)                                       #
# --------------------------------------------------------------------------- #
def _first_agent(design: TechDesign) -> AgentDef:
    """Target for spec-pack-level rich data. A single HTML spec pack describes
    ONE bounded context; when the markdown declares no explicit agent we anchor
    rich extractions to a synthesized primary agent."""
    if design.agents:
        return design.agents[0]
    raise ValueError("rich merge requires at least one agent")


def _merge_states(agent: AgentDef, rich_states: list[dict]) -> None:
    known = {s.id for s in agent.states}
    for rs in rich_states:
        if rs["id"] in known:
            # enrich terminal flag on existing
            for s in agent.states:
                if s.id == rs["id"]:
                    s.terminal = s.terminal or rs.get("terminal", False)
            continue
        agent.states.append(StateDef(
            id=rs["id"], name=rs["name"], description=rs.get("description", ""),
            terminal=rs.get("terminal", False), hold=rs.get("hold", False)))
        known.add(rs["id"])


def _merge_entities(agent: AgentDef, rich_entities: list[dict]) -> None:
    known = {e.name for e in agent.entities}
    for re_ in rich_entities:
        typed = [TypedField(**tf) for tf in re_.get("typed_fields", [])]
        if re_["name"] in known:
            e = next(x for x in agent.entities if x.name == re_["name"])
            e.typed_fields.extend(t for t in typed
                                  if t.name not in {x.name for x in e.typed_fields})
            e.fields.extend(f for f in re_.get("fields", []) if f not in e.fields)
            e.owner = e.owner or re_.get("owner", "")
            e.scope = e.scope or re_.get("scope", "")
            continue
        agent.entities.append(EntityDef(
            name=re_["name"], table=re_.get("table"), fields=re_.get("fields", []),
            typed_fields=typed, owner=re_.get("owner", ""),
            scope=re_.get("scope", ""), acts=re_.get("acts", [])))
        known.add(re_["name"])


def _merge_transitions(agent: AgentDef, rich: list[dict]) -> None:
    known = {t.id for t in agent.transitions}
    for rt in rich:
        if rt["id"] in known:
            continue
        agent.transitions.append(TransitionDef(**rt))
        known.add(rt["id"])


def _merge_holds(agent: AgentDef, rich: list[dict]) -> None:
    known = {h.hold_type for h in agent.holds}
    for rh in rich:
        if rh["hold_type"] in known:
            continue
        agent.holds.append(HoldDef(**rh))
        known.add(rh["hold_type"])


def _merge_invariants(agent: AgentDef, rich: list[dict]) -> None:
    known = {i.id for i in agent.invariant_defs}
    for ri in rich:
        if ri["id"] in known:
            continue
        agent.invariant_defs.append(InvariantDef(**ri))
        agent.invariants.append(ri["rule"])
        known.add(ri["id"])


def _merge_entry_points(agent: AgentDef, rich: list[dict]) -> None:
    known = {e.id for e in agent.entry_points}
    for re_ in rich:
        if re_["id"] in known:
            continue
        steps = [ProcessingStep(**s) for s in re_.get("processing", [])]
        ep = EntryPoint(
            id=re_["id"], kind=re_.get("kind", "command"),
            name=re_.get("name", ""), proposed=re_.get("proposed", False),
            transition=re_.get("transition", ""), route=re_.get("route", ""),
            input_schema=re_.get("input_schema", ""),
            guards=re_.get("guards", []), processing=steps,
            outputs=re_.get("outputs", []), errors=re_.get("errors", []),
            idempotency=re_.get("idempotency", ""), tests=re_.get("tests", []),
            description=re_.get("name", ""))
        agent.entry_points.append(ep)
        known.add(ep.id)
        # one Level-4 atomic tool per entry point
        tname = re.sub(r"[^a-z0-9]+", "_", (ep.name or ep.id).lower()).strip("_") or ep.id.lower().replace("-", "_")
        if tname not in {t.name for t in agent.tools}:
            mutating = ep.kind in ("command", "event_handler")
            agent.tools.append(ToolDef(name=tname, description=ep.name or ep.id,
                                       mutating=mutating, entry_point=ep.id,
                                       kind=ep.kind))


def _merge_ears(agent: AgentDef, rich: dict) -> None:
    for r in rich.get("ears_requirements", []):
        if r["id"] in {e.id for e in agent.ears_requirements}:
            continue
        clauses = [c for c in r.get("clauses", [])]
        from .model import EarsClause
        agent.ears_requirements.append(EarsRequirement(
            id=r["id"], title=r.get("title", ""), posture=r.get("posture", ""),
            clauses=[EarsClause(**c) for c in clauses]))
    for n in rich.get("nfr_requirements", []):
        agent.nfr_requirements.append(NfrRequirement(**n))


def merge_rich(design: TechDesign, rich_docs: list[dict]) -> TechDesign:
    """Merge a list of htmlspec.extract_rich() payloads into the design."""
    for rich in rich_docs:
        if not rich:
            continue
        agent = _first_agent(design)
        kind = rich.get("__kind__")
        if kind == "entity_state":
            _merge_entities(agent, rich.get("entities", []))
            _merge_states(agent, rich.get("states", []))
            _merge_transitions(agent, rich.get("transitions", []))
            _merge_holds(agent, rich.get("holds", []))
            _merge_invariants(agent, rich.get("invariants", []))
        elif kind == "entry_points":
            _merge_entry_points(agent, rich.get("entry_points", []))
        elif kind == "requirements":
            _merge_ears(agent, rich)
    return design


def compile_design_rich(spec_texts: dict[str, str], rich_docs: list[dict],
                        mesh_name: str = "spec-mesh") -> TechDesign:
    """compile_design + rich HTML merge. If the markdown declares no agent but
    rich entity/state data exists, synthesize a primary domain-agent."""
    try:
        design = compile_design(spec_texts, mesh_name=mesh_name)
    except ValueError:
        if not rich_docs:
            raise
        # no markdown agent blocks: anchor on a synthesized primary agent
        design = TechDesign(mesh_name=mesh_name, agents=[
            AgentDef(name=f"{mesh_name}-agent", role="domain-agent",
                     objective=f"Primary agent for mesh {mesh_name}")],
            source_docs=sorted(spec_texts.keys()))
    return merge_rich(design, rich_docs)
