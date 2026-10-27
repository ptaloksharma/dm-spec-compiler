"""COMPLETE END-TO-END KIT TEST with dummy data — fully local, no auth/cloud.

Runs the entire spec->code->verify pipeline + Buddy API + security gates in one
self-contained script. Every step prints a real PASS/FAIL with evidence.
"""
import subprocess, sys, os, tempfile, importlib.util, shutil, json, time, urllib.request

R = []
def rec(step, name, ok, detail=""):
    R.append((step, name, bool(ok)))
    print(f"[{('PASS' if ok else 'FAIL'):4}] {step}: {name}" + (f"  — {str(detail)[:64]}" if detail else ""))

HOME = os.path.expanduser("~")
SPEC = f"{HOME}/dm-spec-compiler"
KIT_CLI = f"{HOME}/dm-agent-kit/dist/cli/index.js"
sys.path.insert(0, SPEC)

# ========================================================================== #
# DUMMY DATA: a complete rich spec pack (domain-agnostic, not ERP)
# ========================================================================== #
DUMMY_ENTITY = """<!DOCTYPE html><html><head><title>Route Entity & State Model</title></head><body>
<h1>Route Ledger — Entity & State Model</h1>
<section id="catalogue"><table class="t">
<tr><th>Entity</th><th>Owner</th><th>Acts</th></tr>
<tr><td><span class="mono">route</span> <span class="pill">v1</span></td><td>Route Agent</td><td>create, approve, start, finish</td></tr>
<tr><td><span class="mono">vehicle</span> <span class="pill">Reference</span></td><td>Fleet Service</td><td>read</td></tr>
</table></section>
<h3>route attributes</h3>
<table class="t attrs">
<tr><th>attr</th><th>type</th><th>note</th></tr>
<tr><td><span class="mono">id</span></td><td><span class="ty">uuid</span></td><td>primary key</td></tr>
<tr><td><span class="mono">vehicle_id</span></td><td><span class="ty">string</span></td><td>assigned vehicle</td></tr>
<tr><td><span class="mono">stops</span></td><td><span class="ty">integer</span></td><td>stop count</td></tr>
<tr><td><span class="mono">version</span></td><td><span class="ty">integer</span></td><td>optimistic lock</td></tr>
</table>
<section id="route-states"><table class="t">
<tr><th>State</th></tr>
<tr><td class="st"><span class="mono">T01</span> <span class="nm">Planned</span> <span class="meaning">route planned</span></td></tr>
<tr><td class="st"><span class="mono">T02</span> <span class="nm">Approved</span> <span class="meaning">route approved</span></td></tr>
<tr><td class="st"><span class="mono">T03</span> <span class="nm">Active</span> <span class="meaning">route in progress</span></td></tr>
<tr><td class="st term"><span class="mono">T04</span> <span class="nm">Done</span> <span class="meaning">route complete</span></td></tr>
</table></section>
<section id="route-trans"><table class="t">
<tr><th>ID</th><th>Transition</th><th>Trigger</th><th>Guard</th></tr>
<tr><td>T01</td><td>Planned -&gt; Approved</td><td>approve</td><td>dispatcher ok</td></tr>
<tr><td>T02</td><td>Approved -&gt; Active</td><td>start</td><td>vehicle assigned</td></tr>
</table></section>
<section id="holds"><table class="t">
<tr><th>Hold</th><th>PlacedBy</th><th>Scope</th></tr>
<tr><td><span class="mono">weather_hold</span></td><td>dispatcher</td><td>route</td></tr>
</table></section>
<section id="invariants"><table class="t">
<tr><th>ID</th><th>Rule</th></tr>
<tr><td><span class="mono">I-01</span></td><td>no overlapping routes per vehicle</td></tr>
<tr><td><span class="mono">I-03</span></td><td>active holds freeze state mutations</td></tr>
</table></section>
</body></html>"""

DUMMY_EP = """<!DOCTYPE html><html><body><h1>Route Entry Points</h1>
<details class="ep" id="EP-RTE-01" data-st="planned" data-k="k-cmd">
<summary><span class="id">EP-RTE-01</span> <span class="nm">CreateRoute</span> command</summary>
<div class="eb">
<div><span class="k">REST</span> POST /routes</div>
<ol><li><span class="lv-det">Code</span> validate input</li>
<li><span class="lv-aid">AI decides</span> optimize stop order</li></ol>
</div></details>
</body></html>"""

