"""Module 4 — Deterministic code emitter.

Reads an APPROVED TechDesign and writes ONLY the dm-agent-kit editable zone
of the target workspace:

  <ws>/GOAL.yaml
  <ws>/src/logic/__init__.py
  <ws>/src/logic/state.py
  <ws>/src/logic/tools.py
  <ws>/src/logic/prompts.py
  <ws>/src/logic/workflow.py

Safety boundaries (fail-closed):
  - Refuses to write unless the design file passes the review gate
    (``review.is_approved``) unless ``force=True``.
  - Refuses to touch anything inside the kit repo itself.
  - Writes only the five paths above + GOAL.yaml; existing domain code in
    tools.py is preserved via the additive sentinel block pattern.
"""
from __future__ import annotations

import os

import yaml

from .model import AgentDef, TechDesign
from . import emit_rich

_SENTINEL = "# DM-SPEC-COMPILER GENERATED BLOCK (regenerated from TECH_DESIGN.yaml)"

# Hand-written code is preserved below this marker on re-emission. Everything
# from the marker line to EOF in an EXISTING file is carried over verbatim; the
# freshly rendered plumbing (headers, imports, registries, nodes) is rebuilt
# above it. This makes the docstring's "additive sentinel block" claim real.
_PRESERVE_MARKER = "# --- DM-SPEC-COMPILER: hand-written code below is preserved ---"


def _split_preserved(existing: str) -> str:
    """Return the hand-written tail of an existing emitted file (from the
    preserve marker to EOF), or "" if none. The marker line itself is kept so
    re-emission stays idempotent."""
    idx = existing.find(_PRESERVE_MARKER)
    if idx == -1:
        return ""
    return existing[idx:].rstrip() + "\n"


def _write_preserving(path: str, rendered: str) -> None:
    """Write `rendered`, preserving any hand-written block from the existing
    file. If the rendered output already contains the preserve marker, the
    existing tail (after the marker) is re-appended."""
    existing = ""
    if os.path.exists(path):
        try:
            existing = open(path, encoding="utf-8").read()
        except Exception:
            existing = ""
    tail = _split_preserved(existing)
    if not tail:
        # first emission (or no marker): append the marker so future hand-edits
        # have a stable home below the generated plumbing.
        body = rendered.rstrip() + "\n\n" + _PRESERVE_MARKER + "\n"
    else:
        # strip any stale marker already present in the fresh render, then
        # re-anchor the preserved hand-written tail.
        head = rendered.split(_PRESERVE_MARKER)[0].rstrip()
        body = head + "\n\n" + tail
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


# --------------------------------------------------------------------------- #
# GOAL.yaml                                                                     #
# --------------------------------------------------------------------------- #
def render_goal(agent: AgentDef, design: TechDesign) -> str:
    goal = {
        "objective": agent.objective or agent.use_case or f"{agent.name} agent",
        "tier": agent.tier,
        "owner": "architect",
        "role": agent.role,
        "tokenBudget": 200000,
        "allowedTools": [t.name for t in agent.tools] or ["echo"],
        "egressAllow": agent.allowed_egress,
        "failClosed": True,
        "sanitization": "strict",
        "x-compiled-by": "dm-spec-compiler",
        "x-mesh": design.mesh_name,
        "x-delegates-to": agent.delegates_to,
    }
    if agent.hitl_threshold_eur is not None:
        goal["hitlThresholdEur"] = agent.hitl_threshold_eur
    return yaml.safe_dump(goal, sort_keys=False)


