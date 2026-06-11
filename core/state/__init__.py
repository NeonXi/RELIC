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
"""

from core.state.app_state import AppState, app_state
from core.state.event_bus import EventBus, event_bus

__all__ = [
    "AppState",
    "app_state",
    "EventBus",
    "event_bus",
]
