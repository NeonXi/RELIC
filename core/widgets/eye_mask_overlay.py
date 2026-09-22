"""
[L4] core.widgets.eye_mask_overlay — EyeMaskOverlay 单屏护眼遮罩 + Manager

归属层:    [L4] (core/widgets/)
允许依赖:  PySide6, ctypes(用于 Win32 透明窗口)
禁止依赖:  core.services/*, core.pages/*, 任何 IO/JSON/网络

职责:
  - EyeMaskOverlay:  覆盖单个指定屏幕的全屏黑色半透明遮罩
  - EyeMaskManager:  统一管理多屏遮罩(按 screen 集合启停),对外提供单实例 API

特性:
  - 每屏一个独立窗口(每屏一个 EyeMaskOverlay 实例)
  - 鼠标完全穿透(WA_TransparentForMouseEvents + WS_EX_TRANSPARENT)
  - 纯黑色半透明遮罩(可调不透明度)
  - 不抢焦点、不拦截点击

迁移记录:
  2026-06-17  从 core/pages/eye_mask_page.py 内部类 EyeMaskOverlay 迁出
  2026-07-20  重构:从"全屏一刀切"改为"按 screen 独立窗口",
              新增 EyeMaskManager 统一管理多屏

本文件相关红线:
- ✗ 禁止 setStyleSheet(f-string) → 用自绘
- ✗ 禁止读写 JSON / 调 service / 任何 IO
- ✗ 禁止硬编码颜色 → 黑色遮罩是功能色(护眼)
"""

# ── 标准库 ──
from __future__ import annotations
import ctypes
from ctypes import wintypes  # noqa: F401  # 显式依赖

# ── PySide6 ──
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QPainter, QColor, QPaintEvent, QGuiApplication


# ═══════════════════════════════════════
#  Win32 透明窗口常量
# ═══════════════════════════════════════
# 这些常量用于把 Qt 窗口设置成"鼠标穿透 + 不抢焦点"的状态。
# PySide6 的 setAttribute(WA_TransparentForMouseEvents) 在某些场景
# 下不够彻底,需要走 Win32 SetWindowLongW 加 WS_EX_TRANSPARENT 才能
# 真正实现"鼠标看到下面的窗口"。

_WS_EX_TRANSPARENT = 0x00000020  # 鼠标穿透
_WS_EX_LAYERED = 0x00080000      # 分层窗口(支持 alpha)
_WS_EX_TOOLWINDOW = 0x00000080   # 工具窗口(不在任务栏显示)
_WS_EX_NOACTIVATE = 0x08000000   # 永不抢焦点
_GWL_EXSTYLE = -20               # SetWindowLongW 的 index:扩展样式

# ── 视觉常量 ──
# 纯黑色 + 默认 25% 不透明度(可被 set_opacity 调整)
DEFAULT_COLOR = (0, 0, 0)
DEFAULT_OPACITY = 25


