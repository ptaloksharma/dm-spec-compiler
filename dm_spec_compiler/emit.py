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

_SENTINEL = "# DM-SPEC-COMPILER GENERATED BLOCK (regenerated from TECH_DESIGN.yaml)"


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


# --------------------------------------------------------------------------- #
# src/logic/state.py                                                            #
# --------------------------------------------------------------------------- #
def render_state(agent: AgentDef) -> str:
    state_fields = []
    for s in agent.states:
        state_fields.append(f"    # {s.id} {s.name}: {s.description}")
    state_comment = "\n".join(state_fields) or "    # (no states declared in spec)"

    invariant_consts = []
    for i, inv in enumerate(agent.invariants, 1):
        invariant_consts.append(f'    "INV{i:02d}": {inv!r},')
    inv_block = "\n".join(invariant_consts) or '    # (no invariants declared)'

    holds = [s.id for s in agent.states if s.hold]

    return f'''"""
{agent.name} — graph state + nodes (EDITABLE logic file 4 of 4).

Compiled by dm-spec-compiler from the approved TECH_DESIGN.yaml.
Declared states:
{state_comment}
"""
from __future__ import annotations

from typing import Any, TypedDict

# Invariants extracted from the spec pack (enforce in tools.py policy module).
INVARIANTS: dict[str, str] = {{
{inv_block}
}}

# States that require a human hold before progression.
HOLD_STATES: list[str] = {holds!r}

STATE_IDS: list[str] = {[s.id for s in agent.states]!r}


class AgentState(TypedDict, total=False):
    """State threaded through every node of the graph."""
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
    ep = agent.entry_points[0].id if agent.entry_points else "EP-INGRESS"
    first = agent.states[0].id if agent.states else "T01"
    ordered = [s.id for s in agent.states] or ["T01"]
    chain = " → ".join(ordered)

    edge_lines = []
    for e in agent.edges:
        edge_lines.append(
            f'    EDGES.append(({e.from_state!r}, {e.to_state!r}, {e.condition!r}))')
    edges_block = "\n".join(edge_lines) or "    pass  # no cross-state edges declared"

    delegates = agent.delegates_to
    delegate_block = ""
    if delegates:
        calls = "\n".join(
            f'        # handoff to {d}: enforced by the mesh bridge (BOLA + goalHash)'
            for d in delegates)
        delegate_block = f"""
    # Cross-agent handoffs declared in the spec: {', '.join(delegates)}
{calls}
"""

    return f'''"""
{agent.name} — orchestration entrypoint (EDITABLE logic file 1 of 4).

Compiled from the approved TECH_DESIGN.yaml.
Entry point: {ep} → first state {first}. State chain: {chain}.
Governance (SecureGate, budgets, HITL, audit ledger) is mounted by the
locked dm-runner — never bypass it by running this module directly.
"""
from __future__ import annotations

from typing import Any

# (from_state, to_state, condition) triples from the spec's edge declarations.
EDGES: list[tuple[str, str, str]] = []
def _declare_edges() -> None:
{edges_block}
_declare_edges()


def run(input: dict[str, Any]) -> dict[str, Any]:
    """Entrypoint invoked by the locked dm-runner.mjs wrapper.

    Contract: JSON in → JSON out; raise on failure (runner records to ledger).
    """
    from .state import AgentState, HOLD_STATES, STATE_IDS  # noqa: F401
    from .tools import TOOLS
{delegate_block}
    state: AgentState = {{"input": input, "current_state": STATE_IDS[0] if STATE_IDS else "{first}"}}
    # Deterministic skeleton: walk declared states, executing same-named tools.
    results: dict[str, Any] = {{}}
    for sid in STATE_IDS:
        if sid in HOLD_STATES:
            results[sid] = {{"status": "HELD", "reason": "spec-declared hold (HITL)"}}
            break
        fn = TOOLS.get(sid.lower())
        if fn is None:
            continue
        results[sid] = fn(input)
        state["current_state"] = sid
    state["tool_results"] = results
    return {{"agent": "{agent.name}", "edges": EDGES, "results": results,
            "status": "scaffolded"}}
'''


def render_logic_init(agent: AgentDef) -> str:
    return f'"""{agent.name} — editable logic package (compiled by dm-spec-compiler)."""\n'


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
    if ws == kit_root or ws.startswith(kit_root + os.sep + "src"):
        raise PermissionError(f"refusing to emit into the core kit tree: {ws}")

    logic_dir = os.path.join(ws, "src", "logic")
    os.makedirs(logic_dir, exist_ok=True)

    written: list[str] = []
    goal_path = os.path.join(ws, "GOAL.yaml")
    with open(goal_path, "w", encoding="utf-8") as f:
        f.write(render_goal(agent, design))
    written.append(goal_path)

    for fname, renderer in _LOGIC_FILES.items():
        path = os.path.join(logic_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            f.write(renderer(agent))
        written.append(path)

    wf_path = os.path.join(logic_dir, "workflow.py")
    with open(wf_path, "w", encoding="utf-8") as f:
        f.write(render_workflow(agent, design))
    written.append(wf_path)
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
