"""WorkBuddy authorization and recoverable web adjustment jobs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_assistant_bridge"
down_revision = "0024_meal_workspace"
branch_labels = None
depends_on = None


def timestamps():
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "workbuddy_connection",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("client_id", sa.String(200), nullable=True),
        sa.Column("credentials", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("state_hash", sa.String(64), nullable=True),
        sa.Column("state_expires_at", sa.DateTime(), nullable=True),
        *timestamps(),
    )
    op.create_table(
        "assistant_adjustment",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("message_id", sa.String(200), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("proposal_id", sa.String(36), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("next_poll_at", sa.DateTime(), nullable=False),
        sa.Column("poll_failures", sa.Integer(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_assistant_adjustment_user_created", "assistant_adjustment", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_table("assistant_adjustment")
    op.drop_table("workbuddy_connection")
