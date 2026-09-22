"""
[L4] core.widgets.trigger_status_bar — TriggerStatusBar 触发器开关/摘要控件

归属层:    [L4] (core/widgets/)
允许依赖:  core.tokens.manager, core.widgets.base (CyberWidgetMixin), PySide6
禁止依赖:  core.services/*, core.pages/*, 任何 IO/JSON/网络

职责:
  - 触发器卡片底部的状态栏(开关 + 名称 + 摘要)
  - 点击切换启用状态(emit toggled(bool))
  - 颜色全部从 TokenManager 取(支持主题切换)

视觉(与项目统一开关风格对齐,同 CyberButton outlined/solid):
  - 启用态 = solid:accent.primary 黄色实心底 + 深色文字(bg.base)
  - 禁用态 = outlined:透明底 + accent.secondary 蓝色描边 + 弱化文字
  - 两态都显示 ON/OFF 文本(用户可感知状态)
  - 右下角切角(项目 Cyberpunk Chamfered 风格,非圆角)

迁移记录: 2026-06-17 从 core/pages/triggers_page.py 内部类 _TriggerStatusBar 迁出
违反规范: §6.5 "Page 禁止内嵌自定义控件,只能组装 Widget/Section"
风格统一: 2026-09-22 圆角→切角、warning底→solid/outlined 开关语义、挂 Mixin

本文件相关红线:
- ✗ 禁止 setStyleSheet(f-string) → 用自绘 + Token
- ✗ 禁止读写 JSON / 调 service / 任何 IO
- ✗ 禁止硬编码颜色/尺寸 → 全部 token / space
"""

# ── 标准库 ──
from __future__ import annotations

# ── PySide6 ──
from PySide6.QtWidgets import QFrame
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPen, QBrush

# ── 项目内 ──
from core.widgets.base import CyberWidgetMixin
from core.tokens.manager import TokenManager


class TriggerStatusBar(CyberWidgetMixin, QFrame):
    """触发器卡片底部状态栏:开关 + 名称 + 摘要,点击切换启用。

    使用流程:
      1. 创建实例,设置 setMinimumHeight(48)
      2. 监听 toggled(bool) 信号,处理启用/禁用
      3. 每次数据更新时调 set_state(enabled, name, summary) 重绘

    视觉(项目统一开关风格,同功能开关页/CD辅助页):
      - 启用态 = solid:黄实心底 + 深色文字
      - 禁用态 = outlined:蓝描边 + 透明底 + 弱化文字
    """

    # ── 信号 ──
    toggled = Signal(bool)  # 用户点击切换,参数是切换后的状态

    def __init__(self, parent=None) -> None:
        QFrame.__init__(self, parent)
        CyberWidgetMixin.__init__(self)
        # ── 状态 ──
        self._enabled: bool = False
        self._name: str = ""
        self._summary: str = ""

        # ── 交互 ──
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(self.space("height.btn_lg", 48))

    # ── 公开 API ──

    def set_state(self, enabled: bool, name: str, summary: str) -> None:
        """更新状态并触发重绘。

        参数:
          enabled: 当前是否启用
          name:    触发器名称(空时显示 "unnamed")
          summary: 摘要描述(空时显示 "not configured")
        """
        self._enabled = enabled
        self._name = name or "unnamed"
        self._summary = summary
        self.update()

    # ── 事件 ──

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._enabled = not self._enabled
            self.toggled.emit(self._enabled)
            self.update()
            event.accept()

    # ── 绘制 ──

    def paintEvent(self, event) -> None:
        """绘制状态栏(切角 + solid/outlined 开关语义)。

        顺序(规范 §5.3): QPainter → 自绘背景/边框/文字 → (QFrame 无默认绘制,无需 super)
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ── 切角路径(右下角,项目 Cyberpunk Chamfered 风格) ──
        corner = self.space("corner.sm", 8)
        path = self._chamfered_path(self.rect(), corner, mode="br")

        # ── 选色(统一开关语义:enabled=solid 黄实心 / disabled=outlined 蓝描边) ──
        if self._enabled:
            bg = self.token_color("components.button.solid.fill")
            border = bg
            status_color = self.token_color("components.button.solid.text")
            summary_color = status_color
        else:
            bg = self.token_color("components.button.outlined.fill")
            border = self.token_color("components.button.outlined.border")
            status_color = self.token_color("components.button.outlined.text")
            summary_color = self.token_color("text.tertiary")

        # ── 填充 + 描边 ──
        painter.fillPath(path, QBrush(bg))
        painter.setPen(QPen(border, self.space("border.thin", 1)))
        painter.drawPath(path)

        # ── 两行文字(坐标按字体度量自适应,间距从 space 取) ──
        pad_x = self.space("spacing.sm", 8) + self.space("spacing.xs", 4)

        font_title = painter.font()
        font_title.setPointSize(self.space("font.sm", 12))
        painter.setFont(font_title)
        fm1 = painter.fontMetrics()
        status = "ON" if self._enabled else "OFF"
        painter.setPen(status_color)
        y1 = fm1.ascent() + self.space("spacing.xs", 4)
        painter.drawText(pad_x, y1, f"{status} · {self._name}")

        font_sub = painter.font()
        font_sub.setPointSize(self.space("font.xs", 10))
        painter.setFont(font_sub)
        fm2 = painter.fontMetrics()
        painter.setPen(summary_color)
        line2 = self._summary or "not configured"
        # 摘要过长时截断,避免溢出切角区域
        elided = fm2.elidedText(
            line2, Qt.TextElideMode.ElideRight, self.width() - pad_x * 2
        )
        y2 = y1 + fm2.ascent() + self.space("spacing.xs", 4)
        painter.drawText(pad_x, y2, elided)
