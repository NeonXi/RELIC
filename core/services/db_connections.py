"""
[L-Service] 数据库连接注册表（新版本）

集中管理所有模块缓存的 SQLite 连接，在数据库重建前一键关闭所有连接，
释放文件锁，确保 shutil.copy2 能成功覆盖 warframe.db。

从 data/db_connections.py 迁移而来。

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

from typing import Any, Callable, Optional


class _DBConnectionRegistry:
    """轻量级数据库连接注册表。"""

    def __init__(self):
        self._handlers: dict[str, Callable[[], None]] = {}

    def register(self, name: str, closer: Callable[[], None]):
        """
        注册一个可关闭的连接。

        Args:
            name: 唯一标识符（如 "relic_db"、"search_widget"）
            closer: 无参调用时关闭该连接的函数/方法
        """
        self._handlers[name] = closer

    def unregister(self, name: str):
        """注销一个连接。"""
        self._handlers.pop(name, None)

    def close_all(self):
        """关闭所有已注册的连接。"""
        for name, closer in list(self._handlers.items()):
            try:
                closer()
            except Exception:
                pass
        self._handlers.clear()

    def registered_names(self) -> list[str]:
        """返回所有已注册的名称（用于调试）。"""
        return list(self._handlers.keys())


# 全局单例
db_conn_registry = _DBConnectionRegistry()


def close_all_db_connections():
    """便捷函数：关闭所有已注册的数据库连接。"""
    db_conn_registry.close_all()
