"""0008: widen orders.order_number to VARCHAR(32).

The format FUDGO-YYYYMMDD-NNNNNN is 21 characters, but the column was
created as VARCHAR(20) in Phase 3's 0006 migration. This was masked
until now because no test checkout ever reached the INSERT (blocked by
the ST_DWithin parameter-binding bug fixed in the same commit).
"""

import sqlalchemy as sa
from alembic import op


revision = "0008_order_number_length"
down_revision = "0007_payments_pending_payment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "orders",
        "order_number",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "orders",
        "order_number",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
