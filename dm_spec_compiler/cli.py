"""dm-spec-compiler CLI — one command per pipeline stage, plus `run` for all.

  ingest     ./blueprints/incoming-specs  → ./blueprints/spec-pack/*.md
  compile    spec-pack/*.md               → ./blueprints/TECH_DESIGN.yaml
  review     TECH_DESIGN.yaml             → approval gate (architect-in-the-loop)
  emit       approved TECH_DESIGN.yaml    → <target>/<agent>/{GOAL.yaml, src/logic/*}
  verify     workspace                    → mesh verify + self/mesh tests + dashboard
  run        all of the above, end-to-end
"""
from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .archify_bridge import render_dashboard
from .canonical import write_canonical
from .design import compile_design, compile_design_rich
from .emit import emit_design
from .ingest import ingest_dir, ingest_file
from .htmlspec import extract_rich
from .model import TechDesign
from .provision import design_sha256, provision_design
from .review import is_approved, review_gate
from .verify import run_all

_CANONICAL = {"requirements.md", "entities.md", "entry-points.md"}


def _read_spec_pack(spec_pack: str) -> dict[str, str]:
    texts: dict[str, str] = {}
    for fname in sorted(os.listdir(spec_pack)):
        if fname in _CANONICAL:
            continue  # derived views, not raw specs — never re-ingest
        if fname.endswith((".md", ".markdown")):
            texts[fname] = open(os.path.join(spec_pack, fname),
                                encoding="utf-8").read()
    if not texts:
        raise SystemExit(f"no markdown specs in {spec_pack} — run `ingest` first")
    return texts


def _collect_rich(incoming: str) -> list[dict]:
    """Deterministically extract rich DOM data from any rich HTML spec pack."""
    rich: list[dict] = []
    if not os.path.isdir(incoming):
        return rich
    for fname in sorted(os.listdir(incoming)):
        if not fname.lower().endswith((".html", ".htm")):
            continue
        path = os.path.join(incoming, fname)
        if not os.path.isfile(path):
            continue
        try:
            doc = ingest_file(path)
        except ValueError:
            continue
        if doc.raw_html:
            payload = extract_rich(fname, doc.raw_html)
            if payload:
                rich.append(payload)
    return rich


def cmd_ingest(args) -> int:
    docs = ingest_dir(args.incoming, args.spec_pack)
    rich = _collect_rich(getattr(args, "incoming", ""))
    for d in docs:
        tag = " [rich]" if d.kind == "html" and any(
            r for r in rich) else ""
        print(f"  ✓ {os.path.basename(d.source_path)} → {d.kind} "
              f"({len(d.markdown)} chars, sha {d.sha256[:8]})"
              + (f"  ⚠ {len(d.warnings)} warnings" if d.warnings else "") + tag)
    if rich:
        kinds = {}
        for r in rich:
            kinds[r["__kind__"]] = kinds.get(r["__kind__"], 0) + 1
        print(f"  ⬢ rich DOM packs detected: "
              + ", ".join(f"{k}×{v}" for k, v in sorted(kinds.items())))
    print(f"ingested {len(docs)} spec(s) → {args.spec_pack}")
    return 0 if docs else 1


def cmd_compile(args) -> int:
    texts = _read_spec_pack(args.spec_pack)
    rich = _collect_rich(getattr(args, "incoming", ""))
    if rich:
        design = compile_design_rich(texts, rich, mesh_name=args.mesh_name)
    else:
        design = compile_design(texts, mesh_name=args.mesh_name)
    os.makedirs(os.path.dirname(args.design) or ".", exist_ok=True)
    with open(args.design, "w", encoding="utf-8") as f:
        f.write(design.to_yaml())
    # canonical views (requirements/entities/entry-points) stay in sync
    for path in write_canonical(design, args.spec_pack):
        print(f"  ✓ canonical → {path}")
    # Archify design-time dashboard (review aid, regenerated every compile)
    seal = render_dashboard(design, args.dashboard)
    print(f"TECH_DESIGN.yaml written → {args.design} "
          f"({len(design.agents)} agents)")
    print(f"  🗺  Archify dashboard → {seal['path']} (spec {seal['spec_hash'][:12]})")
    for a in design.agents:
        print(f"  • {a.name} [{a.role}/{a.tier}] states={len(a.states)} "
              f"tools={len(a.tools)} eps={len(a.entry_points)}")
    return 0


