"""
[L4] core.widgets.hotkey_capture_edit — HotkeyCaptureEdit 热键捕获输入框

归属层:    [L4] (core/widgets/)
允许依赖:  core.tokens.manager, PySide6
禁止依赖:  core.services/*, core.pages/*, 任何 IO/JSON/网络

职责:
  - 提供可点击/可按键捕获的热键输入框
  - 捕获模式:点击后 grabKeyboard(),记录修饰键和普通键的组合
  - 状态通知: capture_started / capture_stopped / captured 三个信号
  - 颜色全部从 TokenManager 取,支持主题切换

迁移记录: 2026-06-17 从 core/pages/toggles_page.py 内部类 _HotkeyCaptureEdit 迁出
违反规范: §6.5 "Page 禁止内嵌自定义控件,只能组装 Widget/Section"

本文件相关红线:
- ✗ 禁止 setStyleSheet(f-string) → 用自绘 + Token
- ✗ 禁止读写 JSON / 调 service / 任何 IO
- ✗ 禁止快捷键硬编码 → 这是 UI 组件,只显示当前值,不存配置
- ✗ 禁止硬编码颜色 → 全部 token.get_qcolor()
"""

# ── 标准库 ──
from __future__ import annotations

# ── PySide6 ──
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QKeyEvent, QPainter, QColor, QPen, QBrush, QPainterPath,
)

# ── 项目内 ──
from core.tokens.manager import TokenManager


