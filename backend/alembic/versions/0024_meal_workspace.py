"""Unified meal workspace and scoped assistant connections."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_meal_workspace"
down_revision = "0023_decision_cooked"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recipe", sa.Column("base_servings", sa.Integer(), nullable=True))
    def timestamps():
        return [
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        ]
    op.create_table(
        "meal_session",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("meal_date", sa.Date(), nullable=False),
        sa.Column("meal_slot", sa.String(20), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("current_proposal_id", sa.String(36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("user_id", "meal_date", "meal_slot", name="uq_meal_session_slot"),
    )
    op.create_table(
        "meal_proposal",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("meal_session.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("eaten_at", sa.DateTime(), nullable=True),
        *timestamps(),
    )
    op.create_index("ix_meal_proposal_session_id", "meal_proposal", ["session_id"])
    op.create_index("ix_meal_proposal_user_created", "meal_proposal", ["user_id", "created_at"])
    op.create_table(
        "meal_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("proposal_id", sa.String(36), sa.ForeignKey("meal_proposal.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_meal_event_proposal_id", "meal_event", ["proposal_id"])
    op.create_table(
        "meal_stock_movement",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("proposal_id", sa.String(36), sa.ForeignKey("meal_proposal.id", ondelete="CASCADE"), nullable=False),
        sa.Column("inventory_id", sa.Integer(), sa.ForeignKey("fridge_inventory.id", ondelete="SET NULL"), nullable=True),
        sa.Column("ingredient_id", sa.Integer(), sa.ForeignKey("ingredient.id"), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("batch", sa.JSON(), nullable=False),
    )
    op.create_index("ix_meal_stock_movement_proposal_id", "meal_stock_movement", ["proposal_id"])
    op.create_table(
        "assistant_grant",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        *timestamps(),
    )
    op.create_index("ix_assistant_grant_user_id", "assistant_grant", ["user_id"])


def downgrade() -> None:
    for table in ("assistant_grant", "meal_stock_movement", "meal_event", "meal_proposal", "meal_session"):
        op.drop_table(table)
    op.drop_column("recipe", "base_servings")
