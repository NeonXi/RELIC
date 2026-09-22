"""
颜色函数库 — Design Token 颜色变换的纯数学实现。

基于 HSL 色彩空间运算，避免 RGB 直接插值导致的色偏问题。
本模块零外部依赖，可独立运行和测试。

支持的函数（对应 ui-framework-design.md 附录 A）:
    lighten(color, percent)   — 提亮，percent ∈ [0, 100]
    darken(color, percent)     — 加深，percent ∈ [0, 100]
    opacity(color, alpha)      — 设置透明度，alpha ∈ [0, 1]
    mix(color_a, color_b, weight) — 混合两色，weight ∈ [0, 1]

See Also:
    ui-framework-design.md 附录 A: 颜色函数规范

## AI 硬约束 — 修改本文件前必读
归属层:    [L-Infrastructure] (core/tokens/)
允许依赖:  PyYAML, Python 标准库
禁止依赖:  PySide6 / QtWidgets / QtCore(任何 Qt 命名空间)
           (Token 是数据层,不能引入 UI)
必读规范:  .trae/rules/开发规范.md §6.1

本文件相关红线:
- 禁止 import PySide6 → Token 不能依赖 UI
- 禁止返回 Qt 对象 → 只能返回 str / int / dict
- 禁止在 Token 里持有 widget 引用
- 禁止在 Token 中做 IO(读文件应该 lazy)

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.1。
"""

from __future__ import annotations

import re
from typing import Union

# 类型别名
ColorInput = Union[str, tuple[int, int, int]]
ColorTuple = tuple[int, int, int]

# 正则：匹配 #RGB、#RRGGBB、#RRGGBBAA 格式
_HEX_PATTERN = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


# ═══════════════════════════════════════════════════
#  基础工具：解析与格式化
# ═══════════════════════════════════════════════════

def parse_color(value: str) -> ColorTuple:
    """解析十六进制颜色字符串为 (R, G, B) 元组。

    Args:
        value: 十六进制颜色，支持 #RGB、#RRGGBB、#RRGGBBAA 三种格式。
               不带 # 前缀也可接受。

    Returns:
        (r, g, b) 元组，每个分量 ∈ [0, 255]

    Raises:
        ValueError: 输入不是合法的十六进制颜色格式

    Examples:
        >>> parse_color("#FFE600")
        (255, 230, 0)
        >>> parse_color("00FFFF")
        (0, 255, 255)
        >>> parse_color("#F60")
        (255, 102, 0)
    """
    match = _HEX_PATTERN.match(value.strip())
    if not match:
        raise ValueError(f"无效的颜色值: {value!r}，期望 #RGB 或 #RRGGBB 格式")

    hex_str = match.group(1)

    # 短格式展开：#ABC → #AABBCC
    if len(hex_str) == 3:
        hex_str = "".join(c * 2 for c in hex_str)

    r = int(hex_str[0:2], 16)
    g = int(hex_str[2:4], 16)
    b = int(hex_str[4:6], 16)

    return (r, g, b)


def to_hex(r: int, g: int, b: int, include_hash: bool = True) -> str:
    """将 (R, G, B) 元组转回十六进制字符串。

    Args:
        r, g, b: 颜色分量，∈ [0, 255]
        include_hash: 是否包含 # 前缀

    Returns:
        大写十六进制字符串，如 "#FFE600"

    Examples:
        >>> to_hex(255, 230, 0)
        '#FFE600'
    """
    prefix = "#" if include_hash else ""
    return f"{prefix}{r:02X}{g:02X}{b:02X}"


def to_rgba(r: int, g: int, b: int, a: float = 1.0) -> str:
    """生成 rgba() CSS 函数字符串。

    Args:
        r, g, b: 颜色分量，∈ [0, 255]
        a: 透明度，∈ [0.0, 1.0]

    Returns:
        如 "rgba(255, 230, 0, 0.5)"
    """
    return f"rgba({r}, {g}, {b}, {a:.4g})"


# ═══════════════════════════════════════════════════
#  色彩空间转换：RGB ↔ HSL
# ═══════════════════════════════════════════════════

def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """将值限制在 [low, high] 范围内。"""
    return max(low, min(high, value))


def rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    """将 RGB (0-255) 转换为 HSL (0-1 范围)。

    Args:
        r, g, b: RGB 分量，∈ [0, 255]

    Returns:
        (h, s, l) 元组：
            h: 色相 ∈ [0, 1)（0=红, 0.33=绿, 0.66=蓝）
            s: 饱和度 ∈ [0, 1]（0=灰, 1=纯色）
            l: 亮度 ∈ [0, 1]（0=黑, 1=白）
    """
    r_norm = r / 255.0
    g_norm = g / 255.0
    b_norm = b / 255.0

    c_max = max(r_norm, g_norm, b_norm)
    c_min = min(r_norm, g_norm, b_norm)
    delta = c_max - c_min

    # 亮度
    lightness = (c_max + c_min) / 2.0

    # 饱和度
    if delta == 0:
        saturation = 0.0
    else:
        saturation = delta / (1.0 - abs(2.0 * lightness - 1.0))

    # 色相
    if delta == 0:
        hue = 0.0
    elif c_max == r_norm:
        hue = ((g_norm - b_norm) / delta) % 6
    elif c_max == g_norm:
        hue = ((b_norm - r_norm) / delta) + 2
    else:
        hue = ((r_norm - g_norm) / delta) + 4

    hue /= 6.0
    if hue < 0:
        hue += 1.0

    return (hue, saturation, lightness)


def hsl_to_rgb(h: float, s: float, l: float) -> ColorTuple:
    """将 HSL (0-1 范围) 转换回 RGB (0-255)。

    Args:
        h: 色相 ∈ [0, 1)
        s: 饱和度 ∈ [0, 1]
        l: 亮度 ∈ [0, 1]

    Returns:
        (r, g, b) 元组，每个分量 ∈ [0, 255]
    """
    def _hue_to_rgb(p: float, q: float, t: float) -> float:
        if t < 0:
            t += 1
        if t > 1:
            t -= 1
        if t < 1/6:
            return p + (q - p) * 6 * t
        if t < 1/2:
            return q
        if t < 2/3:
            return p + (q - p) * (2/3 - t) * 6
        return p

    if s == 0:
        v = round(l * 255)
        return (v, v, v)

    q = l * (1 + s) if l < 0.5 else l + s - l * s
    p = 2 * l - q

    r = _hue_to_rgb(p, q, h + 1/3)
    g = _hue_to_rgb(p, q, h)
    b = _hue_to_rgb(p, q, h - 1/3)

    return (round(r * 255), round(g * 255), round(b * 255))


# ═══════════════════════════════════════════════════
#  核心颜色变换函数
# ═══════════════════════════════════════════════════

def lighten(color: ColorInput, percent: float) -> str:
    """提亮颜色。

    通过提高 HSL 中的 L（亮度）分量实现。保持色相不变，
    饱和度随亮度自动调整以避免过曝变白。

    Args:
        color: 输入颜色，支持 hex 字符串或 (r,g,b) 元组
        percent: 提亮百分比，∈ [0, 100]

    Returns:
        提亮后的 hex 颜色字符串（如 "#1A1A3D"）

    Examples:
        >>> lighten("#0E0E24", 10%)
        '#16162E'  # 近似值，实际以计算结果为准
        >>> lighten("#000000", 50%)  # 纯黑提亮 50%
        '#808080'
    """
    r, g, b = _ensure_tuple(color)
    h, s, l = rgb_to_hsl(r, g, b)

    # 亮度提升：percent/100 映射到 [0, 1-l]
    l_new = l + (1.0 - l) * (percent / 100.0)
    l_new = _clamp(l_new, 0.0, 1.0)

    # 提亮时适当降低饱和度，防止高亮区域过饱和
    s_new = s * (1.0 - (percent / 200.0))
    s_new = _clamp(s_new, 0.0, 1.0)

    return to_hex(*hsl_to_rgb(h, s_new, l_new))


def darken(color: ColorInput, percent: float) -> str:
    """加深颜色。

    通过降低 HSL 中的 L（亮度）分量实现。

    Args:
        color: 输入颜色
        percent: 加深百分比，∈ [0, 100]

    Returns:
        加深后的 hex 颜色字符串

    Examples:
        >>> darken("#08081A", 5%)
        '#070717'  # 近似值
    """
    r, g, b = _ensure_tuple(color)
    h, s, l = rgb_to_hsl(r, g, b)

    # 亮度降低：percent/100 映射到 [0, l]
    l_new = l * (1.0 - percent / 100.0)
    l_new = _clamp(l_new, 0.0, 1.0)

    # 加深时略微提升饱和度，增强色彩感
    s_new = s + (1.0 - s) * (percent / 200.0)
    s_new = _clamp(s_new, 0.0, 1.0)

    return to_hex(*hsl_to_rgb(h, s_new, l_new))


