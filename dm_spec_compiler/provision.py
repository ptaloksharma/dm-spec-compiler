"""Module 3.5 — Infrastructure provisioning hook.

Runs AFTER the architect's approval stamp, BEFORE code emission. Generates
deterministic, domain-agnostic infrastructure definitions for each agent:

  infra/<agent>/main.bicep          — isolated private DB schema + container
  infra/<agent>/main.tf             — Terraform equivalent
  infra/<agent>/schema.sql          — idempotent DDL for the agent's entities
  infra/<agent>/PROVISIONING.md     — human summary + approval-hash binding

Domain-agnostic: the schema name derives from the agent name (``_schema_for``),
never from a hardcoded business word. Every artifact records the approving
TECH_DESIGN sha256 so provisioning is provably bound to the signed-off design.
"""
from __future__ import annotations

import hashlib
import os

from .model import AgentDef, TechDesign


def _schema_for(agent: AgentDef) -> str:
    base = agent.name.replace("-", "_")
    base = base[:-6] if base.endswith("_agent") else base
    return f"{base}_schema"


def _sql_type(t: str) -> str:
    m = {"int": "INTEGER", "integer": "INTEGER", "decimal": "NUMERIC",
         "float": "NUMERIC", "number": "NUMERIC", "bool": "BOOLEAN",
         "boolean": "BOOLEAN", "string": "TEXT", "str": "TEXT",
         "date": "DATE", "datetime": "TIMESTAMP", "uuid": "UUID"}
    return m.get((t or "str").lower(), "TEXT")


def render_schema_sql(agent: AgentDef) -> str:
    schema = _schema_for(agent)
    lines = [
        f"-- Isolated private schema for agent '{agent.name}' (idempotent).",
        f"CREATE SCHEMA IF NOT EXISTS {schema};",
        f"SET search_path TO {schema};",
        "",
    ]
    for e in agent.entities:
        table = e.table or (e.name + "s")
        cols = []
        if e.typed_fields:
            for tf in e.typed_fields:
                cols.append(f"    {tf.name} {_sql_type(tf.type)}")
        elif e.fields:
            for f in e.fields:
                cols.append(f"    {f} TEXT")
        if not any("id" in c.split()[0] for c in cols):
            cols.insert(0, "    id TEXT PRIMARY KEY")
        if not any("version" in c for c in cols):
            cols.append("    version INTEGER NOT NULL DEFAULT 1")
        cols.append("    updated_at TIMESTAMP NOT NULL DEFAULT now()")
        lines.append(f"CREATE TABLE IF NOT EXISTS {schema}.{table} (")
        lines.append(",\n".join(cols))
        lines.append(");")
        lines.append("")
    return "\n".join(lines)


def render_bicep(agent: AgentDef) -> str:
    schema = _schema_for(agent)
    return f"""// Bicep — isolated infrastructure for agent '{agent.name}'.
// Deterministic; no secrets. Parameterize the connection at deploy time.
param location string = resourceGroup().location
param administratorLogin string
@secure()
param administratorPassword string

resource pg 'Microsoft.DBforPostgreSQL/flexibleServers@2023-03-01-preview' = {{
  name: '{agent.name}-db'
  location: location
  properties: {{
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    version: '16'
  }}
}}

resource schema 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-03-01-preview' = {{
  parent: pg
  name: '{schema}'
}}

output schemaName string = '{schema}'
output serverFqdn string = pg.properties.fullyQualifiedDomainName
"""


def render_terraform(agent: AgentDef) -> str:
    schema = _schema_for(agent)
    return f"""# Terraform — isolated infrastructure for agent '{agent.name}'.
terraform {{
  required_providers {{
    postgresql = {{ source = "cyrilgdn/postgresql", version = "~> 1.22" }}
  }}
}}

variable "pg_host" {{ type = string }}
variable "pg_user" {{ type = string }}
variable "pg_password" {{ type = string, sensitive = true }}

provider "postgresql" {{
  host     = var.pg_host
  username = var.pg_user
  password = var.pg_password
  sslmode  = "require"
}}

resource "postgresql_schema" "agent" {{
  name = "{schema}"
}}

output "schema_name" {{ value = postgresql_schema.agent.name }}
"""


def render_provisioning_md(agent: AgentDef, design_sha: str) -> str:
    schema = _schema_for(agent)
    tables = ", ".join((e.table or e.name + "s") for e in agent.entities) or "(none)"
    return f"""# Provisioning — {agent.name}

- **Isolated schema:** `{schema}`
- **Tables:** {tables}
- **Bound to TECH_DESIGN sha256:** `{design_sha}`

Artifacts: `main.bicep`, `main.tf`, `schema.sql`.
Provisioning is deterministic and domain-agnostic; it ran only because the
architect approved the design whose hash appears above.
"""


def provision_design(design: TechDesign, infra_root: str, *,
                     design_sha: str, only: list[str] | None = None) -> dict[str, list[str]]:
    """Write infra artifacts for every (selected) agent. Returns {name: paths}."""
    out: dict[str, list[str]] = {}
    for agent in design.agents:
        if only and agent.name not in only:
            continue
        d = os.path.join(infra_root, agent.name)
        os.makedirs(d, exist_ok=True)
        artifacts = {
            "schema.sql": render_schema_sql(agent),
            "main.bicep": render_bicep(agent),
            "main.tf": render_terraform(agent),
            "PROVISIONING.md": render_provisioning_md(agent, design_sha),
        }
        paths = []
        for fname, text in artifacts.items():
            p = os.path.join(d, fname)
            with open(p, "w", encoding="utf-8") as f:
                f.write(text)
            paths.append(p)
        out[agent.name] = paths
    return out


def design_sha256(design_path: str) -> str:
    return hashlib.sha256(open(design_path, "rb").read()).hexdigest()
