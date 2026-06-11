"""
[L2] ThemePage — 主题换肤页面。

依赖: widgets/, sections/theme_edit_section.py, sections/theme_bg_section.py
职责: 预设切换 + 自定义颜色编辑
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QCheckBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from core.pages.base_page import PageBase
from core.widgets.button import CyberButton
from core.widgets.panel import CyberPanel
from core.widgets.card import CyberCard


class ThemePage(PageBase):
    page_id = "theme"
    page_title = ""  # 由 nav token 动态获取
    page_icon = "nav_theme"

    def __init__(self):
        super().__init__()
        self.page_title = self._copy("nav.theme", "主题换肤")

    def build_content(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(16)

        # ── 标题 ──
        title = QLabel(self._copy("theme.title", "外观与主题"))
        title.setFont(QFont("Iceberg", self._font_size("lg_xl", 18)))
        accent = self._color("accent.primary")
        title.setStyleSheet(f"color: {accent}; padding: 4px 0;")
        layout.addWidget(title)

        # ── 启动设置 ──
        startup_card = CyberCard(title=self._copy("theme.card_startup", "启动设置"))
        startup_layout = startup_card.content_layout()
        startup_layout.setContentsMargins(16, 28, 16, 16)
        startup_layout.setSpacing(12)

        # 开启动画开关
        splash_row = QHBoxLayout()
        splash_row.setSpacing(10)

        splash_cb = QCheckBox(self._copy("theme.label_splash", "显示开启动画 (像素 RELIC)"))
        splash_cb.setChecked(True)
        splash_cb.setCursor(Qt.CursorShape.PointingHandCursor)
        splash_cb.setStyleSheet(f"""
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
            QCheckBox:hover {{ color: {self._color('accent.secondary')}; }}
        """)
        splash_row.addWidget(splash_cb)

        preview_btn = CyberButton(text=self._copy("theme.btn_preview", "预览"), variant="ghost")
        preview_btn.setFixedWidth(60)
        preview_btn.setToolTip(self._copy("theme.tip_preview", "预览开启动画效果"))
        preview_btn.clicked.connect(lambda: self._preview_splash())
        splash_row.addWidget(preview_btn)

        splash_row.addStretch()
        startup_layout.addLayout(splash_row)

        layout.addWidget(startup_card)

        # ── 像素字体编辑器 ──
        editor_card = CyberCard(title=self._copy("theme.card_pixel_font", "像素字体编辑器"))
        editor_layout = editor_card.content_layout()
        editor_layout.setContentsMargins(12, 24, 12, 12)
        editor_layout.setSpacing(8)

        try:
            from core.widgets.pixel_font_editor import _PixelFontEditorPanel
            editor_panel = _PixelFontEditorPanel()
            editor_layout.addWidget(editor_panel)
        except Exception as e:
            import traceback
            # 控制台输出完整错误信息（供开发调试）
            print(f"[ThemePage] 像素字体编辑器加载失败: {e}", flush=True)
            traceback.print_exc()
            # UI 仅显示简短提示，不暴露内部细节
            err_lbl = QLabel(self._copy("theme.err_load_failed", "加载失败: {error}", error=str(e)))
            err_lbl.setStyleSheet(f"color: {self._color('semantic.warning')}; font-size: {self._font_size('sm', 11)}px;")
            err_lbl.setWordWrap(True)
            editor_layout.addWidget(err_lbl)

        layout.addWidget(editor_card)
        layout.addStretch()

        return container

    def _preview_splash(self) -> None:
        """预览开启动画。"""
        print("[ThemePage] 预览按钮被点击", flush=True)
        try:
            from core.widgets.splash_screen import CyberSplashScreen
            parent = self.window()  # AppShell QMainWindow
            print("[ThemePage] 创建 CyberSplashScreen (embedded)...", flush=True)

            def _on_finished():
                if self._preview_splash_instance:
                    self._preview_splash_instance.close()
                    self._preview_splash_instance.deleteLater()
                    self._preview_splash_instance = None

            self._preview_splash_instance = CyberSplashScreen(
                parent=parent, enabled=True, on_finished=_on_finished)
            self._preview_splash_instance.setGeometry(
                0, 0, parent.width(), parent.height())
            self._preview_splash_instance.show()
            print("[ThemePage] splash.show() 已调用", flush=True)
        except Exception as e:
            print(f"[ThemePage] 预览失败: {e}", flush=True)
