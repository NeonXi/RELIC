"""
core.tokens — Design Token 系统。

提供完整的四层 Token 架构实现：
- color_utils: 颜色变换函数（lighten/darken/opacity/mix）
- resolver:   Token 引用解析引擎（@引用链 + 函数变换）
- manager:    Token 管理器（单例 + 预设加载 + 便捷查询）

依赖关系:
    color_utils ← (无外部依赖)
    resolver    ← color_utils
    manager     ← resolver + PyYAML

使用方式::

    from core.tokens import TokenManager

    tm = TokenManager.get()
    tm.load_preset("cyberpunk")

    color = tm.get("components.button.solid.fill")  → "#FFE600"
    height = tm.space("height.btn_md")               → 36

## AI 硬约束 — 修改本文件前必读
归属层:    [L-Infrastructure] (core/tokens/)
允许依赖:  PyYAML, Python 标准库
禁止依赖:  PySide6 / QtWidgets / QtCore(任何 Qt 命名空间)
           (Token 是数据层,不能引入 UI)
必读规范:  .trae/rules/开发规范.md §6.1

本文件相关红线:
- 禁止 import PySide6 → Token 不能依赖 UI
- 禁止返回 Qt 对象 → 只能返回 str / int / dict
- 禁止在 Token 里持有 widget 引用
- 禁止在 Token 中做 IO(读文件应该 lazy)

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.1。
"""

from core.tokens.color_utils import (
    parse_color,
    to_hex,
    to_rgba,
    lighten,
    darken,
    opacity as opacity_fn,
    mix as mix_fn,
    is_color_value,
)
from core.tokens.resolver import TokenResolver, TokenResolveError
from core.tokens.manager import TokenManager

__all__ = [
    # 颜色函数
    "parse_color",
    "to_hex",
    "to_rgba",
    "lighten",
    "darken",
    "opacity_fn",
    "mix_fn",
    "is_color_value",
    # 解析器
    "TokenResolver",
    "TokenResolveError",
    # 管理器
    "TokenManager",
]
