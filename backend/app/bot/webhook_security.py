"""飞书事件回调的安全校验 - 签名校验与事件体解密

独立成模块的原因: 这几个都是纯函数, 不碰数据库也不发网络请求, 可以单独单测。
飞书回调有三层可选防护, 本项目全支持:
  1. 签名校验 (encrypt_key) - 校验 X-Lark-Signature
  2. verification_token - 校验事件体里的 token 字段
  3. 事件体加密 - encrypt_key 配置后, 事件体是 {"encrypt": "..."} 密文
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Mapping, Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "x-lark-signature"
TIMESTAMP_HEADER = "x-lark-request-timestamp"
NONCE_HEADER = "x-lark-request-nonce"
AES_BLOCK_SIZE = 16


def calculate_signature(timestamp: str, encrypt_key: str) -> str:
    """计算飞书事件订阅签名

    注意飞书的算法比较特殊: 待签名串是 "timestamp\\nencrypt_key", 然后对它做
    空 key 的 HMAC-SHA256 (官方示例就是这么写的), 不是把 encrypt_key 当 HMAC key。
    签名校验逻辑别按"常识"改。
    """
    string_to_sign = f"{timestamp}\n{encrypt_key}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def verify_signature(headers: Mapping[str, str], encrypt_key: str) -> bool:
    """校验请求头签名; 未配置 encrypt_key 时不做校验 (返回 True)"""
    if not encrypt_key:
        return True
    timestamp = _header(headers, TIMESTAMP_HEADER)
    signature = _header(headers, SIGNATURE_HEADER)
    if not timestamp or not signature:
        logger.warning("飞书回调缺少签名请求头, 已拒绝")
        return False
    expected = calculate_signature(timestamp, encrypt_key)
    if not hmac.compare_digest(expected, signature):
        logger.warning("飞书回调签名不匹配, 已拒绝")
        return False
    return True


def verify_token(body: Dict[str, Any], verification_token: str) -> bool:
    """校验事件体里的 token; 未配置 verification_token 时不做校验"""
    if not verification_token:
        return True
    token = str(body.get("token") or body.get("header", {}).get("token") or "")
    if not token:
        logger.warning("飞书回调缺少 token 字段, 已拒绝")
        return False
    if not hmac.compare_digest(token, verification_token):
        logger.warning("飞书回调 token 不匹配, 已拒绝")
        return False
    return True


def is_encrypted(body: Dict[str, Any]) -> bool:
    """事件体是否为密文 (配置了 encrypt_key 时飞书会加密)"""
    return isinstance(body.get("encrypt"), str) and bool(body["encrypt"])


def decrypt_event(encrypted: str, encrypt_key: str) -> Dict[str, Any]:
    """解密事件体

    算法与飞书官方一致: key = sha256(encrypt_key), AES-256-CBC, 前 16 字节是 IV,
    明文按 PKCS7 填充。解密失败抛 ValueError (调用方统一转 400)。
    """
    if not encrypt_key:
        raise ValueError("未配置 encrypt_key, 无法解密事件体")
    try:
        raw = base64.b64decode(encrypted)
    except Exception as exc:  # noqa: BLE001 - 非法 base64
        raise ValueError("事件体不是合法的 base64") from exc
    if len(raw) <= AES_BLOCK_SIZE:
        raise ValueError("事件体长度不合法")

    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    iv, payload = raw[:AES_BLOCK_SIZE], raw[AES_BLOCK_SIZE:]
    if len(payload) % AES_BLOCK_SIZE != 0:
        raise ValueError("事件体长度不是分组大小的整数倍")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    try:
        plain = decryptor.update(payload) + decryptor.finalize()
    except ValueError as exc:
        raise ValueError("事件体解密失败, 请检查 encrypt_key") from exc
    plain = _unpad(plain)
    try:
        data = json.loads(plain.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("事件体解密后不是合法 JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("事件体解密后不是 JSON 对象")
    return data


def _unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("事件体解密结果为空")
    pad = data[-1]
    if pad < 1 or pad > AES_BLOCK_SIZE or pad > len(data):
        raise ValueError("事件体填充不合法")
    return data[:-pad]


def _header(headers: Mapping[str, str], name: str) -> Optional[str]:
    """大小写不敏感地取请求头 (Starlette 的 Headers 本身不区分大小写, dict 就不一定)"""
    value = headers.get(name)
    if value:
        return value
    lowered = name.lower()
    for key, item in headers.items():
        if key.lower() == lowered:
            return item
    return None


def encrypt_event(payload: Dict[str, Any], encrypt_key: str) -> Dict[str, Any]:
    """encrypt_event 与 decrypt_event 严格互逆, 供集成测试/自检构造密文事件体

    生产路径不会调用它。放在同一模块是为了让加解密两侧永远共用一套算法,
    避免测试里另写一份实现、真接飞书时才发现对不上。
    """
    if not encrypt_key:
        raise ValueError("encrypt_key 不能为空")
    key = hashlib.sha256(encrypt_key.encode("utf-8")).digest()
    iv = hashlib.sha256(("iv:" + encrypt_key).encode("utf-8")).digest()[:AES_BLOCK_SIZE]
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    pad = AES_BLOCK_SIZE - len(body) % AES_BLOCK_SIZE
    body += bytes([pad]) * pad
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    cipher_text = encryptor.update(body) + encryptor.finalize()
    return {"encrypt": base64.b64encode(iv + cipher_text).decode("utf-8")}
