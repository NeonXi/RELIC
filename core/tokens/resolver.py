"""
Token 引用解析器 — Design Token 的核心引擎。

负责将预设文件中的 @引用链和函数变换解析为最终值。
本模块仅依赖 color_utils.py，不依赖 PySide6，可独立运行和测试。

支持的引用语法:
    @path.to.token          → 递归引用另一个 token 的值
    lighten(color, p%)      → 提亮颜色
    darken(color, p%)        → 加深颜色
    opacity(color, a)       → 设置透明度
    mix(a, b, w)            → 混合两色

See Also:
    ui-framework-design.md §2.2 Token 引用解析机制
"""

from __future__ import annotations

import re
from typing import Any

from core.tokens.color_utils import (
    lighten,
    darken,
    opacity as opacity_fn,
    mix as mix_fn,
    parse_color,
    to_hex,
    is_color_value,
)

# ═══════════════════════════════════════════════════
#  异常定义
# ═══════════════════════════════════════════════════

class TokenResolveError(Exception):
    """Token 解析失败时抛出。"""

    def __init__(self, key: str, message: str):
        self.key = key
        self.message = message
        super().__init__(f"Token 解析错误 [{key}]: {message}")


# ═══════════════════════════════════════════════════
#  正则模式（编译一次，全局复用）
# ═══════════════════════════════════════════════════

# 匹配 @引用: @brand.yellow 或 @bg.raised 或 @alias.accent.primary
_REF_PATTERN = re.compile(r"^@([\w.]+)$")

# 匹配函数调用: lighten(#0E0E24, 10%), darken(@bg.base, 5%)
_FUNC_PATTERN = re.compile(
    r"^(lighten|darken|opacity|mix)\((.+)\)$",
    re.IGNORECASE
)

# 匹配函数参数: 从括号内提取各参数
_ARG_PATTERN = re.compile(r",\s*")


# ═══════════════════════════════════════════════════
#  解析器核心
# ═══════════════════════════════════════════════════

