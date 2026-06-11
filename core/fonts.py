"""
字体管理器 — 内嵌字体注册与获取。

将 assets/fonts/ 下的 .ttf/.otf 文件注册到 QApplication，
使项目不依赖用户系统安装的字体。

使用方式::

    from core.fonts import FontManager
    FontManager.register_all()   # 启动时调用一次

    # 之后直接用字体名创建 QFont
    from PySide6.QtGui import QFont
    font = QFont("Iceberg", 12)
"""

from __future__ import annotations

import os

# ══════════════════════════════════════════════
#  内嵌字体清单（文件名 → 逻辑名称）
#  逻辑名称就是 QFont() 中使用的 family 名字
# ══════════════════════════════════════════════

FONTS = {
    "Iceberg-Regular.ttf":                  "Iceberg",
    "Monoton-Regular.ttf":                  "Monoton",
    "AlibabaPuHuiTi-3-45-Light.ttf":        "Alibaba PuHuiTi 3",
}

# 字体目录（相对于项目根目录）
_FONTS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts")

# 已注册标记
_registered: bool = False


def register_all() -> list[str]:
    """注册所有内嵌字体到 Qt 字体数据库。

    应在创建 QApplication 之后、任何 UI 组件之前调用（仅一次）。

    Returns:
        成功注册的字体逻辑名称列表。
    """
    global _registered
    if _registered:
        return []

    from PySide6.QtGui import QFontDatabase

    ok_names: list[str] = []
    fonts_dir = os.path.abspath(_FONTS_DIR)

    for filename, family in FONTS.items():
        path = os.path.join(fonts_dir, filename)
        if not os.path.exists(path):
            print(f"[Fonts] 文件不存在: {path}", flush=True)
            continue

        font_id = QFontDatabase.addApplicationFont(path)
        if font_id < 0:
            print(f"[Fonts] 注册失败: {filename}", flush=True)
            continue

        # 验证注册后的实际 family 名称
        families = QFontDatabase.applicationFontFamilies(font_id)
        actual_family = families[0] if families else family
        ok_names.append(actual_family)
        print(f"[Fonts] 已注册: {filename} → \"{actual_family}\"", flush=True)

    _registered = True
    return ok_names


def get(family: str, fallback: str = "Microsoft YaHei UI") -> str:
    """获取字体 family 名称，已注册则返回内嵌字体，否则返回 fallback。

    Args:
        family: 期望的字体系列名（如 "Iceberg"）
        fallback: 未注册时的回退字体

    Returns:
        实际可用的字体系列名。
    """
    from PySide6.QtGui import QFontDatabase
    # 检查该 family 是否在已注册字体中
    for _, reg_family in FONTS.items():
        if reg_family == family and _registered:
            return family
    return fallback
