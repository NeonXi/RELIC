"""
color_utils 单元测试 — 颜色解析与变换函数。

覆盖:
  - parse_color: hex 字符串 → (R, G, B) 元组
  - to_hex / to_rgba: 格式化输出
  - rgb_to_hsl / hsl_to_rgb: 色彩空间转换
  - lighten / darken / opacity / mix: 核心颜色变换
  - is_color_value: 合法性判断
  - 边界条件: 空值、非法格式、极值
"""

from __future__ import annotations

import pytest

from core.tokens.color_utils import (
    parse_color,
    to_hex,
    to_rgba,
    rgb_to_hsl,
    hsl_to_rgb,
    lighten,
    darken,
    opacity,
    mix,
    is_color_value,
)


# ═══════════════════════════════════════════════════
#  parse_color — 颜色字符串解析
# ═══════════════════════════════════════════════════

class TestParseColor:

    def test_full_hex_with_hash(self):
        assert parse_color("#FFE600") == (255, 230, 0)

    def test_full_hex_without_hash(self):
        assert parse_color("00FFFF") == (0, 255, 255)

    def test_short_hex_3char(self):
        """#F60 → #FF6600"""
        assert parse_color("#F60") == (255, 102, 0)

    def test_short_hex_without_hash(self):
        assert parse_color("F00") == (255, 0, 0)

    def test_8digit_hex_alpha_ignored(self):
        """8 位 hex 只取 RGB 分量。"""
        assert parse_color("#FF000080")[:3] == (255, 0, 0)

    def test_black(self):
        assert parse_color("#000000") == (0, 0, 0)

    def test_white(self):
        assert parse_color("#FFFFFF") == (255, 255, 255)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            parse_color("not-a-color")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_color("")

    def test_whitespace_trimmed(self):
        assert parse_color("  #FFE600  ") == (255, 230, 0)


# ═══════════════════════════════════════════════════
#  to_hex / to_rgba — 格式化输出
# ═══════════════════════════════════════════════════

class TestToHex:

    def test_basic(self):
        assert to_hex(255, 230, 0) == "#FFE600"

    def test_no_hash_prefix(self):
        assert to_hex(0, 128, 255, include_hash=False) == "0080FF"

    def test_zero_values(self):
        assert to_hex(0, 0, 0) == "#000000"

    def test_max_values(self):
        assert to_hex(255, 255, 255) == "#FFFFFF"


class TestToRgba:

    def test_full_opacity(self):
        result = to_rgba(255, 0, 0, 1.0)
        assert result == "rgba(255, 0, 0, 1)"

    def test_half_opacity(self):
        result = to_rgba(0, 255, 255, 0.5)
        assert "0.5" in result

    def test_zero_opacity(self):
        result = to_rgba(255, 230, 0, 0.0)
        assert "0" in result


# ═══════════════════════════════════════════════════
#  rgb_to_hsl / hsl_to_rgb — 色彩空间往返
# ═══════════════════════════════════════════════════

class TestColorSpaceRoundTrip:

    @pytest.mark.parametrize("r,g,b", [
        (255, 0, 0),      # 红
        (0, 255, 0),      # 绿
        (0, 0, 255),      # 蓝
        (255, 255, 255),  # 白
        (0, 0, 0),        # 黑
        (128, 128, 128),  # 灰
        (255, 230, 0),    # 黄
        (14, 14, 36),     # 深蓝背景
    ])
    def test_round_trip(self, r, g, b):
        """RGB → HSL → RGB 往返应保持一致（允许 ±1 量化误差）。"""
        h, s, l = rgb_to_hsl(r, g, b)
        rr, rg, rb = hsl_to_rgb(h, s, l)
        assert abs(rr - r) <= 1, f"R: {r} -> {rr}"
        assert abs(rg - g) <= 1, f"G: {g} -> {rg}"
        assert abs(rb - b) <= 1, f"B: {b} -> {rb}"

    def test_black_is_zero_lightness(self):
        _, _, l = rgb_to_hsl(0, 0, 0)
        assert l == 0.0

    def test_white_is_full_lightness(self):
        _, _, l = rgb_to_hsl(255, 255, 255)
        assert l == 1.0

    def test_gray_has_zero_saturation(self):
        _, s, _ = rgb_to_hsl(128, 128, 128)
        assert s == 0.0

    def test_red_hue_near_zero(self):
        h, _, _ = rgb_to_hsl(255, 0, 0)
        assert 0.0 <= h < 0.05


