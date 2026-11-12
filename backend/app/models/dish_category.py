"""菜品类别字典表 —— 可维护的分类标准

为什么建表:
    类别枚举如果只写在代码里, 改一个名字/加一个类别就要改代码发版。这张表把
    「有哪些类别、叫什么、怎么排序、是否启用」交给运维维护; recipe 上只存一个
    code, 天然保证「每道菜只归属一个类别」。

为什么不建数据库外键:
    测试夹具 conftest.clean_tables 会 TRUNCATE 所有表, 字典表被清空后,
    任何 NOT NULL + FK 的列都会让测试和造数据直接失败。分类标准在运行时由
    services/dish_rules.py 的常量提供(与 shared/dish-category.ts 有 parity 测试钉住),
    这张表是给运维查询/维护用的, 不是运行时依赖。别把它改成必查。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DishCategory(Base, TimestampMixin):
    __tablename__ = "dish_category"

    code: Mapped[str] = mapped_column(String(32), primary_key=True, comment="类别 code, 与 shared/dish-category.ts 一致")
    name: Mapped[str] = mapped_column(String(50), nullable=False, comment="展示名称")
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True, comment="口径说明")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="展示顺序")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用")
