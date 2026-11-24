"""reviews: an analyst agrees with or overturns a decision

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-25 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("agent_label", sa.String(length=16), nullable=False),
        sa.Column("final_label", sa.String(length=16), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("reviewer", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("job_id", "policy_version", name=op.f("pk_reviews")),
    )
    op.create_index("ix_reviews_version_verdict", "reviews", ["policy_version", "verdict"])


def downgrade() -> None:
    op.drop_index("ix_reviews_version_verdict", table_name="reviews")
    op.drop_table("reviews")
