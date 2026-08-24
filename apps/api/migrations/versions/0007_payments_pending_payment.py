"""0007: payments -- PENDING_PAYMENT order state, payment_attempts, payment_webhook_events, currency column.

Hand-written because Alembic autogenerator can't reliably detect ALTER TYPE
add-value (PostgreSQL needs ``ALTER TYPE orderstatus ADD VALUE``).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID


revision = "0007_payments_pending_payment"
down_revision = "0007_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add PENDING_PAYMENT to the orderstatus enum.
    op.execute("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'pending_payment'")

    # 2. Add the paymentattemptstatus + webhookprovider enum types.
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE paymentattemptstatus AS ENUM ("
        "'initiated','requires_action','succeeded','failed','cancelled'"
        "); EXCEPTION WHEN duplicate_object THEN null; END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE webhookprovider AS ENUM ('stripe','mpesa'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$"
    )

    # 3. Add `currency` to payments. (`refunded_at` already exists from Phase 3.)
    op.add_column(
        "payments",
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="KES"),
    )

    # 4. Create payment_attempts table.
    op.create_table(
        "payment_attempts",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("payment_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "method",
            sa.String(length=16),
            nullable=False,
            server_default="stub",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="initiated",
        ),
        sa.Column("stripe_payment_intent_id", sa.String(length=200), nullable=True),
        sa.Column("stripe_client_secret", sa.String(length=500), nullable=True),
        sa.Column("mpesa_checkout_request_id", sa.String(length=200), nullable=True),
        sa.Column("mpesa_merchant_request_id", sa.String(length=200), nullable=True),
        sa.Column("mpesa_phone_e164", sa.String(length=20), nullable=True),
        sa.Column("request_payload", JSONB, nullable=True),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "payment_id", "idempotency_key",
            name="uq_payment_attempts_payment_idempotency_key",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"],
            name="fk_payment_attempts_payment_id",
        ),
    )
    op.create_index(
        "ix_payment_attempts_payment", "payment_attempts", ["payment_id"]
    )
    op.create_index(
        "ix_payment_attempts_status", "payment_attempts", ["status"]
    )
    op.create_index(
        "ix_payment_attempts_stripe_payment_intent",
        "payment_attempts",
        ["stripe_payment_intent_id"],
    )
    op.create_index(
        "ix_payment_attempts_mpesa_checkout_request",
        "payment_attempts",
        ["mpesa_checkout_request_id"],
    )

    # 5. Create payment_webhook_events table.
    op.create_table(
        "payment_webhook_events",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "provider",
            sa.String(length=16),
            nullable=False,
            server_default="stripe",
        ),
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "provider", "event_id", name="uq_webhook_provider_event_id"
        ),
    )
    op.create_index(
        "ix_payment_webhook_events_received_at",
        "payment_webhook_events",
        ["received_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_webhook_events_received_at", table_name="payment_webhook_events"
    )
    op.drop_table("payment_webhook_events")
    op.drop_index("ix_payment_attempts_mpesa_checkout_request", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_stripe_payment_intent", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_status", table_name="payment_attempts")
    op.drop_index("ix_payment_attempts_payment", table_name="payment_attempts")
    op.drop_table("payment_attempts")
    op.drop_column("payments", "currency")
    # Removing enum values from PG is awkward; leave the types in place.
    # (Reversing ALTER TYPE ADD VALUE requires creating a new type.)
