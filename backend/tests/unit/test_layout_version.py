"""V1.2.0 R-16 灰度版本的取值行为

这个文件存在的唯一原因是那条铁律: **后端不许替前端兜底灰度归属**。

服务端没配 layout_version 时必须返回 null。如果兜底成 'v1.2', 那些"压根不知道自己
被分在哪组"的用户会被算进 v1.2 的样本里, J1 闭环率的版本切片就成了假的 —— 而它
恰好是这次改版唯一能证明"改版是好事还是坏事"的东西。这种错不会报错, 只会让结论
看起来很漂亮。

所以这里把"没配 / 配了空串 / 配了值"三种情况钉死。取值函数放在 app.config 而不是
某个 API 模块里, 是因为 /api/decide 和 /api/today 都要下发它。
"""
from __future__ import annotations

import app.config as config_module
from app.config import current_layout_version


class _FakeSettings:
    """只带 layout_version 的替身 —— 不必为这个测试拉起整个配置装配"""

    def __init__(self, value: str | None) -> None:
        self.layout_version = value


def _patch(monkeypatch, value: str | None) -> None:
    monkeypatch.setattr(config_module, "get_settings", lambda: _FakeSettings(value))


def test_unknown_group_is_null_not_v12(monkeypatch):
    """没配置 → null。'不知道' 和 '在 v1.2 组' 必须能区分开"""
    _patch(monkeypatch, None)
    assert current_layout_version() is None


def test_blank_config_is_treated_as_unset(monkeypatch):
    """配了 key 但值是空串 == 没配。yaml 里手抖留空是常态, 不能当成某个组"""
    _patch(monkeypatch, "   ")
    assert current_layout_version() is None


def test_configured_value_passes_through(monkeypatch):
    """配了就原样下发 —— 灰度是运营开关, 中间不能有任何加工"""
    _patch(monkeypatch, " v1.1 ")
    assert current_layout_version() == "v1.1"