class EyeMaskOverlay(QWidget):
    """单屏护眼遮罩窗口。

    覆盖 ``QGuiApplication.screens()[screen_index]`` 这一个屏幕。

    特性:
      - 覆盖单个指定屏幕(由 screen_index 决定)
      - 鼠标完全穿透,不抢焦点、不拦截点击
      - 纯黑色半透明遮罩
      - 可调不透明度(0-100%)
      - 切换显示用 show_mask() / hide_mask() / toggle()

    平台差异:
      - Windows: 用 Win32 SetWindowLongW 进一步确保 WS_EX_TRANSPARENT
        (Qt 的 WA_TransparentForMouseEvents 在某些焦点场景不彻底)
      - 其它平台: 退化到只用 Qt 的 WA 属性

    使用方式::
        overlay = EyeMaskOverlay(screen_index=0)
        overlay.set_opacity(40)  # 40% 黑色
        overlay.show_mask()
        # ... 用户不需要操作任何东西 ...
        overlay.hide_mask()

    参数:
      screen_index: QGuiApplication.screens() 中的索引
      parent:      Qt 父对象(一般 None,顶层窗口)
    """

    def __init__(self, screen_index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._screen_index = screen_index
        # ── 初始颜色 = 纯黑 + DEFAULT_OPACITY% ──
        self._color = QColor(*DEFAULT_COLOR, int(DEFAULT_OPACITY * 255 / 100))
        self._visible = False
        self._setup_window()

    # ── 内部:窗口设置 ──

    def _setup_window(self) -> None:
        """设置窗口标志 + Win32 透明属性。"""
        # ── Qt 层:无边框 + 置顶 + 工具窗口 + X11 绕过 WM ──
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.X11BypassWindowManagerHint
        )
        # ── Qt 层:透明背景 + 鼠标穿透 + 不抢焦点 ──
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # ── Win32 层:再加固一次透明属性(某些场景 Qt 属性不够) ──
        self._apply_win32_transparent()
        # ── 定位到目标屏幕 ──
        self._cover_target_screen()

    def _apply_win32_transparent(self) -> None:
        """通过 Win32 SetWindowLongW 注入 WS_EX_TRANSPARENT 等扩展样式。

        失败时静默(非 Windows 或权限不足)— Qt 层的属性已能保证基本效果。
        """
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            ex_style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, _GWL_EXSTYLE,
                ex_style | _WS_EX_TRANSPARENT | _WS_EX_LAYERED
                | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE,
            )
        except Exception:
            # 非 Windows / 无 ctypes:用 Qt 属性已能基本工作
            pass

    def showEvent(self, event) -> None:
        """窗口显示时重新应用 Win32 透明属性(防止某些场景下样式被重置)。"""
        super().showEvent(event)
        self._apply_win32_transparent()

    def _cover_target_screen(self) -> None:
        """让窗口几何对齐到目标屏幕(按 screen_index 查找,失效则退化到主屏)。"""
        screens = QGuiApplication.screens()
        if not screens:
            # 极端兜底:无屏幕信息时用 1920x1080
            self.setGeometry(0, 0, 1920, 1080)
            return
        if 0 <= self._screen_index < len(screens):
            self.setGeometry(screens[self._screen_index].geometry())
        else:
            # 索引失效(热插拔后索引越界),退化到主屏
            self.setGeometry(screens[0].geometry())

    # ── 公开 API ──

    def set_opacity(self, pct: int) -> None:
        """设置不透明度百分比(0-100)。"""
        alpha = max(0, min(255, int(pct * 255 / 100)))
        self._color.setAlpha(alpha)
        if self._visible:
            self.update()

    def get_opacity_pct(self) -> int:
        """获取当前不透明度百分比。"""
        return int(self._color.alpha() * 100 / 255)

    def is_visible(self) -> bool:
        """当前是否显示中。"""
        return self._visible

    def show_mask(self) -> None:
        """显示护眼遮罩(单屏)。"""
        if not self._visible:
            self._visible = True
            self._cover_target_screen()
            self.show()
            self.update()

    def hide_mask(self) -> None:
        """隐藏护眼遮罩。"""
        if self._visible:
            self._visible = False
            self.hide()

    def toggle(self) -> None:
        """切换显隐。"""
        if self._visible:
            self.hide_mask()
        else:
            self.show_mask()

    # ── 绘制 ──

    def paintEvent(self, event: QPaintEvent) -> None:
        """绘制纯色矩形遮罩。

        顺序(规范 §5.3): QPainter → 自绘 fillRect → (QWidget 无默认绘制,无需 super)
        """
        if not self._visible:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self._color)


# ═══════════════════════════════════════
#  EyeMaskManager — 多屏遮罩统一管理
# ═══════════════════════════════════════

