"""
[L4] core.widgets.immersive — 沉浸黑色模式 纯函数模块

归属层:    [L4] (core/widgets/)
允许依赖:  PySide6.QtGui, core.tokens.manager;
           延迟 import core.widgets.base(仅函数体内,避免循环导入)
禁止依赖:  core.services/*, core.pages/*, 任何 IO/JSON/网络

职责:
  沉浸黑色模式的**唯一**颜色计算实现:
    1. 读取全局沉浸状态(存放在 CyberWidgetMixin 类级属性);
    2. RGB 覆写(沉浸底色预设:主题色 / 纯黑);
    3. alpha 折减(沉浸强度 0-100)。

  供以下调用方复用(此前各自内联实现,已收敛到本模块):
    - core/widgets/base.py        (CyberWidgetMixin 的 5 个 helper)
    - core/pages/base_page.py     (_resolve_immersive_bg_str)
    - core/widgets/hotkey_capture_edit.py (_resolve_immersive_bg)
    - core/app_shell.py           (窗口底色 / 导航容器底色)

设计说明:
  - 状态仍以 CyberWidgetMixin 类级属性为唯一属主(set_immersive_global /
    set_immersive_color_mode 写入),本模块只读 → 行为零变化;
  - 全部是无状态纯函数(QColor 入参一律拷贝,不修改原对象);
  - 为什么延迟 import base:base.py 模块级 import 本模块,
    若本模块也在模块级 import base 会构成循环;函数体内 import 时
    base 已加载完成,安全。

## AI 硬约束 — 修改本文件前必读
- ✗ 禁止在函数外持有 widget / service 引用 → 纯函数
- ✗ 禁止硬编码颜色 → 纯黑兜底取 surface.overlay token,失败才 #000000
- ✗ 改折减/覆写规则只改这里 → 调用方无需感知
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtGui import QColor

# 兜底纯黑(仅在 surface.overlay token 缺失/非法时使用;
# 沉浸底色=纯黑本身是用户语义"黑色",此字面量是该语义的最后防线)
_FALLBACK_BLACK_RGB = (0, 0, 0)


# ════════════════════════════════════
#  状态读取(延迟 import,只读)
# ════════════════════════════════════

def is_active() -> bool:
    """沉浸模式是否开启。"""
    from core.widgets.base import CyberWidgetMixin
    return bool(CyberWidgetMixin._cyber_immersive)


def override_color() -> Optional[QColor]:
    """沉浸底色覆写色(主题切换时由 AppShell 写入;None=沿用 token 原色)。"""
    from core.widgets.base import CyberWidgetMixin
    o = CyberWidgetMixin._cyber_immersive_color_override
    return o if o is not None else None


def _strength() -> int:
    """沉浸强度 0-100(越大底色越透)。"""
    from core.widgets.base import CyberWidgetMixin
    return max(0, min(100, int(CyberWidgetMixin._cyber_immersive_strength)))


# ════════════════════════════════════
#  核心计算(唯一实现)
# ════════════════════════════════════

def alpha_factor(normal_alpha: float) -> float:
    """按沉浸强度折减 alpha:非沉浸返回原值;沉浸返回 ×(1 - 强度/100)。"""
    if not is_active():
        return normal_alpha
    return normal_alpha * (1.0 - _strength() / 100.0)


def resolve_qcolor(color: QColor, alpha: float) -> QColor:
    """QColor 路径唯一入口:沉浸时覆写 RGB + 折减 alpha。

    Args:
        color: 原色(调用方从 token 取好;会被拷贝,不修改原对象)
        alpha: 非沉浸时的目标 alpha(paintEvent / QSS 前的最终透明度)

    Returns:
        最终 QColor(已应用 RGB 覆写和 alpha 折减)
    """
    color = QColor(color)  # 拷贝,避免修改原对象
    if is_active():
        o = override_color()
        if o is not None:
            color = QColor(o.red(), o.green(), o.blue(), color.alpha())
    color.setAlphaF(alpha_factor(alpha))
    return color


def resolve_current_alpha(color: QColor) -> QColor:
    """QColor 路径(保留原 alpha)入口:沉浸时覆写 RGB,按原 alpha 折减。

    与 resolve_qcolor 区别:目标 alpha 不由调用方给定,而是沿用 color
    自带的 alpha(适合调用方已按状态设好 alpha 的场景,如
    HotkeyCaptureEdit 的三态底色)。
    """
    return resolve_qcolor(color, color.alphaF())


def override_rgb(color: QColor) -> QColor:
    """只覆写 RGB 不折减 alpha(窗口底色 / 导航容器底色专用)。

    QMainWindow 是窗口最底层,不能折减 alpha(否则窗口本身透明露出桌面);
    导航容器的 alpha 折减由调用方自行 setAlphaF。
    覆写时 alpha 重置为 255(与原导航实现保持一致,底层底色本就不透明)。
    """
    color = QColor(color)  # 拷贝
    if is_active():
        o = override_color()
        if o is not None:
            # 三参构造:alpha 重置为 255(原 _cyber_resolve_nav_bg_color 行为)
            color = QColor(o.red(), o.green(), o.blue())
    return color


def black_rgb(tm) -> QColor:
    """沉浸纯黑底色:取 surface.overlay token,失败兜底纯黑字面量。

    Args:
        tm: TokenManager 实例(调用方传入,避免本模块绑定单例)

    Returns:
        纯黑语义的 QColor(alpha=255;调用方按需再改 alpha)
    """
    try:
        s = tm.get("surface.overlay")
        c = QColor(s) if s else None
        if c is not None and c.isValid():
            return QColor(c.red(), c.green(), c.blue())
    except Exception:
        pass
    return QColor(*_FALLBACK_BLACK_RGB)


def resolve_token_str(tm, key: str, alpha: float = 1.0) -> str:
    """QSS 字符串路径唯一入口:token key → 沉浸覆写 → ``#AARRGGBB``。

    供 Page 层(_apply_form_style / _apply_spin_style 等)与 Widget 层
    (_apply_popup_style / _apply_text_style 等)构造 QSS 时调用。

    Args:
        tm: TokenManager 实例
        key: 颜色 token 路径(如 ``alias.bg.raised``)
        alpha: 非沉浸时的目标 alpha

    Returns:
        QSS 可直接拼接的颜色字符串(#AARRGGBB,支持 alpha 通道)
    """
    qcolor = tm.get_qcolor(key)
    return resolve_qcolor(qcolor, alpha).name(QColor.NameFormat.HexArgb)
