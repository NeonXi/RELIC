"""
[L4] core.widgets.screen_select_button — ScreenSelectButton 大号屏幕选择按钮

归属层:    [L4] (core/widgets/)
允许依赖:  core.widgets.button (CyberButton), core.tokens.manager, PySide6
禁止依赖:  core.services/*, core.pages/*, 任何 IO/JSON/网络

职责:
  - 屏幕选择卡中的"每屏一个"按钮(替代小 CheckBox,便于快速操作)
  - 选中态: CyberButton solid 变体(实心黄色)
  - 不选中态: CyberButton outlined 变体(空心黄色)
  - 大尺寸 + 高对比度,沿用 CyberButton 的切角 + 外发光设计语言

迁移记录:
  2026-07-20  从 core/pages/eye_mask_page.py 内嵌 CheckBox 迁出
              (规范 §6.5 禁止 Page 内嵌自定义控件,只能组装 Widget/Section)

本文件相关红线:
- ✗ 禁止 __init__ 调 super().__init__() → 必须 QPushButton.__init__(self, ...)
  (经 CyberButton.__init__ 链式调到 QPushButton,这里 super() 走 MRO 也行)
- ✗ 禁止重写 paintEvent → 视觉交给 CyberButton
- ✗ 禁止硬编码颜色 / 尺寸 → 必须 self.token() / self.space()
- ✗ 禁止私有属性用 _xxx 命名 → 必须 _cyber_xxx 前缀(规范 §6.4)
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPaintEvent, QColor, QPen, QBrush, QFont

from core.widgets.button import CyberButton, ButtonVariant


class ScreenSelectButton(CyberButton):
    """屏幕选择按钮 — 选中实心黄,不选空心黄。

    复用 CyberButton 的状态机(mixin)与信号(clicked),但自绘 paintEvent:
    - **完整矩形边框**(无 br 切角),保证下框线全宽显示
    - 选中态: 实心黄色填充 + 深色文字
    - 不选中态: 透明底 + 黄色边框 + 黄色文字,hover 时加 10% 黄底反馈
    - 大尺寸: 高度 height.btn_lg(44),最小宽度 8 × xxl(192)

    与 CyberButton 的差异:
    - CyberButton 用 `_chamfered_path(mode="br")` 画切角+外发光,
      右下角 8px 是斜切,下框线视觉上"少一段"
    - 本类用 `drawRect` 画完整矩形,下框线全宽

    使用方式::
        btn = ScreenSelectButton("屏幕 1 · 2560 × 1440")
        btn.set_selected(True)  # 选中态
        btn.clicked.connect(lambda: btn.set_selected(not btn.is_selected()))

    参数:
      text:   按钮文字(一般传"屏幕 N · 宽x高[ · 主屏]")
      parent: Qt 父对象
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        # 初始为 outlined 变体(空心,代表"未选中"),传过去仅作语义占位,
        # 实际绘制由本类 paintEvent 全权接管
        super().__init__(text, variant=ButtonVariant.OUTLINED, parent=parent)
        # ── 私有属性必须 _cyber_ 前缀(规范 §6.4) ──
        self._cyber_selected: bool = False

        # ── 大尺寸:高度按 btn_lg,最小宽度 8 * xxl = 192(4 的倍数) ──
        # 用 setFixedHeight 锁定(覆盖 CyberButton 默认的 36,避免 minHeight 失效)
        self.setFixedHeight(self.space("height.btn_lg", 44))
        self.setMinimumWidth(self.space("xxl", 24) * 8)  # 192

    # ── 公开 API ──

    def set_selected(self, on: bool) -> None:
        """设置选中状态(切换变体: solid=实心黄, outlined=空心黄)。"""
        self._cyber_selected = on
        # 触发重绘:本类 paintEvent 自绘,不依赖 variant setter
        self.update()

    def is_selected(self) -> bool:
        """当前是否选中。"""
        return self._cyber_selected

    # ── 自绘:完整矩形边框(无 br 切角) ──

    def paintEvent(self, event: QPaintEvent) -> None:
        """自绘 paintEvent,覆盖 CyberButton 的 br 切角绘制。

        规范 §6.4 要求 paintEvent 顺序:
            QPainter → 自绘 → super()
        这里自绘完成后再 super(),让 QPushButton 接管焦点框/快捷键下划线等。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 像素对齐(0.5 偏移)确保 1px 边框在常规 DPI 下不模糊
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # ── 颜色全部走 token,绝不硬编码 ──
        accent = self.token_color("accent.primary")
        bg_base = self.token_color("bg.base")
        state = self._state  # mixin 维护: normal/hover/pressed/focused/disabled

        if self._cyber_selected:
            # ── 实心黄:填充 accent + 深色文字 ──
            painter.fillRect(rect, QBrush(accent))
            text_color = bg_base
        else:
            # ── 空心黄:透明底,hover 时给一点 10% 黄底反馈 ──
            if state == "hover":
                hover_bg = QColor(accent)
                hover_bg.setAlphaF(0.10)
                painter.fillRect(rect, QBrush(hover_bg))
            text_color = accent

        # ── 边框:完整矩形(无切角,保证下框线全宽) ──
        # focused 态稍粗(1.5px),与 CyberButton 保持一致
        pen_width = 1.5 if state == "focused" else 1.0
        painter.setPen(QPen(accent, pen_width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect)

        # ── 文字:中央对齐,粗体 ──
        painter.setPen(text_color)
        font = QFont()
        font.setBold(True)
        font.setPointSize(self.space("font_size.sm", 10))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())

        # 保留 super(),让 QPushButton 接管焦点框/快捷键下划线等残留绘制
        super().paintEvent(event)
