"""0003: add delivery fields to restaurant_profiles (Phase 3 prep)."""

import sqlalchemy as sa
from alembic import op

revision = "0005_restaurant_delivery_fields"
down_revision = "0003_restaurants_promotions_menu"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "restaurant_profiles",
        sa.Column(
            "delivery_fee",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
            server_default="0.00",
        ),
    )
    op.add_column(
        "restaurant_profiles",
        sa.Column(
            "delivery_radius_km",
            sa.Float(),
            nullable=False,
            server_default="5.0",
        ),
    )
    op.add_column(
        "restaurant_profiles",
        sa.Column(
            "min_order_amount",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
            server_default="0.00",
        ),
    )


def downgrade() -> None:
    op.drop_column("restaurant_profiles", "min_order_amount")
    op.drop_column("restaurant_profiles", "delivery_radius_km")
    op.drop_column("restaurant_profiles", "delivery_fee")
