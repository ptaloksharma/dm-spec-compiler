-- Isolated private schema for agent 'fleet-orchestrator' (idempotent).
CREATE SCHEMA IF NOT EXISTS fleet_orchestrator_schema;
SET search_path TO fleet_orchestrator_schema;

CREATE TABLE IF NOT EXISTS fleet_orchestrator_schema.vehicles (
    id TEXT,
    plate TEXT,
    capacity_kg TEXT,
    status TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
