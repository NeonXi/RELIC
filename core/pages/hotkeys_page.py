"""
[L2] HotkeysPage — 快捷键配置页面。

依赖: widgets/, services/hotkey_service.py
职责: 快捷键绑定与冲突检测
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from core.pages.base_page import PageBase
from core.widgets.button import CyberButton
from core.widgets.line_edit import CyberLineEdit
from core.widgets.card import CyberCard
from core.tokens.manager import TokenManager


class HotkeysPage(PageBase):
    page_id = "hotkeys"
    page_title = ""  # 由 nav token 动态获取
    page_icon = "nav_hotkeys"

    def __init__(self):
        super().__init__()
        self.page_title = self._copy("nav.hotkeys", "快捷键")

    def build_content(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(16)

        # ── 标题 ──
        title = QLabel(self._copy("hotkeys.title", "快捷键设置"))
        title.setFont(QFont("Iceberg", self._font_size("lg_xl", 18)))
        accent = self._color("accent.primary")
        title.setStyleSheet(f"color: {accent}; padding: 4px 0;")
        layout.addWidget(title)

        desc = QLabel(self._copy("hotkeys.desc", "自定义全局快捷键，点击输入框后按下新组合键"))
        desc.setStyleSheet(f"color: {self._color('text.tertiary')}; font-size: {self._font_size('sm', 12)}px; padding: 0 0 12px 0;")
        layout.addWidget(desc)

        # ── 快捷键列表 ──
        hotkey_card = CyberCard(title=self._copy("hotkeys.card_binding", "快捷键绑定"))
        hk_layout = hotkey_card.content_layout()
        hk_layout.setContentsMargins(16, 28, 16, 16)
        hk_layout.setSpacing(10)

        hotkeys = [
            (self._copy("hotkeys.hk_toggle_window", "显示/隐藏主窗口"), "Ctrl+Shift+W"),
            (self._copy("hotkeys.hk_quick_search", "快速搜索物品"), "Ctrl+F"),
            (self._copy("hotkeys.hk_refresh_data", "刷新数据源"), "F5"),
            (self._copy("hotkeys.hk_copy_selected", "复制当前选中项"), "Ctrl+C"),
            (self._copy("hotkeys.hk_open_settings", "打开设置面板"), "Ctrl+,"),
            (self._copy("hotkeys.hk_toggle_theme", "切换深色/浅色主题"), "Ctrl+Shift+T"),
            (self._copy("hotkeys.hk_export_view", "导出当前视图"), "Ctrl+S"),
            (self._copy("hotkeys.hk_show_help", "显示帮助文档"), "F1"),
        ]

        for action_name, default_key in hotkeys:
            row = QHBoxLayout()
            row.setSpacing(12)

            name_lbl = QLabel(action_name)
            name_lbl.setStyleSheet(f"color: {self._color('text.primary')}; font-size: {self._font_size('sm_md', 13)}px;")
            name_lbl.setMinimumWidth(160)
            row.addWidget(name_lbl)

            key_input = CyberLineEdit()
            key_input.setText(default_key)
            key_input.setReadOnly(True)
            key_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
            key_input.setFixedWidth(140)
            key_input.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(key_input)

            reset_btn = CyberButton(text=self._copy("common.reset", "重置"), variant="ghost")
            reset_btn.setFixedWidth(50)
            row.addWidget(reset_btn)

            row.addStretch()

            hk_layout.addLayout(row)

        layout.addWidget(hotkey_card)

        # ── 冲突检测提示 ──
        tip_frame = QFrame()
        _hk_accent = TokenManager.instance().get_qcolor("accent.primary")
        tip_frame.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({_hk_accent.red()}, {_hk_accent.green()}, {_hk_accent.blue()}, 0.06);
                border: 1px solid rgba({_hk_accent.red()}, {_hk_accent.green()}, {_hk_accent.blue()}, 0.2);
                border-radius: {self._spacing('corner.xs', 4)}px;
                padding: {self._spacing('spacing.sm', 8)}px;
            }}
        """)
        tip_layout = QHBoxLayout(tip_frame)
        tip_layout.setContentsMargins(12, 8, 12, 8)

        tip_icon = QLabel("!")
        tip_icon.setStyleSheet(f"color: {self._color('accent.primary')}; font-size: {self._font_size('md', 14)}px; font-weight: bold;")
        tip_icon.setFixedWidth(20)
        tip_layout.addWidget(tip_icon)

        tip_text = QLabel(self._copy("hotkeys.tip", "提示：修改快捷键后请确认不与其他软件冲突。部分系统级快捷键可能无法覆盖。"))
        tip_text.setStyleSheet(f"color: {self._color('alias.text.tertiary')}; font-size: {self._font_size('xs', 11)}px;")
        tip_text.setWordWrap(True)
        tip_layout.addWidget(tip_text, stretch=1)

        layout.addWidget(tip_frame)
        layout.addStretch()

        return container
