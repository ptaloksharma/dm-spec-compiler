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
