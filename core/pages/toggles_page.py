"""
[L-Page] TogglesPage — 功能开关 + 快捷键配置页面。

依赖: PySide6 + data/feature_toggles.json + data/hotkeys.json + data/triggers.json
用途: 管理应用功能模块的开启/关闭状态 + 全局快捷键绑定 + 辅助触发器开关。

功能:
  - 功能开关（核心功能 / 界面行为）
  - 辅助触发器启用/禁用（同步自 triggers.json）
  - 快捷键绑定（框选截图 / 全屏截图）
  - 保存修改到 JSON 文件
  - 支持恢复默认值

数据源:
  - data/feature_toggles.json （功能开关）
  - data/triggers.json       （辅助触发器）
  - data/hotkeys.json        （快捷键）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QSizePolicy, QFrame, QMessageBox,
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont, QKeyEvent

from core.pages.base_page import PageBase
from core.widgets.panel import CyberPanel
from core.widgets.button import CyberButton
from core.widgets.card import CyberCard
from core.widgets.toggle_switch import CyberToggleSwitch
from core.tokens.manager import TokenManager
from core.trigger_config import (
    load_triggers, save_triggers,
    format_trigger_summary,
)


# ── 功能开关定义 ──
# 格式: (token_key, 默认值, 所属分组)
_TOGGLE_DEFS = [
    # ── 核心功能 ──
    ("check_status", True, "core"),
    ("query_parts",  True, "core"),
    ("translate",    False, "core"),
]

_GROUP_NAMES = {
    "core": "toggles.group_core",
    "ui":   "toggles.group_ui",
}

_DEFAULT_VALUES = {k: v for k, v, _ in _TOGGLE_DEFS}

# ── 快捷键定义 ──
# 格式: (action_key, token_label, 默认值)
_HOTKEY_DEFS = [
    ("select",     "hotkey.label_select",     "ctrl+g"),
    ("fullscreen", "hotkey.label_fullscreen", "ctrl+h"),
    ("eye_mask",   "hotkey.label_eye_mask",   "ctrl+j"),
]


class _HotkeyCaptureEdit(QWidget):
    """热键捕获输入框：点击后按下组合键即可记录。"""

    captured = Signal(str)  # (key_str)
    capture_started = Signal()   # 进入捕获模式
    capture_stopped = Signal()  # 退出捕获模式

    def __init__(self, initial: str = "", parent=None):
        super().__init__(parent)
        self._current = initial
        self._capturing = False
        self._pressed_modifiers: set[str] = set()
        self._pressed_keys: set[str] = set()

        self.setFixedHeight(32)
        self.setMinimumWidth(140)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景
        path = QPainterPath()
        r = 6
        path.addRoundedRect(0, 0, self.width(), self.height(), r, r)

        if self._capturing:
            bg = TokenManager.instance().get_qcolor("accent.primary").darker(300)
            border = TokenManager.instance().get_qcolor("accent.secondary")
        elif self.hasFocus():
            bg = TokenManager.instance().get_qcolor("bg.raised")
            border = TokenManager.instance().get_qcolor("border.focus")
        else:
            bg = TokenManager.instance().get_qcolor("bg.base")
            border = TokenManager.instance().get_qcolor("border.subtle")

        p.fillPath(path, QBrush(bg))
        p.setPen(QPen(border, 1))
        p.drawPath(path)

        # 文字
        if self._capturing:
            text = "按下组合键..."
            color = TokenManager.instance().get_qcolor("accent.secondary")
        else:
            text = self._format_display(self._current)
            color = TokenManager.instance().get_qcolor("text.primary")

        p.setPen(color)
        f = self.font()
        f.setPointSize(11)
        p.setFont(f)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

    def _format_display(self, key_str: str) -> str:
        """格式化显示：首字母大写 + 空格分隔。"""
        if not key_str:
            return "未设置"
        return " + ".join(k.upper() for k in key_str.split("+"))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_capture()

    def _start_capture(self):
        """开始捕获模式。"""
        self._capturing = True
        self._pressed_modifiers.clear()
        self._pressed_keys.clear()
        self.setFocus()
        self.update()
        self.grabKeyboard()
        self.capture_started.emit()

    def _stop_capture(self):
        """结束捕获模式。"""
        self._capturing = False
        self.releaseKeyboard()
        self.update()
        self.capture_stopped.emit()

    def keyPressEvent(self, event: QKeyEvent):
        if not self._capturing:
            super().keyPressEvent(event)
            return

        # 忽略纯修饰键按下
        mod_map = {
            Qt.Key.Key_Control: "ctrl",
            Qt.Key.Key_Alt:     "alt",
            Qt.Key.Key_Shift:   "shift",
            Qt.Key.Key_Meta:    "win",
        }

        if event.key() in mod_map:
            self._pressed_modifiers.add(mod_map[event.key()])
            return

        # 普通键 → 组合完成
        key_name = self._map_key(event.key())
        if not key_name:
            return

        parts = sorted(self._pressed_modifiers) + [key_name]
        new_hotkey = "+".join(parts)
        self._current = new_hotkey
        self.captured.emit(new_hotkey)
        self._stop_capture()

    def keyReleaseEvent(self, event: QKeyEvent):
        mod_map = {
            Qt.Key.Key_Control: "ctrl",
            Qt.Key.Key_Alt:     "alt",
            Qt.Key.Key_Shift:   "shift",
            Qt.Key.Key_Meta:    "win",
        }
        if event.key() in mod_map:
            self._pressed_modifiers.discard(mod_map[event.key()])

    def focusOutEvent(self, event):
        if self._capturing:
            self._stop_capture()
        super().focusOutEvent(event)

    @staticmethod
    def _map_key(qt_key: int) -> str | None:
        """Qt 键码 → 小写字符串。"""
        _KEY_MAP = {
            Qt.Key.Key_A: 'a', Qt.Key.Key_B: 'b', Qt.Key.Key_C: 'c', Qt.Key.Key_D: 'd',
            Qt.Key.Key_E: 'e', Qt.Key.Key_F: 'f', Qt.Key.Key_G: 'g', Qt.Key.Key_H: 'h',
            Qt.Key.Key_I: 'i', Qt.Key.Key_J: 'j', Qt.Key.Key_K: 'k', Qt.Key.Key_L: 'l',
            Qt.Key.Key_M: 'm', Qt.Key.Key_N: 'n', Qt.Key.Key_O: 'o', Qt.Key.Key_P: 'p',
            Qt.Key.Key_Q: 'q', Qt.Key.Key_R: 'r', Qt.Key.Key_S: 's', Qt.Key.Key_T: 't',
            Qt.Key.Key_U: 'u', Qt.Key.Key_V: 'v', Qt.Key.Key_W: 'w', Qt.Key.Key_X: 'x',
            Qt.Key.Key_Y: 'y', Qt.Key.Key_Z: 'z',
            Qt.Key.Key_0: '0', Qt.Key.Key_1: '1', Qt.Key.Key_2: '2', Qt.Key.Key_3: '3',
            Qt.Key.Key_4: '4', Qt.Key.Key_5: '5', Qt.Key.Key_6: '6', Qt.Key.Key_7: '7',
            Qt.Key.Key_8: '8', Qt.Key.Key_9: '9',
            Qt.Key.Key_F1: 'f1', Qt.Key.Key_F2: 'f2', Qt.Key.Key_F3: 'f3', Qt.Key.Key_F4: 'f4',
            Qt.Key.Key_F5: 'f5', Qt.Key.Key_F6: 'f6', Qt.Key.Key_F7: 'f7', Qt.Key.Key_F8: 'f8',
            Qt.Key.Key_F9: 'f9', Qt.Key.Key_F10: 'f10', Qt.Key.Key_F11: 'f11', Qt.Key.Key_F12: 'f12',
            Qt.Key.Key_Space: 'space',
            Qt.Key.Key_Tab: 'tab',
            Qt.Key.Key_Return: 'enter',
            Qt.Key.Key_Enter: 'enter',
            Qt.Key.Key_Escape: None,  # 取消捕获
            Qt.Key.Key_Backspace: None,
        }
        return _KEY_MAP.get(qt_key, chr(qt_key).lower() if 32 < qt_key < 127 else None)

    @property
    def value(self) -> str:
        return self._current

    @value.setter
    def value(self, v: str):
        self._current = v
        self.update()


class TogglesPage(PageBase):
    """功能开关 + 快捷键配置页面。"""

    page_id = "toggles"
    page_title = ""
    page_icon = "nav_toggles"

    def __init__(self):
        self._toggles_path = Path(__file__).resolve().parent.parent.parent / 'data' / 'feature_toggles.json'
        self._toggles_data: dict[str, bool] = {}
        self._checkboxes: dict[str, QCheckBox] = {}

        # 快捷键数据
        self._hotkeys_data: dict[str, str] = {}
        self._hotkey_edits: dict[str, _HotkeyCaptureEdit] = {}

        # 辅助触发器数据
        self._triggers_data: list[dict] = []
        self._trigger_checkboxes: list[tuple[CyberToggleSwitch, int]] = []  # (toggle_switch, index_in_list)
        self._triggers_layout: Optional[QVBoxLayout] = None  # 触发器卡片的内容布局引用

        # ★ 必须在 PageBase.__init__ 之前加载数据，
        #   因为 PageBase 内部会调用 build_content() 构建UI
        self._load_toggles()
        self._load_hotkeys()
        self._load_triggers()

        PageBase.__init__(self)

        self.page_title = self._copy("nav.toggles", "功能开关")

    # ════════════════════════════════════
    #  数据加载/保存
    # ════════════════════════════════════

    def _load_toggles(self) -> None:
        """从 JSON 文件加载功能开关。"""
        try:
            if self._toggles_path.exists():
                raw = json.loads(self._toggles_path.read_text(encoding="utf-8"))
                self._toggles_data = {
                    k: bool(v) for k, v in raw.items()
                    if isinstance(v, (bool, int))
                }
            else:
                self._toggles_data = dict(_DEFAULT_VALUES)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[TogglesPage] 加载失败，使用默认值: {e}", flush=True)
            self._toggles_data = dict(_DEFAULT_VALUES)

    def _save_toggles(self) -> bool:
        """保存当前设置到 JSON 文件。"""
        try:
            current = {}
            for key, cb in self._checkboxes.items():
                current[key] = cb.isChecked()

            # 同步内存中的开关状态（供 update_feature_toggles 使用）
            self._toggles_data = current

            self._toggles_path.write_text(
                json.dumps(current, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except OSError as e:
            print(f"[TogglesPage] 保存失败: {e}", flush=True)
            return False

    def _load_hotkeys(self) -> None:
        """加载快捷键配置。"""
        try:
            from core.hotkey_config import load_hotkeys, DEFAULT_HOTKEYS
            raw = load_hotkeys()
            # 只取我们关心的 action（排除 query_price 等）
            self._hotkeys_data = {
                k: raw.get(k, DEFAULT_HOTKEYS.get(k, ""))
                for k, _, _ in _HOTKEY_DEFS
            }
        except Exception as e:
            print(f"[TogglesPage] 加载热键失败: {e}", flush=True)
            self._hotkeys_data = {k: d for k, _, d in _HOTKEY_DEFS}

    def _save_hotkeys(self) -> bool:
        """保存快捷键配置。"""
        try:
            from core.hotkey_config import load_hotkeys, save_hotkeys, DEFAULT_HOTKEYS

            # 合并：保留用户其他自定义项，更新当前编辑的
            all_hks = load_hotkeys()
            for key, edit in self._hotkey_edits.items():
                all_hks[key] = edit.value

            return save_hotkeys(all_hks)
        except Exception as e:
            print(f"[TogglesPage] 保存热键失败: {e}", flush=True)
            return False

    def _load_triggers(self) -> None:
        """从 triggers.json 加载辅助触发器列表。"""
        try:
            self._triggers_data = load_triggers()
        except Exception as e:
            print(f"[TogglesPage] 加载触发器失败: {e}", flush=True)
            self._triggers_data = []

    def _save_triggers(self) -> bool:
        """将触发器启用/禁用状态保存回 triggers.json。

        只更新 enabled 字段，不修改其他配置。
        """
        try:
            print(f"[TogglesPage] _save_triggers: 开关数={len(self._trigger_checkboxes)}", flush=True)
            for sw, idx in self._trigger_checkboxes:
                if idx < len(self._triggers_data):
                    self._triggers_data[idx]["enabled"] = sw.isChecked()
                    print(f"  [{idx}] {self._triggers_data[idx].get('name')}: enabled={sw.isChecked()}", flush=True)
            ok = save_triggers(self._triggers_data)
            print(f"[TogglesPage] _save_triggers: 保存{'成功' if ok else '失败'}", flush=True)
            return ok
        except Exception as e:
            print(f"[TogglesPage] 保存触发器失败: {e}", flush=True)
            return False

    # ════════════════════════════════════
    #  即时保存 + 通知引擎
    # ════════════════════════════════════

    def _apply_toggles(self) -> None:
        """保存功能开关并通知管线服务。"""
        if not self._save_toggles():
            return
        try:
            shell = self._get_shell()
            if shell and shell.pipeline:
                shell.pipeline.update_feature_toggles(self._toggles_data)
        except Exception:
            pass

    def _apply_hotkeys(self) -> None:
        """保存快捷键并通知管线重注册。"""
        if not self._save_hotkeys():
            return
        try:
            shell = self._get_shell()
            if shell and shell.pipeline:
                shell.pipeline.reregister_hotkeys()
        except Exception:
            pass

    def _apply_triggers(self) -> None:
        """保存触发器状态并通知引擎热重载。"""
        if not self._save_triggers():
            return
        try:
            shell = self._get_shell()
            if shell and hasattr(shell, 'trigger_manager') and shell.trigger_manager:
                shell.trigger_manager.reload()
                print("[TogglesPage] 触发器引擎已重载", flush=True)
        except Exception:
            pass

    # ════════════════════════════════════
    #  UI 构建
    # ════════════════════════════════════

    def build_content(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(
            self._spacing("lg", 20), self._spacing("sm", 8),
            self._spacing("lg", 20), self._spacing("lg", 20)
        )
        layout.setSpacing(self._spacing("xs", 4))

        # ── 标题 ──
        title = QLabel(self._copy("toggles.title", "功能控制面板"))
        title.setFont(QFont("Iceberg", self._font_size("lg_xl", 18)))
        accent = self._color("accent.primary")
        title.setStyleSheet(f"color: {accent}; padding: 4px 0;")
        layout.addWidget(title)

        desc = QLabel(
            self._copy("toggles.desc",
                       "开启或关闭各项功能模块，修改快捷键后需重启生效")
        )
        desc.setStyleSheet(
            f"color: {self._color('text.tertiary')}; "
            f"font-size: {self._font_size('sm', 12)}px; padding: 0 0 12px 0;"
        )
        layout.addWidget(desc)

        # ── 按钮栏 ──
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_reset = CyberButton(
            text=self._copy("toggles.btn_reset", "恢复默认"), variant="ghost"
        )
        btn_reset.setFixedWidth(90)
        btn_reset.clicked.connect(self._on_reset_defaults)
        btn_row.addWidget(btn_reset)

        layout.addLayout(btn_row)

        # ════════════════════
        #  第一区：功能开关
        # ════════════════════
        groups: dict[str, list[tuple]] = {}
        for key, default_val, group_id in _TOGGLE_DEFS:
            if group_id not in groups:
                groups[group_id] = []
            groups[group_id].append((key, default_val))

        for group_id, toggle_list in groups.items():
            group_label_key = _GROUP_NAMES.get(group_id, group_id)
            group_name = self._copy(group_label_key, group_id)

            card = CyberCard(title=group_name)
            card_layout = card.content_layout()
            card_layout.setContentsMargins(
                self._spacing("md", 16),
                self._spacing("lg_xl", 28),
                self._spacing("md", 16),
                self._spacing("md", 16)
            )
            card_layout.setSpacing(self._spacing("sm", 10))

            for key, _default_val in toggle_list:
                current_val = self._toggles_data.get(key, _default_val)
                row = self._build_toggle_row(key, current_val)
                card_layout.addLayout(row)

            layout.addWidget(card)

        # ════════════════════
        #  第二区：辅助触发器开关
        # ════════════════════
        self._build_triggers_card(layout)

        # ════════════════════
        #  第三区：快捷键绑定
        # ════════════════════
        hk_card = CyberCard(title=self._copy("hotkeys.card_binding", "快捷键绑定"))
        hk_layout = hk_card.content_layout()
        hk_layout.setContentsMargins(
            self._spacing("md", 16),
            self._spacing("lg_xl", 28),
            self._spacing("md", 16),
            self._spacing("md", 16)
        )
        hk_layout.setSpacing(self._spacing("sm", 10))

        for action_key, label_token, default_val in _HOTKEY_DEFS:
            row = self._build_hotkey_row(action_key, label_token, default_val)
            hk_layout.addLayout(row)

        layout.addWidget(hk_card)

        # ── 提示 ──
        tip_frame = QFrame()
        _tip_accent = TokenManager.instance().get_qcolor("accent.primary")
        tip_frame.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({_tip_accent.red()}, {_tip_accent.green()}, {_tip_accent.blue()}, 0.06);
                border: 1px solid rgba({_tip_accent.red()}, {_tip_accent.green()}, {_tip_accent.blue()}, 0.2);
                border-radius: 4px;
                padding: {self._spacing('spacing.sm', 8)}px;
            }}
        """)
        tip_layout = QHBoxLayout(tip_frame)
        tip_layout.setContentsMargins(12, 8, 12, 8)

        tip_icon = QLabel("!")
        tip_icon.setStyleSheet(
            f"color: {self._color('accent.primary')}; "
            f"font-size: {self._font_size('md', 14)}px; font-weight: bold;"
        )
        tip_icon.setFixedWidth(20)
        tip_layout.addWidget(tip_icon)

        tip_text = QLabel(
            self._copy("hotkeys.tip",
                       "提示：修改快捷键后请确认不与其他软件冲突，部分修改需要重启应用生效。"
                       "支持的修饰键：Ctrl / Alt / Shift / Win")
        )
        tip_text.setStyleSheet(
            f"color: {self._color('alias.text.tertiary')}; "
            f"font-size: {self._font_size('xs', 11)}px;"
        )
        tip_text.setWordWrap(True)
        tip_layout.addWidget(tip_text, stretch=1)

        layout.addWidget(tip_frame)
        layout.addStretch()

        return container

    def _build_toggle_row(self, key: str, current_val: bool) -> QHBoxLayout:
        """构建一行功能开关。"""
        row = QHBoxLayout()
        row.setSpacing(8)

        label_text = self._copy(f"toggles.toggle_{key}", key)
        cb = QCheckBox(label_text)
        cb.setChecked(bool(current_val))
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.setStyleSheet(f"""
            QCheckBox {{
                color: {self._color('text.primary')};
                font-size: {self._font_size('sm_md', 13)}px;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 1.5px solid {self._color('border.emphasis')};
                border-radius: 4px;
                background: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {self._color('accent.secondary')};
                border-color: {self._color('accent.secondary')};
            }}
            QCheckBox::indicator:hover {{
                border-color: {self._color('accent.secondary')};
            }}
        """)

        # ── 状态点（先创建，再在信号中引用）──
        status_dot = QLabel("●" if current_val else "○")
        status_dot.setStyleSheet(
            f"color: {self._color('brand.green') if current_val else self._color('neutral.dark')}; "
            f"font-size: {self._font_size('micro', 10)}px;"
        )
        status_dot.setFixedWidth(20)

        cb.stateChanged.connect(lambda state, dot=status_dot, k=key: (
            dot.setText("●" if state == Qt.CheckState.Checked.value else "○"),
            dot.setStyleSheet(
                f"color: {self._color('brand.green') if state == Qt.CheckState.Checked.value else self._color('neutral.dark')}; "
                f"font-size: {self._font_size('micro', 10)}px;"
            ),
            self._toggles_data.__setitem__(k, state == Qt.CheckState.Checked.value),
            self._apply_toggles(),
        )[-1])

        self._checkboxes[key] = cb
        row.addWidget(cb, stretch=1)
        row.addWidget(status_dot)

        return row

    def _build_hotkey_row(self, action_key: str, label_token: str, default_val: str) -> QHBoxLayout:
        """构建一行快捷键绑定。"""
        row = QHBoxLayout()
        row.setSpacing(12)

        name_lbl = QLabel(self._copy(label_token, action_key))
        name_lbl.setStyleSheet(
            f"color: {self._color('text.primary')}; "
            f"font-size: {self._font_size('sm_md', 13)}px;"
        )
        name_lbl.setMinimumWidth(140)
        row.addWidget(name_lbl)

        current_val = self._hotkeys_data.get(action_key, default_val)
        key_edit = _HotkeyCaptureEdit(initial=current_val)
        key_edit.captured.connect(lambda val, k=action_key: self._on_hotkey_captured(k, val))
        # ★ 捕获模式时暂停全局热键，避免按键被热键拦截
        key_edit.capture_started.connect(self._pause_hotkeys)
        key_edit.capture_stopped.connect(self._resume_hotkeys)
        self._hotkey_edits[action_key] = key_edit
        row.addWidget(key_edit)

        reset_btn = CyberButton(text=self._copy("common.reset", "重置"), variant="ghost")
        reset_btn.setFixedWidth(50)
        reset_btn.clicked.connect(lambda checked, k=action_key, dv=default_val: self._reset_hotkey(k, dv))
        row.addWidget(reset_btn)

        row.addStretch()
        return row

    def _on_hotkey_captured(self, action_key: str, value: str):
        """热键捕获完成回调 — 即时保存。"""
        print(f"[TogglesPage] 热键 {action_key} → {value}", flush=True)
        self._hotkeys_data[action_key] = value
        self._apply_hotkeys()

    def _reset_hotkey(self, action_key: str, default_val: str):
        """重置单个热键为默认值 — 即时保存。"""
        edit = self._hotkey_edits.get(action_key)
        if edit:
            edit.value = default_val
        self._hotkeys_data[action_key] = default_val
        self._apply_hotkeys()

    # ════════════════════════════════════
    #  辅助触发器开关区域
    # ════════════════════════════════════

    def _build_triggers_card(self, parent_layout: QVBoxLayout) -> None:
        """构建辅助触发器开关卡片，插入到父布局中。

        只创建卡片壳体和描述文字，内容由 _populate_triggers_section 填充。
        底部始终显示"前往详细配置"按钮。
        """
        group_name = self._copy("toggles.group_triggers", "辅助触发器")
        card = CyberCard(title=group_name)
        card_layout = card.content_layout()
        card_layout.setContentsMargins(
            self._spacing("md", 16),
            self._spacing("lg_xl", 28),
            self._spacing("md", 16),
            self._spacing("md", 16)
        )
        card_layout.setSpacing(self._spacing("sm", 10))

        # ★ 内层布局：存放触发器行，on_enter 时清理重建
        self._triggers_layout = QVBoxLayout()
        self._triggers_layout.setContentsMargins(0, 0, 0, 0)
        self._triggers_layout.setSpacing(self._spacing("sm", 10))
        card_layout.addLayout(self._triggers_layout)

        self._populate_triggers_section()

        # ── 底部：前往详细配置按钮（不在内层布局中，不会被清理）──
        goto_btn = CyberButton(
            text=self._copy("toggles.trigger_goto_config", "前往详细配置"),
            variant="outlined",
        )
        goto_btn.setFixedWidth(120)
        goto_btn.clicked.connect(self._goto_triggers_page)
        card_layout.addWidget(goto_btn)

        parent_layout.addWidget(card)

    def _goto_triggers_page(self):
        """导航到触发器配置页面。"""
        if self._app_shell is not None:
            self._app_shell._switch_to("triggers")

    def _populate_triggers_section(self) -> None:
        """★ 清除旧控件并重新加载触发器数据构建开关行。

        每次 on_enter 时调用，确保 UI 与磁盘数据完全一致。
        """
        layout = self._triggers_layout
        if layout is None:
            print(f"[TogglesPage] _populate_triggers_section: layout is None, 跳过", flush=True)
            return

        print(f"[TogglesPage] _populate_triggers_section: 清除旧控件, 数据={len(self._triggers_data)}个", flush=True)
        # 清除旧控件
        self._clear_layout(layout)
        self._trigger_checkboxes.clear()

        if not self._triggers_data:
            empty_lbl = QLabel(
                self._copy("toggles.trigger_empty", "暂无触发器")
            )
            empty_lbl.setStyleSheet(
                f"color: {self._color('text.tertiary')}; "
                f"font-size: {self._font_size('sm', 12)}px;"
            )
            layout.addWidget(empty_lbl)
        else:
            for idx, trigger in enumerate(self._triggers_data):
                row = self._build_trigger_toggle_row(trigger, idx)
                layout.addLayout(row)

    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        """安全清空布局中的所有子控件。"""
        if layout is None:
            return
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            sub_layout = item.layout()
            if sub_layout is not None:
                TogglesPage._clear_layout(sub_layout)

    def _build_trigger_toggle_row(self, trigger: dict, idx: int) -> QHBoxLayout:
        """构建一行辅助触发器开关：[切角按钮] 名称 + 摘要 [状态点]。"""
        row = QHBoxLayout()
        row.setSpacing(10)

        name = trigger.get("name", "")
        enabled = bool(trigger.get("enabled", False))
        summary = format_trigger_summary(trigger)

        display_name = name if name else self._copy(
            "triggers.state_unnamed", "未命名"
        )
        label_text = f"{display_name}  —  {summary}"

        # ── 切角开关按钮 ──
        sw = CyberToggleSwitch(text=label_text, checked=enabled)
        sw.toggled.connect(
            lambda checked, i=idx, s=sw: self._on_trigger_clicked(i, checked, s)
        )

        self._trigger_checkboxes.append((sw, idx))
        row.addWidget(sw, stretch=1)

        # ── 状态指示点 ──
        status_dot = QLabel("●" if enabled else "○")
        dot_color = self._color("brand.green") if enabled else self._color("neutral.dark")
        status_dot.setStyleSheet(
            f"color: {dot_color}; "
            f"font-size: {self._font_size('micro', 10)}px;"
        )
        status_dot.setFixedWidth(20)
        row.addWidget(status_dot)

        # 保存 dot 引用以便回调更新
        sw._status_dot = status_dot

        return row

    def _on_trigger_clicked(self, idx: int, checked: bool, sw: CyberToggleSwitch) -> None:
        """用户点击触发器开关：更新内存 + UI + 即时保存 + 重载引擎。"""
        print(f"[TogglesPage] _on_trigger_clicked idx={idx}, checked={checked}", flush=True)
        # 更新内存数据
        if idx < len(self._triggers_data):
            self._triggers_data[idx]["enabled"] = checked
        # 更新状态点
        dot = getattr(sw, '_status_dot', None)
        if dot is not None:
            dot.setText("●" if checked else "○")
            dot_color = self._color("brand.green") if checked else self._color("neutral.dark")
            dot.setStyleSheet(
                f"color: {dot_color}; "
                f"font-size: {self._font_size('micro', 10)}px;"
            )
        # ★ 即时保存文件 + 通知引擎热重载
        self._apply_triggers()

    # ════════════════════════════════════
    #  操作回调
    # ════════════════════════════════════

    def on_enter(self):
        """页面进入时重新加载最新配置并重建 UI。"""
        print(f"[TogglesPage] on_enter() 开始", flush=True)
        self._load_toggles()
        self._load_hotkeys()
        self._load_triggers()
        print(f"[TogglesPage] on_enter() 触发器数据: {len(self._triggers_data)}个", flush=True)
        for t in self._triggers_data:
            print(f"  {t.get('name')}: enabled={t.get('enabled')}", flush=True)

        # 同步功能开关 checkbox 状态
        for key, cb in self._checkboxes.items():
            val = self._toggles_data.get(key, _DEFAULT_VALUES.get(key, False))
            cb.blockSignals(True)
            cb.setChecked(bool(val))
            cb.blockSignals(False)

        # 同步热键输入框状态
        for key, edit in self._hotkey_edits.items():
            val = self._hotkeys_data.get(key, "")
            edit.value = val

        # ★ 从磁盘重新加载触发器数据，重建整个触发器开关区域
        self._populate_triggers_section()
        print(f"[TogglesPage] on_enter() 完成, 复选框数={len(self._trigger_checkboxes)}", flush=True)

    def _on_reset_defaults(self):
        """恢复默认值并即时保存。"""
        # 功能开关恢复默认（阻断信号，避免每个 checkbox 触发一次保存）
        for key, default_val in _DEFAULT_VALUES.items():
            cb = self._checkboxes.get(key)
            if cb is not None:
                cb.blockSignals(True)
                cb.setChecked(default_val)
                cb.blockSignals(False)
            self._toggles_data[key] = default_val

        # 热键恢复默认
        for action_key, _, default_val in _HOTKEY_DEFS:
            edit = self._hotkey_edits.get(action_key)
            if edit is not None:
                edit.value = default_val
            self._hotkeys_data[action_key] = default_val

        # 一次性保存
        self._apply_toggles()
        self._apply_hotkeys()

    def _get_shell(self):
        """获取 AppShell 实例。"""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        for w in app.topLevelWidgets():
            if hasattr(w, 'pipeline'):
                return w
        return None

    def _pause_hotkeys(self):
        """暂停所有全局热键（进入捕获模式时调用）。"""
        try:
            shell = self._get_shell()
            if shell and shell.pipeline and shell.pipeline._hotkey_mgr:
                shell.pipeline._hotkey_mgr.clear()
        except Exception:
            pass

    def _resume_hotkeys(self):
        """恢复全局热键（退出捕获模式时调用）。"""
        try:
            shell = self._get_shell()
            if shell and shell.pipeline and shell.pipeline._hotkey_mgr:
                shell.pipeline._hotkey_mgr.register_initial()
        except Exception:
            pass
