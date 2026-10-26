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
            # editable-zone only: no stray files at workspace root
            root_files = set(os.listdir(ws))
            self.assertEqual(root_files, {"GOAL.yaml", "src"})

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


if __name__ == "__main__":
    unittest.main()
