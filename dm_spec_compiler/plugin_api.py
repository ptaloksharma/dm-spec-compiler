"""
dm-spec-compiler Plugin API — programmatic JSON/dict interface for integration
into dm-agent-kit CLI and Buddy UI.

Every function returns a structured dict with:
  - status: "ok" | "error" | "blocked" | "skipped"
  - data: stage-specific payload (file paths, hashes, counts, gate results)
  - error: message if status != "ok"
  - metadata: stage metadata (timing, sha256, warnings)
"""
from __future__ import annotations

import os
import sys
import time

from . import __version__
from .archify_bridge import render_dashboard
from .canonical import write_canonical
from .design import compile_design, compile_design_rich
from .emit import emit_design
from .ingest import ingest_dir
from .htmlspec import extract_rich
from .model import TechDesign
from .provision import provision_design
from .review import is_approved, review_gate
from .verify import lint_policy, mesh_verify, register_mesh_agents, run_all

_SPEC_COMP_DIR = os.path.abspath(os.path.dirname(__file__))
_SPEC_COMP_ROOT = os.path.dirname(_SPEC_COMP_DIR)


def _normalize_paths(paths: list[str], cwd: str) -> list[str]:
    return [os.path.relpath(p, cwd) if p.startswith(cwd) else p for p in paths]