DUMMY_REQ = """<!DOCTYPE html><html><body><h1>Route Requirements</h1>
<section id="nfr"><table class="nfr-table">
<tr><th>Category</th><th>Requirement</th><th>Target</th></tr>
<tr><td>Performance</td><td>route calc latency</td><td>&lt; 200ms</td></tr>
</table></section>
<div class="req-card" id="REQ-01">
<span class="req-id">REQ-01</span> <span class="req-title">Route creation</span> <span class="posture">Automate</span>
<div class="ears-item"><span class="ears-tag">Event</span> <span class="ears-text">when a route is requested the system shall create it</span></div>
</div>
</body></html>"""

def banner(t):
    print("\n" + "=" * 70 + f"\n  {t}\n" + "=" * 70)

def run(cmd, cwd=None, timeout=120, env=None):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout, env=env)

def _run_pipeline():
    banner("STEP 1: Ingest dummy spec pack -> markdown")
    from dm_spec_compiler.ingest import ingest_dir
    tmp = tempfile.mkdtemp(prefix="e2e-")
    inc, sp = os.path.join(tmp, "incoming"), os.path.join(tmp, "spec-pack")
    os.makedirs(inc); os.makedirs(sp)
    open(os.path.join(inc, "Route_Entity_and_State_Model.html"), "w").write(DUMMY_ENTITY)
    open(os.path.join(inc, "Route_Entry_Point_Catalogue.html"), "w").write(DUMMY_EP)
    open(os.path.join(inc, "Route-REQ.html"), "w").write(DUMMY_REQ)
    docs = ingest_dir(inc, sp)
    rec("1", "3 dummy HTML packs ingested to markdown", len(docs) == 3 and all(d.kind == "html" for d in docs),
        f"{len(docs)} docs")

    banner("STEP 2: Deterministic rich extraction (no LLM guessing)")
    from dm_spec_compiler.cli import _collect_rich
    from dm_spec_compiler.design import compile_design_rich
    rich = _collect_rich(inc)
    rec("2", "rich DOM pack detected", len(rich) >= 1, f"{len(rich)} packs")
    d = compile_design_rich({}, rich, mesh_name="route-mesh")
    a = d.agents[0]
    rec("2", "entities + typed fields extracted", len(a.entities) >= 1 and len(a.entities[0].typed_fields) >= 3,
        f"{len(a.entities)} ent, {len(a.entities[0].typed_fields)} fields")
    rec("2", "states + terminal flags", len(a.states) >= 4 and any(s.terminal for s in a.states), f"{len(a.states)} states")
    rec("2", "transitions", len(a.transitions) >= 1, f"{len(a.transitions)}")
    rec("2", "holds", len(a.holds) >= 1, f"{len(a.holds)}")
    rec("2", "invariants I-01/I-03", any(i.id == "I-03" for i in a.invariant_defs), f"{[i.id for i in a.invariant_defs]}")
    rec("2", "entry points + autonomy", len(a.entry_points) >= 1, f"{len(a.entry_points)} EPs")

    banner("STEP 3: Pydantic TECH_DESIGN validation + canonical views")
    from dm_spec_compiler.model import TechDesign
    from dm_spec_compiler.canonical import write_canonical
    d2 = TechDesign.from_yaml(d.to_yaml())
    rec("3", "TECH_DESIGN pydantic round-trip", d2.mesh_name == "route-mesh")
    cp = write_canonical(d, sp)
    rec("3", "canonical views (3 files)", len(cp) == 3, f"{len(cp)}")

    banner("STEP 4: Architect review gate + SHA-256 stamp fail-closed")
    from dm_spec_compiler import review
    dp = os.path.join(tmp, "TECH_DESIGN.yaml")
    open(dp, "w").write(d.to_yaml())
    rec("4", "pre-approval blocked", not review.is_approved(dp))
    review.approve(dp)
    rec("4", "SHA-256 .approved stamp written", os.path.exists(dp + ".approved"))
    open(dp, "a").write("\n# tamper\n")
    rec("4", "post-approval edit invalidates stamp", not review.is_approved(dp))
    open(dp, "w").write(d.to_yaml()); review.approve(dp)  # restore

    banner("STEP 5: Provision infra artifacts + --apply fail-closed")
    from dm_spec_compiler import provision
    from dm_spec_compiler.provision import ApplyError
    infra = os.path.join(tmp, "infra")
    out = provision.provision_design(d, infra, design_sha="x")
    files = set(os.listdir(os.path.join(infra, a.name)))
    rec("5", "schema.sql/bicep/tf/PROVISIONING.md", {"schema.sql", "main.bicep", "main.tf", "PROVISIONING.md"}.issubset(files))
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    try:
        provision.provision_design(d, infra, design_sha="x", apply=True, env=env)
        rec("5", "--apply fail-closed (no DATABASE_URL)", False)
    except ApplyError as e:
        rec("5", "--apply fail-closed (no DATABASE_URL)", "DATABASE_URL" in str(e))

    banner("STEP 6: Emit editable-zone + PermissionError on kit core")
    from dm_spec_compiler import emit
    tgt = os.path.join(tmp, "agents")
    emit.emit_design(d, tgt)
    ws = os.path.join(tgt, a.name)
    need = ["intent.txt", "GOAL.yaml", "agent.py", "src/logic/state.py", "src/logic/tools.py",
            "src/logic/prompts.py", "src/logic/workflow.py"]
    rec("6", "all 7 editable-zone files emitted", all(os.path.exists(os.path.join(ws, p)) for p in need))
    rec("6", "signed GOAL.yaml (configProvenance)", "configProvenance" in open(os.path.join(ws, "GOAL.yaml")).read())
    try:
        emit.emit_design(d, os.path.expanduser("~/dm-agent-kit"))
        rec("6", "emit -> kit ROOT raises PermissionError", False)
    except PermissionError:
        rec("6", "emit -> kit ROOT raises PermissionError", True)

    banner("STEP 7: Runtime invariant gate (fail-closed before Level-4 tools)")
    logic = os.path.join(ws, "src", "logic")
    def load(n):
        spec = importlib.util.spec_from_file_location("logic." + n, os.path.join(logic, n + ".py"))
        m = importlib.util.module_from_spec(spec); sys.modules["logic." + n] = m
        pkg = sys.modules.setdefault("logic", type(sys)("logic")); pkg.__path__ = [logic]
        spec.loader.exec_module(m); return m
    st = load("state"); load("prompts"); load("tools"); wf = load("workflow")
    v = st.check_all_invariants({"active_holds": [{"hold_type": "weather_hold"}], "exceptions": [], "entity": {"status": "planned"}})
    rec("7", "check_all_invariants -> structured I-03 Violation", any(x["id"] == "I-03" for x in v), f"{len(v)} violations")
    rec("7", "invariant_gate fail-closed -> exception", wf._gate_route({"violations": v}) == "exception")
    rec("7", "invariant_gate passes clean state", wf._gate_route({"violations": []}) != "exception")
    rec("7", "build_graph compiles (LangGraph)", wf.build_graph() is not None)

    banner("STEP 8: Live runtime --self-test / --mesh-test (no SKIP)")
    r = run(["python3", os.path.join(ws, "agent.py"), "--self-test"], cwd=ws, timeout=60)
    rec("8", "agent.py --self-test PASS", r.returncode == 0 and "SELF-TEST PASS" in (r.stdout + r.stderr),
        (r.stdout + r.stderr).strip().splitlines()[-1][:50] if (r.stdout + r.stderr).strip() else "")
    r = run(["python3", os.path.join(ws, "agent.py"), "--mesh-test"], cwd=ws, timeout=60)
    rec("8", "agent.py --mesh-test PASS", r.returncode == 0 and "MESH-TEST PASS" in (r.stdout + r.stderr))

    banner("STEP 9: Full verify via plugin_api (mesh/lint/self/mesh/archify)")
    from dm_spec_compiler import plugin_api
    res = plugin_api.api_verify(tgt, dp)
    gates = {x["name"]: x["status"] for x in res["data"]["results"]}
    rec("9", "api_verify all gates", res["status"] == "ok", f"{gates}")
    rec("9", "lint-policy gate PASS", any("lint" in n and gates[n] == "PASS" for n in gates))

    banner("STEP 10: Buddy UI REST seam (7 routes + dashboard + tab)")
    # (a) Route-dispatch logic — deterministic, in-process (no daemon lifecycle).
    node_check = (
        'const{handleSpecRoute}=require("%s/dm-agent-kit/dist/buddy/specRoutes.js");'
        'const{Readable}=require("node:stream");'
        'function p(x,m){const q=new Readable({read(){}});q.method=m||"POST";q.push("{}");q.push(null);'
        'return handleSpecRoute(q,{writeHead(){},end(){}},x)}'
        'let a=[];for(const s of["ingest","compile","review","approve","provision","emit","verify"])a.push(p("/api/spec/"+s)===true);'
        'console.log(JSON.stringify({post7:a.every(Boolean),dash:p("/api/spec/dashboard","GET")===true,pass:p("/api/chat")===false}))'
    ) % HOME
    r = run(["node", "-e", node_check], timeout=60)
    disp = {}
    for _ln in (r.stdout + "\n" + r.stderr).splitlines():
        _ln = _ln.strip()
        if _ln.startswith("{") and "post7" in _ln:
            try:
                disp = json.loads(_ln)
                break
            except Exception:
                pass
    rec("10", "7 POST /api/spec/* dispatch (in-process)", disp.get("post7") is True)
    rec("10", "GET /api/spec/dashboard route", disp.get("dash") is True)
    rec("10", "additive passthrough (non-spec routes)", disp.get("pass") is True,
        f"disp={disp}")
    # Spec Compiler tab markup present in served HTML template
    ui = open(f"{HOME}/dm-agent-kit/src/buddy/ui.ts").read()
    rec("10", "Spec Compiler & ArchiMate tab in UI",
        'id="specIncoming"' in ui and 'id="specApproveBtn"' in ui and 'id="specDash"' in ui)

    # (b) Daemon stability — boots and serves the tab live (best-effort, tolerant).
    srv = subprocess.Popen(["node", KIT_CLI, "buddy", "--port", "7781", "--no-open"],
                           cwd=tmp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           start_new_session=True)
    def http(method, path, body=None, timeout=20):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:7781{path}", data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as rr:
                return rr.status, rr.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()
        except (ConnectionResetError, ConnectionRefusedError, OSError):
            return 0, ""
    up = False
    for _ in range(60):
        time.sleep(0.25)
        if http("GET", "/api/status", timeout=4)[0] == 200:
            up = True
            break
    rec("10", "Buddy daemon boots + stays alive", up)
    if up:
        sc, bodytxt = http("GET", "/", timeout=10)
        rec("10", "GET / serves Spec Compiler tab (live)", sc == 200 and "Spec Compiler" in bodytxt)
    try:
        srv.terminate()
    except Exception:
        pass

    banner("STEP 11: pytest regression (other suites — excludes this e2e file)")
    # Run the deterministic unit/integration suites, NOT this e2e file itself
    # (running `pytest tests/` from inside a tests/ test would recurse).
    r = run([f"{SPEC}/.venv/bin/python", "-m", "pytest",
             "tests/test_pipeline.py", "tests/test_wizard_to_compiler_contract.py",
             "tests/test_gap_coverage.py", "-q"], cwd=SPEC, timeout=120)
    line = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l]
    last = line[-1] if line else ""
    rec("11", "deterministic suites pass (47-1 e2e)", "passed" in r.stdout and "failed" not in last, last)

    shutil.rmtree(tmp, ignore_errors=True)

    banner("FINAL TALLY")
    print(f"Steps executed: {len(set(x[0] for x in R))} | Checks: {len(R)} | "
          f"Passed: {sum(1 for x in R if x[2])} | Failed: {sum(1 for x in R if not x[2])}")
    print("=" * 70)



def test_complete_end_to_end():
    """Full 11-step spec->code->verify + Buddy API + security-gates pipeline."""
    R.clear()
    _run_pipeline()
    fails = [(st, n) for st, n, ok in R if not ok]
    assert not fails, f"E2E failures: {fails}"


if __name__ == "__main__":
    _run_pipeline()
    import sys as _s
    _s.exit(1 if any(not ok for _, _, ok in R) else 0)
