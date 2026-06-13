"""
Triggers Page — 辅助触发器配置页面。

遵循 ui-framework-design.md 规范：
  - Token 驱动（颜色/字号/间距/文案全部从 Token 获取）
  - Copy Token 驱动（所有用户可见文字通过 _copy() 获取）
  - 继承原生控件 + 最小化自绘
  - 使用 core/widgets/ 下的赛博风格组件

数据层: core/trigger_config.py
引擎:   core/trigger_manager.py
"""

from __future__ import annotations

import sys
import time

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QMessageBox, QFrame,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush,
    QPainterPath, QFont, QCursor,
)

from core.pages.base_page import PageBase
from core.widgets.line_edit import CyberLineEdit
from core.widgets.button import CyberButton
from core.widgets.card import CyberCard
from core.widgets.combo_box import CyberComboBox
from core.widgets.hotkey_edit import HotkeyEdit
from core.tokens.manager import TokenManager
from core.trigger_config import (
    load_triggers, save_triggers,
    create_blank_trigger, create_blank_action,
    TRIGGER_INPUT_TYPES,
    MOUSE_BUTTONS, MOUSE_BUTTON_VALUES,
    ACTION_TYPES, ACTION_TYPE_VALUES,
    MOUSE_CLICK_BUTTONS, MOUSE_CLICK_VALUES,
    format_trigger_summary,
)



# ============================================================
#  UI 层日志（与 trigger_manager.py 统一格式）
# ============================================================

def _ui_log(msg: str, tag: str = "UI"):
    ts = time.strftime("%H:%M:%S", time.localtime())
    print(f"[TRIGGER][{tag}] {ts} | {msg}", file=sys.stderr, flush=True)


# ============================================================
#  _TriggerStatusBar — 自绘开关/摘要控件
# ============================================================

class _TriggerStatusBar(QFrame):
    """触发器卡片底部状态栏：[ON/OFF] + 名称 + 摘要，点击切换启用。"""

    toggled = Signal(bool)

    def __init__(self, parent=None):
        QFrame.__init__(self, parent)
        self._enabled = False
        self._name = ""
        self._summary = ""
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(48)

    def set_state(self, enabled: bool, name: str, summary: str):
        self._enabled = enabled
        self._name = name or "unnamed"
        self._summary = summary
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._enabled = not self._enabled
            self.toggled.emit(self._enabled)
            self.update()
            event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        r = 5

        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, r, r)

        if self._enabled:
            bg = TokenManager.instance().get_qcolor("semantic.warning")
            border = TokenManager.instance().get_qcolor("accent.primary")
            text_color = TokenManager.instance().get_qcolor("text.primary")
        else:
            bg = QColor(0, 0, 0, 0)
            border = TokenManager.instance().get_qcolor("border.subtle")
            text_color = TokenManager.instance().get_qcolor("text.tertiary")

        painter.fillPath(path, QBrush(bg))
        painter.setPen(
            QPen(border, 1,
                  Qt.PenStyle.DashLine if not self._enabled else Qt.PenStyle.SolidLine)
        )
        painter.drawPath(path)

        status = "ON" if self._enabled else "OFF"
        line1 = f"[{status}] {self._name}"
        line2 = self._summary or "not configured"

        font = QFont()
        font.setPointSize(12)
        painter.setFont(font)
        painter.setPen(text_color)
        painter.drawText(14, 22, line1)

        font2 = QFont()
        font2.setPointSize(10)
        painter.setFont(font2)
        painter.setPen(text_color.darker(130) if self._enabled else text_color)
        painter.drawText(14, 40, line2)


# ============================================================
#  _CrosshairPicker — 全屏十字线选点器（PySide6 版）
# ============================================================