def _current_cwd() -> str:
    return os.getcwd()


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------- #
# Stage 1: Ingest
# --------------------------------------------------------------------------- #
def api_ingest(incoming: str, spec_pack: str) -> dict:
    """
    Ingest raw spec packs (HTML/MD/PDF) from `incoming` directory,
    write clean markdown to `spec_pack`, and return counts + per-file info.
    """
    t0 = time.time()
    try:
        docs = ingest_dir(incoming, spec_pack)
        rich = []
        for fname in sorted(os.listdir(incoming)):
            if fname.lower().endswith((".html", ".htm")):
                path = os.path.join(incoming, fname)
                if os.path.isfile(path):
                    try:
                        doc = ingest_dir.__module__
                        # use module-level ingest_file
                        from .ingest import ingest_file
                        d = ingest_file(path)
                        if d.raw_html:
                            from .htmlspec import extract_rich
                            r = extract_rich(fname, d.raw_html)
                            if r:
                                payload = {"file": fname, "kind": r.pop("__kind__"), **r}
                                rich.append(payload)
                    except Exception:
                        pass

        return {
            "status": "ok",
            "data": {
                "files": [
                    {
                        "source": d.source_path,
                        "dest": os.path.join(spec_pack, os.path.basename(os.path.splitext(d.source_path)[0]) + ".md"),
                        "kind": d.kind,
                        "chars": len(d.markdown),
                        "sha256": d.sha256,
                        "warnings": len(d.warnings),
                    }
                    for d in ingest_dir(incoming, spec_pack)  # re-ingest for list (cheap)
                ],
                "rich_packs": rich,
                "total_files": len(docs),
            },
            "metadata": {
                "version": __version__,
                "timestamp": _iso_now(),
                "duration_ms": int((time.time() - t0) * 1000),
            },
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# --------------------------------------------------------------------------- #
# Stage 2: Compile
# --------------------------------------------------------------------------- #
def api_compile(spec_pack: str, design: str, mesh_name: str = "spec-mesh",
                dashboard: str | None = None, incoming: str | None = None) -> dict:
    """
    Compile the spec-pack markdown into TECH_DESIGN.yaml.
    If rich HTML packs are detected in `incoming`, merges them.
    Writes canonical views (requirements.md, entities.md, entry-points.md)
    and design-time ArchiMate dashboard (if dashboard path provided).
    Returns the design object, spec hash, and artifact paths.
    """
    t0 = time.time()
    try:
        # Load spec-pack markdown
        texts = {}
        for fname in sorted(os.listdir(spec_pack)):
            if fname in {"requirements.md", "entities.md", "entry-points.md"}:
                continue
            if fname.endswith((".md", ".markdown")):
                texts[fname] = open(os.path.join(spec_pack, fname), encoding="utf-8").read()
        if not texts:
            return {"status": "error", "error": f"no markdown specs in {spec_pack}"}

        # Collect rich packs
        rich = []
        if incoming and os.path.isdir(incoming):
            for fname in sorted(os.listdir(incoming)):
                if fname.lower().endswith((".html", ".htm")):
                    path = os.path.join(incoming, fname)
                    if os.path.isfile(path):
                        try:
                            from .ingest import ingest_file
                            doc = ingest_file(path)
                            if doc.raw_html:
                                from .htmlspec import extract_rich
                                r = extract_rich(fname, doc.raw_html)
                                if r:
                                    rich.append({"file": fname, "kind": r.pop("__kind__"), **r})
                        except Exception:
                            pass

        # Compile
        if rich:
            d = compile_design_rich(texts, rich, mesh_name=mesh_name)
        else:
            d = compile_design(texts, mesh_name=mesh_name)

        # Write TECH_DESIGN.yaml
        os.makedirs(os.path.dirname(design) or ".", exist_ok=True)
        with open(design, "w", encoding="utf-8") as f:
            f.write(d.to_yaml())

        # Canonical views
        canon_paths = write_canonical(d, spec_pack)

        # Dashboard
        dash_path = dashboard or os.path.join(os.path.dirname(design), "architecture-dashboard.html")
        seal = render_dashboard(d, dash_path)

        return {
            "status": "ok",
            "data": {
                "design": d.model_dump(mode="json"),
                "design_path": design,
                "canonical_paths": canon_paths,
                "dashboard_path": seal["path"],
                "spec_hash": seal["spec_hash"],
                "html_hash": seal["html_hash"],
                "mesh_name": mesh_name,
                "agent_count": len(d.agents),
                "rich_packs": rich,
            },
            "metadata": {
                "version": __version__,
                "timestamp": _iso_now(),
                "duration_ms": int((time.time() - t0) * 1000),
            },
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# --------------------------------------------------------------------------- #
# Stage 3: Review / Approval
# --------------------------------------------------------------------------- #
def api_review_status(design: str) -> dict:
    """Check if design is already approved (stamp exists + matches sha)."""
    try:
        if not os.path.exists(design):
            return {"status": "error", "error": f"design not found: {design}"}
        return {"status": "ok", "data": {"approved": is_approved(design)}}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def api_approve(design: str, assume_yes: bool = False, dashboard: str | None = None) -> dict:
    """
    Approve the design (write sha-bound stamp). If TTY and not assume_yes,
    presents interactive review loop with dashboard link.
    """
    t0 = time.time()
    try:
        if not os.path.exists(design):
            return {"status": "error", "error": f"design not found: {design}"}
        ok = review_gate(design, assume_yes=assume_yes, dashboard_path=dashboard)
        return {
            "status": "ok" if ok else "blocked",
            "data": {"approved": ok, "design": design},
            "metadata": {"timestamp": _iso_now(), "duration_ms": int((time.time() - t0) * 1000)},
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# --------------------------------------------------------------------------- #
# Stage 4: Provision
# --------------------------------------------------------------------------- #
def api_provision(design: str, infra: str, agents: list[str] | None = None,
                  apply: bool = False) -> dict:
    """
    Provision infrastructure for approved design.
    Requires approval stamp. Writes per-agent infra/<agent>/ artifacts.
    With apply=True, executes live apply (psql / terraform) fail-closed and
    seals the receipt into each PROVISIONING.md.
    """
    t0 = time.time()
    try:
        if not os.path.exists(design):
            return {"status": "error", "error": f"design not found: {design}"}
        if not is_approved(design):
            return {"status": "blocked", "error": "design not approved — run approve first"}

        from .provision import provision_design, design_sha256, ApplyError
        d = TechDesign.from_yaml(open(design, encoding="utf-8").read())
        sha = design_sha256(design)
        try:
            out = provision_design(d, infra, design_sha=sha, only=agents, apply=apply)
        except ApplyError as e:
            return {"status": "error", "error": f"live apply failed (fail-closed): {e}"}
        return {
            "status": "ok",
            "data": {
                "infra_root": infra,
                "design_sha": sha,
                "apply": apply,
                "provisioned": {
                    name: _normalize_paths(paths, os.getcwd())
                    for name, paths in out.items()
                },
            },
            "metadata": {"timestamp": _iso_now(), "duration_ms": int((time.time() - t0) * 1000)},
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# --------------------------------------------------------------------------- #
# Stage 5: Emit
# --------------------------------------------------------------------------- #
def api_emit(design: str, target: str, agents: list[str] | None = None,
             force: bool = False) -> dict:
    """
    Emit code into target workspace.
    Requires approval stamp unless force=True.
    """
    t0 = time.time()
    try:
        if not os.path.exists(design):
            return {"status": "error", "error": f"design not found: {design}"}
        if not force and not is_approved(design):
            return {"status": "blocked", "error": "design not approved — run approve first (or force)"}

        d = TechDesign.from_yaml(open(design, encoding="utf-8").read())
        out = emit_design(d, target, only=agents)
        return {
            "status": "ok",
            "data": {
                "target_root": target,
                "emitted": {
                    name: _normalize_paths(paths, os.getcwd())
                    for name, paths in out.items()
                },
            },
            "metadata": {"timestamp": _iso_now(), "duration_ms": int((time.time() - t0) * 1000)},
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# --------------------------------------------------------------------------- #
# Stage 6: Verify
# --------------------------------------------------------------------------- #
def api_verify(workspace: str, design: str | None = None) -> dict:
    """
    Run the full verification suite on an emitted workspace.
    Includes: mesh register (multi-agent), mesh verify, lint-policy per agent,
    self-test, mesh-test, archify dashboard.
    """
    t0 = time.time()
    try:
        if not os.path.exists(workspace):
            return {"status": "error", "error": f"workspace not found: {workspace}"}

        # Find agent workspaces
        agent_ws = []
        if os.path.isdir(workspace):
            for d in sorted(os.listdir(workspace)):
                p = os.path.join(workspace, d)
                if os.path.isdir(p):
                    agent_ws.append(p)

        agents = None
        if design and os.path.exists(design):
            try:
                from .model import TechDesign
                agents = TechDesign.from_yaml(open(design, encoding="utf-8").read()).agents
            except Exception:
                pass

        results = run_all(workspace, agent_ws, agents=agents)
        return {
            "status": "ok",
            "data": {
                "workspace": workspace,
                "results": [
                    {"name": r.name, "status": r.status, "detail": r.detail, "ok": r.ok}
                    for r in results
                ],
                "all_ok": all(r.ok for r in results),
            },
            "metadata": {"timestamp": _iso_now(), "duration_ms": int((time.time() - t0) * 1000)},
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# --------------------------------------------------------------------------- #
# Convenience: Full Run
# --------------------------------------------------------------------------- #
def api_run(incoming: str, spec_pack: str, design: str, target: str, infra: str,
            mesh_name: str = "spec-mesh", dashboard: str | None = None,
            assume_yes: bool = False) -> dict:
    """
    Full end-to-end pipeline: ingest → compile → review → provision → emit → verify.
    Returns combined status + all artifacts.
    """
    t0 = time.time()
    overall_status = "ok"
    combined = {"ingest": None, "compile": None, "review": None,
                "provision": None, "emit": None, "verify": None}

    # Ingest
    r = api_ingest(incoming, spec_pack)
    combined["ingest"] = r
    if r["status"] != "ok": overall_status = "error"

    # Compile
    r = api_compile(spec_pack, os.path.join(os.path.dirname(design) or ".", "TECH_DESIGN.yaml"),
                    mesh_name=mesh_name, dashboard=dashboard, incoming=incoming)
    combined["compile"] = r
    if r["status"] != "ok": overall_status = "error"

    # Review
    design_path = os.path.join(os.path.dirname(design) or ".", "TECH_DESIGN.yaml")
    r = api_approve(design_path, assume_yes=assume_yes)
    combined["review"] = r
    if r["status"] != "ok": overall_status = "error"

    # Provision
    r = api_provision(design_path, os.path.join(os.path.dirname(target) or ".", "infra"))
    combined["provision"] = r
    if r["status"] != "ok": overall_status = "error"

    # Emit
    r = api_emit(design_path, target)
    combined["emit"] = r
    if r["status"] != "ok": overall_status = "error"

    # Verify
    r = api_verify(target, design_path)
    combined["verify"] = r
    if r["status"] != "ok": overall_status = "error"

    return {
        "status": overall_status,
        "data": combined,
        "metadata": {"version": __version__, "timestamp": _iso_now(),
                     "duration_ms": int((time.time() - t0) * 1000)},
    }


# --------------------------------------------------------------------------- #
# CLI Entry (for kit subcommand delegation)
# --------------------------------------------------------------------------- #
def cli_main(argv: list[str] | None = None) -> int:
    """Standalone CLI entry point (delegates to existing cli.py)."""
    from .cli import main
    return main(argv)