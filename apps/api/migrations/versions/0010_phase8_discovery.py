"""0010: Phase 8 discovery -- search FTS, reviews, taxonomy, favorites, prefs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID


revision = "0010_phase8_discovery"
down_revision = "0009_phase6_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0. pg_trgm for fuzzy matching headroom
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # 1. Taxonomy tables
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS cuisines (
          id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          slug VARCHAR(50) NOT NULL UNIQUE,
          name VARCHAR(100) NOT NULL,
          icon_url VARCHAR(500),
          display_order INTEGER NOT NULL DEFAULT 0,
          is_active BOOLEAN NOT NULL DEFAULT true,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_cuisines_slug ON cuisines (slug)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dietary_tags (
          id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          slug VARCHAR(50) NOT NULL UNIQUE,
          name VARCHAR(100) NOT NULL,
          icon_url VARCHAR(500),
          is_allergen BOOLEAN NOT NULL DEFAULT false,
          is_active BOOLEAN NOT NULL DEFAULT true,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dietary_tags_slug ON dietary_tags (slug)"
    )

    # 2. M2M tables
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS restaurant_cuisines (
          restaurant_id UUID NOT NULL REFERENCES restaurant_profiles(id) ON DELETE CASCADE,
          cuisine_id UUID NOT NULL REFERENCES cuisines(id) ON DELETE CASCADE,
          PRIMARY KEY (restaurant_id, cuisine_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS menu_item_dietary_tags (
          menu_item_id UUID NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
          dietary_tag_id UUID NOT NULL REFERENCES dietary_tags(id) ON DELETE CASCADE,
          PRIMARY KEY (menu_item_id, dietary_tag_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS customer_favorite_restaurants (
          customer_id UUID NOT NULL REFERENCES customer_profiles(id) ON DELETE CASCADE,
          restaurant_id UUID NOT NULL REFERENCES restaurant_profiles(id) ON DELETE CASCADE,
          added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (customer_id, restaurant_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS customer_favorite_menu_items (
          customer_id UUID NOT NULL REFERENCES customer_profiles(id) ON DELETE CASCADE,
          menu_item_id UUID NOT NULL REFERENCES menu_items(id) ON DELETE CASCADE,
          added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (customer_id, menu_item_id)
        )
        """
    )

    # 3. rating_count columns
    op.add_column(
        "restaurant_profiles",
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "courier_profiles",
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
    )

    # 4. Customer profile preferences
    op.add_column(
        "customer_profiles",
        sa.Column("dietary_preferences", JSONB, nullable=False, server_default="[]"),
    )
    op.add_column(
        "customer_profiles",
        sa.Column("allergens", JSONB, nullable=False, server_default="[]"),
    )

    # 5. Review tables
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS restaurant_reviews (
          id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          customer_id UUID NOT NULL REFERENCES customer_profiles(id),
          restaurant_id UUID NOT NULL REFERENCES restaurant_profiles(id),
          order_id UUID NOT NULL REFERENCES orders(id),
          rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
          comment TEXT,
          photo_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
          response TEXT,
          response_at TIMESTAMPTZ,
          responder_user_id UUID REFERENCES users(id),
          is_hidden BOOLEAN NOT NULL DEFAULT false,
          hidden_by_user_id UUID REFERENCES users(id),
          hidden_reason VARCHAR(500),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_restaurant_review_customer_restaurant
            UNIQUE (customer_id, restaurant_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_restaurant_reviews_restaurant_created "
        "ON restaurant_reviews (restaurant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_restaurant_reviews_is_hidden "
        "ON restaurant_reviews (is_hidden)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS menu_item_reviews (
          id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          customer_id UUID NOT NULL REFERENCES customer_profiles(id),
          menu_item_id UUID NOT NULL REFERENCES menu_items(id),
          order_id UUID NOT NULL REFERENCES orders(id),
          rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
          comment TEXT,
          photo_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
          is_hidden BOOLEAN NOT NULL DEFAULT false,
          hidden_by_user_id UUID REFERENCES users(id),
          hidden_reason VARCHAR(500),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_menu_item_review_customer_menu_item
            UNIQUE (customer_id, menu_item_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_menu_item_reviews_menu_item_created "
        "ON menu_item_reviews (menu_item_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_menu_item_reviews_is_hidden "
        "ON menu_item_reviews (is_hidden)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS courier_reviews (
          id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          customer_id UUID NOT NULL REFERENCES customer_profiles(id),
          courier_id UUID NOT NULL REFERENCES courier_profiles(id),
          delivery_id UUID NOT NULL REFERENCES deliveries(id),
          order_id UUID NOT NULL REFERENCES orders(id),
          rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
          comment TEXT,
          is_hidden BOOLEAN NOT NULL DEFAULT false,
          hidden_by_user_id UUID REFERENCES users(id),
          hidden_reason VARCHAR(500),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_courier_review_customer_delivery
            UNIQUE (customer_id, delivery_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_courier_reviews_courier_created "
        "ON courier_reviews (courier_id, created_at)"
    )

    # 6. Helpful votes (polymorphic)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS review_helpful_votes (
          id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
          user_id UUID NOT NULL REFERENCES users(id),
          review_id UUID NOT NULL,
          review_type VARCHAR(20) NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          CONSTRAINT uq_review_helpful_vote UNIQUE (review_id, user_id, review_type)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_helpful_votes_review "
        "ON review_helpful_votes (review_id, review_type)"
    )

    # 7. Aggregate recomputation triggers
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_recompute_restaurant_rating() RETURNS TRIGGER AS $$
        BEGIN
          UPDATE restaurant_profiles
          SET rating = COALESCE((
            SELECT AVG(rating)::numeric(3,2) FROM restaurant_reviews
            WHERE restaurant_id = COALESCE(NEW.restaurant_id, OLD.restaurant_id)
              AND is_hidden = false
          ), 0),
          rating_count = (
            SELECT COUNT(*) FROM restaurant_reviews
            WHERE restaurant_id = COALESCE(NEW.restaurant_id, OLD.restaurant_id)
              AND is_hidden = false
          )
          WHERE id = COALESCE(NEW.restaurant_id, OLD.restaurant_id);
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_recompute_restaurant_rating ON restaurant_reviews"
    )
    op.execute(
        f"""CREATE TRIGGER trg_recompute_{'restaurant'}_rating
        AFTER INSERT OR UPDATE OR DELETE ON {'restaurant'}_reviews
        FOR EACH ROW EXECUTE FUNCTION fn_recompute_{'restaurant'}_rating()"""
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_recompute_courier_rating() RETURNS TRIGGER AS $$
        BEGIN
          UPDATE courier_profiles
          SET rating = COALESCE((
            SELECT AVG(rating)::numeric(3,2) FROM courier_reviews
            WHERE courier_id = COALESCE(NEW.courier_id, OLD.courier_id)
              AND is_hidden = false
          ), 0),
          rating_count = (
            SELECT COUNT(*) FROM courier_reviews
            WHERE courier_id = COALESCE(NEW.courier_id, OLD.courier_id)
              AND is_hidden = false
          )
          WHERE id = COALESCE(NEW.courier_id, OLD.courier_id);
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_recompute_courier_rating ON courier_reviews"
    )
    op.execute(
        f"""CREATE TRIGGER trg_recompute_{'courier'}_rating
        AFTER INSERT OR UPDATE OR DELETE ON {'courier'}_reviews
        FOR EACH ROW EXECUTE FUNCTION fn_recompute_{'courier'}_rating()"""
    )

    # 8. FTS: generated tsvector columns + GIN indexes.
    # NOTE: the ORM column name must not collide with the type name, so we
    # call the column `fts` in the DB and reference it via text() in queries.
    op.execute(
        """
        ALTER TABLE restaurant_profiles ADD COLUMN IF NOT EXISTS fts tsvector
        GENERATED ALWAYS AS (
          to_tsvector('english', coalesce(restaurant_name,'') || ' ' || coalesce(address,''))
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_restaurant_profiles_fts "
        "ON restaurant_profiles USING GIN(fts)"
    )
    op.execute(
        """
        ALTER TABLE menu_items ADD COLUMN IF NOT EXISTS fts tsvector
        GENERATED ALWAYS AS (
          to_tsvector('english', coalesce(title,'') || ' ' || coalesce(description,''))
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_menu_items_fts ON menu_items USING GIN(fts)"
    )

    # 9. Seed data (idempotent)
    op.execute(
        """
        INSERT INTO cuisines (slug, name, display_order) VALUES
          ('indian','Indian',1), ('chinese','Chinese',2), ('italian','Italian',3),
          ('mexican','Mexican',4), ('japanese','Japanese',5), ('american','American',6),
          ('ethiopian','Ethiopian',7), ('korean','Korean',8), ('thai','Thai',9),
          ('mediterranean','Mediterranean',10)
        ON CONFLICT (slug) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO dietary_tags (slug, name, is_allergen) VALUES
          ('vegetarian','Vegetarian',false), ('vegan','Vegan',false),
          ('gluten-free','Gluten-Free',false), ('halal','Halal',false),
          ('kosher','Kosher',false), ('dairy-free','Dairy-Free',false),
          ('nut-free','Nut-Free',true), ('shellfish-free','Shellfish-Free',true),
          ('soy-free','Soy-Free',true), ('egg-free','Egg-Free',true)
        ON CONFLICT (slug) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_recompute_courier_rating ON courier_reviews")
    op.execute("DROP FUNCTION IF EXISTS fn_recompute_courier_rating()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_recompute_restaurant_rating ON restaurant_reviews"
    )
    op.execute("DROP FUNCTION IF EXISTS fn_recompute_restaurant_rating()")
    op.execute("DROP TABLE IF EXISTS review_helpful_votes")
    op.execute("DROP TABLE IF EXISTS courier_reviews")
    op.execute("DROP TABLE IF EXISTS menu_item_reviews")
    op.execute("DROP TABLE IF EXISTS restaurant_reviews")
    op.execute("ALTER TABLE customer_profiles DROP COLUMN IF EXISTS allergens")
    op.execute(
        "ALTER TABLE customer_profiles DROP COLUMN IF EXISTS dietary_preferences"
    )
    op.execute("ALTER TABLE courier_profiles DROP COLUMN IF EXISTS rating_count")
    op.execute(
        "ALTER TABLE restaurant_profiles DROP COLUMN IF EXISTS rating_count"
    )
    op.execute("DROP TABLE IF EXISTS customer_favorite_menu_items")
    op.execute("DROP TABLE IF EXISTS customer_favorite_restaurants")
    op.execute("DROP TABLE IF EXISTS menu_item_dietary_tags")
    op.execute("DROP TABLE IF EXISTS restaurant_cuisines")
    op.execute("DROP TABLE IF EXISTS dietary_tags")
    op.execute("DROP TABLE IF EXISTS cuisines")
    op.execute("ALTER TABLE menu_items DROP COLUMN IF EXISTS fts")
    op.execute("ALTER TABLE restaurant_profiles DROP COLUMN IF EXISTS fts")