def opacity(color: ColorInput, alpha: float) -> str:
    """设置颜色的透明度。

    返回带 alpha 的 hex 字符串（8 位），供下游转换为 QColor 时使用。
    注意：标准 6 位 hex 无法表达透明度，因此返回 8 位格式。

    Args:
        color: 输入颜色
        alpha: 透明度值，∈ [0.0, 1.0]，0=全透，1=不透

    Returns:
        8 位 hex 字符串（如 "#00FFFF80"）

    Examples:
        >>> opacity("#00FFFF", 0.5)
        '#00FFFF80'
        >>> opacity("#FFE600", 0.35)
        '#FFE60059'
    """
    r, g, b = _ensure_tuple(color)
    a_int = round(_clamp(alpha, 0.0, 1.0) * 255)
    return f"#{r:02X}{g:02X}{b:02X}{a_int:02X}"


def mix(color_a: ColorInput, color_b: ColorInput, weight: float = 0.5) -> str:
    """混合两种颜色。

    在 HSL 空间中线性插值，避免 RGB 直插的色偏问题。
    weight 控制混合比例：0=全部取 color_a，1=全部取 color_b。

    Args:
        color_a: 第一种颜色
        color_b: 第二种颜色
        weight: 混合权重，∈ [0, 1]

    Returns:
        混合后的 hex 颜色字符串

    Examples:
        >>> mix("#FFFFFF", "#000000", 0.3)
        '#B3B3B3'  # 30% 黑 + 70% 白 ≈ 深灰
    """
    r1, g1, b1 = _ensure_tuple(color_a)
    r2, g2, b2 = _ensure_tuple(color_b)

    h1, s1, l1 = rgb_to_hsl(r1, g1, b1)
    h2, s2, l2 = rgb_to_hsl(r2, g2, b2)

    # HSL 各分量线性插值
    w = _clamp(weight, 0.0, 1.0)

    # 色相插值需处理环绕（0 和 1 是同一色调）
    h_diff = h2 - h1
    if h_diff > 0.5:
        h_diff -= 1.0
    elif h_diff < -0.5:
        h_diff += 1.0
    h_new = (h1 + h_diff * w) % 1.0

    s_new = s1 + (s2 - s1) * w
    l_new = l1 + (l2 - l1) * w

    return to_hex(*hsl_to_rgb(h_new, _clamp(s_new), _clamp(l_new)))


# ═══════════════════════════════════════════════════
#  内部辅助
# ═══════════════════════════════════════════════════

def _ensure_tuple(color: ColorInput) -> ColorTuple:
    """统一输入为 (r, g, b) 元组。"""
    if isinstance(color, str):
        return parse_color(color)
    return tuple(color)  # type: ignore[return-value]


def is_color_value(value: str) -> bool:
    """判断字符串是否是合法的颜色值（hex 格式或 transparent）。

    用于 Token 解析器判断一个 token 值是否需要颜色函数处理。

    Args:
        value: 待检测字符串

    Returns:
        如果是合法颜色返回 True
    """
    if value.lower() == "transparent":
        return True
    return bool(_HEX_PATTERN.match(value.strip()))


# 匹配 CSS rgb(r,g,b) / rgba(r,g,b,a) 函数
_CSS_RGB_PATTERN = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*"
    r"(?:,\s*([0-9]*\.?[0-9]+)\s*)?\)$",
    re.IGNORECASE,
)


def css_color_to_hex(value: str) -> str | None:
    """将 CSS ``rgb()/rgba()`` 函数字符串归一化为 Qt 兼容的十六进制。

    ``QColor(name)`` 不支持 CSS ``rgba(r,g,b,a)`` 函数语法，只认 hex。
    Token 解析层负责把这类值归一化，避免下游 ``QColor`` 解析失败回退。

    Args:
        value: 如 ``"rgba(255, 230, 0, 0.15)"`` 或 ``"rgb(255, 0, 0)"``

    Returns:
        - 带透明: ``"#AARRGGBB"``（与 ``QColor.NameFormat.HexArgb`` 一致，
          QSS / QColor 通用）
        - 不透明: ``"#RRGGBB"``
        - 不匹配或分量越界: ``None``
    """
    m = _CSS_RGB_PATTERN.match(value.strip())
    if not m:
        return None
    r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not all(0 <= c <= 255 for c in (r, g, b)):
        return None
    a_str = m.group(4)
    if a_str is None:
        return f"#{r:02X}{g:02X}{b:02X}"
    a = round(_clamp(float(a_str), 0.0, 1.0) * 255)
    return f"#{a:02X}{r:02X}{g:02X}{b:02X}"
