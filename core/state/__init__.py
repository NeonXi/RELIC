"""
core.state — 应用状态管理。

提供全局状态容器和事件总线：
- app_state:  AppState（全局状态单例：主题/语言/偏好）
- event_bus: EventBus（发布-订阅事件总线）

依赖关系:
    app_state ← PySide6 (QObject)
    event_bus ← PySide6 (QObject)

See Also:
    ui-framework-design.md §8 状态管理与数据流

## AI 硬约束 — 修改本文件前必读
归属层:    [L-State] (core/state/)
允许依赖:  PySide6.Signal(可发信号), Python 标准库
禁止依赖:  core.widgets/* / core.pages/* / core.services/*
           (State 是中间层,不能反向调上层)
必读规范:  .trae/rules/开发规范.md §6.6

本文件相关红线:
- 禁止持有 widget 引用 → State 只存数据,不发 UI 调用
- 禁止跨 EventBus 直接调 Page 方法 → 走事件订阅
- 禁止在 State 中改主题色 → 走 theme_config
- 禁止 State 在 __init__ 中做 IO → 用 lazy / explicit init

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.6。
"""

from core.state.app_state import AppState, app_state
from core.state.event_bus import EventBus, event_bus

__all__ = [
    "AppState",
    "app_state",
    "EventBus",
    "event_bus",
]
