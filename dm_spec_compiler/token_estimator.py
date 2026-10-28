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
        # tool-schema overhead: the full tool-schema JSON is re-sent on every
        # step's model call — surface its per-step multiplier explicitly.
        schema_overhead = _tok(" ".join(
            f"{t.name} {t.description}" for t in agent.tools)) if not getattr(s, "hold", False) else 0
        rows.append({
            "node": f"{s.id} {s.name}",
            "kind": "hold" if getattr(s, "hold", False) else "state",
            "prompt_tokens": base + _tok(dev_note),
            "tool_tokens": tool_io if not getattr(s, "hold", False) else 0,
            "tool_schema_overhead": schema_overhead,
            "est_tokens": max(1, total),
        })
    return rows


def estimate_tokens(design: TechDesign, dsh_log_path: str | None = None) -> dict:
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
    dsh = parse_dsh_log(dsh_log_path) if dsh_log_path else None
    return {
        "build_tokens": total_build,
        "expected_run_tokens": expected,
        "max_loop_tokens": maxloop,
        "cost_per_1000_runs": per_1k,
        "agents": agents,
        "dsh_runtime": dsh,
        "price_book": PRICE_BOOK,
        "model_note": "~4 chars/token; 60/40 in/out split; max-loop = every node fans out once.",
    }

# --------------------------------------------------------------------------- #
# DSH session-log adapter (optional runtime telemetry ingestion)              #
# --------------------------------------------------------------------------- #
# The static estimate above is design-time (AST/topology). When dsh session /
# step logs are present we ALSO surface *observed* runtime tokens. Scoping rule
# to prevent double-counting:
#   - per-function / per-node breakdown  -> STEP + MODEL spans only
#   - turn / session totals              -> parent AGENT spans only
# A parent AGENT span in dsh repeats the SUM of its child MODEL/STEP spans, so
# summing both layers would double-count. We therefore keep the two strictly
# separate and never add AGENT totals into the per-node figures.
import json as _json
import os as _os


def _span_kind(rec: dict) -> str:
    return str(rec.get("gen_ai.span.kind") or rec.get("span.kind")
               or rec.get("span_kind") or rec.get("kind") or "").upper()


def _span_tokens(rec: dict) -> int:
    for k in ("gen_ai.usage.total_tokens", "total_tokens", "tokens",
              "gen_ai.usage.completion_tokens"):
        v = rec.get(k)
        if isinstance(v, (int, float)) and v:
            return int(v)
    pt = rec.get("prompt_tokens") or rec.get("gen_ai.usage.prompt_tokens") or 0
    ct = rec.get("completion_tokens") or 0
    return int(pt) + int(ct)


def _tool_defs_overhead(rec: dict) -> int:
    """gen_ai.tool.definitions: tool schemas re-sent on every MODEL call. The
    per-step multiplier across a multi-step turn is `definitions` (count) —
    we surface it so the table can show the repeated schema cost."""
    v = rec.get("gen_ai.tool.definitions")
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, list):
        return len(v)
    return 0


def parse_dsh_log(path: str) -> dict | None:
    """Parse a dsh session/step log (JSONL or JSON array). Returns a scoped
    summary or None if the file has no recognizable dsh spans. Deterministic."""
    if not _os.path.exists(path):
        return None
    records: list[dict] = []
    try:
        text = open(path, encoding="utf-8").read().strip()
        if not text:
            return None
        if text.startswith("["):
            records = [r for r in _json.loads(text) if isinstance(r, dict)]
        else:
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    try:
                        records.append(_json.loads(line))
                    except Exception:
                        pass
    except Exception:
        return None
    if not records:
        return None

    step_rows: list[dict] = []
    agent_turns: dict[str, int] = {}
    sessions: set[str] = set()
    for rec in records:
        sid = str(rec.get("dsh.session.id") or rec.get("session_id")
                  or rec.get("sessionId") or rec.get("trace_id") or "")
        if sid:
            sessions.add(sid)
        kind = _span_kind(rec)
        toks = _span_tokens(rec)
        if kind in ("AGENT",):
            # parent turn total — kept OUT of per-node to avoid double counting
            agent_turns[sid or "?"] = agent_turns.get(sid or "?", 0) + toks
        elif kind in ("STEP", "MODEL", "") and toks:
            # per-function breakdown (STEP/MODEL spans; '' = legacy token_usage rows)
            step_rows.append({
                "node": str(rec.get("tool") or rec.get("gen_ai.operation.name")
                              or rec.get("name") or rec.get("step") or "model-call"),
                "kind": kind.lower() or "model",
                "span_tokens": toks,
                "tool_definitions": _tool_defs_overhead(rec),
                "session_id": sid,
            })
    if not step_rows and not agent_turns:
        return None
    return {
        "step_rows": step_rows,
        "agent_turn_tokens": agent_turns,
        "observed_step_tokens": sum(r["span_tokens"] for r in step_rows),
        "observed_turn_tokens": sum(agent_turns.values()) if agent_turns else None,
        "sessions": sorted(sessions),
        "source": _os.path.basename(path),
        "note": ("per-node = STEP/MODEL spans; turn totals = AGENT spans only "
                 "(never summed together — avoids double-counting)."),
    }

