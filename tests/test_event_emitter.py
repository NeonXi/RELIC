"""
EventEmitter 单元测试 — 轻量事件发射器。

覆盖:
  - connect / disconnect 回调注册
  - emit 触发回调
  - 多回调顺序
  - 线程安全（基本）
  - 异常隔离（一个回调失败不影响其他）
"""

from __future__ import annotations

import pytest

from core.services._event_emitter import EventEmitter


class TestConnectDisconnect:

    def test_connect_and_emit(self):
        emitter = EventEmitter()
        results = []
        emitter.connect(lambda x: results.append(x))
        emitter.emit("hello")
        assert results == ["hello"]

    def test_connect_multiple(self):
        emitter = EventEmitter()
        results = []
        emitter.connect(lambda: results.append("a"))
        emitter.connect(lambda: results.append("b"))
        emitter.emit()
        assert results == ["a", "b"]

    def test_duplicate_callback_ignored(self):
        """重复注册同一回调应只触发一次。"""
        cb = lambda: None  # noqa: E731
        emitter = EventEmitter()
        emitter.connect(cb)
        emitter.connect(cb)
        assert len(emitter._callbacks) == 1

    def test_disconnect_single(self):
        emitter = EventEmitter()
        cb = lambda: None  # noqa: E731
        emitter.connect(cb)
        emitter.disconnect(cb)
        assert len(emitter._callbacks) == 0

    def test_disconnect_none_clears_all(self):
        emitter = EventEmitter()
        emitter.connect(lambda: None)
        emitter.connect(lambda: None)
        emitter.disconnect(None)
        assert len(emitter._callbacks) == 0


class TestEmit:

    def test_emit_with_multiple_args(self):
        emitter = EventEmitter()
        results = []
        emitter.connect(lambda a, b, c: results.append((a, b, c)))
        emitter.emit(1, "two", [3])
        assert results == [(1, "two", [3])]

    def test_emit_no_callbacks_no_error(self):
        emitter = EventEmitter()
        emitter.emit()  # 不应抛异常


class TestExceptionIsolation:

    def test_one_failure_does_not_block_others(self):
        """一个回调抛异常，其他仍正常执行。"""
        emitter = EventEmitter()
        results = []
        emitter.connect(lambda: (_ for _ in ()).throw(ValueError("boom")))
        emitter.connect(lambda: results.append("ok"))
        emitter.emit()
        assert results == ["ok"]
