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
from .design import compile_design
from .emit import emit_design
from .ingest import ingest_dir
from .model import TechDesign
from .review import is_approved, review_gate
from .verify import run_all


def _read_spec_pack(spec_pack: str) -> dict[str, str]:
    texts: dict[str, str] = {}
    for fname in sorted(os.listdir(spec_pack)):
        if fname.endswith((".md", ".markdown")):
            texts[fname] = open(os.path.join(spec_pack, fname),
                                encoding="utf-8").read()
    if not texts:
        raise SystemExit(f"no markdown specs in {spec_pack} — run `ingest` first")
    return texts


def cmd_ingest(args) -> int:
    docs = ingest_dir(args.incoming, args.spec_pack)
    for d in docs:
        print(f"  ✓ {os.path.basename(d.source_path)} → {d.kind} "
              f"({len(d.markdown)} chars, sha {d.sha256[:8]})"
              + (f"  ⚠ {len(d.warnings)} warnings" if d.warnings else ""))
    print(f"ingested {len(docs)} spec(s) → {args.spec_pack}")
    return 0 if docs else 1


def cmd_compile(args) -> int:
    texts = _read_spec_pack(args.spec_pack)
    design = compile_design(texts, mesh_name=args.mesh_name)
    os.makedirs(os.path.dirname(args.design) or ".", exist_ok=True)
    with open(args.design, "w", encoding="utf-8") as f:
        f.write(design.to_yaml())
    print(f"TECH_DESIGN.yaml written → {args.design} "
          f"({len(design.agents)} agents)")
    for a in design.agents:
        print(f"  • {a.name} [{a.role}/{a.tier}] states={len(a.states)} "
              f"tools={len(a.tools)} eps={len(a.entry_points)}")
    return 0


def cmd_review(args) -> int:
    if not os.path.exists(args.design):
        raise SystemExit(f"{args.design} not found — run `compile` first")
    ok = review_gate(args.design, assume_yes=args.yes)
    if ok:
        print(f"APPROVED → {args.design}.approved")
        return 0
    print("BLOCKED — design not approved (non-interactive: approve the file first)",
          file=sys.stderr)
    return 2


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
        sp.add_argument("--mesh-name", default="spec-mesh")
        sp.add_argument("--target", default="./agents")

    for name in ("ingest", "compile", "review", "emit", "verify", "run"):
        sp = sub.add_parser(name)
        common(sp)
        if name in ("review", "run"):
            sp.add_argument("--yes", action="store_true",
                            help="non-interactive auto-approve (architect gate)")
        if name in ("emit", "run"):
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
