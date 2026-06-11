"""
页面基类 — PageBase。

所有功能页面的公共接口和生命周期管理。
每个页面继承此类后自动注册到导航系统。

使用方式::

    class TogglesPage(PageBase):
        page_id = "toggles"
        page_title = "功能开关"
        page_icon = "nav_toggles"

        def build_content(self) -> QWidget:
            # 返回页面的主内容 widget
            ...
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from core.tokens.manager import TokenManager


class PageBase(QWidget):
    """页面基类。

    提供统一的页面生命周期：
      - on_enter: 页面被切换到（获得焦点）
      - on_leave: 页面被切走（失去焦点）
      - on_theme_change: 主题变更时刷新
      - build_content: 构建页面内容（子类必须实现）
    """

    # ── 子类必须定义的属性 ──
    page_id: str = ""           # 唯一标识，如 "toggles"
    page_title: str = ""        # 显示标题
    page_icon: str = ""         # 图标 key（对应 icon_loader 的 nav/xxx）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._app_shell = None   # 引用宿主 AppShell（由 AppShell 注入）

        tm = TokenManager.instance()
        self._tm = tm
        self._bg_color_str = tm.get("alias.bg.raised")
        self._text_primary_str = tm.get("alias.text.primary")

        self._setup_base_ui()

    # ── Token 辅助方法 ──

    def _color(self, key: str) -> str:
        """获取 token 颜色的 hex 字符串，供 stylesheet 使用。

        Token 必须存在于 YAML 预设文件中，否则抛出异常。
        """
        qcolor = self._tm.get_qcolor(key)
        return qcolor.name()

    def _font_size(self, key: str, fallback: int = 12) -> int:
        """获取 token 字号值。"""
        return self._tm.space(f"font.{key}", fallback)

    def _spacing(self, key: str, fallback: int = 8) -> int:
        """获取 token 间距值（space.spacing.*）。"""
        return self._tm.space(f"spacing.{key}", fallback)

    def _copy(self, key: str, default: str = "", **kwargs) -> str:
        """获取文案 token 字符串，支持模板变量替换。"""
        return self._tm.copy(key, default, **kwargs)

    # ══════════════════════════════════
    #  基础布局
    # ══════════════════════════════════

    def _setup_base_ui(self):
        """构建基础容器布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        content = self.build_content()
        if content:
            layout.addWidget(content)

    # ══════════════════════════════════
    #  子类必须实现
    # ══════════════════════════════════

    def build_content(self) -> QWidget:
        """构建并返回页面的主内容 Widget。

        子类必须覆盖此方法。返回的 widget 将被放入内容区域。

        Returns:
            QWidget 实例
        """
        return self._build_placeholder()

    # ══════════════════════════════════
    #  生命周期钩子（子类可选覆盖）
    # ══════════════════════════════════

    def on_enter(self):
        """页面被切换到时调用。"""
        pass

    def on_leave(self):
        """页面被切走时调用。"""
        pass

    def on_theme_change(self):
        """主题变更时调用，用于刷新颜色等。"""
        self.update()

    # ══════════════════════════════════
    #  内部工具
    # ══════════════════════════════════

    def _build_placeholder(self) -> QFrame:
        """默认占位页面（子类未覆盖 build_content 时使用）。"""
        frame = QFrame()
        frame.setStyleSheet(f"background-color: transparent;")

        layout = QVBoxLayout(frame)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(f"[ {self.page_id} ]")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font_size = TokenManager.instance().space("font.xl", 20)
        title_font = QFont("Microsoft YaHei", font_size, QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {self._text_primary_str};")

        subtitle = QLabel("Coming Soon...")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub_font_size = TokenManager.instance().space("font.md", 14)
        sub_font = QFont("Microsoft YaHei", sub_font_size)
        sub_font.setItalic(True)
        subtitle.setFont(sub_font)
        subtitle.setStyleSheet(f"color: {self._color('alias.text.tertiary')};")

        layout.addWidget(title)
        layout.addWidget(subtitle)

        return frame

    def set_app_shell(self, shell):
        """注入宿主 AppShell 引用。"""
        self._app_shell = shell
