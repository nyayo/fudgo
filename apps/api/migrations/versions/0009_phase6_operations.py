"""0009: Phase 6 -- admin role, notifications, payouts, payout_attempts, audit_log."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID


revision = "0009_phase6_operations"
down_revision = "0008_order_number_length"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. users.is_admin + usertype 'admin' enum value
    op.add_column(
        "users",
        sa.Column(
            "is_admin", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index("ix_users_is_admin", "users", ["is_admin"])
    op.execute("ALTER TYPE usertype ADD VALUE IF NOT EXISTS 'admin'")

    # 2. Enum types (idempotent)
    for name, values in [
        ("payoutstatus", ("scheduled", "processing", "completed", "failed", "cancelled")),
        ("payoutattemptstatus", ("initiated", "succeeded", "failed")),
        ("payoutmethod", ("mpesa_b2c", "stripe_connect")),
        ("auditlogaction", (
            "user_suspended", "user_reinstated", "restaurant_approved",
            "restaurant_suspended", "payment_refunded_manually",
            "payout_triggered_manually", "payout_cancelled",
            "order_cancelled_manually", "notification_broadcast",
        )),
    ]:
        vals = ",".join(f"'{v}'" for v in values)
        op.execute(
            f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({vals}); "
            f"EXCEPTION WHEN duplicate_object THEN null; END $$"
        )

    # 3. notifications table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
          id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          user_id UUID NOT NULL REFERENCES users(id),
          event_type VARCHAR(50) NOT NULL,
          message TEXT NOT NULL,
          order_id UUID REFERENCES orders(id),
          is_read BOOLEAN NOT NULL DEFAULT false,
          redirect_url VARCHAR(500),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_read_created "
        "ON notifications (user_id, is_read, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_order "
        "ON notifications (order_id)"
    )

    # 4. payouts table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payouts (
          id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          order_id UUID REFERENCES orders(id),
          delivery_id UUID REFERENCES deliveries(id),
          restaurant_id UUID REFERENCES restaurant_profiles(id),
          courier_id UUID REFERENCES courier_profiles(id),
          method VARCHAR(20) NOT NULL DEFAULT 'mpesa_b2c',
          status payoutstatus NOT NULL DEFAULT 'scheduled',
          gross_amount NUMERIC(10,2) NOT NULL,
          platform_fee NUMERIC(10,2) NOT NULL DEFAULT 0.00,
          net_amount NUMERIC(10,2) NOT NULL,
          mpesa_phone_e164 VARCHAR(20),
          mpesa_occasion VARCHAR(100),
          scheduled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          processed_at TIMESTAMPTZ,
          completed_at TIMESTAMPTZ,
          failed_at TIMESTAMPTZ,
          failure_reason VARCHAR(500),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payouts_restaurant_status "
        "ON payouts (restaurant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payouts_courier_status "
        "ON payouts (courier_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payouts_status_scheduled "
        "ON payouts (status, scheduled_at)"
    )

    # 5. payout_attempts table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payout_attempts (
          id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          payout_id UUID NOT NULL REFERENCES payouts(id),
          attempt_number INTEGER NOT NULL DEFAULT 1,
          status VARCHAR(20) NOT NULL DEFAULT 'initiated',
          mpesa_transaction_id VARCHAR(200),
          mpesa_conversation_id VARCHAR(200),
          request_payload JSONB,
          response_payload JSONB,
          error_code VARCHAR(50),
          error_message VARCHAR(500),
          initiated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          failed_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payout_attempts_payout "
        "ON payout_attempts (payout_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_payout_attempts_status "
        "ON payout_attempts (status)"
    )

    # 6. audit_log table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
          id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          actor_user_id UUID NOT NULL REFERENCES users(id),
          action auditlogaction NOT NULL,
          target_type VARCHAR(50) NOT NULL,
          target_id VARCHAR(100) NOT NULL,
          details JSONB NOT NULL DEFAULT '{}'::jsonb,
          ip_address VARCHAR(64),
          user_agent VARCHAR(500),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_log_actor_created "
        "ON audit_log (actor_user_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_log_action_target "
        "ON audit_log (action, target_type, target_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP TABLE IF EXISTS payout_attempts")
    op.execute("DROP TABLE IF EXISTS payouts")
    op.execute("DROP TABLE IF EXISTS notifications")
    op.drop_index("ix_users_is_admin", table_name="users")
    op.drop_column("users", "is_admin")
    # PG cannot remove enum values; leave the added enum values in place.
