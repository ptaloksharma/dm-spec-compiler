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
_STATE_ID_RE = re.compile(r"^T\d{2}$")
_EP_ID_RE = re.compile(r"^EP-[A-Z0-9][A-Z0-9_-]{0,20}$")
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")


class StateDef(BaseModel):
    id: str
    name: str
    description: str = ""
    invariant: Optional[str] = None
    hold: bool = False

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _STATE_ID_RE.match(v):
            raise ValueError(f"state id must look like T01..T99, got {v!r}")
        return v


class EntryPoint(BaseModel):
    id: str
    kind: str = "ingress"  # ingress | capture | schedule | handoff
    description: str = ""
    target_state: Optional[str] = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _EP_ID_RE.match(v):
            raise ValueError(f"entry point id must look like EP-XXX, got {v!r}")
        return v


class ToolDef(BaseModel):
    name: str
    description: str = ""
    mutating: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not _TOOL_RE.match(v):
            raise ValueError(f"tool name must be snake_case, got {v!r}")
        return v


class EntityDef(BaseModel):
    name: str
    table: Optional[str] = None
    fields: list[str] = Field(default_factory=list)


class EdgeDef(BaseModel):
    from_state: str
    to_state: str
    condition: str = "always"


class AgentDef(BaseModel):
    name: str
    role: str = "domain-agent"        # ui-coordinator | domain-agent | sub-agent
    tier: str = "fast-path"
    objective: str = ""
    use_case: str = ""
    states: list[StateDef] = Field(default_factory=list)
    entry_points: list[EntryPoint] = Field(default_factory=list)
    tools: list[ToolDef] = Field(default_factory=list)
    entities: list[EntityDef] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
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
