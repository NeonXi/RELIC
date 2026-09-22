"""
[L-Service] 轻量事件发射器

替代 PySide6 Signal，用于 services 层解耦 Qt 依赖。
支持 .connect(callable) / .emit(*args) 模式，与 Qt Signal 接口兼容。

## AI 硬约束 — 修改本文件前必读
归属层:    [L-Service] (core/services/)
允许依赖:  Python 标准库 + data/* + core.hotkey_config 等纯模块
禁止依赖:  PySide6 / QtWidgets / QtGui / QtCore(Signal 除外)
           core.widgets/* / core.pages/* / core.recognizers/*
必读规范:  .trae/rules/开发规范.md §6.2

本文件相关红线:
- 禁止 import PySide6 → Service 是纯逻辑,不能碰 UI
- 禁止返回 Qt 对象 → 只能返回 dict / list / str / int / bool
- 禁止在 Service 中发信号调用 widget → 状态走 core.state / EventBus
- 禁止未捕获的 IO/网络异常冒泡 → 必须 try/except 降级
- 禁止在 Service 中持有 widget 引用

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.2。
"""

from __future__ import annotations

import threading
from typing import Callable


class EventEmitter:
    """轻量事件发射器(Signal 替代品)。

    解决 services 层不能 import PySide6 的约束(开发规范 §6.2):
      - .connect(cb): 注册回调
      - .disconnect(cb=None): 断开回调(None 清空所有)
      - .emit(*args): 触发所有回调,异常被吞掉(避免一个失败带垮全部)

    与 Qt Signal 接口一致但纯 Python,可被多线程安全使用(内置 lock)。
    """

    def __init__(self):
        self._callbacks: list[Callable] = []
        self._lock = threading.Lock()

    def connect(self, callback: Callable):
        """注册回调，兼容 Qt Signal.connect 风格。"""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def disconnect(self, callback: Callable = None):
        """断开回调。传入 None 则清空所有。"""
        with self._lock:
            if callback is None:
                self._callbacks.clear()
            elif callback in self._callbacks:
                self._callbacks.remove(callback)

    def emit(self, *args):
        """触发所有回调。"""
        with self._lock:
            callbacks = list(self._callbacks)
        for cb in callbacks:
            try:
                cb(*args)
            except Exception:
                pass