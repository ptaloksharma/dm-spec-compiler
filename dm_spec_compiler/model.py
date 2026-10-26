"""TECH_DESIGN schema — the single validated intermediate artifact.

Everything the emitter writes is derived from one ``TechDesign`` instance that
passes pydantic validation. Deterministic extractors produce the raw fields;
an OPTIONAL LLM pass may propose summary text, but its output is validated
through this same schema (zero structural drift).
"""
from __future__ import annotations

import re
from typing import Optional

import yaml
from pydantic import BaseModel, Field, field_validator

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
_STATE_ID_RE = re.compile(r"^T\d{2}[a-z]?$")
_EP_ID_RE = re.compile(r"^EP-[A-Z0-9][A-Z0-9_-]{0,20}$")
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")
_INV_ID_RE = re.compile(r"^I-\d{2}$")


class StateDef(BaseModel):
    id: str
    name: str
    description: str = ""
    invariant: Optional[str] = None
    hold: bool = False
    terminal: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _STATE_ID_RE.match(v):
            raise ValueError(f"state id must look like T01..T99 (or T10b), got {v!r}")
        return v


class TransitionDef(BaseModel):
    """A labelled state-machine transition (from rich transition tables)."""
    id: str
    from_state: str           # may be "Any" for wildcard transitions
    to_state: str
    trigger: str = ""
    guard: str = ""
    effect: str = ""
    scenario: str = ""


class HoldDef(BaseModel):
    hold_type: str
    placed_by: str = ""
    scope: str = ""
    auto_release: str = ""
    on_release: str = ""


class InvariantDef(BaseModel):
    id: str                   # I-01..I-13
    rule: str

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _INV_ID_RE.match(v):
            raise ValueError(f"invariant id must look like I-01, got {v!r}")
        return v


class TypedField(BaseModel):
    name: str
    type: str = "str"
    note: str = ""


class ProcessingStep(BaseModel):
    text: str
    autonomy: str = "code"    # code | ai_suggests | ai_decides | person


class EarsClause(BaseModel):
    tag: str                  # Event | State | Unwanted | Ubiquitous
    text: str


class EntryPoint(BaseModel):
    id: str
    kind: str = "ingress"     # ingress | capture | schedule | handoff | command | event_handler | query
    description: str = ""
    target_state: Optional[str] = None
    name: str = ""
    proposed: bool = False
    transition: str = ""                # e.g. "Draft -> Submitted"
    route: str = ""                     # REST route / trigger
    input_schema: str = ""
    guards: list[str] = Field(default_factory=list)
    processing: list[ProcessingStep] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)   # outbox events
    errors: list[str] = Field(default_factory=list)
    idempotency: str = ""
    tests: list[str] = Field(default_factory=list)     # Given/When/Then

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _EP_ID_RE.match(v):
            raise ValueError(f"entry point id must look like EP-XXX, got {v!r}")
        return v

    def autonomy_flags(self) -> set[str]:
        return {s.autonomy for s in self.processing}


class ToolDef(BaseModel):
    name: str
    description: str = ""
    mutating: bool = False
    entry_point: Optional[str] = None   # EP id this tool implements
    kind: str = "command"               # command | event_handler | query

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _TOOL_RE.match(v):
            raise ValueError(f"tool name must be snake_case, got {v!r}")
        return v


class EntityDef(BaseModel):
    name: str
    table: Optional[str] = None
    fields: list[str] = Field(default_factory=list)          # legacy flat names
    typed_fields: list[TypedField] = Field(default_factory=list)
    owner: str = ""
    scope: str = ""                     # v1 | Later | Reference | Outside
    acts: list[str] = Field(default_factory=list)


class EdgeDef(BaseModel):
    from_state: str
    to_state: str
    condition: str = "always"


class EarsRequirement(BaseModel):
    id: str
    title: str = ""
    posture: str = ""                   # Automate | Detect + escalate | Reference | Assist
    clauses: list[EarsClause] = Field(default_factory=list)


class NfrRequirement(BaseModel):
    category: str
    requirement: str
    target: str = ""


class AgentDef(BaseModel):
    name: str
    role: str = "domain-agent"        # ui-coordinator | domain-agent | sub-agent
    tier: str = "fast-path"
    objective: str = ""
    use_case: str = ""
    states: list[StateDef] = Field(default_factory=list)
    transitions: list[TransitionDef] = Field(default_factory=list)
    holds: list[HoldDef] = Field(default_factory=list)
    invariant_defs: list[InvariantDef] = Field(default_factory=list)
    entry_points: list[EntryPoint] = Field(default_factory=list)
    tools: list[ToolDef] = Field(default_factory=list)
    entities: list[EntityDef] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    ears_requirements: list[EarsRequirement] = Field(default_factory=list)
    nfr_requirements: list[NfrRequirement] = Field(default_factory=list)
    edges: list[EdgeDef] = Field(default_factory=list)
    hitl_threshold_eur: Optional[int] = None
    allowed_egress: list[str] = Field(default_factory=list)
    delegates_to: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(f"agent name must be kebab-case, got {v!r}")
        return v

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        allowed = {"ui-coordinator", "domain-agent", "sub-agent"}
        if v not in allowed:
            raise ValueError(f"role must be one of {sorted(allowed)}, got {v!r}")
        return v


class TechDesign(BaseModel):
    schema_version: str = "dm-spec-compiler/v1"
    mesh_name: str = "spec-mesh"
    agents: list[AgentDef]
    source_docs: list[str] = Field(default_factory=list)
    source_hashes: dict[str, str] = Field(default_factory=dict)

    def agent(self, name: str) -> AgentDef:
        for a in self.agents:
            if a.name == name:
                return a
        raise KeyError(name)

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            self.model_dump(mode="json"), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, text: str) -> "TechDesign":
        return cls.model_validate(yaml.safe_load(text))
