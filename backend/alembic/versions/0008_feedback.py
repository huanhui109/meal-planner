"""用户反馈表 (微信小程序/H5 收集问题/建议/菜谱纠错)

匿名可提交 (user_id 可空): 用户首次启动就能反馈, 无需登录
状态字段方便后台跟单 (T3.1 admin 接口)
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_feedback"
down_revision = "0007_menu_source"
branch_labels = None
depends_on = None

TABLE = "feedback"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=True,
            comment="所属用户, 匿名反馈为空",
        ),
        sa.Column(
            "category",
            sa.String(length=20),
            nullable=False,
            server_default="other",
            comment="反馈类型: bug/suggestion/recipe/other",
        ),
        sa.Column("content", sa.Text(), nullable=False, comment="反馈内容"),
        sa.Column(
            "contact",
            sa.String(length=100),
            nullable=True,
            comment="联系方式 (邮箱/微信), 可选",
        ),
        sa.Column(
            "device_info",
            sa.Text(),
            nullable=True,
            comment="设备信息 JSON: 型号/系统/微信版本/客户端版本",
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="open",
            comment="状态: open/processing/closed",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
            comment="提交时间",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="fk_feedback_user", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # 处理队列扫描: 未处理按时间排序
    op.create_index(
        "ix_feedback_status_created", TABLE, ["status", "created_at"]
    )
    # 用户的反馈历史
    op.create_index(
        "ix_feedback_user_created", TABLE, ["user_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_feedback_user_created", table_name=TABLE)
    op.drop_index("ix_feedback_status_created", table_name=TABLE)
    op.drop_table(TABLE)
