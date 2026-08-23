"""0002: User-domain tables + auth tables for Phase 1.

This migration is hand-written so the GIST indexes are explicit. Order is
preserved by the FK graph; auth tables sit before profile tables so the
profile FKs resolve cleanly.
"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0002_users_and_auth"
down_revision = "0001_postgis_healthcheck"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")
        ),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("first_name", sa.String(80), nullable=False, server_default=""),
        sa.Column("last_name", sa.String(80), nullable=False, server_default=""),
        sa.Column(
            "user_type",
            sa.Enum("customer", "courier", "restaurant", "restaurant_staff", name="usertype"),
            nullable=False,
        ),
        sa.Column(
            "auth_provider",
            sa.Enum("email", "phone", "google", "github", "linkedin", name="authprovider"),
            nullable=False,
            server_default="email",
        ),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_staff", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("google_id", sa.String(255), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("phone", name="uq_users_phone"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("google_id", name="uq_users_google_id"),
    )
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_phone", "users", ["phone"])
    op.create_index("ix_users_user_type", "users", ["user_type"])
    op.create_index("ix_users_is_verified", "users", ["is_verified"])
    op.create_index("ix_users_auth_provider", "users", ["auth_provider"])
    op.create_index("ix_users_user_type_is_verified", "users", ["user_type", "is_verified"])

    # 2. email_verifications
    op.create_table(
        "email_verifications",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")
        ),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("otp", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_email_verifications_email", "email_verifications", ["email"])
    op.create_index("ix_email_verifications_expires_at", "email_verifications", ["expires_at"])
    op.create_index(
        "ix_email_verifications_email_is_verified",
        "email_verifications",
        ["email", "is_verified"],
    )

    # 3. phone_verifications
    op.create_table(
        "phone_verifications",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")
        ),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("otp", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_phone_verifications_phone", "phone_verifications", ["phone"])
    op.create_index("ix_phone_verifications_expires_at", "phone_verifications", ["expires_at"])
    op.create_index(
        "ix_phone_verifications_phone_is_verified",
        "phone_verifications",
        ["phone", "is_verified"],
    )

    # 4. revoked_tokens
    op.create_table(
        "revoked_tokens",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")
        ),
        sa.Column("jti", sa.String(128), nullable=False),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False, server_default="logout"),
        sa.Column("revoked_at_user", UUID(as_uuid=True), nullable=True),
        sa.UniqueConstraint("jti", name="uq_revoked_tokens_jti"),
    )
    op.create_index("ix_revoked_tokens_jti", "revoked_tokens", ["jti"])
    op.create_index(
        "ix_revoked_tokens_user_expires",
        "revoked_tokens",
        ["revoked_at_user", "expires_at"],
    )

    # 5. customer_profiles
    op.create_table(
        "customer_profiles",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "current_location",
            Geography(geometry_type="POINT", srid=4326),
            nullable=True,
        ),
        sa.Column("date_of_birth", sa.Date, nullable=True),
        sa.Column("order_stats", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.UniqueConstraint("user_id", name="uq_customer_profiles_user_id"),
    )
    op.create_index("ix_customer_profiles_user_id", "customer_profiles", ["user_id"])
    op.execute(
        "CREATE INDEX ix_customer_profiles_current_location ON customer_profiles USING GIST (current_location)"
    )

    # 6. courier_profiles
    op.create_table(
        "courier_profiles",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "vehicle_type",
            sa.Enum("bike", "motorcycle", "car", name="vehicletype"),
            nullable=False,
        ),
        sa.Column("license_number", sa.String(80), nullable=True),
        sa.Column("is_available", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_approved", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "current_location",
            Geography(geometry_type="POINT", srid=4326),
            nullable=True,
        ),
        sa.Column(
            "performance_stats", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("rating", sa.Numeric(3, 2), nullable=False, server_default="0"),
        sa.Column("total_deliveries", sa.Integer, nullable=False, server_default="0"),
        sa.Column("earnings_balance", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", name="uq_courier_profiles_user_id"),
    )
    op.create_index("ix_courier_profiles_user_id", "courier_profiles", ["user_id"])
    op.create_index("ix_courier_profiles_is_available", "courier_profiles", ["is_available"])
    op.create_index("ix_courier_profiles_is_approved", "courier_profiles", ["is_approved"])
    op.create_index("ix_courier_profiles_rating", "courier_profiles", ["rating"])
    op.create_index(
        "ix_courier_profiles_total_deliveries", "courier_profiles", ["total_deliveries"]
    )
    op.execute(
        "CREATE INDEX ix_courier_profiles_current_location ON courier_profiles USING GIST (current_location)"
    )

    # 7. restaurant_profiles
    op.create_table(
        "restaurant_profiles",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("restaurant_name", sa.String(200), nullable=False),
        sa.Column("business_license", sa.String(120), nullable=False),
        sa.Column("address", sa.Text, nullable=False),
        sa.Column(
            "location",
            Geography(geometry_type="POINT", srid=4326),
            nullable=False,
            server_default=sa.text("ST_GeogFromText('SRID=4326;POINT(0 0)')"),
        ),
        sa.Column("opening_hours", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rating", sa.Numeric(3, 2), nullable=False, server_default="0"),
        sa.Column("is_approved", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("user_id", name="uq_restaurant_profiles_user_id"),
        sa.UniqueConstraint("business_license", name="uq_restaurant_profiles_business_license"),
    )
    op.create_index("ix_restaurant_profiles_user_id", "restaurant_profiles", ["user_id"])
    op.create_index("ix_restaurant_profiles_rating", "restaurant_profiles", ["rating"])
    op.execute(
        "CREATE INDEX ix_restaurant_profiles_location ON restaurant_profiles USING GIST (location)"
    )

    # 8. restaurant_staff_profiles
    op.create_table(
        "restaurant_staff_profiles",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "restaurant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("restaurant_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum("manager", "waiter", "cashier", name="staffrole"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "date_joined",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", name="uq_restaurant_staff_profiles_user_id"),
    )
    op.create_index(
        "ix_restaurant_staff_profiles_user_id", "restaurant_staff_profiles", ["user_id"]
    )
    op.create_index(
        "ix_restaurant_staff_profiles_restaurant_id",
        "restaurant_staff_profiles",
        ["restaurant_id"],
    )

    # 9. addresses
    op.create_table(
        "addresses",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("street", sa.String(200), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column(
            "location",
            Geography(geometry_type="POINT", srid=4326),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_addresses_user_id", "addresses", ["user_id"])
    op.execute("CREATE INDEX ix_addresses_location ON addresses USING GIST (location)")

    # 10. notification_preferences
    op.create_table(
        "notification_preferences",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("receive_push", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("receive_email", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "promotions_and_offers", sa.Boolean, nullable=False, server_default=sa.text("true")
        ),
        sa.Column("new_restaurants", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("review_reminders", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.UniqueConstraint("user_id", name="uq_notification_preferences_user_id"),
    )
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"])

    # 11. devices
    op.create_table(
        "devices",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("registration_id", sa.Text, nullable=False),
        sa.Column(
            "platform",
            sa.Enum("android", "ios", "web", name="deviceplatform"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
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
    )
    op.create_index("ix_devices_user_id", "devices", ["user_id"])
    op.create_index("ix_devices_registration_id", "devices", ["registration_id"])


def downgrade() -> None:
    op.drop_index("ix_devices_registration_id", table_name="devices")
    op.drop_index("ix_devices_user_id", table_name="devices")
    op.drop_table("devices")
    op.drop_index("ix_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")
    op.execute("DROP INDEX IF EXISTS ix_addresses_location")
    op.drop_index("ix_addresses_user_id", table_name="addresses")
    op.drop_table("addresses")
    op.drop_index(
        "ix_restaurant_staff_profiles_restaurant_id", table_name="restaurant_staff_profiles"
    )
    op.drop_index("ix_restaurant_staff_profiles_user_id", table_name="restaurant_staff_profiles")
    op.drop_table("restaurant_staff_profiles")
    op.execute("DROP INDEX IF EXISTS ix_restaurant_profiles_location")
    op.drop_index("ix_restaurant_profiles_rating", table_name="restaurant_profiles")
    op.drop_index("ix_restaurant_profiles_user_id", table_name="restaurant_profiles")
    op.drop_table("restaurant_profiles")
    op.execute("DROP INDEX IF EXISTS ix_courier_profiles_current_location")
    op.drop_index("ix_courier_profiles_total_deliveries", table_name="courier_profiles")
    op.drop_index("ix_courier_profiles_rating", table_name="courier_profiles")
    op.drop_index("ix_courier_profiles_is_approved", table_name="courier_profiles")
    op.drop_index("ix_courier_profiles_is_available", table_name="courier_profiles")
    op.drop_index("ix_courier_profiles_user_id", table_name="courier_profiles")
    op.drop_table("courier_profiles")
    op.execute("DROP INDEX IF EXISTS ix_customer_profiles_current_location")
    op.drop_index("ix_customer_profiles_user_id", table_name="customer_profiles")
    op.drop_table("customer_profiles")
    op.drop_index("ix_revoked_tokens_user_expires", table_name="revoked_tokens")
    op.drop_index("ix_revoked_tokens_jti", table_name="revoked_tokens")
    op.drop_table("revoked_tokens")
    op.drop_index("ix_phone_verifications_phone_is_verified", table_name="phone_verifications")
    op.drop_index("ix_phone_verifications_expires_at", table_name="phone_verifications")
    op.drop_index("ix_phone_verifications_phone", table_name="phone_verifications")
    op.drop_table("phone_verifications")
    op.drop_index("ix_email_verifications_email_is_verified", table_name="email_verifications")
    op.drop_index("ix_email_verifications_expires_at", table_name="email_verifications")
    op.drop_index("ix_email_verifications_email", table_name="email_verifications")
    op.drop_table("email_verifications")
    op.drop_index("ix_users_user_type_is_verified", table_name="users")
    op.drop_index("ix_users_auth_provider", table_name="users")
    op.drop_index("ix_users_is_verified", table_name="users")
    op.drop_index("ix_users_user_type", table_name="users")
    op.drop_index("ix_users_phone", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS deviceplatform")
    op.execute("DROP TYPE IF EXISTS staffrole")
    op.execute("DROP TYPE IF EXISTS vehicletype")
    op.execute("DROP TYPE IF EXISTS authprovider")
    op.execute("DROP TYPE IF EXISTS usertype")