class _CrosshairPicker(QWidget):
    """全屏十字线取点覆盖层。

    调用 show_overlay() 后显示半透明遮罩 + 红色十字准星，
    鼠标移动时十字线跟随，左键点击即捕获坐标并发射 position_picked 信号。
    """

    position_picked = Signal(int, int)

    def __init__(self):
        super().__init__()
        self._track_timer = QTimer(self)
        self._track_timer.timeout.connect(self._update_mouse_pos)
        self._mouse_pos = None

        # 计算所有屏幕总区域
        from PySide6.QtGui import QGuiApplication
        screens = QGuiApplication.screens()
        total_rect = screens[0].geometry() if screens else self.geometry()
        for s in screens[1:]:
            total_rect = total_rect.united(s.geometry())
        self._total_rect = total_rect

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setCursor(Qt.CursorShape.BlankCursor)

    def show_overlay(self):
        """显示覆盖层（覆盖所有屏幕）。"""
        self.setGeometry(self._total_rect)
        self._mouse_pos = None
        self._track_timer.start(16)  # ~60fps
        self.show()

    def _update_mouse_pos(self):
        self._mouse_pos = QCursor.pos()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pw = self.width()
        ph = self.height()
        painter.fillRect(0, 0, pw, ph, QColor(0, 0, 0, 60))

        if not self._mouse_pos:
            return

        px = self._mouse_pos.x() - self._total_rect.x()
        py = self._mouse_pos.y() - self._total_rect.y()

        # 红色虚线十字线
        pen_dash = QPen(QColor(220, 30, 30), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen_dash)
        painter.drawLine(0, py, pw, py)
        painter.drawLine(px, 0, px, ph)

        # 红色实心小十字（中心）
        pen_solid = QPen(QColor(220, 30, 30), 2)
        painter.setPen(pen_solid)
        painter.drawLine(px - 16, py, px + 16, py)
        painter.drawLine(px, py - 16, px, py + 16)

        # 坐标文字
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Microsoft YaHei", 11))
        coord_text = f"X: {self._mouse_pos.x()}  Y: {self._mouse_pos.y()}"
        fm = painter.fontMetrics()
        tw = fm.boundingRect(coord_text).width() + 16
        th = fm.height() + 8
        tx = px + 20
        ty = py + 20
        if tx + tw > pw:
            tx = px - tw - 20
        if ty + th > ph:
            ty = py - th - 20
        painter.fillRect(tx, ty, tw, th, QColor(0, 0, 0, 180))
        painter.drawText(tx + 8, ty + fm.ascent() + 4, coord_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = QCursor.pos()
            self.position_picked.emit(pos.x(), pos.y())
            self._track_timer.stop()
            self.hide()


# ============================================================
#  TriggersPage
# ============================================================

class TriggersPage(PageBase):
    page_id = "triggers"
    page_title = ""
    page_icon = "nav_triggers"

    def __init__(self):
        self._trigger_card_widgets: list[dict] = []

        super().__init__()
        self.page_title = self._copy("nav.triggers", "Triggers")

    # ════════════════════════════════════
    #  主内容构建
    # ════════════════════════════════════

    def build_content(self) -> QWidget:
        _ui_log("build_content()", "UI_INIT")
        _sp = self._spacing
        _fs = self._font_size
        _co = self._color
        _cp = self._copy

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(_sp("lg", 20), _sp("sm", 8), _sp("lg", 20), _sp("lg", 20))
        layout.setSpacing(_sp("xs", 4))

        # ── 标题 ──
        title = QLabel(_cp("triggers.title", "Trigger Config"))
        title.setFont(QFont("Iceberg", _fs("lg_xl", 18)))
        title.setStyleSheet(f"color: {_co('accent.primary')}; padding: 4px 0;")
        layout.addWidget(title)

        desc = QLabel(
            _cp("triggers.desc",
                "Detect specified input then auto-execute actions (key / click / move)")
        )
        desc.setStyleSheet(
            f"color: {_co('text.tertiary')}; "
            f"font-size: {_fs('sm', 11)}px; padding: 0 0 12px 0;"
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ── 卡片容器 ──
        self._cards_container = QWidget()
        self._cards_container.setStyleSheet("background-color: transparent;")
        cards_layout = QVBoxLayout(self._cards_container)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(_sp("sm", 10))
        layout.addWidget(self._cards_container)

        # ── 加载已有触发器 ──
        triggers_data = load_triggers()
        if not triggers_data:
            triggers_data = [create_blank_trigger()]

        for t in triggers_data:
            cw = self._build_trigger_card(t, cards_layout)
            cards_layout.addWidget(cw["card"])
            self._trigger_card_widgets.append(cw)

        # ── 新增按钮 ──
        btn_add = CyberButton(text=_cp("triggers.btn_add", "+ Add Trigger"), variant="ghost")
        btn_add.clicked.connect(lambda: self._on_add_trigger_card(cards_layout))
        layout.addWidget(btn_add)

        # ── 提示框 ──
        tip_frame = self._build_tip_frame()
        layout.addWidget(tip_frame)

        layout.addStretch()
        return container

    # ════════════════════════════════════
    #  提示框
    # ════════════════════════════════════

    def _build_tip_frame(self) -> QWidget:
        frame = QFrame()
        _accent = TokenManager.instance().get_qcolor("accent.primary")
        frame.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({_accent.red()}, {_accent.green()}, {_accent.blue()}, 0.06);
                border: 1px solid rgba({_accent.red()}, {_accent.green()}, {_accent.blue()}, 0.2);
                border-radius: 4px;
            }}
        """)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)

        icon = QLabel("!")
        icon.setStyleSheet(
            f"color: {self._color('accent.primary')}; "
            f"font-size: {self._font_size('md', 14)}px; font-weight: bold;"
        )
        icon.setFixedWidth(20)
        layout.addWidget(icon)

        text = QLabel(
            self._copy("triggers.tip",
                       "Tip: changes auto-save. Mouse-move works with crosshair picker. "
                       "Keyboard capture temporarily intercepts global hotkeys.")
        )
        text.setStyleSheet(
            f"color: {self._color('alias.text.tertiary')}; "
            f"font-size: {self._font_size('xs', 11)}px;"
        )
        text.setWordWrap(True)
        layout.addWidget(text, stretch=1)

        return frame

    # ════════════════════════════════════
    #  单个触发器卡片
    # ════════════════════════════════════

    def _build_trigger_card(self, trigger_data: dict, parent_layout) -> dict:
        """构建一个完整的触发器卡片：名称 + 触发输入 + 动作列表 + 状态栏 + 删除。

        Args:
            trigger_data: 触发器配置字典。
            parent_layout: 卡片要添加到的父布局。

        Returns:
            包含所有子控件引用的 dict，供信号连接和数据读取使用。
        """
        _h = 32  # 统一行高
        _sp = self._spacing
        _fs = self._font_size
        _co = self._color
        _cp = self._copy

        card_name = trigger_data.get("name") or _cp("triggers.untitled", "Untitled")
        card = CyberCard(title=card_name)
        cl = card.content_layout()
        cl.setContentsMargins(_sp("md", 16), _sp("lg_xl", 28), _sp("md", 16), _sp("md", 16))
        cl.setSpacing(_sp("sm", 10))

        # ────────────────────────────────
        #  第 1 行：名称
        # ────────────────────────────────
        name_row = QHBoxLayout()
        name_row.setSpacing(8)

        name_label = QLabel(_cp("triggers.label_name", "Name:"))
        name_label.setFixedWidth(40)
        name_label.setFixedHeight(_h)
        name_label.setStyleSheet(
            f"color: {_co('text.primary')}; "
            f"font-size: {_fs('sm', 12)}px;"
        )

        name_input = CyberLineEdit(placeholder=_cp("triggers.ph_name", "e.g. Quick Pickup"))
        name_input.setText(trigger_data.get("name", ""))
        name_input.setFixedHeight(_h)

        name_row.addWidget(name_label)
        name_row.addWidget(name_input, 1)
        cl.addLayout(name_row)

        # ────────────────────────────────
        #  第 2 行：触发器类型 + 输入值 + 延迟
        # ────────────────────────────────
        trigger_row = QHBoxLayout()
        trigger_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        trigger_row.setSpacing(8)

        type_label = QLabel(_cp("triggers.label_trigger", "Trigger:"))
        type_label.setFixedWidth(40)
        type_label.setFixedHeight(_h)
        type_label.setStyleSheet(name_label.styleSheet())

        ti = trigger_data.get("trigger_input", {})
        current_ti_type = ti.get("type", "mouse")

        # 触发器类型下拉（mouse / keyboard）
        trigger_type_combo = CyberComboBox()
        trigger_type_combo.addItems(TRIGGER_INPUT_TYPES)
        tidx = (TRIGGER_INPUT_TYPES.index(current_ti_type)
                if current_ti_type in TRIGGER_INPUT_TYPES else 0)
        trigger_type_combo.setCurrentIndex(tidx)
        trigger_type_combo.setFixedHeight(_h)

        # 鼠标按钮选择（mouse 模式显示）
        mouse_btn_combo = CyberComboBox()
        for _btn_val, _btn_lbl in MOUSE_BUTTONS:
            mouse_btn_combo.addItem(_btn_lbl)
        current_btn = ti.get("button", "right")
        bidx = (MOUSE_BUTTON_VALUES.index(current_btn)
                if current_btn in MOUSE_BUTTON_VALUES else 1)
        mouse_btn_combo.setCurrentIndex(bidx)
        mouse_btn_combo.setFixedHeight(_h)

        # 键盘按键捕获（keyboard 模式显示）
        kb_key_input = HotkeyEdit(initial=ti.get("key", ""))
        kb_key_input.setFixedHeight(_h)

        # 延迟毫秒数
        delay_label = QLabel(_cp("triggers.label_delay", "Delay:"))
        delay_label.setFixedHeight(_h)
        delay_label.setStyleSheet(name_label.styleSheet())

        delay_spin = QSpinBox()
        delay_spin.setRange(0, 5000)
        delay_spin.setSingleStep(5)
        delay_spin.setValue(trigger_data.get("delay_ms", 10))
        delay_spin.setSuffix(" ms")
        delay_spin.setFixedWidth(100)
        delay_spin.setFixedHeight(_h)
        self._apply_form_style(delay_spin)

        # 组装触发行（先全部 addWidget，再设置显隐）
        trigger_row.addWidget(type_label)
        trigger_row.addWidget(trigger_type_combo)
        trigger_row.addWidget(mouse_btn_combo)
        trigger_row.addWidget(kb_key_input)
        trigger_row.addStretch()
        trigger_row.addWidget(delay_label)
        trigger_row.addWidget(delay_spin)
        cl.addLayout(trigger_row)

        # 显隐联动（必须在 addWidget 之后）
        mouse_btn_combo.setVisible(current_ti_type != "keyboard")
        kb_key_input.setVisible(current_ti_type == "keyboard")

        def _on_trigger_type_changed(index):
            is_kb = TRIGGER_INPUT_TYPES[index] == "keyboard"
            mouse_btn_combo.setVisible(not is_kb)
            kb_key_input.setVisible(is_kb)

        trigger_type_combo.currentIndexChanged.connect(_on_trigger_type_changed)

        # ────────────────────────────────
        #  动作列表区域
        # ────────────────────────────────
        actions_label = QLabel(_cp("triggers.label_actions", "Actions:"))
        actions_label.setStyleSheet(name_label.styleSheet())
        cl.addWidget(actions_label)

        actions_container = QWidget()
        actions_container.setStyleSheet("background-color: transparent;")
        actions_layout = QVBoxLayout(actions_container)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        cl.addWidget(actions_container)

        action_widgets_list: list[dict] = []
        actions_data = trigger_data.get("actions", [])
        if not actions_data:
            actions_data = [create_blank_action()]

        for act in actions_data:
            aw = self._build_action_row(act, actions_layout)
            action_widgets_list.append(aw)

        # + 添加动作按钮
        btn_add_act = CyberButton(text=_cp("triggers.btn_add_action", "+ Add Action"), variant="ghost")

        def _make_add_action():
            blank = create_blank_action()
            aw = self._build_action_row(blank, actions_layout)
            action_widgets_list.append(aw)
            self._wire_action_changes(aw, on_change_fn)
            aw["btn_del_act"].clicked.connect(
                lambda checked, a=aw, c=cw: self._on_delete_action_row(a, c)
            )
            btn_add_act.setParent(None)
            actions_layout.addWidget(btn_add_act)

        btn_add_act.clicked.connect(_make_add_action)
        actions_layout.addWidget(btn_add_act)

        # ────────────────────────────────
        #  状态栏（开关 + 摘要）
        # ────────────────────────────────
        status_bar = _TriggerStatusBar()
        status_bar.set_state(
            bool(trigger_data.get("enabled", False)),
            trigger_data.get("name", ""),
            format_trigger_summary(trigger_data),
        )
        status_bar.toggled.connect(lambda checked: self._on_status_toggle(status_bar, checked))
        cl.addWidget(status_bar)

        # ── 删除按钮（红色 danger 样式）──
        del_row = QHBoxLayout()
        del_row.addStretch()
        btn_delete = CyberButton(
            text=_cp("triggers.btn_delete", "删除触发器"), variant="semantic.danger"
        )
        del_row.addWidget(btn_delete)
        cl.addLayout(del_row)

        # ────────────────────────────────
        #  变化回调（即时保存 + 更新摘要）
        # ────────────────────────────────
        def on_change_fn():
            # 同步卡片标题
            new_name = name_input.text().strip()
            title_text = new_name or _cp("triggers.untitled", "Untitled")
            if card._title_bar and card._title_bar.text() != title_text:
                card._title_bar.setText(title_text)
            # 更新状态栏摘要
            self._refresh_status_bar(
                status_bar, name_input, trigger_type_combo,
                mouse_btn_combo, kb_key_input, delay_spin,
                action_widgets_list,
            )
            self._save_all_triggers()

        # 连接名称和触发器字段信号
        name_input.textChanged.connect(on_change_fn)
        trigger_type_combo.currentIndexChanged.connect(on_change_fn)
        mouse_btn_combo.currentIndexChanged.connect(on_change_fn)
        kb_key_input.captured.connect(on_change_fn)
        delay_spin.valueChanged.connect(on_change_fn)

        # 连接已有动作行的信号
        for aw in action_widgets_list:
            self._wire_action_changes(aw, on_change_fn)

        # ── 构建返回值字典 ──
        cw = {
            "card": card,
            "name_input": name_input,
            "trigger_type_combo": trigger_type_combo,
            "mouse_btn_combo": mouse_btn_combo,
            "kb_key_input": kb_key_input,
            "delay_spin": delay_spin,
            "status_bar": status_bar,
            "action_widgets": action_widgets_list,
            "btn_delete": btn_delete,
            "actions_container": actions_container,
            "btn_add_action": btn_add_act,
        }

        # 连接动作行删除按钮（cw 定义后才可引用）
        for aw in action_widgets_list:
            aw["btn_del_act"].clicked.connect(
                lambda checked, a=aw, c=cw: self._on_delete_action_row(a, c)
            )

        btn_delete.clicked.connect(lambda: self._on_delete_trigger_card(card))

        return cw

    # ════════════════════════════════════
    #  单个动作行
    # ════════════════════════════════════

    def _build_action_row(self, action_data: dict, parent_layout) -> dict:
        """构建单个响应动作行：类型下拉 + 值输入 + 删除按钮。

        根据动作类型自动切换值输入控件的显隐：
          - key         → HotkeyEdit（快捷键捕获）
          - mouse_click → QComboBox（鼠标按钮选择）
          - mouse_move  → CyberLineEdit（坐标输入）

        Args:
            action_data: 动作配置字典。
            parent_layout: 行要添加到的父布局。

        Returns:
            包含该行所有控件引用的 dict。
        """
        _h = 30  # 动作行高度略小于主表单
        _co = self._color
        _fs = self._font_size
        _cp = self._copy

        row = QHBoxLayout()
        row.setSpacing(6)

        # ── 动作类型下拉 ──
        type_combo = CyberComboBox()
        for _atype_val, _atype_lbl in ACTION_TYPES:
            type_combo.addItem(_atype_lbl)
        current_atype = action_data.get("type", "key")
        aidx = (ACTION_TYPE_VALUES.index(current_atype)
                if current_atype in ACTION_TYPE_VALUES else 0)
        type_combo.setCurrentIndex(aidx)
        type_combo.setFixedHeight(_h)

        # ── 按键值输入（HotkeyEdit）──
        key_value_input = HotkeyEdit(initial=action_data.get("value", ""))
        key_value_input.setFixedHeight(_h)
        key_value_input.setFixedWidth(140)

        # ── 鼠标点击值选择 ──
        click_value_combo = CyberComboBox()
        for _click_val, _click_lbl in MOUSE_CLICK_BUTTONS:
            click_value_combo.addItem(_click_lbl)
        current_click = action_data.get("value", "")
        cidx = (MOUSE_CLICK_VALUES.index(current_click)
                if current_click in MOUSE_CLICK_VALUES else 0)
        click_value_combo.setCurrentIndex(cidx)
        click_value_combo.setFixedHeight(_h)
        click_value_combo.setFixedWidth(100)

        # ── 鼠标移动坐标（只读显示 + 十字线选点按钮）──
        move_coord_label = QLabel(action_data.get("value", "") or "---")
        move_coord_label.setFixedHeight(_h)
        move_coord_label.setMinimumWidth(80)
        move_coord_label.setStyleSheet(
            f"background-color: {self._color('bg.base')}; color: {self._color('text.primary')}; "
            f"border: 1px solid {self._color('border.subtle')}; border-radius: 4px; "
            f"padding: 4px 8px;"
        )
        move_coord_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        btn_pick_pos = CyberButton(text=_cp("triggers.btn_pick", "Pick"), variant="ghost")
        btn_pick_pos.setFixedHeight(_h)

        # ── 删除按钮（红色 danger 样式）──
        btn_del_act = CyberButton(text="✕", variant="semantic.danger")
        btn_del_act.setFixedSize(30, _h)

        # 先全部加入布局（确保 setVisible 在 addWidget 之后生效）
        row.addWidget(type_combo)
        row.addWidget(key_value_input)
        row.addWidget(click_value_combo)
        row.addWidget(move_coord_label)
        row.addWidget(btn_pick_pos)
        row.addWidget(btn_del_act)

        # 设置初始显隐（必须在 addWidget 之后）
        atype = ACTION_TYPE_VALUES[aidx] if aidx < len(ACTION_TYPE_VALUES) else "key"
        key_value_input.setVisible(atype == "key")
        click_value_combo.setVisible(atype == "mouse_click")
        move_coord_label.setVisible(atype == "mouse_move")
        btn_pick_pos.setVisible(atype == "mouse_move")

        def _on_action_type_changed(idx):
            t = ACTION_TYPE_VALUES[idx] if idx < len(ACTION_TYPE_VALUES) else "key"
            key_value_input.setVisible(t == "key")
            click_value_combo.setVisible(t == "mouse_click")
            move_coord_label.setVisible(t == "mouse_move")
            btn_pick_pos.setVisible(t == "mouse_move")

        type_combo.currentIndexChanged.connect(_on_action_type_changed)

        # 十字线选点回调
        def _on_pick_position(x: int, y: int):
            coord_text = f"{x}, {y}"
            move_coord_label.setText(coord_text)
            self._save_all_triggers()  # 即时保存

        btn_pick_pos.clicked.connect(self._open_crosshair_picker(_on_pick_position))

        parent_layout.addLayout(row)

        return {
            "type_combo": type_combo,
            "key_value_input": key_value_input,
            "click_value_combo": click_value_combo,
            "move_coord_label": move_coord_label,
            "btn_pick_pos": btn_pick_pos,
            "btn_del_act": btn_del_act,
        }

    # ════════════════════════════════════
    #  样式工具
    # ════════════════════════════════════

    @staticmethod
    def _apply_form_style(widget):
        """对 QSpinBox 应用统一的深色表单样式。"""
        _tm = TokenManager.instance()
        base_bg = _tm.get_qcolor("bg.base").name()
        base_border = _tm.get_qcolor("border.subtle").name()
        focus_border = _tm.get_qcolor("border.focus").name()
        text_color = _tm.get_qcolor("text.primary").name()

        base_ss = (
            f"background-color: {base_bg}; "
            f"color: {text_color}; "
            f"border: 1px solid {base_border}; "
            f"border-radius: 4px; "
            f"padding: 4px 8px;"
        )
        focus_ss = f"border: 1px solid {focus_border};"

        if isinstance(widget, QSpinBox):
            widget.setStyleSheet(
                f"QSpinBox {{ {base_ss} }} "
                f"QSpinBox:focus {{{focus_ss}}}"
            )

    @staticmethod
    def _wire_action_changes(aw: dict, fn):
        """连接动作行所有变化信号到统一回调。"""
        aw["key_value_input"].captured.connect(fn)
        aw["click_value_combo"].currentIndexChanged.connect(fn)
        # mouse_move 的坐标通过十字线选点器设置，无需 textChanged 信号

    def _open_crosshair_picker(self, on_picked):
        """返回一个回调函数，点击后打开全屏十字线选点器。

        Args:
            on_picked: 坐标选中后的回调，签名为 (x, y) -> None

        Returns:
            可连接到 clicked 信号的函数。
        """
        if not hasattr(self, "_crosshair_picker"):
            self._crosshair_picker = _CrosshairPicker()

        def _open():
            # 断开旧连接
            try:
                self._crosshair_picker.position_picked.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._crosshair_picker.position_picked.connect(on_picked)
            self._crosshair_picker.show_overlay()

        return _open

    def _find_trigger_manager(self):
        """在组件链上查找 TriggerManager 实例。"""
        # 1) 直接用 AppShell 引用（最可靠）
        if self._app_shell is not None:
            mgr = getattr(self._app_shell, '_trigger_manager', None)
            _ui_log(f"find_mgr() | _app_shell={type(self._app_shell).__name__} | "
                    f"_trigger_manager={'FOUND' if mgr else 'NONE'} | "
                    f"running={mgr.is_running if mgr else 'N/A'}", "UI_MGR_DBG")
            if mgr is not None:
                return mgr
        else:
            _ui_log("find_mgr() | _app_shell is None", "UI_MGR_DBG")

        # 2) 回退：遍历 parent() 链
        widget = self.parent()
        while widget is not None:
            if hasattr(widget, '_trigger_manager') and widget._trigger_manager is not None:
                return widget._trigger_manager
            widget = widget.parent()

        _ui_log("find_mgr() | NOT FOUND", "UI_MGR_WARN")
        return None

    # ════════════════════════════════════
    #  事件处理
    # ════════════════════════════════════

    def _on_add_trigger_card(self, parent_layout):
        blank = create_blank_trigger()
        cw = self._build_trigger_card(blank, parent_layout)
        parent_layout.addWidget(cw["card"])
        self._trigger_card_widgets.append(cw)
        self._save_all_triggers()

    def _on_delete_trigger_card(self, card: CyberCard):
        reply = QMessageBox.question(
            self,
            self._copy("common.confirm", "Confirm"),
            self._copy("triggers.delete_confirm", "Delete this trigger?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for i, cw in enumerate(self._trigger_card_widgets):
            if cw["card"] is card:
                self._trigger_card_widgets.pop(i)
                break

        card.hide()
        card.setParent(None)
        card.deleteLater()
        self._save_all_triggers()

    def _on_delete_action_row(self, action_widget: dict, parent_cw: dict):
        aw = action_widget
        if aw in parent_cw["action_widgets"]:
            parent_cw["action_widgets"].remove(aw)

        for ctrl in [
            aw["type_combo"], aw["key_value_input"],
            aw["click_value_combo"], aw["move_coord_label"],
            aw["btn_pick_pos"], aw["btn_del_act"],
        ]:
            if ctrl is not None:
                ctrl.hide()
                ctrl.setParent(None)
                ctrl.deleteLater()

        self._save_all_triggers()

    def _on_status_toggle(self, bar: _TriggerStatusBar, checked: bool):
        _ui_log(f"status_toggle() | trigger='{bar._name}' | "
                f"enabled={checked}", "UI_TOGGLE")
        # ★ 即时保存，对端页面（TogglesPage）在 on_enter 时从磁盘读取最新状态。
        self._save_all_triggers()

    # ════════════════════════════════════
    #  页面生命周期
    # ════════════════════════════════════

    def on_enter(self):
        """页面进入时从磁盘重新加载触发器数据，同步状态栏。

        确保在开关页面修改后，返回本页时状态栏与磁盘数据一致。
        """
        current_data = load_triggers()

        # 数量不一致 → 完全重建（由 build_content 处理，最简单的方式是重载整个页面）
        if len(current_data) != len(self._trigger_card_widgets):
            # 触发重建：移除旧内容，重新构建
            container = self.layout().itemAt(0).widget()
            if container:
                old_layout = container.layout()
                if old_layout:
                    while old_layout.count():
                        item = old_layout.takeAt(0)
                    container.setParent(None)
                    container.deleteLater()
            # 重建内容
            new_content = self.build_content()
            self.layout().addWidget(new_content)
            return

        # 数量一致 → 只同步 enabled 状态
        for i, cw in enumerate(self._trigger_card_widgets):
            bar = cw.get("status_bar")
            if bar is None:
                continue
            disk_enabled = bool(current_data[i].get("enabled", False))
            if bar._enabled != disk_enabled:
                name_input = cw.get("name_input")
                name = name_input.text().strip() if name_input else ""
                summary = self._build_summary_from_card(cw)
                bar.blockSignals(True)
                bar.set_state(disk_enabled, name, summary)
                bar.blockSignals(False)

    def on_leave(self):
        """页面离开时确保数据已持久化。"""
        self._save_all_triggers()
        _ui_log("on_leave() → 已强制保存触发器状态", "UI_LIFECYCLE")

    def _build_summary_from_card(self, cw: dict) -> str:
        """从卡片控件字典读取当前值，生成触发器摘要文本。"""
        ttc = cw.get("trigger_type_combo")
        mbc = cw.get("mouse_btn_combo")
        kbi = cw.get("kb_key_input")
        dsp = cw.get("delay_spin")
        awl = cw.get("action_widgets", [])

        ti_type = "mouse"
        if ttc is not None:
            idx = ttc.currentIndex()
            ti_type = TRIGGER_INPUT_TYPES[idx] if idx < len(TRIGGER_INPUT_TYPES) else "mouse"

        trigger_input = {"type": ti_type}
        if ti_type == "mouse" and mbc is not None:
            midx = mbc.currentIndex()
            trigger_input["button"] = (
                MOUSE_BUTTON_VALUES[midx] if midx < len(MOUSE_BUTTON_VALUES) else "right"
            )
        elif ti_type == "keyboard" and kbi is not None:
            trigger_input["key"] = kbi.value

        delay = int(dsp.value()) if dsp else 0

        actions = []
        for aw in awl:
            tc = aw.get("type_combo")
            if tc is None:
                continue
            aidx = tc.currentIndex()
            atype = ACTION_TYPES[aidx] if aidx < len(ACTION_TYPES) else "key"
            action = {"type": atype}
            if atype in ("key", "hold"):
                val_edit = aw.get("value_edit")
                action["value"] = int(val_edit.text()) if val_edit and val_edit.text().isdigit() else 1
            elif atype == "mouse_click":
                mcc = aw.get("mouse_click_combo")
                if mcc is not None:
                    mcidx = mcc.currentIndex()
                    action["button"] = (
                        MOUSE_CLICK_VALUES[mcidx] if mcidx < len(MOUSE_CLICK_VALUES) else "left"
                    )
            actions.append(action)

        return format_trigger_summary({
            "name": "",
            "enabled": True,
            "trigger_input": trigger_input,
            "delay_ms": delay,
            "actions": actions,
        })

    # ════════════════════════════════════
    #  数据持久化
    # ════════════════════════════════════

    def _save_all_triggers(self):
        """从所有卡片控件读取当前值，写入 JSON 文件。"""
        triggers = []

        for cw in self._trigger_card_widgets:
            # 名称
            name_input = cw.get("name_input")
            name = name_input.text().strip() if name_input else ""

            # 触发输入
            ttc = cw.get("trigger_type_combo")
            mbc = cw.get("mouse_btn_combo")
            kbi = cw.get("kb_key_input")
            dsp = cw.get("delay_spin")

            ti_type = "mouse"
            if ttc is not None:
                idx = ttc.currentIndex()
                ti_type = TRIGGER_INPUT_TYPES[idx] if idx < len(TRIGGER_INPUT_TYPES) else "mouse"

            trigger_input = {"type": ti_type}
            if ti_type == "mouse":
                if mbc is not None:
                    midx = mbc.currentIndex()
                    trigger_input["button"] = (
                        MOUSE_BUTTON_VALUES[midx]
                        if midx < len(MOUSE_BUTTON_VALUES) else "right"
                    )
            else:
                if kbi is not None:
                    trigger_input["key"] = kbi.value

            # 延迟
            delay_ms = int(dsp.value()) if dsp else 10

            # 动作列表
            actions = []
            for aw in cw.get("action_widgets", []):
                tc = aw.get("type_combo")
                if tc is None:
                    continue
                aidx = tc.currentIndex()
                atype = ACTION_TYPE_VALUES[aidx] if aidx < len(ACTION_TYPE_VALUES) else "key"

                value = ""
                if atype == "key":
                    kvi = aw.get("key_value_input")
                    value = kvi.value if kvi else ""
                elif atype == "mouse_click":
                    cvc = aw.get("click_value_combo")
                    if cvc is not None:
                        cidx = cvc.currentIndex()
                        value = (
                            MOUSE_CLICK_VALUES[cidx]
                            if cidx < len(MOUSE_CLICK_VALUES) else ""
                        )
                elif atype == "mouse_move":
                    mvi = aw.get("move_coord_label")
                    value = mvi.text().strip() if mvi else ""

                actions.append({"type": atype, "value": value})

            data = {
                "name": name,
                "enabled": cw["status_bar"]._enabled,
                "trigger_input": trigger_input,
                "delay_ms": delay_ms,
                "actions": actions,
            }
            triggers.append(data)

        save_triggers(triggers)

        # 通知引擎热重载（从父组件链获取 TriggerManager 引用）
        mgr = self._find_trigger_manager()
        if mgr is not None:
            mgr.reload(triggers)
            enabled_count = sum(1 for t in triggers if t.get("enabled"))
            _ui_log(f"save() | saved={len(triggers)} triggers | "
                    f"enabled={enabled_count} | reload OK", "UI_SAVE")
        else:
            _ui_log("save() | saved but TriggerManager NOT FOUND (reload skipped!)", "UI_SAVE_WARN")

    # ════════════════════════════════════
    #  状态栏刷新
    # ════════════════════════════════════

    @staticmethod
    def _refresh_status_bar(bar, name_input, trigger_type_combo,
                             mouse_btn_combo, kb_key_input, delay_spin,
                             action_widgets_list):
        """根据当前控件值更新状态栏的摘要文本。"""
        name = name_input.text().strip() if name_input else ""

        # 构造临时 trigger_data 用于 format_trigger_summary
        ti_type = "mouse"
        if trigger_type_combo is not None:
            idx = trigger_type_combo.currentIndex()
            ti_type = TRIGGER_INPUT_TYPES[idx] if idx < len(TRIGGER_INPUT_TYPES) else "mouse"

        ti = {"type": ti_type}
        if ti_type == "mouse" and mouse_btn_combo is not None:
            midx = mouse_btn_combo.currentIndex()
            ti["button"] = (
                MOUSE_BUTTON_VALUES[midx]
                if midx < len(MOUSE_BUTTON_VALUES) else "right"
            )
        elif ti_type == "keyboard" and kb_key_input is not None:
            ti["key"] = kb_key_input.value

        delay = int(delay_spin.value()) if delay_spin else 0

        actions = []
        for aw in action_widgets_list:
            tc = aw.get("type_combo")
            if tc is None:
                continue
            aidx = tc.currentIndex()
            atype = ACTION_TYPE_VALUES[aidx] if aidx < len(ACTION_TYPE_VALUES) else "key"

            value = ""
            if atype == "key":
                kvi = aw.get("key_value_input")
                value = kvi.value if kvi else ""
            elif atype == "mouse_click":
                cvc = aw.get("click_value_combo")
                if cvc is not None:
                    cidx = cvc.currentIndex()
                    value = (
                        MOUSE_CLICK_VALUES[cidx]
                        if cidx < len(MOUSE_CLICK_VALUES) else ""
                    )
            elif atype == "mouse_move":
                mvi = aw.get("move_coord_label")
                value = mvi.text().strip() if mvi else ""

            actions.append({"type": atype, "value": value})

        bar.set_state(
            bar._enabled,
            name,
            format_trigger_summary({
                "trigger_input": ti,
                "delay_ms": delay,
                "actions": actions,
            }),
        )