# ═══════════════════════════════════════════════════
#  lighten — 提亮
# ═══════════════════════════════════════════════════

class TestLighten:

    def test_lighten_black(self):
        """纯黑提亮应变灰。"""
        result = lighten("#000000", 50)
        r, g, b = parse_color(result)
        assert r > 0 and g > 0 and b > 0

    def test_lighten_zero_percent_no_change(self):
        """提亮 0% 应不变。"""
        assert lighten("#FF0000", 0) == "#FF0000"

    def test_lighten_returns_hex(self):
        result = lighten("#0E0E24", 10)
        assert result.startswith("#")
        assert len(result) == 7

    def test_lighten_tuple_input(self):
        """支持 (r,g,b) 元组输入。"""
        result = lighten((0, 0, 0), 50)
        assert result.startswith("#")


# ═══════════════════════════════════════════════════
#  darken — 加深
# ═══════════════════════════════════════════════════

class TestDarken:

    def test_darken_white(self):
        """纯白加深应变暗。"""
        result = darken("#FFFFFF", 50)
        r, g, b = parse_color(result)
        assert r < 255

    def test_darken_zero_percent_no_change(self):
        assert darken("#FF0000", 0) == "#FF0000"

    def test_darken_already_dark(self):
        """已经很深的颜色加深不应出错。"""
        result = darken("#0E0E24", 5)
        assert result.startswith("#")


# ═══════════════════════════════════════════════════
#  opacity — 透明度
# ═══════════════════════════════════════════════════

class TestOpacity:

    def test_half_opacity_returns_8hex(self):
        result = opacity("#00FFFF", 0.5)
        assert len(result) == 9  # # + 8 hex digits

    def test_full_opacity(self):
        result = opacity("#FFE600", 1.0)
        assert result.endswith("FF")

    def test_zero_opacity(self):
        result = opacity("#FFE600", 0.0)
        assert result.endswith("00")

    def test_clamp_above_one(self):
        """alpha > 1 应被钳制为 FF。"""
        result = opacity("#FF0000", 2.0)
        assert result.endswith("FF")

    def test_clamp_below_zero(self):
        """alpha < 0 应被钳制为 00。"""
        result = opacity("#FF0000", -1.0)
        assert result.endswith("00")


# ═══════════════════════════════════════════════════
#  mix — 混合两色
# ═══════════════════════════════════════════════════

class TestMix:

    def test_weight_zero_is_color_a(self):
        """weight=0 应全部取 color_a。"""
        assert mix("#FF0000", "#0000FF", 0) == "#FF0000"

    def test_weight_one_is_color_b(self):
        """weight=1 应全部取 color_b。"""
        assert mix("#FF0000", "#0000FF", 1) == "#0000FF"

    def test_mid_mix_is_between(self):
        """50% 混合应在两者之间。"""
        result = mix("#000000", "#FFFFFF", 0.5)
        r, g, b = parse_color(result)
        assert 64 < r < 192  # 大约 128 左右

    def test_same_color_returns_same(self):
        assert mix("#FF0000", "#FF0000", 0.5) == "#FF0000"


# ═══════════════════════════════════════════════════
#  is_color_value — 合法性判断
# ═══════════════════════════════════════════════════

class TestIsColorValue:

    @pytest.mark.parametrize("value", [
        "#FF0000",
        "#00FFFF",
        "F00",
        "abcdef",
        "transparent",
    ])
    def test_valid_colors(self, value):
        assert is_color_value(value) is True

    @pytest.mark.parametrize("value", [
        "red",
        "rgb(255,0,0)",
        "",
        "not-color",
        "12345",
    ])
    def test_invalid_colors(self, value):
        assert is_color_value(value) is False
