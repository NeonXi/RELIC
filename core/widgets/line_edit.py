"""
CyberLineEdit — 赛博风格输入框。

继承 QLineEdit 原生能力（文字输入、撤销、复制粘贴等），
仅覆盖视觉部分（切角背景 + 状态边框）。

使用方式::

    input = CyberLineEdit(placeholder="搜索...")
    input.set_placeholder("请输入内容")
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLineEdit, QWidget
from PySide6.QtGui import (
    QPainter, QPaintEvent, QFocusEvent, QColor,
    QPen, QBrush, QPainterPath,
)
from PySide6.QtCore import Qt, QRectF

from core.widgets.base import CyberWidgetMixin


class CyberLineEdit(CyberWidgetMixin, QLineEdit):
    """赛博风格输入框。"""

    def __init__(
        self,
        placeholder: str = "",
        parent: Optional[QWidget] = None,
    ):
        QLineEdit.__init__(self, parent)

        if placeholder:
            self.setPlaceholderText(placeholder)

        # 尺寸
        h = self.space("height.input", 36)
        self.setFixedHeight(h)

        # 隐藏原生边框和背景，完全自绘
        self.setStyleSheet("""
            QLineEdit {
                border: none;
                background: transparent;
                padding-left: 12px;
                padding-right: 12px;
            }
        """)

        # 文字颜色
        text_color = self.token_color("components.input.text")
        palette = self.palette()
        palette.setColor(palette.ColorRole.Text, text_color)
        self.setPalette(palette)

    def set_placeholder(self, text: str) -> None:
        """设置占位符文字。"""
        self.setPlaceholderText(text)

    # ── 事件 ──

    def enterEvent(self, event) -> None:
        self.cyber_enter_event(event)

    def leaveEvent(self, event) -> None:
        self.cyber_leave_event(event)

    def focusInEvent(self, event: QFocusEvent) -> None:
        self.cyber_focus_in_event(event)
        super().focusInEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.cyber_focus_out_event(event)
        super().focusOutEvent(event)

    # ── 绘制 ──

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        corner = self.space("components.input.corner_size", 6)
        path = self._chamfered_path(QRectF(self.rect()), corner, mode="all")

        # 背景
        bg_color = self.token_color("components.input.bg")

        state = self._state
        if state == "focused":
            try:
                bg_color = self.token_color("semantic.state.focused.bg")
            except Exception:
                pass
            bg_color.setAlphaF(0.95)
        elif state == "hover":
            bg_color.setAlphaF(0.85)
        else:
            bg_color.setAlphaF(0.75)

        painter.fillPath(path, QBrush(bg_color))

        # 边框
        if state == "focused":
            border_color = self.token_color("components.input.border_focus")
            pen_width = 1.5
        else:
            border_color = self.token_color("components.input.border")
            pen_width = 1.0

        painter.setPen(QPen(border_color, pen_width))
        painter.drawPath(path)

        # 让 Qt 渲染文字（光标、选中、占位符等）
        super().paintEvent(event)
