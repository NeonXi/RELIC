"""
EventBus — 轻量级发布-订阅事件总线。

用于解耦的跨组件通信：
- 一对多通知（一个事件，多个订阅者）
- 跨层级松耦合通信（发送者不知道接收者是谁）
- 工具类功能触发（导出、打印、日志等）

适用场景：
- 数据保存后多个组件需更新
- 全局 loading 显示/隐藏
- 工具操作（导出、日志记录）

不适用场景：
- 频繁触发的高频事件（用直连信号更高效）
- 需要返回值的调用

See Also:
    ui-framework-design.md §8.5 EventBus — 解耦跨组件通信

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

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    """轻量级发布-订阅事件总线。

    Attributes:
        data_saved: 数据保存事件 (source_id, data)
        data_deleted: 数据删除事件 (source_id, item_id)
        request_close_dialog: 关闭弹窗请求
        request_show_loading: 显示/隐藏全局 loading (visible: bool)
        request_scroll_to_top: 滚动到顶部 (page_id: str)
        export_requested: 导出请求 (format, data)
        log_requested: 日志记录请求 (level, message)
    """

    # ====== 预定义事件频道 ======
    # 数据类
    data_saved = Signal(str, object)       # (source_id, data)
    data_deleted = Signal(str, str)        # (source_id, item_id)

    # UI 类
    request_close_dialog = Signal()
    request_show_loading = Signal(bool)
    request_scroll_to_top = Signal(str)

    # 工具类
    export_requested = Signal(str, str)     # (format, data)
    log_requested = Signal(str, str)        # (level, message)

    def subscribe(self, signal: Signal, slot: Callable) -> Callable[[], None]:
        """订阅事件。

        Args:
            signal: 要订阅的信号（如 event_bus.data_saved）
            slot: 回调函数

        Returns:
            取消订阅的函数（调用即可取消订阅）
        """
        signal.connect(slot)

        def unsubscribe():
            signal.disconnect(slot)

        return unsubscribe


# ── 模块级单例实例 ──
event_bus = EventBus()
