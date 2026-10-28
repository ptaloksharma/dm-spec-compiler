"""Gap-coverage tests (Phase 2): pin the unpinned v0.5.0/v0.5.1 code paths.

Covers modules/seams with no dedicated tests:
  - plugin_api.py     — the JSON/dict seam consumed by dm-agent CLI + Buddy UI
  - htmlspec.py       — deterministic rich DOM extraction (3 shapes)
  - emit_rich.py      — production template renderers (state/tools/prompts/workflow)
  - provision --apply — receipt sealing + fail-closed binary/DB guards
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.expanduser("~/dm-spec-compiler"))

from dm_spec_compiler import plugin_api, provision
from dm_spec_compiler.cli import _collect_rich
from dm_spec_compiler.design import compile_design_rich
from dm_spec_compiler.htmlspec import extract_rich
from dm_spec_compiler.model import TechDesign
from dm_spec_compiler.provision import ApplyError

FIX_RICH = os.path.expanduser("~/dm-spec-compiler/tests/fixtures/incoming-rich")


def _design() -> TechDesign:
    rich = _collect_rich(FIX_RICH)
    return compile_design_rich({}, rich, mesh_name="inventory-mesh")


class PluginApiSeamTest(unittest.TestCase):
    """The plugin_api JSON envelope contract consumed by external callers."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="gap-api-")
        self.design_path = os.path.join(self.tmp, "TECH_DESIGN.yaml")
        with open(self.design_path, "w", encoding="utf-8") as f:
            f.write(_design().to_yaml())

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_envelope_shape(self) -> None:
        """Every plugin_api call returns {status, data|error, metadata}."""
        res = plugin_api.api_review_status(self.design_path)
        self.assertIn("status", res)
        self.assertIn(res["status"], ("ok", "error", "blocked", "skipped"))

    def test_missing_design_returns_error_not_exception(self) -> None:
        res = plugin_api.api_review_status(os.path.join(self.tmp, "nope.yaml"))
        self.assertEqual(res["status"], "error")
        self.assertIn("not found", res["error"])

    def test_provision_blocked_without_approval(self) -> None:
        """api_provision must be blocked (not error) when unapproved."""
        res = plugin_api.api_provision(self.design_path, os.path.join(self.tmp, "infra"))
        self.assertEqual(res["status"], "blocked")

    def test_emit_blocked_without_approval(self) -> None:
        res = plugin_api.api_emit(self.design_path, os.path.join(self.tmp, "agents"))
        self.assertEqual(res["status"], "blocked")

    def test_ingest_counts_and_rich_detection(self) -> None:
        sp = os.path.join(self.tmp, "spec-pack")
        res = plugin_api.api_ingest(FIX_RICH, sp)
        self.assertEqual(res["status"], "ok")
        self.assertGreaterEqual(res["data"]["total_files"], 1)
        self.assertGreaterEqual(len(res["data"]["rich_packs"]), 1)


class HtmlSpecExtractionTest(unittest.TestCase):
    """Deterministic DOM extraction — zero LLM guessing."""

    def test_three_rich_shapes_detected(self) -> None:
        kinds = set()
        for fname in sorted(os.listdir(FIX_RICH)):
            if fname.endswith(".html"):
                raw = open(os.path.join(FIX_RICH, fname), encoding="utf-8").read()
                r = extract_rich(fname, raw)
                if r:
                    kinds.add(r["__kind__"])
        self.assertIn("entity_state", kinds)
        self.assertIn("entry_points", kinds)
        self.assertIn("requirements", kinds)

    def test_extraction_is_deterministic(self) -> None:
        """Same input → identical output across runs (no sampling)."""
        fname = sorted(os.listdir(FIX_RICH))[0]
        raw = open(os.path.join(FIX_RICH, fname), encoding="utf-8").read()
        a = extract_rich(fname, raw)
        b = extract_rich(fname, raw)
        self.assertEqual(a, b)


class EmitRichTemplateTest(unittest.TestCase):
    """Production template renderers produce parseable, guarded code."""

    def test_state_has_active_validators(self) -> None:
        from dm_spec_compiler import emit_rich
        agent = _design().agents[0]
        out = emit_rich.render_state(agent)
        self.assertIn("def check_all_invariants", out)
        self.assertIn("class Violation", out)
        self.assertIn("list[Violation]", out)

    def test_workflow_has_invariant_gate(self) -> None:
        from dm_spec_compiler import emit_rich
        d = _design()
        out = emit_rich.render_workflow(d.agents[0], d)
        self.assertIn("def invariant_gate", out)
        self.assertIn("exception", out)
        import ast
        ast.parse(out)  # must be valid Python


