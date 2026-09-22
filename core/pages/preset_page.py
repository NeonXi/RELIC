"""
[L2] PresetPage — 语言预设页面。

依赖: widgets/
职责: 预留，待以后开发

## AI 硬约束 — 修改本文件前必读
归属层:    [L2] (core/pages/)
允许依赖:  core.widgets/*, core.services/*(读), PySide6
禁止依赖:  core.tokens/* 直接调用(只能间接), 任何反向依赖 widgets
必读规范:  .trae/rules/开发规范.md §6.5

本文件相关红线:
- ✗ 禁止 setStyleSheet(f"...") → 必须用 Token 或继承自 CyberWidget
- ✗ 禁止重写 paintEvent → 视觉交给 Widget
- ✗ 禁止预设数据写在 Page → 走 data/presets/*.yaml
- ✗ 禁止硬编码颜色 / 尺寸 → 必须 token / space

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.5,别走捷径。
"""


from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

from core.pages.base_page import PageBase


class PresetPage(PageBase):
    """语言预设页面。

    切换界面文案语言(中/英),预览词条翻译效果。
    修改后写回 data/language_preset.json 并触发 AppShell 刷新所有页面。
    """
    page_id = "preset"
    page_title = ""  # 由 nav token 动态获取
    page_icon = "nav_preset"

    def __init__(self):
        super().__init__()
        self.page_title = self._copy("nav.preset", "语言预设")

    def build_content(self) -> QWidget:
        """构建语言预设页(中英文切换 + 词条预览)。"""
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