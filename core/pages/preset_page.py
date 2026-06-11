"""
[L2] PresetPage — 语言预设页面。

依赖: widgets/
职责: 预留，待以后开发
"""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

from core.pages.base_page import PageBase


class PresetPage(PageBase):
    page_id = "preset"
    page_title = ""  # 由 nav token 动态获取
    page_icon = "nav_preset"

    def __init__(self):
        super().__init__()
        self.page_title = self._copy("nav.preset", "语言预设")

    def build_content(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        placeholder = QLabel(self._copy("preset.placeholder", "语言预设功能开发中..."))
        placeholder.setStyleSheet(
            f"color: {self._color('alias.text.tertiary')}; "
            f"font-size: {self._font_size('sm_md', 13)}px;"
        )
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(placeholder)

        return container