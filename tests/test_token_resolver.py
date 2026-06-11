"""
TokenResolver 单元测试 — Token 引用解析引擎。

覆盖:
  - 基础值解析（raw 层）
  - @引用链解析（alias 层）
  - 函数变换（lighten/darken/opacity/mix）
  - 循环引用检测
  - 缓存机制
  - 错误处理（不存在 key、非法参数）
"""

from __future__ import annotations

import pytest

from core.tokens.resolver import TokenResolver, TokenResolveError


# ═══════════════════════════════════════════════════
#  测试数据
# ═══════════════════════════════════════════════════

MINIMAL_PRESET = {
    "raw": {
        "yellow": "#FFE600",
        "cyan": "#00FFFF",
        "red": "#FF0000",
        "dark_bg": "#0E0E24",
    },
    "alias": {
        "accent": {
            "primary": "@raw.yellow",
        },
        "bg": {
            "base": "@raw.dark_bg",
            "chain": "@alias.accent.primary",  # 二级引用链
        },
    },
    "semantic": {
        "danger": "@raw.red",
        "warning": "lighten(@raw.yellow, 20%)",
        "mixed": "mix(@raw.yellow, @raw.cyan, 0.3)",
    },
}


def _make_resolver(data=None):
    if data is None:
        data = MINIMAL_PRESET
    return TokenResolver(data)


# ═══════════════════════════════════════════════════
#  初始化
# ═══════════════════════════════════════════════════

class TestInit:

    def test_accepts_dict(self):
        resolver = _make_resolver()
        assert resolver is not None

    def test_rejects_non_dict(self):
        with pytest.raises(TypeError):
            TokenResolver("not a dict")

    def test_rejects_none(self):
        with pytest.raises(TypeError):
            TokenResolver(None)


# ═══════════════════════════════════════════════════
#  Raw 层解析
# ═══════════════════════════════════════════════════

class TestRawResolve:

    def test_simple_color(self):
        r = _make_resolver()
        assert r.resolve("raw.yellow") == "#FFE600"

    def test_another_color(self):
        r = _make_resolver()
        assert r.resolve("raw.cyan") == "#00FFFF"

    def test_unknown_key_raises(self):
        r = _make_resolver()
        with pytest.raises(TokenResolveError):
            r.resolve("raw.nonexistent")

    def test_resolve_color_tuple(self):
        r = _make_resolver()
        assert r.resolve_color("raw.yellow") == (255, 230, 0)


# ═══════════════════════════════════════════════════
#  Alias 引用链
# ═══════════════════════════════════════════════════

class TestAliasResolve:

    def test_single_alias(self):
        r = _make_resolver()
        assert r.resolve("alias.accent.primary") == "#FFE600"

    def test_chained_alias(self):
        """alias.bg.chain → alias.accent.primary → raw.yellow"""
        r = _make_resolver()
        assert r.resolve("alias.bg.chain") == "#FFE600"

    def test_alias_to_bg(self):
        r = _make_resolver()
        assert r.resolve("alias.bg.base") == "#0E0E24"


# ═══════════════════════════════════════════════════
#  函数变换
# ═══════════════════════════════════════════════════

class TestFunctionTransforms:

    def test_lighten_transform(self):
        r = _make_resolver()
        value = r.resolve("semantic.warning")
        assert value.startswith("#")
        assert value != "#FFE600"  # 应该被提亮

    def test_mix_transform(self):
        r = _make_resolver()
        value = r.resolve("semantic.mixed")
        assert value.startswith("#")

    def test_direct_reference_in_function(self):
        """函数参数中直接使用 @引用。"""
        r = _make_resolver()
        value = r.resolve("semantic.danger")
        assert value == "#FF0000"


# ═══════════════════════════════════════════════════
#  缓存机制
# ═══════════════════════════════════════════════════

class TestCaching:

    def test_second_call_returns_cached(self):
        r = _make_resolver()
        val1 = r.resolve("raw.yellow")
        val2 = r.resolve("raw.yellow")
        assert val1 is val2 or val1 == val2

    def test_resolved_keys_grows(self):
        r = _make_resolver()
        assert len(r.resolved_keys) == 0
        r.resolve("raw.yellow")
        assert "raw.yellow" in r.resolved_keys

    def test_reload_clears_cache(self):
        r = _make_resolver()
        r.resolve("raw.yellow")
        assert len(r.resolved_keys) > 0
        r.reload(MINIMAL_PRESET)
        assert len(r.resolved_keys) == 0


# ═══════════════════════════════════════════════════
#  循环引用检测
# ═══════════════════════════════════════════════════

class TestCircularReference:

    def test_direct_cycle_detected(self):
        data = {"a": "@a"}
        r = TokenResolver(data)
        with pytest.raises(TokenResolveError):
            r.resolve("a")

    def test_indirect_cycle_detected(self):
        data = {"a": "@b", "b": "@c", "c": "@a"}
        r = TokenResolver(data)
        with pytest.raises(TokenResolveError):
            r.resolve("a")


# ═══════════════════════════════════════════════════
#  边界情况
# ═══════════════════════════════════════════════════

class TestEdgeCases:

    def test_empty_preset_resolves_nothing(self):
        r = TokenResolver({})
        with pytest.raises(TokenResolveError):
            r.resolve("anything")

    def test_resolve_color_transparent(self):
        data = {"color": "transparent"}
        r = TokenResolver(data)
        assert r.resolve_color("color") == (0, 0, 0)

    def test_deeply_nested_dict_key(self):
        data = {"level1": {"level2": {"level3": "#ABCDEF"}}}
        r = TokenResolver(data)
        assert r.resolve("level1.level2.level3") == "#ABCDEF"