class ProvisionApplyReceiptTest(unittest.TestCase):
    """--apply receipt sealing + fail-closed guards."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="gap-prov-")
        self.d = _design()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_apply_fails_closed_without_database_url(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        with self.assertRaises(ApplyError):
            provision.provision_design(self.d, self.tmp, design_sha="x", apply=True, env=env)

    def test_no_receipt_without_apply(self) -> None:
        out = provision.provision_design(self.d, self.tmp, design_sha="x")
        md = open(os.path.join(self.tmp, self.d.agents[0].name, "PROVISIONING.md")).read()
        self.assertNotIn("Live Apply Receipt", md)

    def test_applyerror_is_fail_closed_runtime_error(self) -> None:
        self.assertTrue(issubclass(ApplyError, RuntimeError))


if __name__ == "__main__":
    unittest.main()

def test_emit_preserves_handwritten_logic_below_sentinel(tmp_path):
    """Option A: re-emission regenerates plumbing but preserves hand-written
    code below the sentinel preserve-marker (emit.py docstring contract)."""
    from dm_spec_compiler.cli import _collect_rich
    from dm_spec_compiler.design import compile_design_rich
    from dm_spec_compiler import emit
    rich = _collect_rich(str(FIX_RICH))
    d = compile_design_rich({}, rich, mesh_name="inventory-mesh")
    a = d.agents[0]
    tgt = str(tmp_path / "agents")

    emit.emit_design(d, tgt)  # first emission
    wf = os.path.join(tgt, a.name, "src", "logic", "tools.py")
    assert emit._PRESERVE_MARKER in open(wf).read()

    # hand-edit below the sentinel, then re-emit
    with open(wf, "a") as f:
        f.write("\n\ndef my_custom_helper(x):\n    return x * 2\n")
    emit.emit_design(d, tgt)
    v2 = open(wf).read()
    assert "my_custom_helper" in v2            # hand-written logic survives
    assert "TOOLS" in v2 and "echo" in v2       # plumbing regenerated
    assert v2.count(emit._PRESERVE_MARKER) == 1  # idempotent marker


def test_emit_preserves_workflow_handwritten_block(tmp_path):
    from dm_spec_compiler.cli import _collect_rich
    from dm_spec_compiler.design import compile_design_rich
    from dm_spec_compiler import emit
    rich = _collect_rich(str(FIX_RICH))
    d = compile_design_rich({}, rich, mesh_name="inventory-mesh")
    a = d.agents[0]
    tgt = str(tmp_path / "agents")
    emit.emit_design(d, tgt)
    wp = os.path.join(tgt, a.name, "src", "logic", "workflow.py")
    with open(wp, "a") as f:
        f.write("\nCUSTOM_WORKFLOW_HOOK = True\n")
    emit.emit_design(d, tgt)
    wv = open(wp).read()
    assert "CUSTOM_WORKFLOW_HOOK" in wv and "build_graph" in wv

# --------------------------------------------------------------------------- #
# Token estimator (deterministic static analysis) + expanded refine grammar
# --------------------------------------------------------------------------- #
def _rich_design():
    from dm_spec_compiler.cli import _collect_rich
    from dm_spec_compiler.design import compile_design_rich
    return compile_design_rich({}, _collect_rich(str(FIX_RICH)), mesh_name="inventory-mesh")


def test_token_estimator_deterministic_and_structured():
    from dm_spec_compiler.token_estimator import estimate_tokens
    d = _rich_design()
    est = estimate_tokens(d)
    assert est["build_tokens"] > 0
    assert est["expected_run_tokens"] > 0
    assert est["max_loop_tokens"] >= est["expected_run_tokens"]
    # deepseek cheaper than frontier baseline
    assert est["cost_per_1000_runs"]["deepseek"]["expected"] < \
        est["cost_per_1000_runs"]["frontier"]["expected"]
    # per-node rows match state count and carry prompt+est
    ag = est["agents"][0]
    assert len(ag["per_node"]) == ag["states"]
    assert all(r["prompt_tokens"] >= 0 and r["est_tokens"] > 0 for r in ag["per_node"])
    # deterministic: same design -> identical numbers
    assert estimate_tokens(d)["expected_run_tokens"] == est["expected_run_tokens"]


def test_api_tokens_endpoint(tmp_path):
    from dm_spec_compiler.plugin_api import api_tokens
    d = _rich_design()
    dp = tmp_path / "TECH_DESIGN.yaml"
    dp.write_text(d.to_yaml())
    res = api_tokens(str(dp))
    assert res["status"] == "ok"
    assert res["data"]["expected_run_tokens"] > 0
    assert "cost_per_1000_runs" in res["data"]


def test_api_events_ring_buffer():
    from dm_spec_compiler.events import emit_event, recent, unread_alert_count
    emit_event("WIZARD", "test event")
    emit_event("GUARDRAIL", "blocked thing", level="block")
    res = recent(limit=10)
    assert res and res[0]["channel"] == "GUARDRAIL"
    assert unread_alert_count() >= 1
    from dm_spec_compiler.plugin_api import api_events
    r = api_events(limit=10)
    assert r["status"] == "ok" and "events" in r["data"]


def test_refine_add_transition(tmp_path):
    from dm_spec_compiler import refine
    d = _rich_design()
    dp = tmp_path / "TECH_DESIGN.yaml"
    dp.write_text(d.to_yaml())
    n = len(d.agents[0].transitions)
    r = refine.refine_design_file(str(dp), "add a transition Planned -> Approved when signed")
    assert r["ok"]
    from dm_spec_compiler.model import TechDesign
    d2 = TechDesign.from_yaml(dp.read_text())
    assert len(d2.agents[0].transitions) == n + 1


def test_refine_remove_state_and_tool(tmp_path):
    from dm_spec_compiler import refine
    from dm_spec_compiler.model import TechDesign
    d = _rich_design()
    dp = tmp_path / "TECH_DESIGN.yaml"
    dp.write_text(d.to_yaml())
    a = d.agents[0]
    some_state = a.states[1].name
    n_states = len(a.states)
    r = refine.refine_design_file(str(dp), f"remove state {some_state}")
    assert r["ok"]
    d2 = TechDesign.from_yaml(dp.read_text())
    assert len(d2.agents[0].states) == n_states - 1
    # remove a tool
    if d2.agents[0].tools:
        tname = d2.agents[0].tools[0].name
        n_tools = len(d2.agents[0].tools)
        r2 = refine.refine_design_file(str(dp), f"remove tool {tname}")
        assert r2["ok"]
        assert len(TechDesign.from_yaml(dp.read_text()).agents[0].tools) == n_tools - 1
    # removing a missing state fails closed
    r3 = refine.refine_design_file(str(dp), "remove state NoSuchStateXYZ")
    assert r3["ok"] is False

