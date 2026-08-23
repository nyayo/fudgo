"""0007: deliveries + courier_locations + courier last_heartbeat_at + order_number_seq.

PostgreSQL native enum types created with the Phase 1 convention:
lowercase, no underscores (``deliverystatus``, ``locationprovider``).

Manual op for:
- CREATE SEQUENCE order_number_seq (replaces the racy COUNT(*)+1 from Phase 3)
- Partial GIST index on courier_profiles.current_location WHERE is_available = true
- Partial index on orders.idempotency_key WHERE idempotency_key IS NOT NULL
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


revision = "0007_deliveries"
down_revision = "0006_carts_orders_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ----------------------------------------------------------------
    # 1. order_number_seq sequence (Phase 3 hot-fix)
    # ----------------------------------------------------------------
    op.execute("CREATE SEQUENCE IF NOT EXISTS order_number_seq START 1 INCREMENT 1 NO CYCLE")

    # Partial index on orders.idempotency_key (only non-NULL values)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orders_idempotency_key_partial "
        "ON orders (idempotency_key) WHERE idempotency_key IS NOT NULL"
    )

    # ----------------------------------------------------------------
    # 2. courier_profiles.last_heartbeat_at
    # ----------------------------------------------------------------
    op.add_column(
        "courier_profiles",
        sa.Column(
            "last_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_courier_profiles_last_heartbeat_at",
        "courier_profiles",
        ["last_heartbeat_at"],
    )

    # ----------------------------------------------------------------
    # 3. Enum types
    # ----------------------------------------------------------------
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE deliverystatus AS ENUM ("
        "'assigned','en_route_pickup','arrived_at_pickup',"
        "'picked_up','en_route_delivery','delivered','failed','cancelled'"
        "); EXCEPTION WHEN duplicate_object THEN null; END $$"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE locationprovider AS ENUM ('gps','network','manual'); "
        "EXCEPTION WHEN duplicate_object THEN null; END $$"
    )

    # ----------------------------------------------------------------
    # 4. deliveries table
    # ----------------------------------------------------------------
    op.create_table(
        "deliveries",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("order_id", PG_UUID(as_uuid=True), nullable=False),
        sa.Column("courier_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "assigned",
                "en_route_pickup",
                "arrived_at_pickup",
                "picked_up",
                "en_route_delivery",
                "delivered",
                "failed",
                "cancelled",
                name="deliverystatus",
                create_type=False,
            ),
            nullable=False,
            server_default="assigned",
        ),
        sa.Column("pickup_address", sa.String(length=500), nullable=False),
        sa.Column("pickup_lat", sa.Float(), nullable=False),
        sa.Column("pickup_lng", sa.Float(), nullable=False),
        sa.Column("dropoff_address", sa.String(length=500), nullable=False),
        sa.Column("dropoff_lat", sa.Float(), nullable=False),
        sa.Column("dropoff_lng", sa.Float(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("en_route_pickup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arrived_at_pickup_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("en_route_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proof_image_url", sa.String(length=500), nullable=True),
        sa.Column("proof_notes", sa.Text(), nullable=True),
        sa.Column("failure_reason", sa.String(length=500), nullable=True),
        sa.Column("cancelled_reason", sa.String(length=500), nullable=True),
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
        sa.UniqueConstraint("order_id", name="uq_deliveries_order_id"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name="fk_deliveries_order_id"),
        sa.ForeignKeyConstraint(
            ["courier_id"], ["courier_profiles.id"], name="fk_deliveries_courier_id"
        ),
    )
    op.create_index("ix_deliveries_order_id", "deliveries", ["order_id"])
    op.create_index("ix_deliveries_courier_id", "deliveries", ["courier_id"])
    op.create_index(
        "ix_deliveries_courier_status", "deliveries", ["courier_id", "status"]
    )
    op.create_index("ix_deliveries_status", "deliveries", ["status"])

    # ----------------------------------------------------------------
    # 5. courier_locations table
    # ----------------------------------------------------------------
    # PostGIS geography column via raw SQL (alembic + geoalchemy2 + op.execute)
    op.execute(
        "CREATE EXTENSION IF NOT EXISTS postgis"
    )
    op.execute(
        "CREATE TABLE courier_locations ("
        "  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),"
        "  courier_id UUID NOT NULL REFERENCES courier_profiles(id),"
        "  location geography(POINT, 4326) NOT NULL,"
        "  heading_degrees DOUBLE PRECISION,"
        "  speed_kmh DOUBLE PRECISION,"
        "  accuracy_m DOUBLE PRECISION,"
        "  battery_level INTEGER,"
        "  source locationprovider NOT NULL DEFAULT 'gps',"
        "  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    )
    op.create_index(
        "ix_courier_locations_courier_id",
        "courier_locations",
        ["courier_id"],
    )
    op.create_index(
        "ix_courier_locations_courier_recorded",
        "courier_locations",
        ["courier_id", "recorded_at"],
    )
    op.create_index(
        "ix_courier_locations_recorded",
        "courier_locations",
        ["recorded_at"],
    )
    op.create_index(
        "ix_courier_locations_location",
        "courier_locations",
        ["location"],
        postgresql_using="gist",
    )

    # ----------------------------------------------------------------
    # 6. Partial GIST index on courier_profiles.current_location
    #    WHERE is_available = TRUE (for "available couriers near me" queries)
    # ----------------------------------------------------------------
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_courier_profiles_available_location "
        "ON courier_profiles USING GIST (current_location) WHERE is_available = true"
    )


def downgrade() -> None:
    op.drop_index(
        "ix_courier_profiles_available_location",
        table_name="courier_profiles",
    )
    op.drop_index("ix_courier_locations_location", table_name="courier_locations")
    op.drop_index("ix_courier_locations_recorded", table_name="courier_locations")
    op.drop_index(
        "ix_courier_locations_courier_recorded", table_name="courier_locations"
    )
    op.drop_index("ix_courier_locations_courier_id", table_name="courier_locations")
    op.drop_table("courier_locations")
    op.drop_index("ix_deliveries_status", table_name="deliveries")
    op.drop_index(
        "ix_deliveries_courier_status", table_name="deliveries"
    )
    op.drop_index("ix_deliveries_courier_id", table_name="deliveries")
    op.drop_index("ix_deliveries_order_id", table_name="deliveries")
    op.drop_table("deliveries")
    sa.Enum(name="locationprovider").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="deliverystatus").drop(op.get_bind(), checkfirst=True)
    op.drop_index(
        "ix_courier_profiles_last_heartbeat_at", table_name="courier_profiles"
    )
    op.drop_column("courier_profiles", "last_heartbeat_at")
    op.execute("DROP INDEX IF EXISTS ix_orders_idempotency_key_partial")
    op.execute("DROP SEQUENCE IF EXISTS order_number_seq")
