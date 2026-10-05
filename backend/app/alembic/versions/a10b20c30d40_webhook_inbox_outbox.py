"""Durable catalog inbox/outbox; additive to the upstream Item application."""
from alembic import op

revision = "a10b20c30d40"
down_revision = "fe56fa70289e"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
    CREATE TABLE webhook_entity (
        external_id varchar(80) PRIMARY KEY,
        item_id uuid NOT NULL UNIQUE REFERENCES item(id) ON DELETE RESTRICT,
        version integer NOT NULL CHECK (version > 0),
        content_hash char(64) NOT NULL
    );
    CREATE TABLE webhook_inbox (
        event_id varchar(80) PRIMARY KEY,
        external_id varchar(80) NOT NULL,
        version integer NOT NULL CHECK (version > 0),
        body_hash char(64) NOT NULL,
        outcome varchar(16) NOT NULL CHECK (outcome IN ('applied','stale','unchanged')),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    CREATE TABLE webhook_outbox (
        id uuid PRIMARY KEY,
        event_id varchar(80) NOT NULL UNIQUE REFERENCES webhook_inbox(event_id),
        payload jsonb NOT NULL,
        state varchar(16) NOT NULL DEFAULT 'pending'
            CHECK (state IN ('pending','delivering','retry','delivered','dead')),
        attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
        available_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        lease_until timestamptz,
        lease_token uuid,
        last_error varchar(80),
        created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
        delivered_at timestamptz
    );
    CREATE INDEX webhook_outbox_due ON webhook_outbox(available_at, created_at)
        WHERE state IN ('pending','retry','delivering');
    CREATE TABLE webhook_audit (
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        outbox_id uuid NOT NULL REFERENCES webhook_outbox(id),
        action varchar(40) NOT NULL,
        actor varchar(80) NOT NULL,
        reason varchar(500) NOT NULL,
        created_at timestamptz NOT NULL DEFAULT clock_timestamp()
    );
    """)


def downgrade():
    op.execute("""
    DROP TABLE webhook_audit;
    DROP TABLE webhook_outbox;
    DROP TABLE webhook_inbox;
    DROP TABLE webhook_entity;
    """)
