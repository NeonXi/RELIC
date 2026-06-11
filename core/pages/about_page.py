"""
[L2] AboutPage — 关于作者页面。

依赖: widgets/
职责: 显示项目信息、版本号、作者信息
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from core.pages.base_page import PageBase
from core.widgets.button import CyberButton
from core.widgets.card import CyberCard


class AboutPage(PageBase):
    page_id = "about"
    page_title = ""  # 由 nav token 动态获取
    page_icon = "nav_about"

    def __init__(self):
        super().__init__()
        self.page_title = self._copy("nav.about", "关于作者")

    def build_content(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(16)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # ── 标题 ──
        title = QLabel(self._copy("about.app_name", "WARFRAME RELIC"))
        title.setFont(QFont("Monoton", 28))
        accent = self._color("accent.primary")
        title.setStyleSheet(f"color: {accent}; padding: 8px 0;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel(self._copy("about.subtitle", "遗物数据查询工具"))
        subtitle.setFont(QFont("Iceberg", 14))
        subtitle.setStyleSheet(f"color: {self._color('text.tertiary')}; padding: 0 0 20px 0;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        # ── 版本信息卡片 ──
        info_card = CyberCard(title=self._copy("about.card_version", "版本信息"), clickable=False)
        info_layout = info_card.content_layout()
        info_layout.setContentsMargins(24, 28, 24, 18)
        info_layout.setSpacing(10)

        version_info = [
            (self._copy("about.label_version", "版本号"), self._copy("about.value_version", "v3.2.1 (Build 20250609)")),
            (self._copy("about.label_ui_framework", "UI 框架"), self._copy("about.value_ui_framework", "Cyberpunk UI v1.0")),
            (self._copy("about.label_runtime", "运行环境"), self._copy("about.value_runtime", "Python 3.12 / PySide6")),
            (self._copy("about.label_data_source", "数据来源"), self._copy("about.value_data_source", "Warframe 官方 API + 社区贡献")),
        ]

        for label_text, value_text in version_info:
            row = QHBoxLayout()
            row.setSpacing(12)

            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color: {self._color('alias.text.tertiary')}; font-size: {self._font_size('sm', 12)}px;")
            lbl.setFixedWidth(80)
            row.addWidget(lbl)

            val = QLabel(value_text)
            val.setStyleSheet(f"color: {self._color('text.primary')}; font-size: {self._font_size('sm', 12)}px; font-family: monospace;")
            row.addWidget(val, stretch=1)

            info_layout.addLayout(row)

        layout.addWidget(info_card)

        # ── 项目信息 ──
        proj_card = CyberCard(title=self._copy("about.card_project", "项目说明"), clickable=False)
        proj_layout = proj_card.content_layout()
        proj_layout.setContentsMargins(24, 28, 24, 18)
        proj_layout.setSpacing(10)

        about_text = QLabel(self._copy("about.project_desc",
            "WARFRAME RELIC 是一款面向 Warframe 玩家的遗物数据查询工具。\n\n"
            "主要功能：\n"
            "• 遗物内含物品与掉落概率查询\n"
            "• Prime 部件市场价格参考\n"
            "• 掉落来源追踪（任务、赏金、突击等）\n"
            "• 个人遗物收集进度管理"
        ))
        about_text.setStyleSheet(f"color: {self._color('text.secondary')}; font-size: {self._font_size('sm', 12)}px; line-height: 1.6;")
        about_text.setWordWrap(True)
        about_text.setAlignment(Qt.AlignmentFlag.AlignLeft)
        proj_layout.addWidget(about_text)

        layout.addWidget(proj_card)

        # ── 技术栈 ──
        tech_card = CyberCard(title=self._copy("about.card_tech", "技术栈"), clickable=False)
        tech_layout = tech_card.content_layout()
        tech_layout.setContentsMargins(24, 28, 24, 18)
        tech_layout.setSpacing(8)

        tech_items = [
            (self._copy("about.tech_pyside6", "PySide6"), self._copy("about.tech_pyside6_desc", "Qt6 Python 绑定，UI 渲染引擎")),
            (self._copy("about.tech_token", "Token 设计系统"), self._copy("about.tech_token_desc", "YAML 驱动的主题配置")),
            (self._copy("about.tech_widgets", "自定义组件库"), self._copy("about.tech_widgets_desc", "CyberPanel / CyberButton / CyberCard 等")),
            (self._copy("about.tech_fonts", "内嵌字体"), self._copy("about.tech_fonts_desc", "Iceberg / Monoton / Alibaba PuHuiTi")),
        ]

        for tech_name, tech_desc in tech_items:
            trow = QHBoxLayout()
            trow.setSpacing(8)

            tname = QLabel(tech_name)
            tname.setStyleSheet(f"color: {self._color('accent.secondary')}; font-size: {self._font_size('sm', 12)}px; font-weight: bold;")
            tname.setFixedWidth(90)
            trow.addWidget(tname)

            tdesc = QLabel(tech_desc)
            tdesc.setStyleSheet(f"color: {self._color('text.tertiary')}; font-size: {self._font_size('xs', 11)}px;")
            trow.addWidget(tdesc, stretch=1)

            tech_layout.addLayout(trow)

        layout.addWidget(tech_card)

        # ── 底部按钮 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        github_btn = CyberButton(text="GitHub", variant="outlined")
        github_btn.setFixedWidth(100)
        btn_row.addWidget(github_btn)

        feedback_btn = CyberButton(text=self._copy("about.btn_feedback", "反馈问题"), variant="ghost")
        feedback_btn.setFixedWidth(100)
        btn_row.addWidget(feedback_btn)

        check_update_btn = CyberButton(text=self._copy("about.btn_check_update", "检查更新"), variant="ghost")
        check_update_btn.setFixedWidth(100)
        btn_row.addWidget(check_update_btn)

        layout.addLayout(btn_row)

        # ── 版权 ──
        copyright_lbl = QLabel("© 2025 WARFRAME-RELIC Team. All rights reserved.")
        copyright_lbl.setStyleSheet(f"color: {self._color('alias.text.disabled')}; font-size: {self._font_size('micro', 10)}px;")
        copyright_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(copyright_lbl)

        layout.addStretch()

        return container
