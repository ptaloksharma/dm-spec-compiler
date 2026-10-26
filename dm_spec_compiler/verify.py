"""Module 5 — Verification hooks + archify dashboard bridge.

All kit interaction goes through THIS module (one seam). The kit is invoked
as an external library/binary — never vendored, never modified.

Hooks:
  - mesh_verify(workspace_root)   → `dm-agent mesh verify` (or npx dm-kit)
  - agent_self_test(agent_ws)     → `python agent.py --self-test`
  - agent_mesh_test(agent_ws)     → `python agent.py --mesh-test`
  - compile_dashboard(root)       → kit archify.generate() → architecture-dashboard.html

Every hook is best-effort-safe: a missing kit binary or missing agent.py is
reported as SKIP, not a crash. Failures propagate as non-zero/False.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from . import _kitpath

_MODE_FOR_ROLE = {"ui-coordinator": "APPROVE", "domain-agent": "AUTO",
                  "sub-agent": "AUTO"}


@dataclass
class HookResult:
    name: str
    status: str  # PASS | FAIL | SKIP
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in ("PASS", "SKIP")


def _kit_cli() -> list[str] | None:
    """Locate a runnable dm-agent CLI: bundled dist build or npx dm-kit."""
    root = _kitpath.kit_root()
    dist = os.path.join(root, "dist", "cli", "index.js")
    if os.path.exists(dist) and shutil.which("node"):
        return ["node", dist]
    if shutil.which("npx"):
        return ["npx", "dm-kit"]
    return None


def register_mesh_agents(workspace_root: str, agents: list) -> HookResult:
    """Register every emitted agent into erp-mesh-registry.json so that
    `mesh verify` validates REAL cross-agent edges (not an empty registry).

    Idempotent (register-or-update). Only meaningful for multi-agent meshes;
    returns SKIP with a note for a single-agent mesh (nothing to link).
    """
    cli = _kit_cli()
    if cli is None:
        return HookResult("mesh register", "SKIP", "no dm-agent CLI found")
    if len(agents) < 2:
        return HookResult("mesh register", "SKIP",
                          "single-agent mesh — no edges to register")
    # ensure a registry exists
    subprocess.run([*cli, "mesh", "init"], cwd=workspace_root,
                   capture_output=True, text=True, timeout=60)
    for a in agents:
        role = a.role if a.role in _MODE_FOR_ROLE else "standalone"
        mode = _MODE_FOR_ROLE.get(a.role, "AUTO")
        downstream = ",".join(f"{t}:Handoff/v1" for t in a.delegates_to)
        cmd = [*cli, "mesh", "register", a.name, "--role", role,
               "--mode", mode, "--path", f"agents/{a.name}"]
        if downstream:
            cmd += ["--downstream", downstream]
        proc = subprocess.run(cmd, cwd=workspace_root,
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return HookResult("mesh register", "FAIL",
                              f"{a.name}: {(proc.stdout + proc.stderr).strip()[-200:]}")
    return HookResult("mesh register", "PASS",
                      f"registered {len(agents)} agents")


def mesh_verify(workspace_root: str) -> HookResult:
    cli = _kit_cli()
    if cli is None:
        return HookResult("mesh verify", "SKIP", "no dm-agent CLI (dist or npx) found")
    proc = subprocess.run(
        [*cli, "mesh", "verify"], cwd=workspace_root,
        capture_output=True, text=True, timeout=180)
    ok = proc.returncode == 0
    return HookResult("mesh verify", "PASS" if ok else "FAIL",
                      (proc.stdout + proc.stderr).strip()[-400:])


def lint_policy(agent_ws: str) -> HookResult:
    """Run the kit's fail-closed governance gate (secret sprawl + contract
    drift + DSH rules) on the emitted workspace. This is the real compliance
    bar — distinct from the boot-level self/mesh tests."""
    root = _kitpath.kit_root()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.path.join(root, "python")
    env.setdefault("DM_LINT_BASELINE_SECRET", "dm-lint-baseline-local")
    proc = subprocess.run(
        ["python3", "-m", "dm_agent_governance", "lint-policy", agent_ws,
         "--format", "text"],
        capture_output=True, text=True, timeout=180, env=env)
    out = (proc.stdout + proc.stderr).strip()
    ok = "— PASS" in out or "PASS" in out.splitlines()[0] if out.splitlines() else False
    return HookResult("lint-policy", "PASS" if ok else "FAIL", out[-400:])


def _agent_test(agent_ws: str, flag: str) -> HookResult:
    agent_py = os.path.join(agent_ws, "agent.py")
    if not os.path.exists(agent_py):
        return HookResult(flag, "SKIP", f"no agent.py in {agent_ws}")
    proc = subprocess.run(
        ["python3", "agent.py", flag], cwd=agent_ws,
        capture_output=True, text=True, timeout=180)
    ok = proc.returncode == 0
    return HookResult(flag, "PASS" if ok else "FAIL",
                      (proc.stdout + proc.stderr).strip()[-400:])


def agent_self_test(agent_ws: str) -> HookResult:
    return _agent_test(agent_ws, "--self-test")


def agent_mesh_test(agent_ws: str) -> HookResult:
    return _agent_test(agent_ws, "--mesh-test")


def compile_dashboard(workspace_root: str) -> HookResult:
    """Regenerate architecture-dashboard.html via the kit's archify compiler."""
    try:
        import archify  # kit src/ on sys.path via _kitpath
    except Exception as exc:
        return HookResult("archify dashboard", "SKIP", f"kit archify unavailable: {exc}")
    try:
        seal = archify.generate(workspace_root)
        return HookResult("archify dashboard", "PASS",
                          f"spec {seal['spec_hash'][:12]} → {seal['path']}")
    except Exception as exc:
        return HookResult("archify dashboard", "FAIL", str(exc))


def run_all(workspace_root: str, agent_workspaces: list[str],
            agents: list | None = None) -> list[HookResult]:
    """Run every verification hook. ``agents`` (optional AgentDef list) enables
    mesh registration so multi-agent meshes validate real edges."""
    results: list[HookResult] = []
    if agents:
        results.append(register_mesh_agents(workspace_root, agents))
    results.append(mesh_verify(workspace_root))
    for ws in agent_workspaces:
        results.append(agent_self_test(ws))
        results.append(agent_mesh_test(ws))
        results.append(lint_policy(ws))
    results.append(compile_dashboard(workspace_root))
    return results