class EyeMaskManager(QObject):
    """多屏护眼遮罩统一管理器。

    维护 N 个 EyeMaskOverlay(N = ``QGuiApplication.screens()`` 当前数量),
    按 ``enabled_screens: set[int]`` 决定哪些屏参与"开/关"动作。

    对外 API(与原 EyeMaskOverlay 完全一致,便于 Page 切换时零改动):
      - set_opacity(pct)
      - show_mask() / hide_mask() / toggle() / is_visible()
      - set_enabled_screens(indices: list[int])

    信号:
      visibility_changed(visible: bool)  任何 show/hide/toggle 之后发射
      enabled_screens_changed(indices: list[int])  set_enabled_screens 之后发射

    设计要点:
      - Manager 一开始就为每屏创建一个 overlay(懒构造,on_enter 触发)
      - 启用集合变更:仅在原集合为空且新集合非空、或反之时真正 show/hide;
        仅是集合内成员变化时,重新同步各 overlay 的可见性即可。
      - 切换屏幕时(opacity 调整 / enabled 调整)对所有 enabled 的 overlay 都生效
    """

    visibility_changed = Signal(bool)
    enabled_screens_changed = Signal(list)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # screen_index -> EyeMaskOverlay
        self._overlays: dict[int, EyeMaskOverlay] = {}
        # 当前启用的屏幕索引集合
        self._enabled: set[int] = set()
        # 当前不透明度百分比(全屏共享)
        self._opacity_pct: int = DEFAULT_OPACITY
        # 整体可见性(只要有任何一屏在显示就视为 True)
        self._any_visible: bool = False

    # ── 屏幕集合管理 ──

    def refresh_screens(self) -> None:
        """按当前 ``QGuiApplication.screens()`` 同步内部 overlay 池。

        - 新出现的屏幕:  按当前 opacity 创建一个 overlay
        - 消失的屏幕:    从池中移除(并 hide)
        - 已存在的屏幕:  保留(状态不变)

        注意: 此方法不会主动改变 ``_enabled``;调用方负责在 ``on_enter`` 时
        重新设置 enabled 集合,以响应用户的最新勾选。
        """
        screens = QGuiApplication.screens()
        current_indices = set(range(len(screens)))

        # 移除已不存在的屏幕
        for idx in list(self._overlays.keys()):
            if idx not in current_indices:
                old = self._overlays.pop(idx)
                old.hide_mask()
                old.deleteLater()
                self._enabled.discard(idx)

        # 为新屏幕创建 overlay
        for idx in current_indices:
            if idx not in self._overlays:
                ov = EyeMaskOverlay(screen_index=idx)
                ov.set_opacity(self._opacity_pct)
                self._overlays[idx] = ov

    def set_enabled_screens(self, indices: list[int]) -> None:
        """设置启用的屏幕集合(替换式)。

        - 移除的: hide_mask
        - 新增的: 如果当前整体在显示中,自动 show_mask
        - 不存在的 screen_index 自动忽略
        """
        new_set = set(indices) & set(self._overlays.keys())
        old_set = set(self._enabled)

        # 1. 退出不再启用的屏幕
        for idx in old_set - new_set:
            ov = self._overlays.get(idx)
            if ov is not None:
                ov.hide_mask()

        # 2. 新启用的屏幕:若整体可见,立即 show
        for idx in new_set - old_set:
            ov = self._overlays.get(idx)
            if ov is not None and self._any_visible:
                ov.show_mask()

        self._enabled = new_set
        self.enabled_screens_changed.emit(sorted(new_set))

    def get_enabled_screens(self) -> list[int]:
        """获取当前启用的屏幕索引列表(升序)。"""
        return sorted(self._enabled)

    def available_screen_indices(self) -> list[int]:
        """获取所有可用屏幕索引(按当前 screens() 顺序)。"""
        return list(self._overlays.keys())

    # ── 整体显隐控制 ──

    def show_mask(self) -> None:
        """在所有启用的屏幕上显示遮罩(未启用的不显示)。"""
        if not self._enabled:
            return
        for idx in self._enabled:
            ov = self._overlays.get(idx)
            if ov is not None:
                ov.show_mask()
        if not self._any_visible:
            self._any_visible = True
            self.visibility_changed.emit(True)

    def hide_mask(self) -> None:
        """隐藏所有屏幕上的遮罩。"""
        for ov in self._overlays.values():
            ov.hide_mask()
        if self._any_visible:
            self._any_visible = False
            self.visibility_changed.emit(False)

    def toggle(self) -> None:
        """切换整体显隐(整体可见 -> 全隐藏,否则 -> 在启用的屏上全显示)。"""
        if self._any_visible:
            self.hide_mask()
        else:
            self.show_mask()

    def is_visible(self) -> bool:
        """整体是否可见。"""
        return self._any_visible

    # ── 不透明度 ──

    def set_opacity(self, pct: int) -> None:
        """设置不透明度(对所有 overlay 生效,无论是否启用)。"""
        self._opacity_pct = pct
        for ov in self._overlays.values():
            ov.set_opacity(pct)

    def get_opacity_pct(self) -> int:
        """获取当前不透明度百分比。"""
        return self._opacity_pct

    # ── 资源 ──

    def shutdown(self) -> None:
        """应用退出时调用:隐藏并释放所有 overlay。"""
        for ov in self._overlays.values():
            ov.hide_mask()
            ov.deleteLater()
        self._overlays.clear()
        self._enabled.clear()
        self._any_visible = False
