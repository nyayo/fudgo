"""0004: cart + orders + payments + order_status_history.

PostgreSQL enum types created with the Phase 1 convention: lowercase, no
underscores (``orderstatus``, ``paymentstatus``, ``paymentmethod``).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0006_carts_orders_payments"
down_revision = "0005_restaurant_delivery_fields"
branch_labels = None
depends_on = None


# Enum types (created with create_type=True so SQLAlchemy knows about them
# on the metadata side and we don't get duplicate-type errors on re-runs).
orderstatus = sa.Enum(
    "placed",
    "confirmed",
    "preparing",
    "ready",
    "picked_up",
    "on_the_way",
    "delivered",
    "cancelled",
    name="orderstatus",
    create_type=True,
)
paymentstatus = sa.Enum(
    "pending",
    "succeeded",
    "failed",
    "refunded",
    name="paymentstatus",
    create_type=True,
)
paymentmethod = sa.Enum(
    "stub",
    "card",
    "mpesa",
    "cash",
    name="paymentmethod",
    create_type=True,
)


def upgrade() -> None:
    # 1. carts (1:1 with customer_profiles)
    op.create_table(
        "carts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customer_profiles.id", ondelete="CASCADE"), nullable=False, unique=True),
    )
    op.create_index("ix_carts_customer_id", "carts", ["customer_id"], unique=True)

    # 2. cart_items
    op.create_table(
        "cart_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("cart_id", UUID(as_uuid=True), sa.ForeignKey("carts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("menu_item_id", UUID(as_uuid=True), sa.ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("special_instructions", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("cart_id", "menu_item_id", name="uq_cart_item_cart_menu"),
    )
    op.create_index("ix_cart_items_cart_id", "cart_items", ["cart_id"])
    op.create_index("ix_cart_items_menu_item_id", "cart_items", ["menu_item_id"])

    # 3. orders
    op.create_table(
        "orders",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_number", sa.String(20), nullable=False, unique=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("customer_profiles.id"), nullable=False),
        sa.Column("restaurant_id", UUID(as_uuid=True), sa.ForeignKey("restaurant_profiles.id"), nullable=False),
        sa.Column("delivery_address_id", UUID(as_uuid=True), sa.ForeignKey("addresses.id"), nullable=False),
        sa.Column("courier_id", UUID(as_uuid=True), sa.ForeignKey("courier_profiles.id"), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0"),
        sa.Column("delivery_fee", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0"),
        sa.Column("service_fee", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0"),
        sa.Column("total_discount_amount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0"),
        sa.Column("status", orderstatus, nullable=False, server_default="placed"),
        sa.Column("idempotency_key", sa.String(64), nullable=True, unique=True),
        sa.Column("cancellation_reason", sa.Text, nullable=True),
        sa.Column("cancelled_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preparing_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_delivery_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orders_order_number", "orders", ["order_number"], unique=True)
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])
    op.create_index("ix_orders_restaurant_id", "orders", ["restaurant_id"])
    op.create_index("ix_orders_courier_id", "orders", ["courier_id"])
    op.create_index("ix_orders_status_placed", "orders", ["status", "placed_at"])
    op.create_index("ix_orders_restaurant_status", "orders", ["restaurant_id", "status"])

    # 4. order_items
    op.create_table(
        "order_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("menu_item_id", UUID(as_uuid=True), sa.ForeignKey("menu_items.id"), nullable=False),
        sa.Column("name_snapshot", sa.String(200), nullable=False),
        sa.Column("unit_price_snapshot", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("effective_unit_price_snapshot", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("applied_promotion_id", UUID(as_uuid=True), nullable=True),
        sa.Column("applied_promotion_name_snapshot", sa.String(255), nullable=True),
        sa.Column("applied_promotion_discount_snapshot", sa.Float, nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("line_subtotal", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("special_instructions", sa.Text, nullable=True),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])

    # 5. order_status_history
    op.create_table(
        "order_status_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", orderstatus, nullable=True),
        sa.Column("to_status", orderstatus, nullable=False),
        sa.Column("changed_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changed_by_role", sa.String(20), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_osh_order_changed", "order_status_history", ["order_id", "changed_at"])

    # 6. payments
    op.create_table(
        "payments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("order_id", UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False, unique=True),
        sa.Column("method", paymentmethod, nullable=False, server_default="stub"),
        sa.Column("status", paymentstatus, nullable=False, server_default="pending"),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("external_reference", sa.String(200), nullable=True),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("succeeded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_payments_order_id", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_osh_order_changed", table_name="order_status_history")
    op.drop_table("order_status_history")
    op.drop_index("ix_order_items_order_id", table_name="order_items")
    op.drop_table("order_items")
    op.drop_index("ix_orders_restaurant_status", table_name="orders")
    op.drop_index("ix_orders_status_placed", table_name="orders")
    op.drop_index("ix_orders_courier_id", table_name="orders")
    op.drop_index("ix_orders_restaurant_id", table_name="orders")
    op.drop_index("ix_orders_customer_id", table_name="orders")
    op.drop_index("ix_orders_order_number", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_cart_items_menu_item_id", table_name="cart_items")
    op.drop_index("ix_cart_items_cart_id", table_name="cart_items")
    op.drop_table("cart_items")
    op.drop_index("ix_carts_customer_id", table_name="carts")
    op.drop_table("carts")
    op.execute("DROP TYPE IF EXISTS paymentmethod")
    op.execute("DROP TYPE IF EXISTS paymentstatus")
    op.execute("DROP TYPE IF EXISTS orderstatus")
