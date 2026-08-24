CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS extension_status (
    name TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'quarantined')),
    expected_version INTEGER NOT NULL DEFAULT 1,
    updated_by TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    command_id TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS catalog_publications (
    id BIGSERIAL PRIMARY KEY,
    catalog_digest TEXT NOT NULL,
    capability_count INTEGER NOT NULL,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invocation_audit (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    tenant_id TEXT NOT NULL,
    capability TEXT,
    method TEXT NOT NULL,
    digest TEXT,
    decision TEXT NOT NULL,
    outcome TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    invocation_id TEXT
);

CREATE INDEX IF NOT EXISTS invocation_audit_occurred_at_idx
    ON invocation_audit (occurred_at DESC);
