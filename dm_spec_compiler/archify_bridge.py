"""Archify design-time dashboard bridge.

Renders a PREVIEW architecture-dashboard.html directly from a TechDesign —
before any code is emitted — so the architect reviews the diagram alongside
TECH_DESIGN.yaml (Module 3). Reuses the kit's archify VIEW RENDERERS (via the
external kit on sys.path) so design-time and as-built diagrams share one
visual language. Falls back to a self-contained 4-view dashboard when the kit
archify is unavailable — never a hard dependency, never vendored.
"""
from __future__ import annotations

import hashlib
import json
import os

from .model import TechDesign


def _esc(s: str) -> str:
    return s.replace('"', "'").replace("<", "(").replace(">", ")")

_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Spec Design Architecture Preview</title>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
<style>
body{background:#0e1224;color:#eef1ff;font-family:system-ui;margin:0;padding:1.2rem}
h1{font-size:1.1rem}.tabs{display:flex;gap:8px;margin:12px 0}
.tabs button{background:#151b31;color:#eef1ff;border:1px solid #818cf8;border-radius:8px;
  padding:6px 14px;cursor:pointer;font-size:13px}
.tabs button.active{background:#818cf8;color:#fff}
.view{display:none;background:#151b31;border-radius:10px;padding:14px}
.view.active{display:block} pre.mermaid{background:transparent}
.meta{color:#96a0c6;font-size:12px;margin-top:8px}
</style></head>
<body>
<h1>🏗️ Spec Design Preview <span class="meta">(mesh __MESH__ · spec __SPECHASH__ · review before approval)</span></h1>
<div class="tabs">
  <button class="active" onclick="show(0,this)">🕸️ Mesh Topology</button>
  <button onclick="show(1,this)">🔄 Workflow Lifecycle</button>
  <button onclick="show(2,this)">📊 Data Flow</button>
  <button onclick="show(3,this)">☁️ Cloud Infrastructure</button>
  <button onclick="show(4,this)">🏛️ ArchiMate Layers</button>
</div>
<div class="view active"><pre class="mermaid">__VIEW0__</pre></div>
<div class="view"><pre class="mermaid">__VIEW1__</pre></div>
<div class="view"><pre class="mermaid">__VIEW2__</pre></div>
<div class="view"><pre class="mermaid">__VIEW3__</pre></div>
<div class="view"><pre class="mermaid">__VIEW4__</pre></div>
<script>
mermaid.initialize({startOnLoad:true,theme:'dark'});
function show(i,btn){
  document.querySelectorAll('.view').forEach((v,j)=>v.classList.toggle('active',i===j));
  document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
}
</script></body></html>"""


def design_to_spec(design: TechDesign) -> dict:
    """Project a TechDesign onto the kit archify's expected spec shape."""
    agents = []
    edges = []
    for a in design.agents:
        agents.append({
            "name": a.name,
            "role": a.role,
            "tier": a.tier,
            "allowedTools": [t.name for t in a.tools],
            "tool_defs": [t.name for t in a.tools],
            "has_doa_gate": a.hitl_threshold_eur is not None,
            "hitl_threshold_eur": a.hitl_threshold_eur,
            "has_secure_gate": True,
            "compliance_packs": ["bola"],
            "sourceHash": None,
            "cloud": "local",
        })
        for tgt in a.delegates_to:
            edges.append({"from": a.name, "to": tgt})
    return {"agents": agents, "edges": edges}


def render_dashboard(design: TechDesign, out_path: str) -> dict:
    """Write the preview dashboard; return the seal {spec_hash, html_hash, path}."""
    spec = design_to_spec(design)
    try:
        import archify  # kit on sys.path via _kitpath
        views = [archify.view_mesh_topology(spec), archify.view_workflow(spec),
                 archify.view_dataflow(spec), archify.view_cloud(spec)]
    except Exception:
        views = [_fallback_mesh(design), _fallback_workflow(design),
                 _fallback_dataflow(design), _fallback_cloud(design)]
    views.append(view_archimate(design))  # VIEW4 — ArchiMate layering

    payload = json.dumps(spec, sort_keys=True, default=str).encode()
    spec_hash = hashlib.sha256(payload).hexdigest()
    html = (_HTML
            .replace("__MESH__", design.mesh_name)
            .replace("__SPECHASH__", spec_hash[:12])
            .replace("__VIEW0__", views[0])
            .replace("__VIEW1__", views[1])
            .replace("__VIEW2__", views[2])
            .replace("__VIEW3__", views[3])
            .replace("__VIEW4__", views[4]))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return {"spec_hash": spec_hash,
            "html_hash": hashlib.sha256(html.encode()).hexdigest(),
            "path": out_path}


# --------------------------------------------------------------------------- #
# ArchiMate layered view (Business / Application / Data / Technology)          #
# --------------------------------------------------------------------------- #
def view_archimate(design: TechDesign) -> str:
    """Map the design onto standard ArchiMate layers as a Mermaid subgraph stack."""
    esc = _esc

    def nid(s: str) -> str:
        return s.replace("-", "_").replace(" ", "_")

    biz: list[str] = []
    app: list[str] = []
    data: list[str] = []
    tech: list[str] = []
    links: list[str] = []

    for a in design.agents:
        an = nid(a.name)
        # Application layer: the agent component + its entry points (app services)
        app.append(f'    {an}[\"⚙️ {esc(a.name)}<br/><<Application Component>>\"]')
        for ep in a.entry_points:
            epn = nid(f"{a.name}_{ep.id}")
            app.append(f'    {epn}[\"{esc(ep.id)} {esc(ep.name)}<br/><<Application Service>>\"]')
            links.append(f"  {an} --> {epn}")
        # Data layer: entities
        for e in a.entities:
            dn = nid(f"{a.name}_{e.name}")
            data.append(f'    {dn}[(\"🗄 {esc(e.name)}<br/><<Data Object>>\")]')
            links.append(f"  {an} --> {dn}")
        # Technology layer: isolated schema per agent
        sn = nid(f"{a.name}_schema")
        tech.append(f'    {sn}[[\"🛢 {esc(_schema_for(a))}<br/><<Infrastructure Node>>\"]]')
        for e in a.entities:
            links.append(f"  {nid(f'{a.name}_{e.name}')} -.->|persisted in| {sn}")

    # Business layer: one business process per mesh (from the coordinator /
    # first agent's objective), linked down to its application component
    if design.agents:
        primary = design.agents[0]
        bp = f'biz_{nid(primary.name)}'
        label = (primary.objective or primary.use_case or design.mesh_name)[:48]
        biz.append(f'    {bp}[\"🎯 {esc(label)}<br/><<Business Process>>\"]')
        links.append(f"  {bp} --> {nid(primary.name)}")

    lines = ["graph TD",
             '  subgraph BIZ[\"🏛 Business Layer\"]'] + (biz or ["    none_b[no business process]"]) + ["  end",
             '  subgraph APP[\"🧩 Application Layer\"]'] + (app or ["    none_a[no components]"]) + ["  end",
             '  subgraph DATA[\"🗄 Data Layer\"]'] + (data or ["    none_d[no data objects]"]) + ["  end",
             '  subgraph TECH[\"🛢 Technology Layer\"]'] + (tech or ["    none_t[no infra nodes]"]) + ["  end"]
    lines += links
    lines.append("  classDef biz fill:#1e3a5f,stroke:#60a5fa,color:#e2e8f0;")
    return "\n".join(lines)


def _schema_for(agent) -> str:
    """Deterministic isolated-schema name for an agent (no domain hardcoding)."""
    base = agent.name.replace("-", "_")
    base = base[:-6] if base.endswith("_agent") else base
    return f"{base}_schema"


# --------------------------------------------------------------------------- #
# Self-contained fallbacks (used only when the kit archify is not importable) #
# --------------------------------------------------------------------------- #
def _fallback_mesh(design: TechDesign) -> str:
    lines = ["graph TD"]
    for a in design.agents:
        lines.append(f"  {a.name.replace('-', '_')}[\"{_esc(a.name)}<br/>{a.role} · {a.tier}\"]")
    for a in design.agents:
        for tgt in a.delegates_to:
            lines.append(f"  {a.name.replace('-', '_')} -->|DSH handoff| {tgt.replace('-', '_')}")
    return "\n".join(lines)


def _fallback_workflow(design: TechDesign) -> str:
    lines = ["graph TD"]
    for a in design.agents:
        an = a.name.replace("-", "_")
        chain = " --> ".join(s.id for s in a.states) or "T01"
        lines.append(f"  subgraph {an}[\"{_esc(a.name)} workflow\"]")
        lines.append(f"    {an}_chain[\"{_esc(chain)}\"]")
        lines.append("  end")
    return "\n".join(lines)


def _fallback_dataflow(design: TechDesign) -> str:
    lines = ["graph LR", "  REQ[spec-pack<br/>source of truth]"]
    for a in design.agents:
        lines.append(f"  REQ --> {a.name.replace('-', '_')}[{_esc(a.name)}]")
    return "\n".join(lines)


def _fallback_cloud(design: TechDesign) -> str:
    return "graph TD\n  local[local-first · no cloud target declared]"
