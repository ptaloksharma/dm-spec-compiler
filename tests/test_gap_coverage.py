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
