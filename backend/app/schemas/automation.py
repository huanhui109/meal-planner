"""自动化 (飞书机器人) 相关 Pydantic 模型"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# 飞书消息接收方类型
RECEIVE_ID_TYPES = ("open_id", "chat_id", "email")


class FeishuConfigUpdate(BaseModel):
    """保存用户自己的飞书应用凭证

    app_secret 是只写的: 传空字符串表示"沿用已保存的密钥", 前端拿不到明文回显。
    """

    app_id: str = Field(default="", max_length=100)
    app_secret: Optional[str] = Field(default=None, max_length=300)
    receive_id: str = Field(default="", max_length=200)
    receive_id_type: str = Field(default="open_id", max_length=20)
    remark: str = Field(default="", max_length=100)
    enabled: bool = True


class FeishuConfigResponse(BaseModel):
    """回给前端的配置视图 - 密钥只给掩码"""

    configured: bool
    enabled: bool
    app_id: str = ""
    app_secret_masked: str = ""
    has_secret: bool = False
    receive_id: str = ""
    receive_id_type: str = "open_id"
    remark: str = ""
    last_verified_at: Optional[str] = None
    last_error: Optional[str] = None
    # 还差哪些必填项, 前端据此逐条提示
    missing_fields: list[str] = []


class FeishuTestResult(BaseModel):
    ok: bool
    message: str