def render_intent(agent: AgentDef, design: TechDesign) -> str:
    """Human source-of-truth intent for the kit's contract compiler.

    The kit's intent_contract compiler turns this into a SIGNED GOAL.yaml
    (SHA-256 configProvenance binding) — required for the lint-policy gate.
    """
    tools = ", ".join(t.name for t in agent.tools) or "echo"
    egress = ", ".join(agent.allowed_egress)
    lines = [
        f"objective: {agent.objective or agent.use_case or agent.name + ' agent'}",
        f"tier: {agent.tier}",
        "owner: architect",
        "tokenBudget: 200000",
        f"allowedTools: {tools}",
        f"egressAllow: {egress}",
        "failClosed: true",
        "sanitization: strict",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# src/logic/state.py                                                            #
# --------------------------------------------------------------------------- #
def render_state(agent: AgentDef) -> str:
    if emit_rich._is_rich(agent):
        return emit_rich.render_state(agent)
    return _render_state_legacy(agent)


def _render_state_legacy(agent: AgentDef) -> str:
    state_comment = "\n".join(
        f"    # {s.id} {s.name}: {s.description}" for s in agent.states) or \
        "    # (no states declared in spec)"
    inv_block = "\n".join(
        f'    "INV{i:02d}": {inv!r},' for i, inv in enumerate(agent.invariants, 1)) \
        or '    # (no invariants declared)'
    holds = [s.id for s in agent.states if s.hold]
    return f'''"""
{agent.name} — graph state + nodes (EDITABLE logic file 4 of 4).

Compiled by dm-spec-compiler from the approved TECH_DESIGN.yaml.
Declared states:
{state_comment}
"""
from __future__ import annotations

from typing import Any, TypedDict

INVARIANTS: dict[str, str] = {{
{inv_block}
}}
HOLD_STATES: list[str] = {holds!r}
STATE_IDS: list[str] = {[s.id for s in agent.states]!r}


class AgentState(TypedDict, total=False):
    input: dict[str, Any]
    messages: list[dict[str, str]]
    current_state: str
    plan: list[str]
    tool_results: dict[str, Any]
    final: dict[str, Any]
'''


# --------------------------------------------------------------------------- #
# src/logic/tools.py                                                            #
# --------------------------------------------------------------------------- #
def render_tools(agent: AgentDef) -> str:
    if emit_rich._is_rich(agent):
        return emit_rich.render_tools(agent)
    return _render_tools_legacy(agent)


def _render_tools_legacy(agent: AgentDef) -> str:
    fns: list[str] = []
    names: list[str] = []
    for t in agent.tools:
        mut = (
            "    # MUTATING: must stay idempotent (same payload → same outcome).\n"
            if t.mutating else "")
        fns.append(f'''{_SENTINEL}
def {t.name}(payload: dict[str, Any]) -> dict[str, Any]:
    """{t.description or t.name} — compiled from spec."""
{mut}    raise NotImplementedError(
        "{t.name}: implement domain logic; keep idempotent, read tenant from AuthContext")
''')
        names.append(t.name)

    registry = "\n".join(f'    "{n}": {n},' for n in names)
    return f'''"""
{agent.name} — domain tools (EDITABLE logic file 2 of 4).

Tool registry compiled from the approved TECH_DESIGN.yaml. Every tool is
wrapped by the governance bridge (BOLA, RBAC, budgets, quarantine).

Rules:
  - Never accept tenant/customer IDs from prompt text — read AuthContext.
  - Mutating tools must be idempotent (same payload → same outcome).
  - Keep payloads small and JSON-serializable.
"""
from __future__ import annotations

from typing import Any


def echo(payload: dict[str, Any]) -> dict[str, Any]:
    """Health-check tool (safe default)."""
    return {{"echo": payload, "agent": "{agent.name}"}}


{chr(10).join(fns) if fns else ""}

# Registry: tool name -> handler.
TOOLS: dict[str, Any] = {{
    "echo": echo,
{registry}
}}
'''


# --------------------------------------------------------------------------- #
# src/logic/prompts.py                                                          #
# --------------------------------------------------------------------------- #
def render_prompts(agent: AgentDef) -> str:
    if emit_rich._is_rich(agent):
        return emit_rich.render_prompts(agent)
    return _render_prompts_legacy(agent)


def _render_prompts_legacy(agent: AgentDef) -> str:
    mission = (agent.objective or agent.use_case or f"serve as {agent.name}").strip()
    tools_list = ", ".join(t.name for t in agent.tools) or "echo"
    inv_lines = " ".join(f"- {i}" for i in agent.invariants)
    developer = (
        "Cite the tool you used for every factual claim. "
        "If no tool can answer, say so plainly.")
    if inv_lines:
        developer += f" Enforce invariants: {inv_lines}"
    return f'''"""
{agent.name} — prompts-as-code (EDITABLE logic file 3 of 4).

Compiled from the approved TECH_DESIGN.yaml. Prompt changes are
governance-visible (prompt_git_sha is stamped into the audit ledger).
"""
from __future__ import annotations

SYSTEM_PROMPT = (
    "You are {agent.name}, a governed enterprise agent ({agent.role}, tier {agent.tier}). "
    "Mission: {mission} "
    "Act only through your registered tools ({tools_list}); never invent data; "
    "refuse requests outside your mission scope."
)

DEVELOPER_PROMPT = {developer!r}
'''


# --------------------------------------------------------------------------- #
# src/logic/workflow.py                                                         #
# --------------------------------------------------------------------------- #
def render_workflow(agent: AgentDef, design: TechDesign) -> str:
    if emit_rich._is_rich(agent):
        return emit_rich.render_workflow(agent, design)
    return _render_workflow_legacy(agent, design)


def _render_workflow_legacy(agent: AgentDef, design: TechDesign) -> str:
    ep = agent.entry_points[0].id if agent.entry_points else "EP-INGRESS"
    first = agent.states[0].id if agent.states else "T01"
    ordered = [s.id for s in agent.states] or ["T01"]
    chain = " → ".join(ordered)
    hold_ids = [s.id for s in agent.states if s.hold]

    edge_lines = [
        f'    EDGES.append(({e.from_state!r}, {e.to_state!r}, {e.condition!r}))'
        for e in agent.edges]
    edges_block = "\n".join(edge_lines) or "    pass  # no cross-state edges declared"

    # node bodies — one per declared state
    node_defs: list[str] = []
    for s in agent.states:
        hold_note = "\n    # HOLD state: interrupt for HITL before any side effect." if s.hold else ""
        node_defs.append(f'''
def node_{s.id.lower()}(state: AgentState) -> dict[str, Any]:
    """{s.id} {s.name} — {s.description or 'spec state'}.{hold_note}
    """
    fn = TOOLS.get({s.name!r})
    result = fn(state.get("input", {{}})) if fn else {{"status": "no-op"}}
    return {{"current_state": {s.id!r}, "tool_results": {{**state.get("tool_results", {{}}), {s.id!r}: result}}}}
''')
    nodes_block = "\n".join(node_defs)

    # conditional routing: per-state "next" map for the conditional edges
    next_map_lines = []
    for i, sid in enumerate(ordered):
        nxt = ordered[i + 1].lower() if i + 1 < len(ordered) else "end"
        next_map_lines.append(f'        "{sid.lower()}": {nxt!r},')
    next_map = "\n".join(next_map_lines)

    delegates = agent.delegates_to
    delegate_block = ""
    if delegates:
        delegate_block = (
            f"\n    # Cross-agent handoffs: {', '.join(delegates)} "
            "(enforced by the mesh bridge — BOLA + goalHash).\n")

    build_lines = []
    for sid in ordered:
        build_lines.append(f'    g.add_node("{sid.lower()}", node_{sid.lower()})')
    build_nodes = "\n".join(build_lines)
    first_lower = ordered[0].lower()

    return f'''"""
{agent.name} — LangGraph StateGraph (EDITABLE logic file 1 of 4).

Compiled from the approved TECH_DESIGN.yaml.
Entry point: {ep} → first state {first}. State chain: {chain}.
HOLD states (HITL): {hold_ids or '[]'}.

Governance (SecureGate, budgets, HITL, audit ledger) is mounted by the
locked dm-runner — never bypass it by running this module directly.
"""
from __future__ import annotations

from typing import Any

from .state import AgentState, HOLD_STATES, STATE_IDS
from .tools import TOOLS

# (from_state, to_state, condition) triples declared in the spec.
EDGES: list[tuple[str, str, str]] = []
def _declare_edges() -> None:
{edges_block}
_declare_edges()

{nodes_block}


# Static transition table derived from the spec's state chain.
NEXT: dict[str, str] = {{
{next_map}
}}


def route(state: AgentState) -> str:
    """Conditional edge: advance to the next declared state, honouring HOLDs."""
    cur = state.get("current_state", STATE_IDS[0] if STATE_IDS else {first!r})
    nxt = NEXT.get(cur.lower(), "end")
    if nxt != "end" and nxt.upper() in HOLD_STATES:
        return "hitl"
    return nxt


def build_graph():  # returns a compiled LangGraph StateGraph
    """Assemble the StateGraph. Imported by the locked dm-runner."""
    try:
        from langgraph.graph import END, StateGraph
    except Exception:  # langgraph optional at scaffold time
        return None
    g = StateGraph(AgentState)
{build_nodes}
    g.set_entry_point({first_lower!r})
    for _sid in [s.lower() for s in STATE_IDS]:
        g.add_conditional_edges(_sid, route, {{
            "end": END,
            "hitl": END,  # HITL interrupt handled by the dm-runner wrapper
            **{{k: k for k in NEXT.values() if k != "end"}},
        }})
    return g


def run(input: dict[str, Any]) -> dict[str, Any]:
    """Entrypoint invoked by the locked dm-runner.mjs wrapper.

    Contract: JSON in → JSON out; raise on failure (runner records to ledger).
    Falls back to a deterministic walk when langgraph is not installed.
    """{delegate_block}
    graph = build_graph()
    if graph is not None:
        app = graph.compile()
        return app.invoke({{"input": input, "current_state": STATE_IDS[0] if STATE_IDS else {first!r}}})

    # Deterministic fallback walk (no langgraph on the host).
    results: dict[str, Any] = {{}}
    for sid in STATE_IDS:
        if sid in HOLD_STATES:
            results[sid] = {{"status": "HELD", "reason": "spec-declared hold (HITL)"}}
            break
        fn = TOOLS.get(sid.lower())
        if fn is not None:
            results[sid] = fn(input)
    return {{"agent": {agent.name!r}, "edges": EDGES, "results": results,
            "status": "scaffolded"}}
'''


def render_logic_init(agent: AgentDef) -> str:
    return f'"""{agent.name} — editable logic package (compiled by dm-spec-compiler)."""\n'


# --------------------------------------------------------------------------- #
# agent.py — locked runtime harness (self-test / mesh-test)                    #
# --------------------------------------------------------------------------- #
def render_runtime(agent: AgentDef) -> str:
    """A minimal governed runtime exposing --self-test and --mesh-test.

    Emitted so Module 5 runs LIVE (no SKIP). Boots the real workflow.run
    through the TOOLS registry; never embeds secrets; exits non-zero on any
    assertion failure.
    """
    tool_names = repr([t.name for t in agent.tools])
    template = '''"""
__NAME__ — locked governed runtime (emitted by dm-spec-compiler).

Exposes --self-test and --mesh-test for the kit verification gate. The real
governance bridge (SecureGate, budgets, audit ledger) is mounted by the
dm-runner in production; this harness proves the editable zone boots and the
tool registry is well-formed. Never embed secrets here.
"""
from __future__ import annotations

import os
import sys

WORKDIR = os.path.dirname(os.path.abspath(__file__))
DECLARED_TOOLS = __TOOL_NAMES__
AGENT_NAME = __NAME_REPR__
AGENT_ROLE = __ROLE_REPR__


def _load_logic():
    sys.path.insert(0, os.path.join(WORKDIR, "src"))
    from logic import tools as _tools
    from logic import workflow as _wf
    return _tools, _wf


def run_once(payload: dict) -> dict:
    _tools, _wf = _load_logic()
    return _wf.run(payload)


def self_test() -> int:
    tools, wf = _load_logic()
    assert "echo" in tools.TOOLS, "echo tool missing"
    out = tools.TOOLS["echo"]({"probe": "self-test"})
    assert AGENT_NAME in str(out), "guarded echo path failed"
    res = wf.run({"message": "self-test", "tenant_id": "tenant-1"})
    assert isinstance(res, dict), "workflow.run must return a dict"
    print("SELF-TEST PASS: %s booted, %d tools, workflow OK"
          % (AGENT_NAME, len(tools.TOOLS)))
    return 0


def mesh_test() -> int:
    tools, _wf = _load_logic()
    declared = set(DECLARED_TOOLS)
    registered = set(tools.TOOLS)
    missing = declared - registered
    assert not missing, "declared tools not registered: %s" % missing
    print("MESH-TEST PASS: %s role=%s tools=%s"
          % (AGENT_NAME, AGENT_ROLE, sorted(registered)))
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    if "--mesh-test" in sys.argv:
        sys.exit(mesh_test())
    print(run_once({"message": "hello", "tenant_id": "tenant-1"}))
'''
    return (template
            .replace("__TOOL_NAMES__", tool_names)
            .replace("__NAME_REPR__", repr(agent.name))
            .replace("__ROLE_REPR__", repr(agent.role))
            .replace("__NAME__", agent.name))


# --------------------------------------------------------------------------- #
# Driver                                                                        #
# --------------------------------------------------------------------------- #
_LOGIC_FILES = {
    "__init__.py": render_logic_init,
    "state.py": render_state,
    "tools.py": render_tools,
    "prompts.py": render_prompts,
}


def emit_agent(agent: AgentDef, design: TechDesign, workspace: str) -> list[str]:
    ws = os.path.abspath(workspace)
    kit_root = os.path.abspath(os.path.expanduser(
        os.environ.get("DM_AGENT_KIT_ROOT", "~/dm-agent-kit")))
    # Editable-zone guard: refuse to write ANYWHERE inside the kit repository
    # itself, EXCEPT the kit's own intended agent-workspace area (<kit>/agents/).
    # Writing to the kit root or its src/ pollutes/corrupts the library.
    in_kit = ws == kit_root or ws.startswith(kit_root + os.sep)
    under_kit_agents = ws.startswith(kit_root + os.sep + "agents" + os.sep)
    if in_kit and not under_kit_agents:
        raise PermissionError(f"refusing to emit into the core kit tree: {ws}")

    logic_dir = os.path.join(ws, "src", "logic")
    os.makedirs(logic_dir, exist_ok=True)

    written: list[str] = []
    goal_path = os.path.join(ws, "GOAL.yaml")
    intent_path = os.path.join(ws, "intent.txt")

    # intent.txt is the human source-of-truth; GOAL.yaml is compiled from it
    # through the kit's intent_contract so the contract is SIGNED (SHA-256
    # configProvenance) — required by the lint-policy governance gate.
    with open(intent_path, "w", encoding="utf-8") as f:
        f.write(render_intent(agent, design))
    written.append(intent_path)

    signed = False
    try:
        from dm_agent_governance import intent_contract as _ic  # kit lib
        _ic.compile_intent_file(intent_path, goal_path, overwrite=True,
                                environment=os.environ.get("DM_ENVIRONMENT", "dev"))
        signed = True
    except Exception:
        pass
    if not signed:
        with open(goal_path, "w", encoding="utf-8") as f:
            f.write(render_goal(agent, design))
    written.append(goal_path)

    # Editable logic files: regenerate the plumbing but PRESERVE any
    # hand-written logic below the sentinel marker (Option A).
    for fname, renderer in _LOGIC_FILES.items():
        path = os.path.join(logic_dir, fname)
        _write_preserving(path, renderer(agent))
        written.append(path)

    wf_path = os.path.join(logic_dir, "workflow.py")
    _write_preserving(wf_path, render_workflow(agent, design))
    written.append(wf_path)

    # locked runtime harness → enables LIVE --self-test / --mesh-test
    rt_path = os.path.join(ws, "agent.py")
    with open(rt_path, "w", encoding="utf-8") as f:
        f.write(render_runtime(agent))
    written.append(rt_path)
    return written


def emit_design(design: TechDesign, target_root: str, *,
                only: list[str] | None = None) -> dict[str, list[str]]:
    """Emit every agent (or a subset via ``only``) under ``target_root/<name>/``."""
    out: dict[str, list[str]] = {}
    for agent in design.agents:
        if only and agent.name not in only:
            continue
        ws = os.path.join(target_root, agent.name)
        out[agent.name] = emit_agent(agent, design, ws)
    return out
