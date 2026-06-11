"""
TokenManager 单元测试 — Design Token 全局管理器。

覆盖:
  - 单例模式（instance/reset）
  - load_from_dict: 从字典加载预设
  - get/get_color/get_qcolor/space/copy 等 API
  - 分类便捷方法（raw/alias/semantic/component）
  - 未加载预设时的安全行为
"""

from __future__ import annotations

import pytest

from core.tokens.manager import TokenManager
from core.tokens.resolver import TokenResolveError


SAMPLE = {
    "raw": {"yellow": "#FFE600", "red": "#FF0000"},
    "alias": {
        "accent": "@raw.yellow",
    },
    "semantic": {
        "danger": "@raw.red",
    },
    "space": {"height": {"btn_md": 36}, "spacing": {"sm": 8}},
    "copy": {"app_title": "WARFRAME Relic Tool"},
}


@pytest.fixture()
def tm():
    """每次测试前重置并加载 SAMPLE 数据的 TokenManager。"""
    TokenManager.reset()
    instance = TokenManager.instance()
    instance.load_from_dict(SAMPLE.copy(), name="test")
    yield instance
    TokenManager.reset()


class TestSingleton:

    def test_instance_returns_same_object(self):
        TokenManager.reset()
        a = TokenManager.instance()
        b = TokenManager.instance()
        assert a is b

    def test_reset_creates_new_instance(self):
        TokenManager.reset()
        a = TokenManager.instance()
        TokenManager.reset()
        b = TokenManager.instance()
        assert a is not b

    def test_double_init_raises(self):
        TokenManager.reset()
        TokenManager.instance()
        with pytest.raises(RuntimeError):
            TokenManager()


class TestLoadFromDict:

    def test_load_sets_preset_name(self, tm):
        assert tm.current_preset == "test"

    def test_load_creates_resolver(self, tm):
        assert tm._resolver is not None

    def test_can_resolve_after_load(self, tm):
        assert tm.get("raw.yellow") == "#FFE600"


class TestGetAPI:

    def test_get_existing_key(self, tm):
        assert tm.get("raw.yellow") == "#FFE600"

    def test_get_nonexistent_with_default(self, tm):
        assert tm.get("nonexistent", "fallback") == "fallback"

    def test_get_nonexistent_no_default_raises(self, tm):
        with pytest.raises(TokenResolveError):
            tm.get("nonexistent")

    def test_get_before_load_returns_default(self):
        TokenManager.reset()
        empty = TokenManager.instance()
        assert empty.get("anything", "safe") == "safe"


class TestGetColor:

    def test_get_color_returns_tuple(self, tm):
        assert tm.get_color("raw.yellow") == (255, 230, 0)

    def test_get_qcolor_returns_qcolor(self, tm):
        qc = tm.get_qcolor("raw.yellow")
        from PySide6.QtGui import QColor
        assert isinstance(qc, QColor)
        assert qc.red() == 255


class TestSpaceAPI:

    def test_space_int_value(self, tm):
        assert tm.space("height.btn_md") == 36

    def test_space_default_for_missing(self, tm):
        assert tm.space("nonexistent", 99) == 99


class TestCopyAPI:

    def test_copy_string(self, tm):
        assert tm.copy("app_title") == "WARFRAME Relic Tool"

    def test_copy_default(self, tm):
        assert tm.copy("missing", default="N/A") == "N/A"


class TestCategoryShortcuts:

    def test_raw_shortcut(self, tm):
        assert tm.raw("yellow") == "#FFE600"

    def test_alias_shortcut(self, tm):
        assert tm.alias("accent") == "#FFE600"

    def test_semantic_shortcut(self, tm):
        assert tm.semantic("danger") == "#FF0000"
