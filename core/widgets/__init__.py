"""
core.widgets — Cyber Widget 组件库。

提供赛博风格 UI 组件的基础设施和具体实现：
- base:           CyberWidgetMixin（切角绘制、状态机、Token 访问）
- button:         CyberButton（solid / outlined / ghost 三种变体）
- panel:          CyberPanel（带标题栏的面板容器）
- line_edit:      CyberLineEdit（输入框）
- combo_box:      CyberComboBox（下拉菜单）
- card:           CyberCard（轻量级内容卡片）
- relic_tooltip:  CyberRelicTooltip（遗物信息悬浮窗）

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
