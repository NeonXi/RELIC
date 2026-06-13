"""
[L2] EyeMaskPage — 护眼遮罩页面。

功能:
  - 全局快捷键 Ctrl+J 切换全屏护眼遮罩
  - 遮罩鼠标穿透（不抢焦点、不拦截点击）
  - 可调节遮罩不透明度
  - 配色固定为纯黑色
  - 快捷键可在此页面或开关控制页面修改

依赖: widgets/
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSlider,
)
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush,
    QFont, QPaintEvent,
)

from core.pages.base_page import PageBase
from core.widgets.card import CyberCard
from core.widgets.button import CyberButton
from core.tokens.manager import TokenManager

# ══════════════════════════════════════════════
#  遮罩默认值（颜色固定为纯黑）
# ══════════════════════════════════════════════

DEFAULT_COLOR = (0, 0, 0)
DEFAULT_OPACITY = 25  # 默认不透明度 25%

# ══════════════════════════════════════════════
#  Win32 鼠标穿透常量
# ══════════════════════════════════════════════

_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_GWL_EXSTYLE = -20


# ══════════════════════════════════════════════
#  全屏遮罩窗口
# ══════════════════════════════════════════════

class EyeMaskOverlay(QWidget):
    """全屏护眼遮罩窗口。

    特性：
    - 覆盖所有显示器
    - 鼠标完全穿透（不抢焦点、不拦截点击）
    - 纯黑色半透明遮罩
    """

    def __init__(self):
        super().__init__()
        self._color = QColor(*DEFAULT_COLOR, int(DEFAULT_OPACITY * 255 / 100))
        self._visible = False
        self._setup_window()

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._apply_win32_transparent()
        self._cover_all_screens()

    def _apply_win32_transparent(self):
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            ex_style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, _GWL_EXSTYLE,
                ex_style | _WS_EX_TRANSPARENT | _WS_EX_LAYERED
                | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE,
            )
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_win32_transparent()

    def _cover_all_screens(self):
        from PySide6.QtGui import QGuiApplication
        screens = QGuiApplication.screens()
        if not screens:
            self.setGeometry(0, 0, 1920, 1080)
            return
        total = screens[0].geometry()
        for s in screens[1:]:
            total = total.united(s.geometry())
        self.setGeometry(total)

    # ── 公开接口 ──

    def set_opacity(self, pct: int):
        alpha = max(0, min(255, int(pct * 255 / 100)))
        self._color.setAlpha(alpha)
        if self._visible:
            self.update()

    def get_opacity_pct(self) -> int:
        return int(self._color.alpha() * 100 / 255)

    def is_visible(self) -> bool:
        return self._visible

    def show_mask(self):
        if not self._visible:
            self._visible = True
            self._cover_all_screens()
            self.show()
            self.update()

    def hide_mask(self):
        if self._visible:
            self._visible = False
            self.hide()

    def toggle(self):
        if self._visible:
            self.hide_mask()
        else:
            self.show_mask()

    def paintEvent(self, event: QPaintEvent):
        if not self._visible:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self._color)


# ══════════════════════════════════════════════
#  开关按钮（继承 CyberButton，切角风格 + 黄色）
# ══════════════════════════════════════════════

class _ToggleButton(CyberButton):
    """开关按钮 — 开启时黄色实心，关闭时黄色边框。遵循切角风格规范。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, variant="outlined", parent=parent)
        self._on = False
        self.setMinimumSize(140, 40)

    def set_on(self, on: bool):
        self._on = on
        self.update()

    def is_on(self) -> bool:
        return self._on

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        corner = self.space("components.button.solid.corner_size", 8)
        path = self._chamfered_path(QRectF(self.rect()), corner, mode="br")

        yellow = TokenManager.instance().get_qcolor("semantic.warning")
        state = self._state

        if self._on:
            # ── 开启：黄色实心填充 ──
            fill_color = QColor(yellow)
            if state == "hover":
                fill_color = fill_color.lighter(110)
            elif state == "pressed":
                fill_color = fill_color.darker(115)
            text_color = QColor("#0a0a1a")
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
        else:
            # ── 关闭：黄色边框 ──
            painter.setPen(QPen(yellow, 1.5 if state == "focused" else 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            text_color = yellow

            # hover 时微填充
            if state == "hover":
                hover_fill = QColor(yellow)
                hover_fill.setAlphaF(0.08)
                painter.fillPath(path, QBrush(hover_fill))

        # ── 文字 ──
        painter.setPen(text_color)
        font_size = self.space("font_size.sm", 10)
        font = QFont()
        font.setPointSize(font_size)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


# ══════════════════════════════════════════════
#  EyeMaskPage
# ══════════════════════════════════════════════

class EyeMaskPage(PageBase):
    page_id = "eye_mask"
    page_title = ""
    page_icon = "nav_about"

    def __init__(self):
        self._opacity_pct = DEFAULT_OPACITY
        self._overlay: EyeMaskOverlay | None = None

        super().__init__()
        self.page_title = self._copy("nav.eye_mask", "护眼遮罩")

        # UI 引用
        self._opacity_slider: QSlider | None = None
        self._opacity_label: QLabel | None = None
        self._toggle_btn: _ToggleButton | None = None

    # ══════════════════════════════════
    #  生命周期
    # ══════════════════════════════════

    def set_app_shell(self, shell):
        super().set_app_shell(shell)
        self._connect_hotkey()

    def _connect_hotkey(self):
        try:
            pipeline = self._app_shell.pipeline
            if pipeline and hasattr(pipeline, 'eye_mask_toggled'):
                pipeline.eye_mask_toggled.connect(self._on_hotkey_toggle)
        except Exception:
            pass

    def on_enter(self):
        self._ensure_overlay()
        if self._app_shell:
            self._connect_hotkey()

    def on_leave(self):
        pass

    def _ensure_overlay(self):
        if self._overlay is None:
            self._overlay = EyeMaskOverlay()
            self._overlay.set_opacity(self._opacity_pct)

    # ══════════════════════════════════
    #  快捷键响应
    # ══════════════════════════════════

    def _on_hotkey_toggle(self):
        self._ensure_overlay()
        self._overlay.toggle()
        self._sync_ui_from_overlay()

    # ══════════════════════════════════
    #  UI 同步
    # ══════════════════════════════════

    def _sync_ui_from_overlay(self):
        if self._toggle_btn and self._overlay:
            visible = self._overlay.is_visible()
            self._toggle_btn.set_on(visible)
            self._toggle_btn.setText("关闭遮罩" if visible else "开启遮罩")

    # ══════════════════════════════════
    #  透明度变更
    # ══════════════════════════════════

    def _on_opacity_changed(self, value: int):
        self._opacity_pct = value
        if self._overlay:
            self._overlay.set_opacity(value)
        if self._opacity_label:
            self._opacity_label.setText(f"{value}%")

    # ══════════════════════════════════
    #  页面构建
    # ══════════════════════════════════

    def build_content(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        accent = self._color("accent.primary")
        warning = TokenManager.instance().get_qcolor("semantic.warning")
        text_tertiary = self._color("text.tertiary")

        # ── 标题 ──
        title = QLabel("护眼遮罩")
        title.setFont(QFont("Iceberg", self._font_size("lg_xl", 18)))
        title.setStyleSheet(f"color: {accent}; padding: 4px 0;")
        layout.addWidget(title)

        desc = QLabel(
            "在屏幕上覆盖一层黑色半透明遮罩，降低屏幕亮度，保护视力。\n"
            "遮罩完全穿透鼠标，不会影响正常操作。"
        )
        desc.setStyleSheet(
            f"color: {text_tertiary}; "
            f"font-size: {self._font_size('sm', 12)}px; "
            f"padding: 0 0 6px 0;"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ── 快捷键提示 ──
        hotkey_tip = QLabel("全局快捷键: Ctrl+J  切换遮罩开/关")
        hotkey_tip.setStyleSheet(
            f"color: {accent}; "
            f"font-size: {self._font_size('sm', 12)}px; "
            f"font-weight: bold; "
            f"background-color: rgba({warning.red()}, {warning.green()}, {warning.blue()}, 0.06); "
            f"border: 1px solid rgba({warning.red()}, {warning.green()}, {warning.blue()}, 0.15); "
            f"border-radius: 4px; "
            f"padding: 6px 12px;"
        )
        hotkey_tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hotkey_tip)

        # ══════════════════════════════════
        #  不透明度卡片
        # ══════════════════════════════════
        opacity_card = CyberCard(title="不透明度", clickable=False)
        opacity_layout = opacity_card.content_layout()
        opacity_layout.setContentsMargins(24, 28, 24, 20)
        opacity_layout.setSpacing(10)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(12)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(5, 80)
        self._opacity_slider.setValue(self._opacity_pct)
        self._opacity_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._opacity_slider.setTickInterval(10)
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)

        accent_secondary = self._color("accent.secondary")
        self._opacity_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                background: {self._color('components.progress.track_bg')};
                height: 6px;
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {accent};
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {accent_secondary};
            }}
            QSlider::sub-page:horizontal {{
                background: {accent};
                border-radius: 3px;
            }}
        """)
        slider_row.addWidget(self._opacity_slider, stretch=1)

        self._opacity_label = QLabel(f"{self._opacity_pct}%")
        self._opacity_label.setStyleSheet(
            f"color: {accent}; "
            f"font-size: {self._font_size('md', 15)}px; "
            f"font-weight: bold; "
            f"font-family: monospace;"
        )
        self._opacity_label.setFixedWidth(45)
        self._opacity_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        slider_row.addWidget(self._opacity_label)

        opacity_layout.addLayout(slider_row)

        tip = QLabel("5% = 几乎透明    25% = 适中护眼    50% = 明显遮罩    80% = 深色滤镜")
        tip.setStyleSheet(
            f"color: {text_tertiary}; "
            f"font-size: {self._font_size('micro', 10)}px;"
        )
        opacity_layout.addWidget(tip)

        layout.addWidget(opacity_card)

        # ══════════════════════════════════
        #  操作按钮
        # ══════════════════════════════════
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._toggle_btn = _ToggleButton(text="开启遮罩")
        self._toggle_btn.clicked.connect(self._on_hotkey_toggle)
        btn_row.addWidget(self._toggle_btn)

        layout.addLayout(btn_row)

        layout.addStretch()

        return container