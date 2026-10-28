"""Structured pipeline event ring buffer (System Logs & Alerts, Tab 4).

A tiny in-memory + optional file-backed ring of pipeline events so the Buddy UI
can render under-the-hood telemetry: which stage ran, when, and why (incl.
guardrail blocks and SHA-stamp invalidations). Deterministic, no external deps.

Channels: WIZARD, ARCHIFY, REFINE, STAMP, PROVISION, EMIT, GUARDRAIL, VERIFY.
"""
from __future__ import annotations

import json
import os
import time

_RING_MAX = 200
_ring: list[dict] = []

# File persistence (JSONL). Each spec API call runs in a fresh process, so the
# in-memory ring alone loses history between stages. Default to a workspace log
# (overridable via DM_SPEC_EVENTS_LOG) so events persist across processes.
_LOG_PATH = os.environ.get("DM_SPEC_EVENTS_LOG") or os.path.join(
    os.environ.get("DM_WORKSPACE_ROOT", os.getcwd()), ".dm", "spec", "events.jsonl")


def _load_persisted() -> None:
    """Hydrate the ring from the JSONL log (best-effort, capped)."""
    if not _LOG_PATH or not os.path.exists(_LOG_PATH):
        return
    try:
        lines = open(_LOG_PATH, encoding="utf-8").read().splitlines()[-_RING_MAX:]
        for ln in lines:
            if ln.strip():
                try:
                    _ring.append(json.loads(ln))
                except Exception:
                    pass
    except Exception:
        pass


_hydrated = False


def emit_event(channel: str, message: str, *, level: str = "info",
               detail: dict | None = None) -> dict:
    """Append a structured event to the ring (and JSONL log if configured)."""
    evt = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "channel": channel.upper(),
        "level": level,            # info | warn | block
        "message": message,
        "detail": detail or {},
    }
    _ring.append(evt)
    if len(_ring) > _RING_MAX:
        del _ring[: len(_ring) - _RING_MAX]
    if _LOG_PATH:
        try:
            os.makedirs(os.path.dirname(_LOG_PATH) or ".", exist_ok=True)
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(evt) + "\n")
        except Exception:
            pass
    return evt


def recent(limit: int = 100, channel: str | None = None) -> list[dict]:
    """Most-recent-first events, optionally filtered by channel."""
    global _hydrated
    if not _hydrated:
        _hydrated = True
        _load_persisted()
    evts = list(reversed(_ring))
    if channel:
        ch = channel.upper()
        evts = [e for e in evts if e["channel"] == ch]
    return evts[:limit]


def unread_alert_count() -> int:
    """Count of warn/block events (drives the header notification bell)."""
    global _hydrated
    if not _hydrated:
        _hydrated = True
        _load_persisted()
    return sum(1 for e in _ring if e["level"] in ("warn", "block"))

# --------------------------------------------------------------------------- #
# DSH runtime log correlation (Tab 4: unified stream)                          #
# --------------------------------------------------------------------------- #
# Ingest dsh runtime interception events (tool calls, pre/post policy gates,
# approval holds, subagent spawns) and normalize them into our channel schema,
# correlating parent + subagent traces via the shared dsh.session.* id so a
# multi-agent execution renders as ONE ordered stream.
import json as _json
import os as _os

_DSH_KIND_CHANNEL = {
    "tool_call": "DSH-TOOL",
    "tool_invocation": "DSH-TOOL",
    "policy_gate": "DSH-GATE",
    "pre_execution_gate": "DSH-GATE",
    "post_execution_gate": "DSH-GATE",
    "approval_hold": "DSH-HOLD",
    "hitl_hold": "DSH-HOLD",
    "subagent_spawn": "DSH-AGENT",
    "agent_spawn": "DSH-AGENT",
}


def ingest_dsh_runtime(path: str) -> int:
    """Parse a dsh runtime log (JSONL/JSON array) and append normalized events
    to the ring. Returns the number of events ingested. Deterministic, tolerant
    of unknown shapes (skipped)."""
    if not _os.path.exists(path):
        return 0
    try:
        text = open(path, encoding="utf-8").read().strip()
    except Exception:
        return 0
    if not text:
        return 0
    records = []
    try:
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
        return 0

    count = 0
    for rec in records:
        etype = str(rec.get("event_type") or rec.get("type") or rec.get("kind") or "").lower()
        channel = _DSH_KIND_CHANNEL.get(etype)
        if not channel:
            # generic dsh event — bucket under DSH
            channel = "DSH"
        session = str(rec.get("dsh.session.id") or rec.get("session_id")
                      or rec.get("trace_id") or "")
        parent = str(rec.get("dsh.session.parent") or rec.get("parent_session_id")
                     or rec.get("parent") or "")
        tool = rec.get("tool") or rec.get("gen_ai.operation.name") or rec.get("name") or ""
        decision = str(rec.get("decision") or rec.get("verdict") or "").upper()
        level = "block" if decision in ("BLOCK", "DENY") else ("warn" if decision in ("HOLD", "SUSPEND") else "info")
        msg = rec.get("message") or (
            f"{etype or 'event'}" + (f" {tool}" if tool else "") +
            (f" [{decision}]" if decision else ""))
        emit_event(channel, str(msg), level=level,
                   detail={"session_id": session, "parent_session": parent,
                           "tool": tool, "decision": decision})
        count += 1
    return count


def unified_stream(limit: int = 100, dsh_log_path: str | None = None) -> list[dict]:
    """The compiler SDLC events + (optionally) dsh runtime events, merged and
    sorted by timestamp so parent/subagent traces render as one stream."""
    if dsh_log_path:
        ingest_dsh_runtime(dsh_log_path)
    return recent(limit=limit)

