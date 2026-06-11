"""
[L-Service] 轻量事件发射器

替代 PySide6 Signal，用于 services 层解耦 Qt 依赖。
支持 .connect(callable) / .emit(*args) 模式，与 Qt Signal 接口兼容。
"""

from __future__ import annotations

import threading
from typing import Callable


class EventEmitter:

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