"""
HotkeyEdit — 赛博风格快捷键捕获控件。

点击后进入捕获模式，按下组合键自动记录。
使用 grabKeyboard() 拦截全局按键，避免与热键冲突。

用法::

    edit = HotkeyEdit(initial="ctrl+shift+a")
    edit.captured.connect(lambda val: print(f"捕获到: {val}"))
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush,
    QPainterPath, QKeyEvent, QFont,
)

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


class HotkeyEdit(CyberWidgetMixin, QWidget):
    """赛博风格快捷键捕获输入框。

    Signals:
        captured(str): 捕获完成，参数为组合键字符串（如 "ctrl+shift+a"）
        capture_started(): 进入捕获模式
        capture_stopped(): 退出捕获模式
    """

    captured = Signal(str)
    capture_started = Signal()
    capture_stopped = Signal()

    def __init__(self, initial: str = "", parent=None):
        QWidget.__init__(self, parent)

        self._value = initial
        self._capturing = False
        self._pressed_modifiers: set[str] = set()

        # 尺寸与交互
        self.setFixedHeight(32)
        self.setMinimumWidth(120)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ── 公开 API ──

    @property
    def value(self) -> str:
        """当前记录的组合键值。"""
        return self._value

    @value.setter
    def value(self, v: str):
        self._value = v
        self.update()

    def hotkey(self) -> str:
        """兼容旧接口别名。"""
        return self._value

    def set_hotkey(self, v: str):
        """兼容旧接口别名。"""
        self._value = v
        self.update()

    # ── 绘制 ──

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景（圆角矩形）
        path = QPainterPath()
        r = 6
        path.addRoundedRect(0, 0, self.width(), self.height(), r, r)

        if self._capturing:
            bg = self.token_color("components.input.focus.bg")
            border = self.token_color("alias.accent.secondary")  # 捕获态高亮
        elif self.hasFocus():
            bg = self.token_color("components.input.hover.bg")
            border = self.token_color("components.input.focus.border")
        else:
            bg = self.token_color("alias.bg.base")
            border = self.token_color("alias.border.subtle")

        painter.fillPath(path, QBrush(bg))
        painter.setPen(QPen(border, 1))
        painter.drawPath(path)

        # 文字
        if self._capturing:
            text = "按下组合键..."
            color = self.token_color("alias.accent.secondary")
        elif self._value:
            text = " + ".join(k.upper() for k in self._value.split("+"))
            color = self.token_color("alias.text.primary")
        else:
            text = "点击设置"
            color = self.token_color("alias.text.disabled")

        painter.setPen(color)
        font = QFont()
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )

    # ── 鼠标事件 ──

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._capturing:
            self._start_capture()

    # ── 捕获生命周期 ──

    def _start_capture(self):
        """进入捕获模式。"""
        self._capturing = True
        self._pressed_modifiers.clear()
        self.setFocus()
        self.update()
        self.grabKeyboard()
        self.capture_started.emit()

    def _stop_capture(self):
        """退出捕获模式。"""
        self._capturing = False
        self.releaseKeyboard()
        self.update()
        self.capture_stopped.emit()

    def _commit(self, combo: str):
        """提交捕获结果。"""
        self._value = combo
        self.captured.emit(combo)
        self._stop_capture()

    # ── 键盘事件 ──

    def keyPressEvent(self, event: QKeyEvent):
        if not self._capturing:
            event.ignore()
            return

        key = event.key()

        # Esc → 取消
        if key == Qt.Key.Key_Escape:
            self._stop_capture()
            event.accept()
            return

        # 修饰键 → 累积显示
        if key in _MODIFIER_KEYS:
            self._pressed_modifiers.add(_MODIFIER_KEYS[key])
            self.update()
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
            event.ignore()
            return
        key = event.key()
        if key in _MODIFIER_KEYS:
            self._pressed_modifiers.discard(_MODIFIER_KEYS[key])
            event.accept()
            return
        event.ignore()

    # ── 焦点事件 ──

    def focusOutEvent(self, event):
        if self._capturing:
            self._stop_capture()
        super().focusOutEvent(event)