def cmd_review(args) -> int:
    if not os.path.exists(args.design):
        raise SystemExit(f"{args.design} not found — run `compile` first")
    ok = review_gate(args.design, assume_yes=args.yes,
                     dashboard_path=args.dashboard)
    if ok:
        print(f"APPROVED → {args.design}.approved")
        return 0
    print("BLOCKED — design not approved (non-interactive: approve the file first)",
          file=sys.stderr)
    return 2


def cmd_provision(args) -> int:
    if not os.path.exists(args.design):
        raise SystemExit(f"{args.design} not found — run `compile` first")
    if not args.force and not is_approved(args.design):
        raise SystemExit(
            "REFUSED — infrastructure provisioning requires the architect's "
            "approval stamp. Run `review` first (or --force).")
    design = TechDesign.from_yaml(open(args.design, encoding="utf-8").read())
    sha = design_sha256(args.design)
    out = provision_design(design, args.infra, design_sha=sha, only=args.agent)
    for name, files in out.items():
        print(f"  ⛁ provisioned {name}: {len(files)} artifacts")
        for f in files:
            print(f"      {f}")
    return 0


def cmd_emit(args) -> int:
    design = TechDesign.from_yaml(open(args.design, encoding="utf-8").read())
    if not args.force and not is_approved(args.design):
        raise SystemExit(
            "REFUSED — design not approved. Run `review` first "
            "(or pass --force to bypass the architect gate).")
    out = emit_design(design, args.target, only=args.agent)
    for name, files in out.items():
        print(f"  ✓ {name}: {len(files)} files")
        for f in files:
            print(f"      {f}")
    return 0


def cmd_verify(args) -> int:
    agent_ws = [os.path.join(args.target, d)
                for d in sorted(os.listdir(args.target))
                if os.path.isdir(os.path.join(args.target, d))]
    results = run_all(args.target, agent_ws)
    worst = 0
    for r in results:
        icon = {"PASS": "✓", "FAIL": "✗", "SKIP": "–"}[r.status]
        print(f"  {icon} {r.name}: {r.status}  {r.detail[:120]}")
        if r.status == "FAIL":
            worst = 1
    return worst


def cmd_run(args) -> int:
    rc = cmd_ingest(args)
    if rc:
        return rc
    rc = cmd_compile(args)
    if rc:
        return rc
    rc = cmd_review(args)
    if rc:
        return rc
    rc = cmd_provision(args)   # infrastructure BEFORE code emission
    if rc:
        return rc
    rc = cmd_emit(args)
    if rc:
        return rc
    return cmd_verify(args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dm-spec-compiler",
                                description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--incoming", default="./blueprints/incoming-specs")
        sp.add_argument("--spec-pack", default="./blueprints/spec-pack")
        sp.add_argument("--design", default="./blueprints/TECH_DESIGN.yaml")
        sp.add_argument("--dashboard", default="./blueprints/architecture-dashboard.html")
        sp.add_argument("--mesh-name", default="spec-mesh")
        sp.add_argument("--target", default="./agents")
        sp.add_argument("--infra", default="./infra")

    for name in ("ingest", "compile", "review", "provision", "emit", "verify", "run"):
        sp = sub.add_parser(name)
        common(sp)
        if name in ("review", "run"):
            sp.add_argument("--yes", action="store_true",
                            help="non-interactive auto-approve (architect gate)")
        if name in ("provision", "emit", "run"):
            sp.add_argument("--force", action="store_true",
                            help="bypass the approval check")
            sp.add_argument("--agent", action="append", default=None,
                            help="emit only this agent (repeatable)")
        sp.set_defaults(func=globals()[f"cmd_{name}"])
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