class HotkeyCaptureEdit(QWidget):
    """热键捕获输入框：点击后按下组合键即可记录。

    使用流程:
      1. 父组件创建实例,设置 initial 值
      2. 监听 captured(str) 信号,获取新热键
      3. 监听 capture_started / capture_stopped 用于切换 UI 状态

    信号:
      captured(str):        用户按下组合键完成捕获,参数是新热键字符串(小写+号分隔)
      capture_started():    用户点击进入捕获模式
      capture_stopped():    退出捕获模式(focus 丢失或 Escape)

    状态机:
      idle --(mousePress)--> capturing --(keyPress)--> idle + emit captured
                            |
                            +--(focusOut)--> idle (放弃捕获)
                            +--(Esc)--> idle (取消捕获)

    行为细节:
      - 固定高度 32 px,最小宽度 140 px
      - 捕获模式下抓取键盘 grabKeyboard(),所有按键都进 keyPressEvent
      - 修饰键(Ctrl/Alt/Shift/Win)单独记录,直到有普通键按下才组合
      - 焦点策略 StrongFocus,鼠标光标 PointingHandCursor

    参数:
      initial: 初始热键字符串(格式: "ctrl+t",小写+号分隔)
      parent:  Qt 父对象
    """

    # ── 信号 ──
    captured = Signal(str)            # 完成捕获,参数是新热键
    capture_started = Signal()        # 进入捕获模式
    capture_stopped = Signal()        # 退出捕获模式

    # ── 静态:Qt 键码 → 小写字符串 的映射 ──
    # 暴露为类属性,便于外部扩展或测试
    _KEY_MAP: dict[int, str | None] = {
        # ── 字母 ──
        Qt.Key.Key_A: 'a', Qt.Key.Key_B: 'b', Qt.Key.Key_C: 'c', Qt.Key.Key_D: 'd',
        Qt.Key.Key_E: 'e', Qt.Key.Key_F: 'f', Qt.Key.Key_G: 'g', Qt.Key.Key_H: 'h',
        Qt.Key.Key_I: 'i', Qt.Key.Key_J: 'j', Qt.Key.Key_K: 'k', Qt.Key.Key_L: 'l',
        Qt.Key.Key_M: 'm', Qt.Key.Key_N: 'n', Qt.Key.Key_O: 'o', Qt.Key.Key_P: 'p',
        Qt.Key.Key_Q: 'q', Qt.Key.Key_R: 'r', Qt.Key.Key_S: 's', Qt.Key.Key_T: 't',
        Qt.Key.Key_U: 'u', Qt.Key.Key_V: 'v', Qt.Key.Key_W: 'w', Qt.Key.Key_X: 'x',
        Qt.Key.Key_Y: 'y', Qt.Key.Key_Z: 'z',
        # ── 数字 ──
        Qt.Key.Key_0: '0', Qt.Key.Key_1: '1', Qt.Key.Key_2: '2', Qt.Key.Key_3: '3',
        Qt.Key.Key_4: '4', Qt.Key.Key_5: '5', Qt.Key.Key_6: '6', Qt.Key.Key_7: '7',
        Qt.Key.Key_8: '8', Qt.Key.Key_9: '9',
        # ── 功能键 F1-F12 ──
        Qt.Key.Key_F1: 'f1', Qt.Key.Key_F2: 'f2', Qt.Key.Key_F3: 'f3', Qt.Key.Key_F4: 'f4',
        Qt.Key.Key_F5: 'f5', Qt.Key.Key_F6: 'f6', Qt.Key.Key_F7: 'f7', Qt.Key.Key_F8: 'f8',
        Qt.Key.Key_F9: 'f9', Qt.Key.Key_F10: 'f10', Qt.Key.Key_F11: 'f11', Qt.Key.Key_F12: 'f12',
        # ── 特殊键 ──
        Qt.Key.Key_Space: 'space',
        Qt.Key.Key_Tab:   'tab',
        Qt.Key.Key_Return: 'enter',
        Qt.Key.Key_Enter:  'enter',
        # ── 取消 / 删除 ──
        Qt.Key.Key_Escape:     None,  # 取消捕获
        Qt.Key.Key_Backspace:  None,  # 也视为取消
    }

    # ── 静态:修饰键 Qt 键码 → 字符串 ──
    _MOD_MAP: dict[int, str] = {
        Qt.Key.Key_Control: "ctrl",
        Qt.Key.Key_Alt:     "alt",
        Qt.Key.Key_Shift:   "shift",
        Qt.Key.Key_Meta:    "win",
    }

    def __init__(self, initial: str = "", parent=None) -> None:
        super().__init__(parent)
        # ── 状态 ──
        self._current: str = initial
        self._capturing: bool = False
        # 捕获期间按下的修饰键集合(防止按一下 Shift 就触发)
        self._pressed_modifiers: set[str] = set()
        # 普通键集合(理论上同一时刻只有一个,保留为集合方便以后扩展)
        self._pressed_keys: set[str] = set()

        # ── 外观尺寸 ──
        self.setFixedHeight(32)
        self.setMinimumWidth(140)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    # ── 绘制 ──

    def paintEvent(self, event) -> None:
        """绘制输入框。

        顺序(规范 §5.3): QPainter → 自绘背景/边框/文字 → (无 super,QWidget 默认无内容)

        颜色根据三态切换:
          - capturing → accent.primary(暗) + accent.secondary(亮边)
          - focus     → bg.raised + border.focus
          - idle      → bg.base + border.subtle
        """
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 圆角路径
        path = QPainterPath()
        radius = 6
        path.addRoundedRect(0, 0, self.width(), self.height(), radius, radius)

        # 选色(沉浸黑色模式时背景 RGB 覆写为沉浸底色)
        tm = TokenManager.instance()
        if self._capturing:
            bg = self._resolve_immersive_bg(
                tm.get_qcolor("accent.primary").darker(300)
            )
            border = tm.get_qcolor("accent.secondary")
        elif self.hasFocus():
            bg = self._resolve_immersive_bg(tm.get_qcolor("bg.raised"))
            border = tm.get_qcolor("border.focus")
        else:
            bg = self._resolve_immersive_bg(tm.get_qcolor("bg.base"))
            border = tm.get_qcolor("border.subtle")

        # 填充 + 边框
        p.fillPath(path, QBrush(bg))
        p.setPen(QPen(border, 1))
        p.drawPath(path)

        # 文字
        if self._capturing:
            text = "按下组合键..."
            color = tm.get_qcolor("accent.secondary")
        else:
            text = self._format_display(self._current)
            color = tm.get_qcolor("text.primary")

        p.setPen(color)
        font = self.font()
        font.setPointSize(11)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

    # ── 内部辅助 ──

    @staticmethod
    def _resolve_immersive_bg(bg: QColor) -> QColor:
        """沉浸黑色模式时覆写背景 RGB 并折减 alpha。

        本控件因键盘捕获逻辑(grabKeyboard + 按键拦截)继承 QWidget,
        未挂 CyberWidgetMixin;计算实现收敛在 core/widgets/immersive.py
        (唯一实现,内部读 Mixin 类级状态),沿用其原 alpha 路径。
        """
        from core.widgets import immersive

        return immersive.resolve_current_alpha(bg)

    @staticmethod
    def _format_display(key_str: str) -> str:
        """格式化显示:首字母大写 + 空格分隔(ctrl+t → Ctrl + T)。"""
        if not key_str:
            return "未设置"
        return " + ".join(k.upper() for k in key_str.split("+"))

    @staticmethod
    def _map_key(qt_key: int) -> str | None:
        """Qt 键码 → 小写字符串。

        规则:
          - 已知键查 _KEY_MAP
          - 未知可打印字符(32 < key < 127)走 chr(key).lower()
          - 其它返回 None(忽略)
        """
        if qt_key in HotkeyCaptureEdit._KEY_MAP:
            return HotkeyCaptureEdit._KEY_MAP[qt_key]
        if 32 < qt_key < 127:
            return chr(qt_key).lower()
        return None

    # ── 鼠标 / 键盘事件 ──

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_capture()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # 非捕获模式:交给父类(QWidget 默认不处理,只拦截即可)
        if not self._capturing:
            super().keyPressEvent(event)
            return

        # Escape / Backspace 取消捕获
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace):
            self._stop_capture()
            return

        # 修饰键:记录到 _pressed_modifiers,继续等待
        if event.key() in self._MOD_MAP:
            self._pressed_modifiers.add(self._MOD_MAP[event.key()])
            return

        # 普通键:组合完成
        key_name = self._map_key(event.key())
        if not key_name:
            return

        # 排序保证稳定性(ctrl+shift+t 和 shift+ctrl+t 表现一致)
        parts = sorted(self._pressed_modifiers) + [key_name]
        new_hotkey = "+".join(parts)
        self._current = new_hotkey
        self.captured.emit(new_hotkey)
        self._stop_capture()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        # 释放修饰键时从集合移除(避免长按 Ctrl 影响下一次捕获)
        if event.key() in self._MOD_MAP:
            self._pressed_modifiers.discard(self._MOD_MAP[event.key()])

    def focusOutEvent(self, event) -> None:
        # 捕获模式下丢失焦点:自动放弃
        if self._capturing:
            self._stop_capture()
        super().focusOutEvent(event)

    # ── 状态切换 ──

    def _start_capture(self) -> None:
        """进入捕获模式。

        副作用:
          - 抓取键盘 grabKeyboard()(即使本 widget 失焦也能收到 keyPress)
          - 清空修饰键/普通键集合
          - emit capture_started
        """
        self._capturing = True
        self._pressed_modifiers.clear()
        self._pressed_keys.clear()
        self.setFocus()
        self.update()
        self.grabKeyboard()
        self.capture_started.emit()

    def _stop_capture(self) -> None:
        """退出捕获模式。

        副作用:
          - 释放键盘 grabKeyboard()
          - emit capture_stopped
        """
        self._capturing = False
        self.releaseKeyboard()
        self.update()
        self.capture_stopped.emit()

    # ── 公开 API ──

    @property
    def value(self) -> str:
        """当前热键字符串(读)。"""
        return self._current

    @value.setter
    def value(self, v: str) -> None:
        """设置当前热键(写),触发重绘。"""
        self._current = v
        self.update()
