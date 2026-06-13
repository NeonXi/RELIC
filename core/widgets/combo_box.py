"""
CyberComboBox — 赛博风格下拉菜单。

继承 QComboBox 原生能力（下拉列表、搜索过滤等），
仅覆盖视觉部分（切角背景 + 状态边框 + 下拉箭头）。

使用方式::

    combo = CyberComboBox()
    combo.addItems(["选项 A", "选项 B", "选项 C"])
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QComboBox, QWidget
from PySide6.QtGui import (
    QPainter, QPaintEvent, QFocusEvent, QColor,
    QPen, QBrush, QPainterPath,
)
from PySide6.QtCore import Qt, QRect, QRectF

from core.widgets.base import CyberWidgetMixin


class CyberComboBox(CyberWidgetMixin, QComboBox):
    """赛博风格下拉菜单。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
    ):
        QComboBox.__init__(self, parent)

        # 尺寸
        h = self.space("height.input", 36)
        self.setFixedHeight(h)

        # 隐藏原生边框和背景，完全自绘
        bg_raised = self.token_color("surface.raised").name()
        text_main = self.token_color("text.primary").name()
        border_default = self.token_color("border.default").name()
        selection_bg = self.token_color("neutral.dark").name()
        accent_primary = self.token_color("accent.primary").name()

        self.setStyleSheet(f"""
            QComboBox {{
                border: none;
                background: transparent;
                padding-left: 12px;
                padding-right: 28px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 24px;
            }}
            QComboBox::down-arrow {{
                image: none;
                width: 0px;
                height: 0px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {bg_raised};
                color: {text_main};
                border: 1px solid {border_default};
                selection-background-color: {selection_bg};
                selection-color: {accent_primary};
                outline: none;
            }}
            /* 下拉列表项 hover 样式 */
            QComboBox QAbstractItemView::item {{
                padding: 6px 12px;
                min-height: 28px;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: {selection_bg};
                color: {accent_primary};
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {selection_bg};
                color: {accent_primary};
            }}
        """)

    # ── 事件 ──

    def wheelEvent(self, event) -> None:
        """禁用滚轮切换下拉选项，避免滚动页面时误改选项。"""
        event.ignore()

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
        from PySide6.QtGui import QPolygonF

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

        # ── 下拉箭头（右侧绘制）──
        arrow_color = self.token_color("accent.secondary")
        if state == "hover" or state == "focused":
            arrow_color = self.token_color("accent.primary")
        painter.setPen(QPen(arrow_color, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        ax = self.width() - 16
        ay = self.height() / 2 - 3
        arrow = QPolygonF([
            __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(ax - 5, ay),
            __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(ax + 5, ay),
            __import__("PySide6.QtCore", fromlist=["QPointF"]).QPointF(ax, ay + 7),
        ])
        painter.drawPolygon(arrow)

        # 让 Qt 渲染文字
        super().paintEvent(event)
