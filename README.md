# dm-spec-compiler

**Standalone, universal spec-to-code & architecture compiler for the `dm-agent-kit` ecosystem.**

Ingests raw requirement/spec packs (HTML / Markdown / PDF) from a local incoming
folder, parses them **deterministically** (BeautifulSoup / PyMuPDF / heading grammars
— **no raw LLM code generation**), compiles a validated `TECH_DESIGN.yaml`, runs an
**Architect-in-the-Loop** review gate, then emits the `dm-agent-kit` **editable zone**
into target agent workspaces. It never touches the core kit repo.

Domain-agnostic by construction: nothing in the pipeline assumes AP, ERP, or any
vertical. A 3-tier logistics mesh, a finance mesh, or a warehouse-robotics fleet are
all just `# Agent:` blocks in a spec.

## Architecture

```
blueprints/incoming-specs/   raw spec packs (.html .md .pdf)
        │  Module 1 · ingest.py        deterministic → clean per-source markdown + provenance
        ▼
blueprints/spec-pack/*.md
        │  Module 2 · design.py        heading/regex grammar → validated model.py (pydantic)
        │             canonical.py     → requirements.md · entities.md · entry-points.md
        │             archify_bridge.py→ architecture-dashboard.html (design-time preview)
        ▼
blueprints/TECH_DESIGN.yaml   +   blueprints/architecture-dashboard.html
        │  Module 3 · review.py        Architect-in-the-Loop: design + diagram side-by-side,
        │                              [a]pprove / [e]dit→re-validate+re-render / [q]uit
        ▼
TECH_DESIGN.yaml.approved   (sha256-bound to the design bytes)
        │  Module 4 · emit.py          deterministic renderers → editable zone ONLY
        ▼
agents/<name>/GOAL.yaml  +  agents/<name>/src/logic/{state,tools,prompts,workflow}.py
        │  Module 5 · verify.py        kit hooks via ONE seam (never vendored)
        ▼
dm-agent mesh verify · agent.py --self-test/--mesh-test · archify as-built dashboard
```

### Hard boundaries (fail-closed)

* **Editable zone only** — the emitter writes exactly 6 paths per agent
  (`GOAL.yaml`, `src/logic/__init__.py`, `state.py`, `tools.py`, `prompts.py`,
  `workflow.py`). Nothing else. Proven by test: workspace root contains only
  `{GOAL.yaml, src}`.
* **Kit is external** — all kit interaction goes through `verify.py` /
  `_kitpath.py`. The kit is resolved via `$DM_AGENT_KIT_ROOT` (default
  `~/dm-agent-kit`) and invoked as a library/binary. Emission into the kit tree
  itself raises `PermissionError`.
* **Approval gate** — `emit` refuses unless `TECH_DESIGN.yaml` is approved.
  The approval stamp (`TECH_DESIGN.yaml.approved`) binds the sha256 of the
  design bytes; editing the YAML after approval invalidates it.
* **workflow.py is a real LangGraph `StateGraph`** — one node per declared
  state, a static `NEXT` transition table, and `add_conditional_edges` routing
  that branches to `hitl` on HOLD states and `end` at the terminal. It
  compiles and executes against a live `langgraph` install, and degrades to a
  deterministic walk when langgraph is absent (scaffold-time safe).

### v0.3.0 — rich πd Genius HTML + production emission + live runtime

* **Rich DOM extraction** (`htmlspec.py`): three HTML spec shapes parsed
  deterministically from the DOM — `*Entity_and_State_Model*` (catalogue
  `.pill` scope, `table.t.attrs` typed fields, `.st`/`.st.term` states,
  `T01..T10b` transitions incl. backward + `Any`-wildcard rows, `#holds`,
  `#invariants`), `*Entry_Point_Catalogue*` (`<details class="ep">` with
  autonomy badges `.lv-det/.lv-ais/.lv-aid/.lv-hum`, guards, outbox outputs,
  idempotency, Given/When/Then tests), and `*-REQ*` (`#nfr` table + `.req-card`
  EARS clauses with posture).
* **Production emission** (`emit_rich.py`): `state.py` emits a `TypedDict` per
  entity + `active_holds`/`exceptions`/`version`/`correlation_id`/
  `legal_entity_id` + `check_i_NN` invariant helpers; `tools.py` emits one
  Level-4 function per Entry Point pre-wired with idempotency dedup,
  `expected_version` optimistic concurrency, StateHistory + OutboxEvent;
  `prompts.py` emits a named+versioned prompt constant per `AI decides`/
  `AI suggests` step enforcing the **Untrusted Text Rule**; `workflow.py`
  emits the I-03 hold-freeze guard, I-04 hold-placed withdrawal, and a
  `NEEDS_DATA` cross-agent branch.
* **Live runtime** (`render_runtime`): every emitted agent gets `agent.py`
  exposing `--self-test` and `--mesh-test`, so Module 5 runs **LIVE (PASS)**
  instead of SKIP. Legacy (sparse-markdown) models still use the v0.2
  templates; rich models are detected and upgraded automatically.