class TokenResolver:
    """Design Token 引用解析器。

    将四层嵌套的 YAML 预设数据解析为扁平化的最终值字典。
    支持 @引用链递归解析和颜色函数变换。

    使用方式::

        from yaml import safe_load
        with open("cyberpunk.yaml") as f:
            data = safe_load(f)

        resolver = TokenResolver(data)
        resolver.resolve("components.button.solid.fill")   → "#FFE600"
        resolver.resolve("space.height.btn_md")             → 36

    Attributes:
        MAX_RESOLVE_DEPTH: 最大递归深度，防止循环引用死锁（默认 16）

    See Also:
        ui-framework-design.md §2.2 Token 引用解析机制
        ui-framework-design.md R02 风险：Token 循环引用
    """

    MAX_RESOLVE_DEPTH: int = 16

    def __init__(self, raw_data: dict[str, Any]):
        """初始化解析器。

        Args:
            raw_data: YAML 加载后的完整字典，包含 raw/alias/semantic/components/space 等顶层键。

        Raises:
            TypeError: 如果 raw_data 不是字典
        """
        if not isinstance(raw_data, dict):
            raise TypeError(
                f"TokenResolver 需要 dict 类型输入，收到 {type(raw_data).__name__}"
            )

        self._raw: dict[str, Any] = raw_data
        self._cache: dict[str, Any] = {}
        self._resolving: set[str] = set()  # 正在解析中的 key，用于检测环

    # ─────────────────────────────────────────────
    #  公共 API
    # ─────────────────────────────────────────────

    def resolve(self, key: str) -> Any:
        """递归解析 token 值，处理 @引用 和 函数变换。

        这是唯一的公共入口。所有 token 值都通过此方法获取。

        Args:
            key: 点分路径，如 "brand.yellow"、"components.button.solid.fill"、
                 "space.height.btn_md"

        Returns:
            解析后的最终值。类型取决于 token 定义：
            - 颜色 → hex 字符串（如 "#FFE600"）
            - 尺寸 → int 或 float（如 36、1.5）
            - 列表 → list（如渐变色列表）
            - "transparent" → 字符串 "transparent"

        Raises:
            TokenResolveError: 引用不存在、超过最大深度、函数参数无效等
        """
        if key in self._cache:
            return self._cache[key]

        value = self._get_raw(key)

        result = self._resolve_value(key, value)
        self._cache[key] = result
        return result

    def resolve_color(self, key: str) -> tuple[int, int, int]:
        """便捷方法：解析颜色 token 并返回 (R, G, B) 元组。

        Args:
            key: 颜色 token 路径

        Returns:
            (r, g, b) 元组，每个分量 ∈ [0, 255]

        Raises:
            TokenResolveError: 解析失败或结果不是合法颜色
        """
        value = self.resolve(key)
        if isinstance(value, str) and value.lower() == "transparent":
            return (0, 0, 0)
        return parse_color(value)

    def reload(self, new_data: dict[str, Any]) -> None:
        """重新加载预设数据并清空缓存。

        用于运行时切换主题场景。

        Args:
            new_data: 新的 YAML 数据字典
        """
        if not isinstance(new_data, dict):
            raise TypeError(f"需要 dict 类型，收到 {type(new_data).__name__}")
        self._raw = new_data
        self._cache.clear()
        self._resolving.clear()

    @property
    def resolved_keys(self) -> list[str]:
        """返回已解析的所有 key 列表（用于调试）。"""
        return list(self._cache.keys())

    # ─────────────────────────────────────────────
    #  内部实现
    # ─────────────────────────────────────────────

    def _get_raw(self, key: str) -> Any:
        """从原始数据中按点分路径取值。

        支持短路径回退：若 ``brand.yellow``（≤2 段）在顶层找不到，
        会自动尝试 ``raw.brand.yellow``、``alias.brand.yellow`` 等前缀。
        深层路径（≥3 段）不做回退，直接精确查找。
        """
        # 1) 先尝试精确匹配
        parts = key.split(".")
        current: Any = self._raw

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                current = None
                break

        if current is not None:
            return current

        # 2) 精确匹配失败 → 仅对短路径（≤2 段）尝试命名空间回退
        if len(parts) <= 2 and isinstance(self._raw, dict):
            for prefix in self._raw:
                if prefix.startswith("_"):
                    continue  # 跳过 _meta 等内部键
                candidate = f"{prefix}.{key}"
                try:
                    return self._get_raw_exact(candidate)
                except TokenResolveError:
                    continue

        # 3) 全部失败 → 报错
        if isinstance(self._raw, dict):
            available = str(list(self._raw.keys()))
        else:
            available = f"<{type(self._raw).__name__}>"
        raise TokenResolveError(
            key, f"路径 '{key}' 未找到。顶层可用键: " + available
        )

    def _get_raw_exact(self, key: str) -> Any:
        """精确路径查找，不做回退（内部使用）。"""
        parts = key.split(".")
        current: Any = self._raw

        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                if isinstance(current, dict):
                    available = str(list(current.keys()))
                else:
                    available = f"<{type(current).__name__}>"
                raise TokenResolveError(
                    key, f"路径 '{key}' 在 '{part}' 处断裂，可用键: " + available
                )

        return current

    def _resolve_value(self, key: str, value: Any, depth: int = 0) -> Any:
        """递归解析单个值。

        Args:
            key: 当前 token 的完整路径（用于缓存和报错）
            value: 待解析的原始值
            depth: 当前递归深度（用于防止无限递归）
        """
        # 深度保护
        if depth > self.MAX_RESOLVE_DEPTH:
            raise TokenResolveError(
                key,
                f"超过最大解析深度 ({self.MAX_RESOLVE_DEPTH})，可能存在循环引用。"
                f"当前解析栈: {sorted(self._resolving)}"
            )

        # 环检测
        if key in self._resolving:
            raise TokenResolveError(
                key,
                f"检测到循环引用！'{key}' 正在被解析中。"
                f"当前解析栈: {sorted(self._resolving)}"
            )

        # None / 布尔 / 数值：直接返回
        if value is None or isinstance(value, (bool, int, float)):
            return value

        # 字典：递归解析每个值
        if isinstance(value, dict):
            self._resolving.add(key)
            try:
                return {
                    k: self._resolve_value(f"{key}.{k}", v, depth + 1)
                    for k, v in value.items()
                }
            finally:
                self._resolving.discard(key)

        # 列表：递归解析每个元素
        if isinstance(value, list):
            return [
                self._resolve_item(item, depth + 1)
                for item in value
            ]

        # 字符串：检查是否是引用或函数
        if isinstance(value, str):
            value = value.strip()

            # 特殊值：透明
            if value.lower() == "transparent":
                return "transparent"

            # @引用
            ref_match = _REF_PATTERN.match(value)
            if ref_match:
                ref_key = ref_match.group(1)
                self._resolving.add(key)
                try:
                    result = self.resolve(ref_key)
                finally:
                    self._resolving.discard(key)
                return result

            # 函数变换
            func_match = _FUNC_PATTERN.match(value)
            if func_match:
                func_name = func_match.group(1).lower()
                args_str = func_match.group(2).strip()
                return self._apply_function(func_name, args_str, key, depth)

            # 普通 hex 颜色字符串：验证后直接返回
            if is_color_value(value):
                return value.upper()  # 统一为大写

            # 其他字符串原样返回（如 "赛博朋克 2077"）
            return value

        # 未知类型原样返回
        return value

    def _resolve_item(self, item: Any, depth: int) -> Any:
        """解析列表中的单个元素。"""
        if isinstance(item, str):
            item = item.strip()

            if item.startswith("@"):
                ref_key = item[1:]
                return self.resolve(ref_key)

            func_match = _FUNC_PATTERN.match(item)
            if func_match:
                func_name = func_match.group(1).lower()
                args_str = func_match.group(2).strip()
                return self._apply_function(func_name, args_str, f"<list-item>", depth)

            if is_color_value(item):
                return item.upper()

            return item

        if isinstance(item, (dict, list)):
            return self._resolve_value("<list-item>", item, depth)

        return item

    def _apply_function(
        self,
        func_name: str,
        args_str: str,
        context_key: str,
        depth: int,
    ) -> Any:
        """应用颜色变换函数。

        Args:
            func_name: 函数名（lighten/darken/opacity/mix）
            args_str: 括号内的参数字符串
            context_key: 当前 token 路径（用于报错）
            depth: 当前深度

        Returns:
            函数执行结果
        """
        # 解析参数（处理可能的嵌套引用）
        raw_args = _ARG_PATTERN.split(args_str)
        resolved_args = []
        for arg in raw_args:
            arg = arg.strip()
            if arg.startswith("@"):
                resolved_args.append(self.resolve(arg[1:]))
            elif is_color_value(arg):
                resolved_args.append(arg.upper())
            else:
                resolved_args.append(arg)

        # 分发到对应函数
        try:
            if func_name == "lighten":
                color = resolved_args[0]
                percent = self._parse_percent(resolved_args[1])
                return lighten(color, percent)

            elif func_name == "darken":
                color = resolved_args[0]
                percent = self._parse_percent(resolved_args[1])
                return darken(color, percent)

            elif func_name == "opacity":
                color = resolved_args[0]
                # opacity 的 alpha 参数: "50%" → 0.5, "0.5" → 0.5
                raw_alpha = resolved_args[1]
                if isinstance(raw_alpha, str) and raw_alpha.endswith("%"):
                    alpha = self._parse_percent(raw_alpha) / 100.0
                else:
                    alpha = float(raw_alpha)
                return opacity_fn(color, alpha)

            elif func_name == "mix":
                color_a = resolved_args[0]
                color_b = resolved_args[1]
                raw_weight = resolved_args[2] if len(resolved_args) > 2 else "50%"
                if isinstance(raw_weight, str) and raw_weight.endswith("%"):
                    weight = self._parse_percent(raw_weight) / 100.0
                else:
                    weight = float(raw_weight)
                return mix_fn(color_a, color_b, weight)

            else:
                raise TokenResolveError(
                    context_key, f"未知函数: {func_name}，支持: lighten/darken/opacity/mix"
                )

        except (ValueError, IndexError) as e:
            raise TokenResolveError(
                context_key, f"函数 {func_name}({args_str}) 参数错误: {e}"
            ) from e

    @staticmethod
    def _parse_percent(value: str) -> float:
        """将百分比字符串转为浮点数。

        支持格式: "10%", "10.5%", "10"

        Args:
            value: 百分比字符串或数字

        Returns:
            浮点数百分比值（如 10.5 表示 10.5%）
        """
        s = str(value).strip().rstrip("%")
        return float(s)
