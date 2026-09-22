"""
AppState — 全局状态容器。

管理跨页面共享的状态：主题、语言、偏好等。
每个字段变化都发射信号，支持响应式更新。

设计原则：
- 只存"真正需要跨页面共享"的数据
- 每个字段变化都发射信号
- 不持有任何 UI 引用（纯数据层）

See Also:
    ui-framework-design.md §8.2 AppState — 全局状态容器

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

from typing import Optional

from PySide6.QtCore import QObject, Signal


class AppState(QObject):
    """全局状态单例，管理跨页面共享的状态。

    Attributes:
        theme_changed: 主题切换信号 (preset_name: str)
        accent_color_changed: 强调色变更信号 (QColor)
        locale_changed: 语言切换信号 (locale_code: str)
        animation_enabled_changed: 动画开关信号 (enabled: bool)
        global_notification: 全局通知信号 (level, message)
        data_refresh_requested: 数据刷新请求信号
    """

    # ====== 主题相关 ======
    theme_changed = Signal(str)               # 参数: preset_name
    accent_color_changed = Signal(object)      # 参数: QColor

    # ====== 用户偏好 ======
    locale_changed = Signal(str)              # 参数: locale code
    animation_enabled_changed = Signal(bool)  # 低配机禁用动画

    # ====== 全局通知 ======
    global_notification = Signal(str, str)    # 参数: (level, message)
    data_refresh_requested = Signal()         # 任意页面请求全局数据刷新

    def __init__(self):
        super().__init__()
        self._current_theme: str = "cyberpunk"
        self._locale: str = "zh_CN"
        self._animation_enabled: bool = True

    @property
    def current_theme(self) -> str:
        """当前主题预设名称。"""
        return self._current_theme

    def set_theme(self, name: str) -> None:
        """切换主题预设，发射 theme_changed 信号。"""
        if name != self._current_theme:
            self._current_theme = name
            self.theme_changed.emit(name)

    @property
    def locale(self) -> str:
        """当前语言代码。"""
        return self._locale

    def set_locale(self, locale_code: str) -> None:
        """切换语言，发射 locale_changed 信号。"""
        if locale_code != self._locale:
            self._locale = locale_code
            self.locale_changed.emit(locale_code)

    @property
    def animation_enabled(self) -> bool:
        """动画是否启用（低配机可禁用以提升性能）。"""
        return self._animation_enabled

    def set_animation_enabled(self, enabled: bool) -> None:
        """设置动画开关。"""
        if enabled != self._animation_enabled:
            self._animation_enabled = enabled
            self.animation_enabled_changed.emit(enabled)

    def notify(self, level: str, message: str) -> None:
        """发送全局通知。

        Args:
            level: 通知级别 ("info" | "warning" | "error")
            message: 通知内容
        """
        self.global_notification.emit(level, message)

    def request_refresh(self) -> None:
        """请求全局数据刷新。"""
        self.data_refresh_requested.emit()


# ── 模块级单例实例 ──
app_state = AppState()
