"""End-to-end tests for dm-spec-compiler. All deterministic — no live kit needed."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from dm_spec_compiler import cli, emit, review  # noqa: E402
from dm_spec_compiler.design import compile_design  # noqa: E402
from dm_spec_compiler.ingest import ingest_dir  # noqa: E402
from dm_spec_compiler.model import TechDesign  # noqa: E402

FIXTURES = os.path.join(REPO, "tests", "fixtures")


class PipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="dmsc-")
        self.spec_pack = os.path.join(self.tmp, "spec-pack")
        self.design_path = os.path.join(self.tmp, "TECH_DESIGN.yaml")
        self.target = os.path.join(self.tmp, "agents")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ingest(self):
        incoming = os.path.join(FIXTURES, "incoming-specs")
        return ingest_dir(incoming, self.spec_pack)

    def _compile(self) -> TechDesign:
        self._ingest()
        texts = {f: open(os.path.join(self.spec_pack, f), encoding="utf-8").read()
                 for f in os.listdir(self.spec_pack) if f.endswith(".md")}
        design = compile_design(texts, mesh_name="logistics-mesh")
        with open(self.design_path, "w", encoding="utf-8") as f:
            f.write(design.to_yaml())
        return design

    # Module 1
    def test_ingest_html_to_markdown(self):
        docs = self._ingest()
        html = [d for d in docs if d.kind == "html"]
        self.assertEqual(len(html), 1)
        doc = html[0]
        self.assertIn("# Agent: logistics-coordinator", doc.markdown)
        self.assertNotIn("<script", doc.markdown)
        self.assertNotIn("track()", doc.markdown)
        self.assertTrue(os.path.exists(
            os.path.join(self.spec_pack, "logistics-mesh.md")))

    def test_ingest_pdf_to_markdown(self):
        docs = self._ingest()
        pdf = [d for d in docs if d.kind == "pdf"]
        self.assertEqual(len(pdf), 1)
        self.assertIn("Warehouse Robotics Mesh", pdf[0].markdown)
        self.assertTrue(os.path.exists(
            os.path.join(self.spec_pack, "warehouse-robotics.md")))

    def test_canonical_spec_files_written(self):
        import argparse
        self._ingest()
        ns = argparse.Namespace(spec_pack=self.spec_pack, design=self.design_path,
                                mesh_name="logistics-mesh",
                                dashboard=os.path.join(self.tmp, "dash.html"))
        cli.cmd_compile(ns)  # canonical files are written at compile, not ingest
        for canonical in ("requirements.md", "entities.md", "entry-points.md"):
            self.assertTrue(os.path.exists(os.path.join(self.spec_pack, canonical)),
                            canonical)
        reqs = open(os.path.join(self.spec_pack, "requirements.md"), encoding="utf-8").read()
        self.assertIn("logistics-coordinator", reqs)
        ents = open(os.path.join(self.spec_pack, "entities.md"), encoding="utf-8").read()
        self.assertIn("vehicle", ents)
        eps = open(os.path.join(self.spec_pack, "entry-points.md"), encoding="utf-8").read()
        self.assertIn("EP-CAP", eps)

    # Module 2
    def test_compile_design_three_tiers(self):
        design = self._compile()
        self.assertEqual(len(design.agents), 3)
        by_name = {a.name: a for a in design.agents}
        self.assertEqual(by_name["logistics-coordinator"].role, "ui-coordinator")
        self.assertEqual(by_name["fleet-orchestrator"].role, "domain-agent")
        self.assertEqual(by_name["customs-agent"].role, "sub-agent")

    def test_states_entrypoints_invariants(self):
        design = self._compile()
        orch = design.agent("fleet-orchestrator")
        self.assertEqual([s.id for s in orch.states], ["T01", "T05", "T07"])
        hold = [s for s in orch.states if s.hold]
        self.assertEqual([s.id for s in hold], ["T07"])
        self.assertEqual(orch.states[1].invariant,
                         "driver hours within legal limit")
        self.assertEqual(orch.hitl_threshold_eur, 25000)
        self.assertEqual(len(orch.invariants), 2)
        self.assertEqual(orch.entry_points[0].id, "EP-CAP")
        self.assertEqual(orch.entities[0].name, "vehicle")
        self.assertIn("capacity_kg", orch.entities[0].fields)

    def test_cross_agent_edges(self):
        design = self._compile()
        coord = design.agent("logistics-coordinator")
        self.assertEqual(coord.delegates_to, ["fleet-orchestrator"])
        self.assertTrue(any(e.condition == "handoff:fleet-orchestrator"
                            for e in coord.edges))

    def test_schema_rejects_bad_state_id(self):
        with self.assertRaises(Exception):
            TechDesign(agents=[{
                "name": "bad-agent",
                "states": [{"id": "X99", "name": "bogus"}],
            }])

    # Module 3
    def test_review_gate_blocks_unapproved_and_validates(self):
        self._compile()
        self.assertFalse(review.is_approved(self.design_path))
        review.approve(self.design_path)
        self.assertTrue(review.is_approved(self.design_path))
        # tamper → approval invalidated (fail-closed)
        with open(self.design_path, "a", encoding="utf-8") as f:
            f.write("\n# tampered\n")
        self.assertFalse(review.is_approved(self.design_path))

    # Module 4
    def test_emit_writes_editable_zone_only(self):
        design = self._compile()
        review.approve(self.design_path)
        out = emit.emit_design(design, self.target)
        self.assertEqual(set(out), {"logistics-coordinator",
                                    "fleet-orchestrator", "customs-agent"})
        for name, files in out.items():
            ws = os.path.join(self.target, name)
            self.assertTrue(os.path.exists(os.path.join(ws, "GOAL.yaml")))
            for f in ("state.py", "tools.py", "prompts.py", "workflow.py", "__init__.py"):
                self.assertTrue(os.path.exists(os.path.join(ws, "src", "logic", f)),
                                f"{name}/{f}")
            # editable-zone + the locked runtime harness: nothing else
            root_files = set(os.listdir(ws))
            self.assertEqual(root_files, {"GOAL.yaml", "src", "agent.py"})

    def test_emitted_python_parses(self):
        import ast
        design = self._compile()
        review.approve(self.design_path)
        out = emit.emit_design(design, self.target)
        for files in out.values():
            for path in files:
                if path.endswith(".py"):
                    ast.parse(open(path, encoding="utf-8").read())

    def test_emitted_goal_matches_contract(self):
        import yaml
        design = self._compile()
        review.approve(self.design_path)
        emit.emit_design(design, self.target)
        goal = yaml.safe_load(open(os.path.join(
            self.target, "fleet-orchestrator", "GOAL.yaml"), encoding="utf-8"))
        self.assertTrue(goal["failClosed"])
        self.assertEqual(goal["sanitization"], "strict")
        self.assertEqual(goal["hitlThresholdEur"], 25000)
        self.assertIn("assign_vehicle", goal["allowedTools"])

    def test_emit_refuses_without_approval(self):
        design = self._compile()  # no approval
        import argparse
        ns = argparse.Namespace(design=self.design_path, target=self.target,
                                force=False, agent=None)
        with self.assertRaises(SystemExit):
            cli.cmd_emit(ns)

    def test_emit_refuses_kit_tree(self):
        design = self._compile()
        kit_src = os.path.join(os.path.expanduser("~/dm-agent-kit"), "src")
        with self.assertRaises(PermissionError):
            emit.emit_agent(design.agents[0], design, kit_src)

    def test_state_chain_and_edges_in_workflow(self):
        design = self._compile()
        review.approve(self.design_path)
        emit.emit_design(design, self.target)
        wf = open(os.path.join(self.target, "fleet-orchestrator",
                               "src", "logic", "workflow.py"), encoding="utf-8").read()
        self.assertIn("T01 → T05 → T07", wf)
        self.assertIn("EP-CAP", wf)
        self.assertIn("customs-agent", wf)  # handoff comment

    def test_workflow_emits_langgraph_stategraph(self):
        design = self._compile()
        review.approve(self.design_path)
        emit.emit_design(design, self.target)
        wf = open(os.path.join(self.target, "fleet-orchestrator",
                               "src", "logic", "workflow.py"), encoding="utf-8").read()
        self.assertIn("StateGraph(AgentState)", wf)
        self.assertIn("add_conditional_edges", wf)
        self.assertIn("def route(", wf)
        self.assertIn("set_entry_point('t01')", wf)
        self.assertIn('"t05": \'t07\'', wf)   # transition table
        self.assertIn('"t07": \'end\'', wf)   # terminal
        self.assertIn('return "hitl"', wf)   # HOLD → hitl branch

    def test_compile_writes_canonical_and_dashboard(self):
        import argparse
        self._ingest()
        ns = argparse.Namespace(spec_pack=self.spec_pack, design=self.design_path,
                                mesh_name="logistics-mesh",
                                dashboard=os.path.join(self.tmp, "architecture-dashboard.html"))
        rc = cli.cmd_compile(ns)
        self.assertEqual(rc, 0)
        for f in ("requirements.md", "entities.md", "entry-points.md"):
            self.assertTrue(os.path.exists(os.path.join(self.spec_pack, f)), f)
        self.assertTrue(os.path.exists(ns.dashboard))
        html = open(ns.dashboard, encoding="utf-8").read()
        self.assertIn("mermaid", html)
        self.assertIn("fleet-orchestrator", html)
        # re-compile must not re-ingest canonical files as specs
        rc2 = cli.cmd_compile(ns)
        self.assertEqual(rc2, 0)

    # CLI end-to-end (non-interactive, auto-approve)
    def test_cli_run_end_to_end(self):
        argv = ["run",
                "--incoming", os.path.join(FIXTURES, "incoming-specs"),
                "--spec-pack", self.spec_pack,
                "--design", self.design_path,
                "--target", self.target,
                "--yes"]
        rc = cli.main(argv)
        # verify stage may SKIP kit hooks on a bare host; 0 or 1 acceptable
        self.assertIn(rc, (0, 1))
        self.assertTrue(os.path.exists(
            os.path.join(self.target, "customs-agent", "src", "logic", "tools.py")))


class RichHtmlTest(unittest.TestCase):
    """Module 1/2 rich πd Genius HTML extraction + Module 4 rich emission."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="dmsc-rich-")
        self.spec_pack = os.path.join(self.tmp, "spec-pack")
        self.target = os.path.join(self.tmp, "agents")
        os.makedirs(self.spec_pack, exist_ok=True)
        self.incoming = os.path.join(FIXTURES, "incoming-rich")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _design(self):
        from dm_spec_compiler.cli import _collect_rich
        from dm_spec_compiler.design import compile_design_rich
        ingest_dir(self.incoming, self.spec_pack)
        texts = {f: open(os.path.join(self.spec_pack, f), encoding="utf-8").read()
                 for f in os.listdir(self.spec_pack) if f.endswith(".md")}
        return compile_design_rich(texts, _collect_rich(self.incoming),
                                   mesh_name="inventory-mesh")

    def test_rich_entity_and_state_extraction(self):
        a = self._design().agents[0]
        # entities with typed fields + scope
        inv = next(e for e in a.entities if e.name == "inventory_item")
        self.assertEqual(inv.scope, "v1")
        self.assertEqual(inv.owner, "Inventory Agent")
        typed = {tf.name: tf.type for tf in inv.typed_fields}
        self.assertEqual(typed.get("on_hand"), "integer")
        self.assertIn("version", typed)
        # states incl terminal flags
        term = {s.id for s in a.states if s.terminal}
        self.assertEqual(term, {"T05", "T06"})
        # transitions incl backward T10b + Any-wildcard T12
        tids = {t.id for t in a.transitions}
        self.assertIn("T10b", tids)
        self.assertIn("T12", tids)
        t10b = next(t for t in a.transitions if t.id == "T10b")
        self.assertEqual(t10b.from_state, "Available")
        self.assertEqual(t10b.to_state, "Counted")
        # holds + invariants
        self.assertEqual({h.hold_type for h in a.holds},
                         {"quality_hold", "cycle_count_hold"})
        inv_ids = {i.id for i in a.invariant_defs}
        self.assertEqual(inv_ids, {"I-01", "I-02", "I-03", "I-04"})

    def test_rich_entry_points_and_autonomy(self):
        a = self._design().agents[0]
        eps = {e.id: e for e in a.entry_points}
        self.assertIn("EP-RSV-01", eps)
        rsv = eps["EP-RSV-01"]
        self.assertEqual(rsv.kind, "command")
        self.assertEqual(rsv.transition, "Available -> Reserved")
        self.assertTrue(rsv.route.startswith("POST"))
        autos = rsv.autonomy_flags()
        self.assertIn("ai_decides", autos)
        self.assertIn("ai_suggests", autos)
        self.assertTrue(rsv.idempotency)
        # query EP
        self.assertEqual(eps["EP-QRY-01"].kind, "query")
        # one tool per EP
        ep_tools = {t.entry_point for t in a.tools if t.entry_point}
        self.assertIn("EP-RSV-01", ep_tools)

    def test_rich_ears_requirements(self):
        a = self._design().agents[0]
        ears = {e.id: e for e in a.ears_requirements}
        self.assertIn("REQ-01", ears)
        self.assertEqual(ears["REQ-01"].posture, "Automate")
        self.assertEqual(ears["REQ-02"].posture, "Detect + escalate")
        self.assertTrue(any(c.tag == "Unwanted"
                            for c in ears["REQ-02"].clauses))
        self.assertTrue(len(a.nfr_requirements) >= 2)

    def test_rich_emission_production_artifacts(self):
        import ast
        d = self._design()
        out = emit.emit_design(d, self.target)
        ws = os.path.join(self.target, d.agents[0].name)
        for f in out[d.agents[0].name]:
            if f.endswith(".py"):
                ast.parse(open(f, encoding="utf-8").read())
        st = open(os.path.join(ws, "src/logic/state.py")).read()
        self.assertIn("class InventoryItem", st)
        self.assertIn("active_holds", st)
        self.assertIn("version: int", st)
        self.assertIn("check_i_03", st)
        tp = open(os.path.join(ws, "src/logic/tools.py")).read()
        self.assertIn("_begin_idempotent", tp)
        self.assertIn("_check_version", tp)
        self.assertIn("_emit_outbox", tp)
        pp = open(os.path.join(ws, "src/logic/prompts.py")).read()
        self.assertIn("UNTRUSTED TEXT RULE", pp)
        self.assertIn("PROMPT_EP_RSV_01", pp)
        wf = open(os.path.join(ws, "src/logic/workflow.py")).read()
        self.assertIn("active_holds", wf)          # I-03
        self.assertIn("recount_requested", wf)     # I-04
        self.assertIn("needs_data", wf)

    def test_rich_runtime_live_pass(self):
        d = self._design()
        emit.emit_design(d, self.target)
        ws = os.path.join(self.target, d.agents[0].name)
        for flag in ("--self-test", "--mesh-test"):
            p = subprocess.run([sys.executable, "agent.py", flag], cwd=ws,
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0,
                             f"{flag} failed: {p.stdout}{p.stderr}")


if __name__ == "__main__":
    unittest.main()