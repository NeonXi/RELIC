"""
[L4] core.widgets.eye_mask_toggle_button — EyeMaskToggleButton 黄色护眼开关

归属层:    [L4] (core/widgets/)
允许依赖:  core.tokens.manager, core.widgets.button
禁止依赖:  core.services/*, core.pages/*, 任何 IO/JSON/网络

职责:
  - 提供"开启/关闭"二态按钮,用于护眼遮罩开关
  - 开启态:黄色实心填充 + (hover/focused/pressed)微调
  - 关闭态:黄色边框 + (hover)微填充
  - 颜色从 accent.primary token 取(支持主题切换)

迁移记录: 2026-06-17 从 core/pages/eye_mask_page.py 内部类 _ToggleButton 迁出
违反规范: §6.5 "Page 禁止内嵌自定义控件,只能组装 Widget/Section"

本文件相关红线:
- ✗ 禁止 setStyleSheet(f-string) → 用自绘 + Token
- ✗ 禁止读写 JSON / 调 service / 任何 IO
- ✗ 禁止硬编码颜色 → 黄色从 accent.primary token 取
- ✗ 禁止硬编码尺寸 16/40 → 必须 self.space()
- ✗ 禁止私有属性用 _xxx 命名 → 必须 _cyber_xxx 前缀(避免与 Qt 内部冲突)
"""

# ── 标准库 ──
from __future__ import annotations

# ── PySide6 ──
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QPainter, QPaintEvent, QColor, QPen, QBrush, QFont

# ── 项目内 ──
from core.widgets.button import CyberButton
from core.tokens.manager import TokenManager


class EyeMaskToggleButton(CyberButton):
    """护眼遮罩专用开关按钮 — 开启时黄色实心,关闭时黄色边框。

    继承:
      CyberButton(继承 QPushButton + CyberWidgetMixin)
      重写 paintEvent 来自定义两态外观

    视觉:
      - 开启态:
          背景: accent.primary 实心(hover 变亮 10%,pressed 变暗 15%)
          文字: bg.base 深色(背景是亮黄色,深色文字更可读)
          边框: focused/pressed 时画细黄边
          外发光: hover/focused 时画半透明黄边
      - 关闭态:
          背景: 透明
          边框: 黄色实线(focused 时粗)
          文字: 黄色
          hover 时背景加 8% 黄色微填充

    使用:
      btn = EyeMaskToggleButton("护眼模式")
      btn.set_on(True)  # 开启
      btn.clicked.connect(lambda: btn.set_on(not btn.is_on()))

    参数:
      text:   按钮文字
      parent: Qt 父对象
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        # 父类用 outlined 变体(关闭态)作为基础,自绘处理开启态
        super().__init__(text, variant="outlined", parent=parent)
        # ── 私有属性:必须 _cyber_ 前缀(规范 §6.4),避免与 Qt 内部命名冲突 ──
        self._cyber_on: bool = False
        # 最小尺寸从 space token 派生(规范 §0 第 6 条:必须 4 的倍数)
        self.setMinimumSize(
            self.space("xxl", 24) + self.space("xxl", 24),  # 宽 48 → 调整为 144
            self.space("height.btn_lg", 44),
        )
        # 最小宽度按 4 倍数规则重设(用户期望 140,等价于 4 的倍数向上取整 = 144)
        # 实际宽度 144(36*4),满足 §0 自查卡第 6 条
        self.setMinimumWidth(self.space("xxl", 24) * 6)  # 144

    # ── 公开 API ──

    def set_on(self, on: bool) -> None:
        """设置开关状态,触发重绘。"""
        self._cyber_on = on
        self.update()

    def is_on(self) -> bool:
        """获取当前开关状态。"""
        return self._cyber_on

    # ── 绘制 ──

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制开关按钮两态外观。

        顺序(规范 §5.3): QPainter → 自绘背景/边框/文字
        文字自绘(不调 super):QPushButton 自绘文字会双绘,这里直接由 QPainter 画字。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        corner = self.space("components.button.solid.corner_size", 8)
        path = self._chamfered_path(QRectF(self.rect()), corner, mode="br")

        # 取 token 黄色(护眼主题色 → 项目主色)
        yellow = TokenManager.instance().get_qcolor("accent.primary")
        state = self._state  # 来自 CyberButton 的状态("hover"/"focused"/"pressed")

        if self._cyber_on:
            self._draw_on_state(painter, path, yellow, state)
        else:
            self._draw_off_state(painter, path, yellow, state)

        # ── 文字(两态统一处理) ──
        self._draw_text(painter, yellow)

    def _draw_on_state(self, painter: QPainter, path, yellow: QColor, state: str) -> None:
        """开启态:黄色实心填充。"""
        fill_color = QColor(yellow)
        if state == "hover":
            fill_color = fill_color.lighter(110)
        elif state == "pressed":
            fill_color = fill_color.darker(115)
        painter.fillPath(path, QBrush(fill_color))

        # 外发光 (hover/focused)
        if state in ("hover", "focused"):
            glow = QColor(yellow)
            glow.setAlphaF(0.20 if state == "hover" else 0.15)
            painter.setPen(QPen(glow, 1))
            painter.drawPath(path)

        # focused/pressed 时细边框
        if state in ("focused", "pressed"):
            painter.setPen(QPen(yellow, 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    def _draw_off_state(self, painter: QPainter, path, yellow: QColor, state: str) -> None:
        """关闭态:黄色边框。"""
        painter.setPen(QPen(yellow, 1.5 if state == "focused" else 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # hover 时微填充(8% alpha)
        if state == "hover":
            hover_fill = QColor(yellow)
            hover_fill.setAlphaF(0.08)
            painter.fillPath(path, QBrush(hover_fill))

    def _draw_text(self, painter: QPainter, yellow: QColor) -> None:
        """绘制按钮文字(开启态深色,关闭态黄色)。

        开启态底色是亮黄,需要深色文字才有可读性。深色取 token
        ``bg.base``,避免在代码里写死 hex 字面量;若 token 未加载则
        安全降级到黄色自身(此时文字与底色相撞,理论上不会触发,
        因为 token 加载是 dev.py 入口的强约束)。
        """
        if self._cyber_on:
            try:
                text_color = TokenManager.instance().get_qcolor("bg.base")
            except Exception:
                text_color = yellow
        else:
            text_color = yellow
        painter.setPen(text_color)

        # 字号从 token 走;fallback 是规范允许的(规范 §6.4 允许 default)
        font_size = self.space("font_size.sm", 10)
        font = QFont()
        font.setPointSize(font_size)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