### v0.4.0 — ArchiMate modeling, architectural gate, infrastructure provisioning

* **ArchiMate layered view** (`archify_bridge.view_archimate`): the dashboard
  gains a 5th tab mapping the design onto standard ArchiMate layers —
  **Business** (Business Process from the primary objective), **Application**
  (Application Component per agent + Application Service per entry point),
  **Data** (Data Object per entity), and **Technology** (Infrastructure Node
  per isolated schema), with realized/persisted-in relationships.
* **Architectural review & modification gate** (`review.py`): the architect
  inspects `TECH_DESIGN.yaml` alongside the ArchiMate diagram; `[e]dit`
  re-validates and re-renders the diagram in the loop; nothing proceeds until
  explicit sign-off writes the sha256-bound `TECH_DESIGN.yaml.approved`.
* **Infrastructure provisioning hook** (`provision.py`, `dm-spec-compiler
  provision`): runs immediately after approval, **before** code emission.
  Emits per-agent `infra/<agent>/{schema.sql, main.bicep, main.tf,
  PROVISIONING.md}` — an idempotent isolated private schema (deterministic
  `<name>_schema`) with DDL for every typed entity. Each artifact records the
  approving design's sha256, so provisioning is provably bound to the
  signed-off design. Refused (fail-closed) without the approval stamp.
  `run` order: ingest → compile → review → **provision** → emit → verify.
* **Deterministic extraction** — states (`T01..`), entry points (`EP-XXX`),
  tools, entities, invariants and cross-agent edges all come from a documented
  markdown grammar. No LLM guessing. (An optional LLM pass may later draft
  *summary text*, but its output must validate through the same pydantic
  `TechDesign` schema — zero structural drift.)

## Spec grammar

Everything is optional; missing sections yield empty lists.

```markdown
## Agent: fleet-orchestrator
role: domain-agent            # ui-coordinator | domain-agent | sub-agent
tier: standard                # fast-path | standard | deep
objective: Orchestrate fleet assignment.
delegates_to: customs-agent   # → cross-agent edges
hitl_threshold_eur: 25000
egress: api.carrier-eu.example

### States
- T01 receive — handoff payload received
- T05 assign — vehicle assigned (invariant: driver hours within legal limit)
- T07 confirm [HOLD] — awaiting ops confirmation

### Entry Points
- EP-CAP capture — orchestrator receives handoff → T01

### Tools
- assign_vehicle — choose a compliant vehicle (mutating)
- check_driver_hours — verify legal driving hours

### Entities
- vehicle(id, plate, capacity_kg, status)

### Invariants
- Driver weekly hours must not exceed the legal maximum.
```

## Usage

```bash
# one-shot end-to-end
dm-spec-compiler run \
  --incoming ./blueprints/incoming-specs \
  --spec-pack ./blueprints/spec-pack \
  --design ./blueprints/TECH_DESIGN.yaml \
  --target ./agents \
  --yes                       # non-interactive auto-approve (drop for TTY review)

# or stage-by-stage
dm-spec-compiler ingest  --incoming ... --spec-pack ...
dm-spec-compiler compile --spec-pack ... --design ...
dm-spec-compiler review  --design ...            # interactive [a]pprove/[e]dit/[q]uit
dm-spec-compiler emit    --design ... --target ./agents [--agent NAME] [--force]
dm-spec-compiler verify  --target ./agents
```

`review` on a TTY prints a per-agent summary and prompts. `[e]dit` opens the
YAML in `$EDITOR` and re-validates on save. Non-interactive runs require the
pre-existing sha-bound stamp (`--yes` writes it).

## Verification hooks (Module 5)

* `mesh verify` — locates the kit CLI (`dist/cli/index.js` → `npx dm-kit`),
  runs `dm-agent mesh verify` in the workspace.
* `agent.py --self-test` / `--mesh-test` — per workspace; **SKIP** (not crash)
  when no `agent.py` exists — correct, since the emitter only writes the
  editable zone (the kit scaffolds the runtime separately).
* `archify.generate()` — regenerates `architecture-dashboard.html` (4-view
  Mermaid: mesh topology / workflow / data-flow / cloud) and stamps the
  Zero-Drift seal into `.dm-lock.json`.

## Development

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m pytest tests -q     # 13 tests, deterministic, no live kit
```

The test suite uses a 3-tier **logistics** fixture (deliberately not ERP) plus a
synthetic PDF, and proves: HTML→markdown stripping, 3-tier role extraction,
state/HOLD/invariant parsing, cross-agent edges, schema rejection of bad ids,
the approval gate (incl. tamper invalidation), editable-zone-only emission,
`ast.parse` of every emitted file, GOAL contract fields, refusal without
approval, refusal to write into the kit tree, and the full CLI run.

## Buddy UI (future)

Modules are UI-ready: `ingest_dir`, `compile_design`, `review_gate`,
`emit_design`, `run_all` are pure functions with file-path in/out — no globals,
no CLI coupling. A Buddy UI (`:7700`) tab can call them directly and render
`render_summary(design)` for the review step.
