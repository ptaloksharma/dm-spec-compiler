"""dm-spec-compiler — standalone universal spec-to-code & architecture compiler.

Ingests raw spec packs (HTML / Markdown / PDF) from a local incoming dir,
parses them DETERMINISTICALLY (no LLM codegen), compiles a validated
TECH_DESIGN.yaml, runs an Architect-in-the-Loop review gate, then emits the
dm-agent-kit editable zone (GOAL.yaml + src/logic/{state,tools,workflow,prompts}.py)
into a target agent workspace — never touching the core kit repo.
"""
from . import _kitpath  # noqa: F401  (must be first — wires the kit onto sys.path)

__version__ = "0.1.0"
