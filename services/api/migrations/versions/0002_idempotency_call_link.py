"""link cached idempotent responses to the call they created

A cached response can carry a call (for example the creation response). Deleting the call, or only its content, must
also forget that response, which is encrypted and so cannot be found by looking inside it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18 03:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("idempotency_keys", schema=None) as batch_op:
        batch_op.add_column(sa.Column("call_id", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_idempotency_keys_call_id"), ["call_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("idempotency_keys", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_idempotency_keys_call_id"))
        batch_op.drop_column("call_id")
