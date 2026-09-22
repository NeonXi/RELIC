"""
[L4/L5] core.widgets — Cyber Widget 组件库

提供赛博风格 UI 组件的基础设施和具体实现:
- base:           CyberWidgetMixin(切角绘制、状态机、Token 访问)
- button:         CyberButton(solid / outlined / ghost 三种变体)
- panel:          CyberPanel(带标题栏的面板容器)
- line_edit:      CyberLineEdit(输入框)
- combo_box:      CyberComboBox(下拉菜单)
- card:           CyberCard(轻量级内容卡片)
- relic_tooltip:  CyberRelicTooltip(遗物信息悬浮窗)

依赖关系:
    base ← PySide6 + core.tokens
    button / panel / line_edit / combo_box / card / relic_tooltip ← base

使用方式::

    from core.widgets import (
        CyberButton, CyberPanel, CyberLineEdit,
        CyberComboBox, CyberCard, CyberRelicTooltip,
    )

    btn = CyberButton("确认", variant="solid")
    tip = CyberRelicTooltip()
    tip.set_data(relic_info=info, sources=sources)

## AI 硬约束 — 修改本目录任何文件前必读
归属层:    [L4/L5] (core/widgets/) — 整层统一规范
允许依赖:  core.tokens.manager, PySide6
禁止依赖:  core.services/*, core.pages/*, core.state/*, data/* 写操作
必读规范:  .trae/rules/开发规范.md §6.4

本层统一红线(适用于 base/button/panel/line_edit/combo_box/card/
hotkey_edit/toggle_switch/log_viewer/splash_screen/pixel_font_editor/
manual_update_dialog/proxy_dialog/relic_tooltip):
- ✗ 禁止 __init__ 调 super().__init__() → 必须显式 Qxxx.__init__(self, ...)
- ✗ 禁止 paintEvent 漏 super() → 文字/快捷键/光标会失效
- ✗ 禁止 paintEvent 顺序写反 → 必须 QPainter → 自绘 → super()
- ✗ 禁止硬编码颜色 "#XXXXXX" 或非 4 倍数尺寸 → 必须 self.token() / self.space()
- ✗ 禁止私有属性用 _xxx 命名 → 必须 _cyber_xxx 前缀
- ✗ 禁止调 Service / 发网络请求 / 读写 JSON
- ✗ 禁止未捕获的异常冒泡到 paintEvent → 必须 try/except 包住自绘代码

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.4,别走捷径。
"""

from core.widgets.base import CyberWidgetMixin
from core.widgets.button import CyberButton, ButtonVariant
from core.widgets.panel import CyberPanel
from core.widgets.line_edit import CyberLineEdit
from core.widgets.combo_box import CyberComboBox
from core.widgets.card import CyberCard
from core.widgets.relic_tooltip import CyberRelicTooltip

__all__ = [
    # 基础设施
    "CyberWidgetMixin",
    # 组件
    "CyberButton",
    "ButtonVariant",
    "CyberPanel",
    "CyberLineEdit",
    "CyberComboBox",
    "CyberCard",
    "CyberRelicTooltip",
]
