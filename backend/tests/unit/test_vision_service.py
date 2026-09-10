"""单元测试: 拍照识别的降级与容错

重点不是"能不能认对菜", 而是"认不出、没配 Key、模型返回垃圾时, 用户看到什么"。
"""
from __future__ import annotations

import io

import pytest
from app.config import Settings, deep_merge, env_overrides, load_yaml_defaults
from app.services.vision_service import VisionError, VisionService
from PIL import Image


def _settings(env: dict | None = None) -> Settings:
    return Settings.model_validate(deep_merge(load_yaml_defaults(), env_overrides(env or {})))


def _png(size=(64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 40, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


CONFIGURED = {"GLM4_API_KEY": "", "APP__LLM__PRIMARY__API_KEY": "test-key"}


@pytest.mark.asyncio
async def test_demo_mode_returns_fixed_items_without_calling_model():
    service = VisionService(_settings({"APP__LLM__DEMO": "true"}))

    async def boom(_messages):  # pragma: no cover - 演示模式不该走到这里
        raise AssertionError("演示模式不应该调用模型")

    service._caller = boom
    result = await service.recognize(_png(), "image/png")
    assert service.configured is True
    assert result["model"] == "demo"
    assert [item["name"] for item in result["items"]] == ["西红柿", "鸡蛋", "西蓝花"]
    assert result["items"][0]["category"] == "蔬菜"


@pytest.mark.asyncio
async def test_unconfigured_service_refuses_clearly():
    service = VisionService(_settings({"APP__LLM__DEMO": "false", "APP__LLM__PRIMARY__API_KEY": ""}))
    assert service.configured is False
    with pytest.raises(VisionError, match="没有配置视觉模型"):
        await service.recognize(_png())


@pytest.mark.asyncio
async def test_success_parses_and_normalizes_items():
    service = VisionService(_settings(CONFIGURED))

    async def caller(_messages):
        return '{"items":[{"name":" 西红柿 ","quantity":"2","unit":"只","category":"蔬菜",' \
               '"confidence":1.7,"expiry_days":4.9},{"name":"","quantity":1}]}'

    service._caller = caller
    result = await service.recognize(_png())
    assert len(result["items"]) == 1
    item = result["items"][0]
    assert item["name"] == "西红柿"
    assert item["quantity"] == 2.0
    assert item["unit"] == "个"  # 只 -> 个
    assert item["confidence"] == 1.0  # 夹到 0-1
    assert item["expiry_days"] == 4


@pytest.mark.asyncio
async def test_unknown_category_falls_back_to_other():
    service = VisionService(_settings(CONFIGURED))

    async def caller(_messages):
        return '{"items":[{"name":"神秘食材","category":"外星"}]}'

    service._caller = caller
    result = await service.recognize(_png())
    assert result["items"][0]["category"] == "其他"
    assert result["items"][0]["unit"] == "个"


@pytest.mark.asyncio
async def test_parses_json_wrapped_in_markdown_fence():
    service = VisionService(_settings(CONFIGURED))

    async def caller(_messages):
        return '好的, 结果如下:\n```json\n{"items":[{"name":"鸡蛋","quantity":6}]}\n```'

    service._caller = caller
    result = await service.recognize(_png())
    assert result["items"][0]["name"] == "鸡蛋"


@pytest.mark.asyncio
async def test_unparsable_answer_becomes_readable_error():
    service = VisionService(_settings(CONFIGURED))

    async def caller(_messages):
        return "这张照片拍得太糊了"

    service._caller = caller
    with pytest.raises(VisionError, match="识别结果看不懂"):
        await service.recognize(_png())


@pytest.mark.asyncio
async def test_upstream_failure_becomes_readable_error():
    service = VisionService(_settings(CONFIGURED))

    async def caller(_messages):
        raise RuntimeError("connection reset by peer")

    service._caller = caller
    with pytest.raises(VisionError, match="识别服务暂时不可用"):
        await service.recognize(_png())


@pytest.mark.asyncio
async def test_oversized_image_is_rejected_before_any_call():
    service = VisionService(_settings({**CONFIGURED, "APP__LLM__VISION__MAX_IMAGE_MB": "0.001"}))
    with pytest.raises(VisionError, match="MB"):
        await service.recognize(_png((400, 400)))


@pytest.mark.asyncio
async def test_non_image_bytes_are_rejected():
    service = VisionService(_settings(CONFIGURED))
    with pytest.raises(VisionError, match="不像是图片"):
        await service.recognize(b"this is definitely not an image")


@pytest.mark.asyncio
async def test_image_is_downscaled_before_being_sent():
    service = VisionService(_settings({**CONFIGURED, "APP__LLM__VISION__MAX_EDGE_PX": "64"}))
    captured = {}

    async def caller(messages):
        captured["url"] = messages[1]["content"][1]["image_url"]["url"]
        return '{"items":[]}'

    service._caller = caller
    await service.recognize(_png((512, 512)))
    assert captured["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_empty_payload_still_returns_shape():
    service = VisionService(_settings(CONFIGURED))

    async def caller(_messages):
        return '{"items": "坏数据"}'

    service._caller = caller
    result = await service.recognize(_png())
    assert result["items"] == []
