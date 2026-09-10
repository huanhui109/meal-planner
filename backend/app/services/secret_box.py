"""对称加密 - 存进数据库的第三方密钥 (飞书 App Secret 等) 不落明文

为什么需要: 飞书 App Secret 相当于应用凭证, 拿到它就能以这个应用的身份发消息。
库里存明文的话, 一次数据库导出/备份泄露就等于凭证泄露。

密钥来源: APP__AUTH__JWT_SECRET。同一条密钥既签 token 又派生加密密钥是不理想的做法,
但在"单机自部署 + 单密钥文件"的部署形态下, 再引入一个必须单独保管的
APP__SECRET_KEY 只会让运维更容易漏配 —— 所以这里从 jwt_secret 做 HKDF 派生,
得到一把与签名用途无关的独立密钥。

没配 jwt_secret 时 (本地裸跑) 退化为固定的开发密钥并打警告, 保证功能可用。
"""

from __future__ import annotations

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# HKDF 的 info 字段: 换个用途换一个字面量即可得到互不相干的密钥
_INFO = b"meal-planner:secret-box:v1"
_DEV_FALLBACK_SECRET = "meal-planner-local-dev-only"
_warned = False


class SecretBoxError(RuntimeError):
    """加解密失败 (对外只暴露可读文案)"""


def _fernet() -> Fernet:
    global _warned
    from app.config import get_settings

    secret = (get_settings().auth.jwt_secret or "").strip()
    if not secret:
        if not _warned:
            logger.warning(
                "未配置 APP__AUTH__JWT_SECRET, 数据库里的第三方密钥使用开发默认密钥加密; 生产环境请务必配置"
            )
            _warned = True
        secret = _DEV_FALLBACK_SECRET

    key = hashlib.sha256(_INFO + secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plaintext: Optional[str]) -> str:
    """加密; 空值原样返回空串 (表示"没配")"""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(token: Optional[str]) -> str:
    """解密; 空值返回空串。密钥换过导致解不开时抛 SecretBoxError"""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretBoxError("无法解密已保存的密钥, 可能更换过 APP__AUTH__JWT_SECRET") from exc


def mask(value: Optional[str], keep: int = 4) -> str:
    """脱敏展示: 只留头尾几个字符, 前端永远拿不到完整密钥"""
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * 6}{value[-keep:]}"
