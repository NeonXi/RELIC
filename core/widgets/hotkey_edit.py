"""
[L4] HotkeyEdit — 赛博风格快捷键捕获控件

继承: CyberWidgetMixin + QLineEdit
依赖: core.tokens.manager
职责: 点击进入捕获模式,记录键盘组合；文字显示/光标由 QLineEdit 接管
信号: captured(str), capture_started(), capture_stopped()

点击后进入捕获模式，按下组合键自动记录。
使用 grabKeyboard() 拦截全局按键，避免与热键冲突。

用法::

    edit = HotkeyEdit(initial="ctrl+shift+a")
    edit.captured.connect(lambda val: print(f"捕获到: {val}"))

## AI 硬约束 — 修改本文件前必读
归属层:    [L4] (core/widgets/)
允许依赖:  core.widgets.base.CyberWidgetMixin, core.tokens.manager, PySide6
禁止依赖:  core.services/*, core.pages/*, core.state/*, data/*
           (本控件拦截全局按键,绝不调业务/数据)
必读规范:  .trae/rules/开发规范.md §6.4

本文件相关红线:
- ✗ 禁止 __init__ 调 super().__init__() → 必须 QLineEdit.__init__(self, parent)
- ✗ 禁止 keyPressEvent 漏 super() → 非捕获态按键处理失效
- ✗ 禁止 paintEvent 漏 super() → 文字不显示
- ✗ 禁止硬编码颜色 / 尺寸 → 必须 self.token() / self.space()
- ✗ 禁止捕获模式未结束时丢失 releaseKeyboard() → 会卡住全局键盘
- ✗ 禁止调 Service / 发网络请求 / 读写 JSON

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.4。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor, QKeyEvent, QPalette, QPainter, QPen, QBrush, QPainterPath,
)
from PySide6.QtWidgets import QLineEdit

from core.widgets.base import CyberWidgetMixin


# ── 修饰键映射 ──

_MODIFIER_ORDER = ["ctrl", "alt", "shift", "win"]

_MODIFIER_KEYS: dict[int, str] = {
    Qt.Key.Key_Control: "ctrl",
    Qt.Key.Key_Alt: "alt",
    Qt.Key.Key_Shift: "shift",
    Qt.Key.Key_Meta: "win",
}

_KEY_NAME_MAP: dict[int, str | None] = {
    Qt.Key.Key_F1: "f1",  Qt.Key.Key_F2: "f2",   Qt.Key.Key_F3: "f3",
    Qt.Key.Key_F4: "f4",  Qt.Key.Key_F5: "f5",   Qt.Key.Key_F6: "f6",
    Qt.Key.Key_F7: "f7",  Qt.Key.Key_F8: "f8",   Qt.Key.Key_F9: "f9",
    Qt.Key.Key_F10: "f10", Qt.Key.Key_F11: "f11", Qt.Key.Key_F12: "f12",
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Up: "up",    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right",
    Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Home: "home",  Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup", Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Escape: None,   # 取消捕获
}


def _map_key(qt_key: int) -> str | None:
    """Qt 键码 → 小写字符串，None 表示忽略/取消。"""
    if qt_key in _MODIFIER_KEYS:
        return None  # 修饰键单独处理
    name = _KEY_NAME_MAP.get(qt_key)
    if name is not None:
        return name
    if Qt.Key.Key_A <= qt_key <= Qt.Key.Key_Z:
        return chr(qt_key).lower()
    if Qt.Key.Key_0 <= qt_key <= Qt.Key.Key_9:
        return chr(qt_key)
    return None


class HotkeyEdit(CyberWidgetMixin, QLineEdit):
    """赛博风格快捷键捕获输入框。

    文字渲染、对齐等由 QLineEdit 原生提供；本控件只自绘外框/背景，
    并通过 QPalette 设置文字颜色。

    Signals:
        captured(str): 捕获完成，参数为组合键字符串（如 "ctrl+shift+a"）
        capture_started(): 进入捕获模式
        capture_stopped(): 退出捕获模式
    """

    captured = Signal(str)
    capture_started = Signal()
    capture_stopped = Signal()

    def __init__(self, initial: str = "", parent=None):
        QLineEdit.__init__(self, parent)

        self._value = initial
        self._capturing = False
        self._pressed_modifiers: set[str] = set()

        # 尺寸与交互（32 为 4 的倍数）
        self.setFixedHeight(32)
        self.setMinimumWidth(120)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # QLineEdit 行为：只读（捕获走 keyPressEvent）、去原生边框（自绘）、居中
        self.setReadOnly(True)
        self.setFrame(False)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 字号从 space token 取（font.xs = 11）
        f = self.font()
        f.setPointSize(self.space("font.xs", 11))
        self.setFont(f)

        self._refresh_visuals()

    # ── 公开 API ──

    @property
    def value(self) -> str:
        """当前记录的组合键值。"""
        return self._value

    @value.setter
    def value(self, v: str):
        self._value = v
        self._refresh_visuals()

    def hotkey(self) -> str:
        """兼容旧接口别名。"""
        return self._value

    def set_hotkey(self, v: str):
        """兼容旧接口别名。"""
        self._value = v
        self._refresh_visuals()

    # ── 显示状态 ──

    def _display_text(self) -> str:
        """根据当前状态生成 QLineEdit 显示文本。"""
        if self._capturing:
            if self._pressed_modifiers:
                mods = " + ".join(m.upper() for m in sorted(self._pressed_modifiers))
                return f"按下组合键... ({mods})"
            return "按下组合键..."
        if self._value:
            return " + ".join(k.upper() for k in self._value.split("+"))
        return "点击设置"

    def _state_colors(self) -> tuple[QColor, QColor, QColor]:
        """返回当前状态的 (背景色, 边框色, 文字色)。

        token_color 内置降级保护，任何 token 缺失都不会导致绘制中断。
        """
        if self._capturing:
            return (
                self._cyber_immersive_resolve_bg("components.input.bg", 1.0),
                self.token_color("alias.accent.secondary"),   # 捕获态青色高亮
                self.token_color("alias.accent.secondary"),
            )
        if self.hasFocus():
            return (
                self._cyber_immersive_resolve_bg("components.input.bg", 1.0),
                self.token_color("components.input.border_focus"),
                self.token_color("alias.text.primary"),
            )
        # 静态：无值时文字用禁用色
        text_c = (
            self.token_color("alias.text.primary")
            if self._value
            else self.token_color("alias.text.disabled")
        )
        return (
            self._cyber_immersive_resolve_bg("alias.bg.base", 1.0),
            self.token_color("alias.border.subtle"),
            text_c,
        )

    def _refresh_visuals(self):
        """同步显示文本与文字颜色（值变化 / 捕获状态变化时调用）。"""
        self.setText(self._display_text())
        _, _, text_color = self._state_colors()
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Text, text_color)
        self.setPalette(pal)
        self.update()

    # ── 绘制（顺序固定：QPainter → 自绘背景 → super()）──

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 圆角背景
        path = QPainterPath()
        r = self.space("corner.sm", 6)
        path.addRoundedRect(0, 0, self.width(), self.height(), float(r), float(r))

        bg, border, _ = self._state_colors()
        painter.fillPath(path, QBrush(bg))
        painter.setPen(QPen(border, self.space("border.thin", 1)))
        painter.drawPath(path)
        painter.end()

        # 文字由 QLineEdit 原生绘制
        super().paintEvent(event)

    # ── 鼠标事件 ──

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._capturing:
            self._start_capture()
            event.accept()
            return
        super().mousePressEvent(event)

    # ── 捕获生命周期 ──

    def _start_capture(self):
        """进入捕获模式。"""
        self._capturing = True
        self._pressed_modifiers.clear()
        self.setFocus()
        self.grabKeyboard()
        self._refresh_visuals()
        self.capture_started.emit()

    def _stop_capture(self):
        """退出捕获模式。"""
        self._capturing = False
        self.releaseKeyboard()
        self._refresh_visuals()
        self.capture_stopped.emit()

    def _commit(self, combo: str):
        """提交捕获结果。"""
        self._value = combo
        self.captured.emit(combo)
        self._stop_capture()

    # ── 键盘事件 ──

    def keyPressEvent(self, event: QKeyEvent):
        # 非捕获态：交给 QLineEdit 默认处理（只读态基本无操作）
        if not self._capturing:
            super().keyPressEvent(event)
            return

        key = event.key()

        # Esc → 取消
        if key == Qt.Key.Key_Escape:
            self._stop_capture()
            event.accept()
            return

        # 修饰键 → 累积并实时显示
        if key in _MODIFIER_KEYS:
            self._pressed_modifiers.add(_MODIFIER_KEYS[key])
            self._refresh_visuals()
            event.accept()
            return

        # 普通键 → 组合完成
        name = _map_key(key)
        if name is None:
            event.accept()  # 忽略不认识的键
            return

        parts = sorted(self._pressed_modifiers) + [name]
        self._commit("+".join(parts))
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent):
        if not self._capturing:
            super().keyReleaseEvent(event)
            return
        key = event.key()
        if key in _MODIFIER_KEYS:
            self._pressed_modifiers.discard(_MODIFIER_KEYS[key])
            self._refresh_visuals()
            event.accept()
            return
        event.ignore()

    # ── 焦点事件 ──

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._refresh_visuals()

    def focusOutEvent(self, event):
        if self._capturing:
            self._stop_capture()
        super().focusOutEvent(event)
        self._refresh_visuals()
