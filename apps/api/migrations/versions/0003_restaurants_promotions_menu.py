"""0003: restaurants + promotions + menu + image tables.

Hand-written so the M2M association table and indexes are explicit.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0003_restaurants_promotions_menu"
down_revision = "0002_users_and_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. promotions
    op.create_table(
        "promotions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("restaurant_id", UUID(as_uuid=True), sa.ForeignKey("restaurant_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.String(225), nullable=False, server_default=""),
        sa.Column("discount", sa.Float, nullable=False),
        sa.Column("banner_url", sa.String(1024), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_promotions_restaurant_id", "promotions", ["restaurant_id"])
    op.create_index("ix_promotions_restaurant_active", "promotions", ["restaurant_id", "is_active"])
    op.create_index("ix_promotions_dates", "promotions", ["start_date", "end_date"])

    # 2. menu_categories
    op.create_table(
        "menu_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("restaurant_id", UUID(as_uuid=True), sa.ForeignKey("restaurant_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("restaurant_id", "name", name="uq_menu_categories_restaurant_name"),
    )
    op.create_index("ix_menu_categories_restaurant_id", "menu_categories", ["restaurant_id"])
    op.create_index("ix_menu_categories_restaurant_position", "menu_categories", ["restaurant_id", "position"])

    # 3. menu_items
    op.create_table(
        "menu_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("restaurant_id", UUID(as_uuid=True), sa.ForeignKey("restaurant_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("menu_categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("price", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("is_available", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_featured", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("prep_time_minutes", sa.Integer, nullable=True),
        sa.Column("allergens", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("restaurant_id", "title", name="uq_menu_items_restaurant_title"),
    )
    op.create_index("ix_menu_items_restaurant_id", "menu_items", ["restaurant_id"])
    op.create_index("ix_menu_items_category_id", "menu_items", ["category_id"])
    op.create_index("ix_menu_items_is_available", "menu_items", ["is_available"])
    op.create_index("ix_menu_items_is_featured", "menu_items", ["is_featured"])
    op.create_index("ix_menu_items_restaurant_available", "menu_items", ["restaurant_id", "is_available"])

    # 4. menu_item_promotions (M2M)
    op.create_table(
        "menu_item_promotions",
        sa.Column("item_id", UUID(as_uuid=True), sa.ForeignKey("menu_items.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("promotion_id", UUID(as_uuid=True), sa.ForeignKey("promotions.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_menu_item_promotions_item", "menu_item_promotions", ["item_id"])
    op.create_index("ix_menu_item_promotions_promo", "menu_item_promotions", ["promotion_id"])

    # 5. menu_item_images
    op.create_table(
        "menu_item_images",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("menu_item_id", UUID(as_uuid=True), sa.ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_url", sa.String(1024), nullable=False),
        sa.Column("alt_text", sa.String(255), nullable=False, server_default=""),
        sa.Column("position", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_menu_item_images_item_id", "menu_item_images", ["menu_item_id"])
    op.create_index("ix_menu_item_images_item_position", "menu_item_images", ["menu_item_id", "position"])

    # 6. menu_category_images
    op.create_table(
        "menu_category_images",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("category_id", UUID(as_uuid=True), sa.ForeignKey("menu_categories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_url", sa.String(1024), nullable=False),
        sa.Column("alt_text", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_menu_category_images_category_id", "menu_category_images", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_menu_category_images_category_id", table_name="menu_category_images")
    op.drop_table("menu_category_images")
    op.drop_index("ix_menu_item_images_item_position", table_name="menu_item_images")
    op.drop_index("ix_menu_item_images_item_id", table_name="menu_item_images")
    op.drop_table("menu_item_images")
    op.drop_index("ix_menu_item_promotions_promo", table_name="menu_item_promotions")
    op.drop_index("ix_menu_item_promotions_item", table_name="menu_item_promotions")
    op.drop_table("menu_item_promotions")
    op.drop_index("ix_menu_items_restaurant_available", table_name="menu_items")
    op.drop_index("ix_menu_items_is_featured", table_name="menu_items")
    op.drop_index("ix_menu_items_is_available", table_name="menu_items")
    op.drop_index("ix_menu_items_category_id", table_name="menu_items")
    op.drop_index("ix_menu_items_restaurant_id", table_name="menu_items")
    op.drop_table("menu_items")
    op.drop_index("ix_menu_categories_restaurant_position", table_name="menu_categories")
    op.drop_index("ix_menu_categories_restaurant_id", table_name="menu_categories")
    op.drop_table("menu_categories")
    op.drop_index("ix_promotions_dates", table_name="promotions")
    op.drop_index("ix_promotions_restaurant_active", table_name="promotions")
    op.drop_index("ix_promotions_restaurant_id", table_name="promotions")
    op.drop_table("promotions")
