#!/usr/bin/env python3
"""数据库说明文档生成器

从 MySQL 的 ``INFORMATION_SCHEMA`` 导出全部表结构 (字段 / 类型 / 约束 / 索引 / 外键),
叠加 ORM 的 ``comment`` 与脚本内置的业务语义字典, 生成 ``docs/database.md``。

为什么用脚本而不是手写:
  * 表结构会随迁移演进, 文档必须能一键重生成, 才不会漂移;
  * 字段含义 (ORM comment) 与枚举取值 (代码里的常量) 是唯一真源, 脚本负责回填。

用法:
  python scripts/gen_db_doc.py            # 生成/覆盖 docs/database.md
  python scripts/gen_db_doc.py --check    # 只校验文档是否与当前库一致 (CI 用)
  python scripts/gen_db_doc.py -o out.md  # 指定输出路径
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pymysql

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "docs" / "database.md"

# ORM 模型是"含义"的第一真源: 迁移常常不带 column comment, 但模型里的 comment= 是齐的。
sys.path.insert(0, str(ROOT / "backend"))
from app.models import Base  # noqa: E402

TABLE_NOTES: Dict[str, str] = {
    "user": "平台用户 (飞书扫码 / 微信小程序 / 本地开发登录)",
    "household": "家庭规模与做饭时间约束",
    "diet_preference": "口味偏好 (菜系 / 辣度 / 主食)",
    "allergy_restriction": "过敏源与忌口 (硬约束)",
    "health_goal": "健康目标与每日营养配比",
    "budget": "预算配置 (工作日 / 周末 / 周上限 / 外卖参考价)",
    "ingredient": "食材字典 (唯一名 + 分类 + 标准单位 + 参考单价)",
    "recipe": "菜谱库 (AI 生成 / 用户创建 / 开源导入)",
    "recipe_ingredient": "菜谱↔食材用量关联",
    "menu": "周菜单 (按用户 + 周起始日)",
    "menu_item": "菜单餐次 (7 天 × 餐次, 承载换菜 / 锁定 / 已做)",
    "menu_generation_task": "异步生成任务队列 (worker 抢占执行 + 配额计数)",
    "fridge_inventory": "冰箱库存批次 (含保质期)",
    "consumption_record": "库存消耗流水 (标记已做的账, 可撤销)",
    "product": "电商商品库 (二期采集占位)",
    "product_mapping": "食材↔商品匹配 (二期)",
    "purchase_record": "采购记录 (补单 / 手动)",
    "activity_log": "活动流水 (推送 / 识别 / 配额计数)",
    "user_feishu_config": "用户级飞书机器人凭证 (加密存储)",
    "alembic_version": "迁移版本元数据",
}

COLUMN_NOTES: Dict[Tuple[str, str], str] = {
    ("*", "id"): "主键, 自增",
    ("*", "created_at"): "创建时间",
    ("*", "updated_at"): "更新时间",
    ("*", "user_id"): "所属用户, 级联删除",
    ("menu_item", "meal_date"): "用餐日期",
    ("menu_item", "meal_type"): "餐次: breakfast/lunch/dinner",
    ("menu_item", "is_locked"): "锁定后不参与重生成",
    ("menu_item", "is_cooked"): "是否已做",
    ("menu_item", "cook_mode"): "自做 self / 外卖 takeout",
    ("menu_item", "estimated_cost"): "预估成本(元)",
    ("menu", "week_start_date"): "周起始日期(周一)",
    ("menu", "status"): "状态: draft/confirmed/active/completed",
    ("menu", "source"): "本份菜单来源: local/ai/mixed",
    ("recipe", "name"): "菜名",
    ("recipe", "cuisine"): "菜系/分类",
    ("recipe", "difficulty"): "难度 1-5",
    ("recipe", "cook_minutes"): "烹饪时间(分钟)",
    ("recipe", "calories"): "热量(kcal)",
    ("recipe", "protein_g"): "蛋白质(g)",
    ("recipe", "carb_g"): "碳水(g)",
    ("recipe", "fat_g"): "脂肪(g)",
    ("recipe", "steps"): "烹饪步骤 (含小贴士)",
    ("recipe", "source"): "来源: ai_generated/user_created/template/howtocook/proj_kitchen",
    ("recipe_ingredient", "quantity"): "用量(标准单位), 无法量化时为 NULL",
    ("recipe_ingredient", "unit"): "标准单位",
    ("recipe_ingredient", "amount_text"): "原始用量文本, 如 '适量'",
    ("ingredient", "name"): "食材名称 (唯一)",
    ("ingredient", "category"): "分类: 蔬菜/水果/肉禽蛋/水产/调味品/乳制品/主食/坚果",
    ("ingredient", "standard_unit"): "标准单位: 个/根/颗/块/把/条/头/g/ml 等",
    ("ingredient", "reference_price"): "参考单价(元/标准单位), 用于成本估算",
    ("menu_generation_task", "status"): "状态: pending/running/succeeded/failed",
    ("menu_generation_task", "is_regeneration"): "是否重新生成 (走独立配额)",
    ("menu_generation_task", "attempts"): "已尝试次数",
    ("menu_generation_task", "week_start_date"): "目标周起始日期",
    ("fridge_inventory", "quantity"): "数量",
    ("fridge_inventory", "unit"): "单位",
    ("fridge_inventory", "purchase_date"): "采购日期",
    ("fridge_inventory", "expiry_date"): "保质期",
    ("fridge_inventory", "source"): "来源: manual/xiaoxiang_auto",
    ("consumption_record", "quantity"): "消耗数量",
    ("consumption_record", "unit"): "消耗时的单位",
    ("consumption_record", "consumed_at"): "消耗时间",
    ("user", "open_id"): "第三方身份命名空间 (唯一)",
    ("user", "union_id"): "飞书 union_id (开发者内唯一)",
    ("user", "name"): "昵称",
    ("user", "avatar_url"): "头像地址",
    ("user", "last_login_at"): "最近登录时间",
    ("household", "member_count"): "家庭人数",
    ("household", "meals_per_day"): "每日餐次",
    ("household", "kitchen_equipments"): "厨房设备, JSON 数组",
    ("household", "weekday_cook_minutes"): "工作日做饭时间(分钟)",
    ("household", "weekend_cook_minutes"): "周末做饭时间(分钟)",
    ("diet_preference", "cuisines"): "偏好菜系, JSON 数组",
    ("diet_preference", "spice_level"): "辣度 0-5",
    ("diet_preference", "flavor_preference"): "口味倾向",
    ("diet_preference", "staple_preference"): "主食偏好",
    ("allergy_restriction", "allergens"): "过敏源列表, JSON 数组",
    ("allergy_restriction", "avoid_ingredients"): "忌口食材, JSON 数组",
    ("allergy_restriction", "dietary_restrictions"): "饮食限制描述",
    ("health_goal", "goal_type"): "目标类型: 减脂/增肌/控糖/控压/维持",
    ("health_goal", "daily_calories"): "每日目标热量(kcal)",
    ("health_goal", "protein_pct"): "蛋白质百分比",
    ("health_goal", "carb_pct"): "碳水百分比",
    ("health_goal", "fat_pct"): "脂肪百分比",
    ("budget", "weekday_daily_budget"): "工作日每日预算(元)",
    ("budget", "weekend_daily_budget"): "周末每日预算(元)",
    ("budget", "weekly_cap"): "周预算上限(元)",
    ("budget", "min_meal_budget"): "单餐预算下限(元)",
    ("budget", "takeout_reference_price"): "一顿外卖参考价(元), 用于自做 vs 外卖对比",
    ("product", "source_platform"): "来源平台: xiaoxiang/meituan_waimai",
    ("product", "sku_id"): "商品 SKU ID",
    ("product", "is_active"): "是否在售",
    ("product", "in_stock"): "是否有货",
    ("product", "price_changed"): "价格是否异常波动",
    ("product_mapping", "match_score"): "匹配度 0-1",
    ("product_mapping", "user_confirmed"): "用户是否确认",
    ("purchase_record", "quantity"): "数量",
    ("purchase_record", "amount"): "金额(元)",
    ("purchase_record", "platform"): "平台: xiaoxiang/meituan_waimai/manual",
    ("activity_log", "channel"): "通道: feishu/vision/system",
    ("activity_log", "kind"): "事件类型: daily_menu_push/evening_check/expiry_check/vision_recognize",
    ("activity_log", "title"): "一句话说明",
    ("activity_log", "status"): "结果: sent/failed/skipped",
    ("activity_log", "occurred_at"): "发生时间",
    ("user_feishu_config", "app_id"): "飞书应用 App ID",
    ("user_feishu_config", "app_secret_encrypted"): "App Secret, 加密后存储",
    ("user_feishu_config", "receive_id"): "接收方 ID (open_id 或 chat_id)",
    ("user_feishu_config", "receive_id_type"): "接收方 ID 类型: open_id/chat_id/email",
    ("user_feishu_config", "enabled"): "关掉后保留配置但不再推送",
    ("user_feishu_config", "remark"): "备注, 例如「家庭群」",
    ("user_feishu_config", "last_verified_at"): "最近一次测试推送成功时间",
    ("user_feishu_config", "last_error"): "最近一次推送失败原因",
    ("menu_generation_task", "request_payload"): "请求参数 JSON",
    ("menu_generation_task", "error"): "失败原因",
    ("menu_generation_task", "started_at"): "开始时间",
    ("menu_generation_task", "finished_at"): "结束时间",
}

# --- 表按业务模块分组 (决定文档第三/四章的组织顺序) ----------------------------
MODULE_GROUPS: List[Tuple[str, List[str]]] = [
    ("用户与偏好", ["user", "household", "diet_preference", "allergy_restriction", "health_goal", "budget"]),
    ("菜谱与食材", ["ingredient", "recipe", "recipe_ingredient"]),
    ("菜单与生成", ["menu", "menu_item", "menu_generation_task"]),
    ("库存与采购", [
        "fridge_inventory", "consumption_record", "product", "product_mapping", "purchase_record",
    ]),
    ("自动化与流水", ["activity_log", "user_feishu_config"]),
    ("迁移元数据", ["alembic_version"]),
]

# --- 枚举/受控取值 (代码常量, INFORMATION_SCHEMA 看不到, 必须人工登记) -----------
ENUM_VALUES: Dict[Tuple[str, str], List[str]] = {
    ("menu", "status"): ["draft 草稿(可编辑)", "confirmed 已确认", "active 执行期", "completed 本周结束"],
    ("menu_item", "meal_type"): ["breakfast 早餐", "lunch 午餐", "dinner 晚餐"],
    ("menu_item", "cook_mode"): ["self 自做", "takeout 外卖"],
    ("menu_generation_task", "status"): ["pending 待领取", "running 执行中", "succeeded 成功", "failed 失败"],
    ("recipe", "source"): [
        "ai_generated AI 生成", "user_created 用户创建", "template 模板",
        "howtocook 导入(HowToCook)", "proj_kitchen 导入(proj.kitchen)",
    ],
    ("ingredient", "category"): [
        "蔬菜", "水果", "肉禽蛋", "水产", "调味品", "乳制品", "主食", "坚果",
    ],
    ("fridge_inventory", "source"): ["manual 手动添加", "xiaoxiang_auto 小象超市自动"],
    ("activity_log", "channel"): ["feishu 飞书", "vision 拍照识别", "system 系统"],
    ("activity_log", "kind"): [
        "daily_menu_push 每日菜单推送", "evening_check 晚间库存监测", "expiry_check 临期检查",
        "vision_recognize 拍照识别",
    ],
    ("activity_log", "status"): ["sent 已发送", "failed 失败", "skipped 已跳过"],
    ("product", "source_platform"): ["xiaoxiang 小象超市", "meituan_waimai 美团外卖"],
    ("purchase_record", "platform"): ["xiaoxiang 小象超市", "meituan_waimai 美团外卖", "manual 手动"],
    ("user", "open_id"): ["ou_* 飞书", "wechat:* 微信小程序", "dev:* 本地开发"],
    ("user_feishu_config", "receive_id_type"): ["open_id", "chat_id", "email"],
    ("health_goal", "goal_type"): ["减脂", "增肌", "控糖", "控压", "维持"],
}

# --- 迁移脚本登记 (版本号 → 说明), 让文档能讲清表是怎么长出来的 -------------------
MIGRATIONS: List[Tuple[str, str]] = [
    ("0001_init", "基线: 19 张业务表"),
    ("0002_consumption_record_keeps_history", "消耗流水保留历史 (SET NULL)"),
    ("0003_v2_today_and_brand", "今日页与品牌 (activity_log 等)"),
    ("0004_consumption_record_identity", "消耗流水自解释 (ingredient_id/unit)"),
    ("0005_generation_task_regeneration", "生成任务重生成配额 (is_regeneration)"),
    ("0006_user_feishu_config", "用户级飞书机器人配置"),
    ("0007_v23_menu_source", "菜单来源标识 (menu.source: local/ai/mixed)"),
]


@dataclass
class Column:
    name: str
    data_type: str
    column_type: str
    nullable: bool
    default: Optional[str]
    comment: str
    extra: str
    ordinal: int


@dataclass
class Table:
    name: str
    comment: str
    columns: List[Column] = field(default_factory=list)
    indexes: Dict[str, List[Tuple[int, str, bool]]] = field(default_factory=dict)  # 名 -> [(seq, col, non_unique)]
    unique_columns: set = field(default_factory=set)  # 单列唯一索引覆盖的列
    fks: List[Tuple[str, str, str, str]] = field(default_factory=list)  # (constraint, col, ref_table, ref_col)

    @property
    def primary_key(self) -> List[str]:
        cols = [c for c in self.columns if c.extra == "auto_increment"]
        if cols:
            return [c.name for c in cols]
        for name, entries in self.indexes.items():
            if name == "PRIMARY":
                return [col for _, col, _ in sorted(entries)]
        return []


def load_env_url() -> str:
    """优先环境变量, 否则读 .env 里的 APP__DATABASE__URL"""
    url = os.environ.get("APP__DATABASE__URL")
    if not url:
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("APP__DATABASE__URL="):
                    url = line.split("=", 1)[1].strip()
                    break
    if not url:
        raise SystemExit("未找到 APP__DATABASE__URL (环境变量或 .env)")
    return url


def connect() -> pymysql.connections.Connection:
    url = load_env_url()
    m = re.match(r"mysql\+\w+://([^:]+):([^@]+)@([^:]+):(\d+)/([\w]+)", url)
    if not m:
        raise SystemExit(f"无法解析数据库连接串: {url}")
    user, pwd, host, port, db = m.groups()
    return pymysql.connect(host=host, port=int(port), user=user, password=pwd, database=db, charset="utf8mb4")


def fetch_tables(cur, db: str) -> Dict[str, Table]:
    cur.execute(
        "SELECT table_name, table_comment FROM information_schema.tables "
        "WHERE table_schema=%s AND table_type='BASE TABLE'",
        (db,),
    )
    tables = {name: Table(name=name, comment=comment or "") for name, comment in cur.fetchall()}

    cur.execute(
        "SELECT table_name, column_name, column_type, is_nullable, column_default, "
        "column_comment, extra, ordinal_position FROM information_schema.columns "
        "WHERE table_schema=%s ORDER BY table_name, ordinal_position",
        (db,),
    )
    for t, name, ctype, nullable, default, comment, extra, ordinal in cur.fetchall():
        base = re.split(r"[ (]", ctype, maxsplit=1)[0]
        tables[t].columns.append(
            Column(
                name=name,
                data_type=base,
                column_type=ctype,
                nullable=(nullable == "YES"),
                default=default,
                comment=comment or "",
                extra=extra or "",
                ordinal=ordinal,
            )
        )

    cur.execute(
        "SELECT table_name, index_name, non_unique, seq_in_index, column_name "
        "FROM information_schema.statistics WHERE table_schema=%s "
        "ORDER BY table_name, index_name, seq_in_index",
        (db,),
    )
    for t, index, non_unique, seq, col in cur.fetchall():
        tables[t].indexes.setdefault(index, []).append((int(seq), col, bool(non_unique)))
    # 单列唯一索引 -> 说明该列是 1:1 关系 (PRIMARY 不算业务唯一约束)
    for table in tables.values():
        for index_name, entries in table.indexes.items():
            if index_name == "PRIMARY":
                continue
            if len(entries) == 1 and not entries[0][2]:
                table.unique_columns.add(entries[0][1])

    cur.execute(
        "SELECT table_name, constraint_name, column_name, referenced_table_name, referenced_column_name "
        "FROM information_schema.key_column_usage "
        "WHERE table_schema=%s AND referenced_table_name IS NOT NULL "
        "ORDER BY table_name, constraint_name, ordinal_position",
        (db,),
    )
    for t, constraint, col, ref_table, ref_col in cur.fetchall():
        tables[t].fks.append((constraint, col, ref_table, ref_col))
    return tables


def fmt_default(col: Column) -> str:
    if col.default is None:
        return "—"
    raw = str(col.default)
    if raw.upper() in {"CURRENT_TIMESTAMP", "NULL"}:
        return raw.upper() if raw.upper() == "CURRENT_TIMESTAMP" else "NULL"
    return f"`{raw}`"


def col_note(table: str, col: Column) -> str:
    if col.comment:
        return col.comment
    note = COLUMN_NOTES.get((table, col.name)) or COLUMN_NOTES.get(("*", col.name))
    if note:
        return note
    enum = ENUM_VALUES.get((table, col.name))
    if enum:
        return "取值: " + " / ".join(enum)
    return "—"


def merge_orm(tables: Dict[str, Table]) -> None:
    """把 ORM 模型的表/字段 comment 合并进来 (DB 里没有 comment 时以模型为准)"""
    for name, orm_table in Base.metadata.tables.items():
        if name not in tables:
            continue
        table = tables[name]
        table.comment = table.comment or orm_table.comment or TABLE_NOTES.get(name, "")
        for col in table.columns:
            if not col.comment:
                orm_col = orm_table.columns.get(col.name)
                if orm_col is not None and orm_col.comment:
                    col.comment = orm_col.comment
    # 库里有但模型没有的表 (如 alembic_version) 用备注兜底
    for name, table in tables.items():
        if not table.comment:
            table.comment = TABLE_NOTES.get(name, "")


def render_er(tables: Dict[str, Table]) -> str:
    lines = ["```mermaid", "erDiagram"]
    for t in sorted(tables):
        for (_constraint, col, ref_table, _ref_col) in sorted(tables[t].fks, key=lambda x: x[1]):
            if ref_table not in tables:
                continue
            one_to_one = col in tables[t].unique_columns
            right = "||--||" if one_to_one else "||--o{"
            lines.append(f'    {ref_table} {right} {t} : "{col}"')
    lines.append("```")
    return "\n".join(lines)


def render_table(table: Table) -> str:
    title = f"#### `{table.name}`"
    if table.comment:
        title += f" — {table.comment}"
    out = [title, ""]
    out.append("| 字段 | 类型 | 可空 | 默认 | 键 | 含义 |")
    out.append("|---|---|---|---|---|---|")
    pk = set(table.primary_key)
    fk_cols = {col for _, col, _, _ in table.fks}
    for col in table.columns:
        keys = []
        if col.name in pk:
            keys.append("PK")
        if col.name in fk_cols:
            keys.append("FK")
        if col.name in table.unique_columns:
            keys.append("UQ")
        if col.extra == "auto_increment":
            keys.append("AUTO")
        out.append(
            f"| `{col.name}` | {col.column_type} | {'是' if col.nullable else '否'} | "
            f"{fmt_default(col)} | {'/'.join(keys) or '—'} | {col_note(table.name, col)} |"
        )

    indexed = {name: entries for name, entries in table.indexes.items() if name != "PRIMARY"}
    if indexed:
        out.append("")
        out.append("**索引**:")
        for name, entries in sorted(indexed.items()):
            cols = ", ".join(f"`{col}`" for _, col, _ in sorted(entries))
            kind = "普通" if entries[0][2] else "唯一"
            out.append(f"- `{name}` ({kind}): {cols}")

    if table.fks:
        out.append("")
        out.append("**外键**:")
        for _constraint, col, ref_table, ref_col in sorted(table.fks, key=lambda x: x[1]):
            out.append(f"- `{col}` → `{ref_table}.{ref_col}`")
    out.append("")
    return "\n".join(out)


def build_document(tables: Dict[str, Table], db: str) -> str:
    business = [t for t in tables if t != "alembic_version"]
    total_cols = sum(len(t.columns) for t in tables.values())
    total_fks = sum(len(t.fks) for t in tables.values())

    out: List[str] = []
    out.append("# 数据库说明文档")
    out.append("")
    out.append("> 本文件由 `scripts/gen_db_doc.py` 从 MySQL `INFORMATION_SCHEMA` 自动生成, "
               "字段含义取自 ORM 的 `comment`, 枚举取值由脚本内置字典维护。")
    out.append("> 请勿手改: 结构变更后执行 `make db-doc` 重新生成。")
    out.append("")
    out.append(f"- 数据库: `{db}` (MySQL 8 / utf8mb4)")
    out.append(f"- 表数量: **{len(business)} 张业务表** + `alembic_version` (迁移元数据)")
    out.append(f"- 字段总数: {total_cols} · 外键总数: {total_fks}")
    out.append(f"- 建表唯一入口: Alembic 迁移 (`make migration MSG=\"...\"` → `make migrate`)")
    out.append("")

    out.append("## 一、概述")
    out.append("")
    out.append("数据分五块: **用户与偏好**(账号、家庭、口味、过敏、目标、预算)、**菜谱与食材**"
               "(食材字典、菜谱、菜谱-食材用量)、**菜单与生成**(周菜单、餐次、异步生成任务)、"
               "**库存与采购**(冰箱批次、消耗流水、商品与映射、采购记录)、**自动化与流水**"
               "(活动流水、用户级飞书配置)。")
    out.append("")
    out.append("依赖方向遵守 `api → services → models`; 表之间通过外键约束保证引用完整性, "
               "删除用户会级联清空其全部业务数据 (`ON DELETE CASCADE`)。")
    out.append("")

    out.append("## 二、ER 关系图")
    out.append("")
    out.append(render_er(tables))
    out.append("")

    out.append("## 三、表清单")
    out.append("")
    out.append("| 模块 | 表 | 说明 | 字段数 | 外键数 |")
    out.append("|---|---|---|---|---|")
    grouped: List[str] = []
    for module, names in MODULE_GROUPS:
        for name in names:
            if name not in tables:
                continue
            grouped.append(name)
            t = tables[name]
            out.append(f"| {module} | `{name}` | {t.comment or '—'} | {len(t.columns)} | {len(t.fks)} |")
    others = [n for n in sorted(tables) if n not in grouped]
    for name in others:
        t = tables[name]
        out.append(f"| 其他 | `{name}` | {t.comment or '—'} | {len(t.columns)} | {len(t.fks)} |")
    out.append("")

    out.append("## 四、表结构明细")
    out.append("")
    for module, names in MODULE_GROUPS:
        present = [n for n in names if n in tables]
        if not present:
            continue
        out.append(f"### {module}")
        out.append("")
        for name in present:
            out.append(render_table(tables[name]))
    for name in others:
        out.append(render_table(tables[name]))

    out.append("## 五、枚举与受控取值")
    out.append("")
    out.append("以下字段以字符串存储受控取值 (代码常量, 非数据库 ENUM):")
    out.append("")
    out.append("| 表 | 字段 | 取值 |")
    out.append("|---|---|---|")
    for (table, column), values in sorted(ENUM_VALUES.items()):
        if table in tables:
            out.append(f"| `{table}` | `{column}` | {' / '.join(values)} |")
    out.append("")

    out.append("## 六、迁移历史")
    out.append("")
    out.append("| 版本 | 说明 |")
    out.append("|---|---|")
    for version, note in MIGRATIONS:
        out.append(f"| `{version}` | {note} |")
    out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成数据库说明文档")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT), help="输出路径")
    parser.add_argument("--check", action="store_true", help="只校验文档是否与库一致")
    args = parser.parse_args()

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DATABASE()")
            db = cur.fetchone()[0]
            tables = fetch_tables(cur, db)
    finally:
        conn.close()

    merge_orm(tables)
    content = build_document(tables, db)
    output = Path(args.output)

    if args.check:
        if not output.exists():
            print(f"[db-doc] 文档不存在: {output}", file=sys.stderr)
            return 1
        if output.read_text(encoding="utf-8") != content:
            print(f"[db-doc] 文档已漂移, 请执行 make db-doc 后提交: {output}", file=sys.stderr)
            return 1
        print(f"[db-doc] OK ({len(tables)} 表)")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(f"[db-doc] 已生成 {output} ({len(tables)} 表)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
