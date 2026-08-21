"""0001: PostGIS + uuid-ossp extensions and the app_healthcheck table.

Revision ID: 0001_postgis_extensions_and_healthcheck
Revises:
Create Date: 2026-08-18 00:00:00+00
"""

from alembic import op

revision = "0001_postgis_healthcheck"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_healthcheck (
            id serial PRIMARY KEY,
            checked_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS app_healthcheck")
    op.execute("DROP EXTENSION IF EXISTS postgis")
    op.execute('DROP EXTENSION IF EXISTS "uuid-ossp"')
