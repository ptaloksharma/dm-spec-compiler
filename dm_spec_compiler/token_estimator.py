"""Deterministic token & cost estimation for the emitted agent (Token Economics).

NO LLM — pure structural analysis of the TechDesign + the emitted logic files
it drives (prompts.py, tools.py, state nodes). Estimates are heuristic but
reproducible: same design → same numbers, so a refine diff is visible.

Rough model (documented, tunable):
  - ~4 chars ≈ 1 token (OpenAI-ish heuristic).
  - Each declared state ⇒ one graph node invocation per run.
  - Each node emits the SYSTEM prompt + a per-state developer note + tool I/O.
  - A HOLD state interrupts (HITL) — counted as a paused node (no tool side effect).
  - "Max loop" = every node visits every other node once (worst case fan-out).
"""
from __future__ import annotations

from .model import TechDesign

# price book (USD per 1K tokens), illustrative defaults
PRICE_BOOK = {
    "deepseek": {"input": 0.00014, "output": 0.00028},   # DeepSeek-chat ~cheap
    "frontier": {"input": 0.003, "output": 0.015},       # frontier baseline
}


def _tok(text: str) -> int:
    """~4 chars per token, floor 1 for non-empty."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _node_tokens(agent) -> list[dict]:
    """Per-state (graph node) estimated tokens for ONE invocation."""
    rows = []
    sys_prompt = (
        f"You are {agent.name}, a governed enterprise agent ({agent.role}, "
        f"tier {agent.tier}). Mission: {agent.objective or agent.use_case or agent.name}. "
        f"Act only through your registered tools."
    )
    base = _tok(sys_prompt)
    for s in agent.states:
        dev_note = f"State {s.id} {s.name}: {s.description or 'spec state'}."
        # the tool bound to this state's name (workflow looks it up by state name)
        tool = next((t for t in agent.tools if t.name == s.name), None)
        tool_io = _tok(f"{tool.name} {tool.description}" if tool else "") + 24  # +io envelope
        hold_pause = 0 if not getattr(s, "hold", False) else -8  # held nodes skip tool call
        total = base + _tok(dev_note) + tool_io + (hold_pause if hold_pause < 0 else 0)
        rows.append({
            "node": f"{s.id} {s.name}",
            "kind": "hold" if getattr(s, "hold", False) else "state",
            "prompt_tokens": base + _tok(dev_note),
            "tool_tokens": tool_io if not getattr(s, "hold", False) else 0,
            "est_tokens": max(1, total),
        })
    return rows


def estimate_tokens(design: TechDesign) -> dict:
    """Return the full Token Economics payload for the dashboard."""
    agents = []
    total_build = 0
    for agent in design.agents:
        per_node = _node_tokens(agent)
        expected_run = sum(r["est_tokens"] for r in per_node) or 1
        n = len(per_node) or 1
        max_loop = expected_run * n  # worst-case every node hits every node
        # Build/refine tokens: the design YAML + a nominal refine iteration.
        build = _tok(design.to_yaml()) + _tok(" ".join(
            f"{a.name} {a.objective or ''} {a.use_case or ''}" for a in design.agents))
        total_build += build
        agents.append({
            "agent": agent.name,
            "role": agent.role,
            "tier": agent.tier,
            "build_tokens": build,
            "expected_run_tokens": expected_run,
            "max_loop_tokens": max_loop,
            "per_node": per_node,
            "tools": len(agent.tools),
            "states": len(agent.states),
            "entry_points": len(agent.entry_points),
        })

    def cost(tokens: int, model: str) -> float:
        pb = PRICE_BOOK[model]
        # assume 60% input / 40% output split
        return round((tokens * 0.6 / 1000 * pb["input"]) + (tokens * 0.4 / 1000 * pb["output"]), 4)

    expected = sum(a["expected_run_tokens"] for a in agents) or 1
    maxloop = sum(a["max_loop_tokens"] for a in agents) or 1
    per_1k = {
        "deepseek": {"expected": cost(expected * 1000, "deepseek"),
                     "max_loop": cost(maxloop * 1000, "deepseek")},
        "frontier": {"expected": cost(expected * 1000, "frontier"),
                     "max_loop": cost(maxloop * 1000, "frontier")},
    }
    return {
        "build_tokens": total_build,
        "expected_run_tokens": expected,
        "max_loop_tokens": maxloop,
        "cost_per_1000_runs": per_1k,
        "agents": agents,
        "price_book": PRICE_BOOK,
        "model_note": "~4 chars/token; 60/40 in/out split; max-loop = every node fans out once.",
    }
