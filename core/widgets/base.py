"""
Cyber Widget 基础设施 — CyberWidgetMixin。

赛博风格 UI 组件的混入基类，提供：
- Token 访问接口（token / space）
- 交互状态机（normal/hover/pressed/focused/disabled/selected）
- 切角路径生成（带缓存）
- 自绘背景方法（切角 + 外发光）

设计原则（Mixin 模式）:
    本类不继承 QWidget，不能单独实例化。
    使用时通过多重继承与 Qt 原生控件组合::

        class CyberButton(CyberWidgetMixin, QPushButton):
            def __init__(self, text="", parent=None):
                QPushButton.__init__(self, text, parent)  # 显式调用目标基类
                # ... CyberWidgetMixin 无需 __init__

使用方式::

    class MyPanel(CyberWidgetMixin, QFrame):
        def paintEvent(self, event):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._draw_chamfered_bg(painter)
            # QFrame 无自身绘制内容，无需 super()

See Also:
    ui-framework-design.md §5.2 Cyber Widget 框架 — Mixin 设计模式
    ui-framework-design.md 附录 B: 多重继承注意事项
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget
    from PySide6.QtGui import QPainter, QColor
    from PySide6.QtCore import QPointF, QRectF, Qt


class CyberWidgetMixin:
    """赛博风格混入类 — 提供切角绘制、状态机、Token 访问能力。

    不继承 QWidget，不能单独实例化。必须与一个 QWidget 子类通过多重继承组合使用。

    Attributes:
        _state: 当前交互状态，可选值见 VALID_STATES
        _path_cache: 切角路径缓存（避免 resize 时重复计算）
        _cache_rect_size: 缓存对应的矩形尺寸
    """

    # ── 合法状态列表 ──
    VALID_STATES = {"normal", "hover", "pressed", "focused", "disabled", "selected"}

    # ── 类级别属性（Mixin 共享）──
    _state: str = "normal"
    _path_cache: Optional[object] = None  # QPolygonF 实例
    _cache_rect_size: Optional[tuple] = None

    # ══════════════════════════════════════════════
    #  Token 访问接口
    # ══════════════════════════════════════════════

    def token(self, key: str) -> str:
        """获取颜色/样式 token 的字符串值。

        这是组件内部获取 token 的主要方式。
        返回字符串类型（hex 颜色或原始值），由调用方决定如何使用。

        Args:
            key: 点分路径，如 "bg.raised"、"accent.primary"、
                 "components.button.solid.fill"

        Returns:
            解析后的字符串值（如 "#0E0E24"、"transparent"）

        Note:
            如果需要 QColor 对象，请使用 token_color() 方法。
        """
        from core.tokens.manager import TokenManager
        tm = TokenManager.instance()
        result = tm.get(key)
        if isinstance(result, str):
            return result
        return str(result)

    def token_color(self, key: str) -> "QColor":
        """获取颜色 token 并返回 QColor 对象。

        便捷方法，省去手动 parse 的步骤。

        Args:
            key: 颜色 token 路径

        Returns:
            QColor 实例
        """
        from PySide6.QtGui import QColor
        from core.tokens.manager import TokenManager

        value = TokenManager.instance().get(key)

        if isinstance(value, str):
            if value.lower() == "transparent":
                return QColor(0, 0, 0, 0)
            return QColor(value)

        if isinstance(value, (int, float)):
            return QColor(int(value), int(value), int(value))

        return QColor(value)

    def space(self, key: str, default: int = 0) -> int:
        """获取空间尺寸 token 的整数值。

        Args:
            key: Space token 路径，如 "height.btn_md"、"spacing.lg"、"corner.md"
            default: 找不到时的默认值

        Returns:
            尺寸整数值（像素），默认 default
        """
        from core.tokens.manager import TokenManager
        return TokenManager.instance().space(key, default=default)

    def copy(self, key: str, default: str = "", **kwargs) -> str:
        """获取文案 token 字符串，支持模板变量替换。

        Args:
            key: 文案 token 路径（不含 "copy." 前缀）
            default: key 不存在时的默认返回值
            **kwargs: 模板变量

        Returns:
            解析后的文案字符串
        """
        from core.tokens.manager import TokenManager
        return TokenManager.instance().copy(key, default, **kwargs)

    # ══════════════════════════════════════════════
    #  状态机
    # ══════════════════════════════════════════════

    @property
    def state(self) -> str:
        """当前交互状态（只读）。"""
        return self._state

    def _set_state(self, new_state: str) -> None:
        """切换交互状态并触发重绘。

        Args:
            new_state: 目标状态，必须是 VALID_STATES 之一
        """
        if new_state not in self.VALID_STATES:
            raise ValueError(
                f"无效的状态 '{new_state}'，合法值: {self.VALID_STATES}"
            )
        old = self._state
        if old != new_state:
            self._state = new_state
            # 触发重绘（依赖 self 是 QWidget 子类的隐式契约）
            widget_self: "QWidget" = self  # type: ignore[assignment]
            widget_self.update()

    # ══════════════════════════════════════════════
    #  标准事件处理（子类应调用或覆盖）
    # ══════════════════════════════════════════════

    def cyber_enter_event(self, event) -> None:
        """鼠标进入 → hover 态。在 enterEvent 中调用。"""
        if self._state != "disabled":
            self._set_state("hover")

    def cyber_leave_event(self, event) -> None:
        """鼠标离开 → normal 态。在 leaveEvent 中调用。"""
        if self._state not in ("disabled", "pressed"):
            self._set_state("normal")

    def cyber_mouse_press_event(self, event) -> None:
        """鼠标按下 → pressed 态。在 mousePressEvent 中调用。"""
        from PySide6.QtCore import Qt
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._state != "disabled"
        ):
            self._set_state("pressed")

    def cyber_mouse_release_event(self, event) -> None:
        """鼠标释放 → hover 或 normal 态。在 mouseReleaseEvent 中调用。"""
        from PySide6.QtCore import Qt
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._state == "pressed"
        ):
            self._set_state("hover")

    def cyber_focus_in_event(self, event) -> None:
        """获得焦点 → focused 态。在 focusInEvent 中调用。"""
        self._set_state("focused")

    def cyber_focus_out_event(self, event) -> None:
        """失去焦点 → normal 态。在 focusOutEvent 中调用。"""
        self._set_state("normal")

    # ══════════════════════════════════════════════
    #  切角路径生成（带缓存）
    # ══════════════════════════════════════════════

    def _chamfered_path(
        self,
        rect: "QRectF",
        corner_size: float,
        mode: str = "all",
    ) -> "object":
        """生成切角矩形路径。

        支持两种切角模式：
        - ``"all"``   : 四角对称切角（传统赛博风）
        - ``"br"``    : 仅右下角切角（赛博朋克标志性风格）

        结果缓存到实例属性中，以 (width, height, mode) 为键。
        当窗口 size 不变时直接返回缓存，避免重复计算。

        Args:
            rect: 控件矩形区域
            corner_size: 切角大小（像素），从每个角切去的直角边长
            mode: 切角模式，"all" 或 "br"

        Returns:
            QPainterPath 实例
        """
        from PySide6.QtGui import QPainterPath
        from PySide6.QtCore import QPointF

        size = (rect.width(), rect.height(), mode)

        # 缓存命中
        if (
            hasattr(self, "_path_cache")
            and self._path_cache is not None
            and getattr(self, "_cache_rect_size", None) == size
        ):
            return self._path_cache  # type: ignore[return-value]

        c = corner_size
        path = QPainterPath()

        if mode == "br":
            # ── 赛博朋克风格：仅右下角切角 ──
            path.moveTo(QPointF(rect.left(), rect.top()))
            path.lineTo(QPointF(rect.right(), rect.top()))
            path.lineTo(QPointF(rect.right(), rect.bottom() - c))
            path.lineTo(QPointF(rect.right() - c, rect.bottom()))
            path.lineTo(QPointF(rect.left(), rect.bottom()))
            path.closeSubpath()
        else:
            # ── 四角对称切角（默认）──
            path.moveTo(QPointF(rect.left() + c, rect.top()))
            path.lineTo(QPointF(rect.right() - c, rect.top()))
            path.lineTo(QPointF(rect.right(), rect.top() + c))
            path.lineTo(QPointF(rect.right(), rect.bottom() - c))
            path.lineTo(QPointF(rect.right() - c, rect.bottom()))
            path.lineTo(QPointF(rect.left() + c, rect.bottom()))
            path.lineTo(QPointF(rect.left(), rect.bottom() - c))
            path.lineTo(QPointF(rect.left(), rect.top() + c))
            path.closeSubpath()

        self._path_cache = path
        self._cache_rect_size = size
        return path

    def _invalidate_path_cache(self) -> None:
        """使切角路径缓存失效（在 resizeEvent 中调用）。"""
        self._path_cache = None
        self._cache_rect_size = None

    # ══════════════════════════════════════════════
    #  自绘：切角背景 + 外发光
    # ══════════════════════════════════════════════

    def _draw_chamfered_bg(
        self,
        painter: "QPainter",
        corner_key: str = "corner.md",
        bg_key: str | None = None,
        glow_key: str | None = None,
        glow_opacity_map: dict[str, float] | None = None,
        mode: str = "all",
    ) -> None:
        """绘制切角背景 + 可选的外发光效果。

        在 paintEvent 中最先调用此方法，然后再调 super().paintEvent()。

        Args:
            painter: 已初始化的 QPainter（需开启 Antialiasing）
            corner_key: 切角大小的 space token 键名（默认 "corner.md"）
            bg_key: 背景颜色的 token 键名。
                    默认为 None，表示自动按 state 查找 semantic.state.{state}.bg
            glow_key: 外发光颜色的 token 键名。
                      默认为 None，表示使用 accent.secondary
            glow_opacity_map: 各状态的发光透明度映射。
                               如 {"hover": 0.15, "focused": 0.2}
                               未列出的状态不画发光
            mode: 切角模式，"all"(四角对称) 或 "br"(仅右下角，赛博朋克风格)
        """
        from PySide6.QtGui import QColor, QPen, QBrush
        from PySide6.QtCore import Qt

        # 取参数
        corner = self.space(corner_key)

        # 背景色
        if bg_key:
            bg_color = self.token_color(bg_key)
        else:
            bg_color = self.token_color("alias.bg.raised")

        # 生成切角路径并填充
        path = self._chamfered_path(self.rect(), corner, mode=mode)
        painter.fillPath(path, QBrush(bg_color))

        # 外发光（仅指定状态启用）
        if glow_opacity_map and self._state in glow_opacity_map:
            if glow_key:
                glow_color = self.token_color(glow_key)
            else:
                glow_color = self.token_color("alias.accent.secondary")

            alpha = glow_opacity_map[self._state]
            glow_color.setAlphaF(alpha)
            painter.setPen(QPen(glow_color, 1))
            painter.drawPath(path)

    def _draw_nav_tab(
        self,
        painter: "QPainter",
        text: str = "",
        selected: bool = False,
        hover: bool = False,
    ) -> None:
        """绘制赛博朋克风格导航标签。

        结构：左侧装饰竖条 + 间隙 + 主内容区（右下角切角）。
        参考：Cyberpunk 2077 UI 导航标签样式。

        Args:
            painter: 已初始化的 QPainter（需开启 Antialiasing）
            text: 标签文字（如 "历程"、"养成"）
            selected: 是否为选中态（选中时左侧竖条加宽高亮 + 反色虚影）
            hover: 是否为悬停态（hover 时背景提亮）
        """
        from PySide6.QtGui import QColor, QPen, QBrush, QPainterPath, QLinearGradient
        from PySide6.QtCore import QPointF, QRectF, Qt
        from core.tokens.manager import TokenManager

        tm = TokenManager.instance()

        # ── Token 参数 ──
        bar_width = tm.space("nav.bar_width", 4)
        bar_width_selected = tm.space("nav.bar_width_selected", 10)
        bar_gap = tm.space("nav.bar_gap", 4)          # 竖条与主内容区间隙
        corner_br = tm.space("nav.corner_br", 6)
        inner_pad = tm.space("nav.inner_pad", 16)

        border_color_str = tm.get("nav.border", "#00FFFF")
        bg_color_str = tm.get("nav.bg", "#0A1628")
        bar_color_str = tm.get("nav.bar", "#00FFFF")
        bar_selected_color_str = tm.get("nav.bar_selected", "#00FFFF")
        text_color_str = tm.get("nav.text", "#E8ECFF")
        # 选中态反色虚影参数
        glow_enabled = bool(tm.get("nav.glow.enabled", True))
        glow_spread = int(tm.space("nav.glow.spread", 6))
        glow_alpha = float(tm.get("nav.glow.alpha", 0.25))

        border_color = QColor(border_color_str)
        bg_color = QColor(bg_color_str)
        bar_color = QColor(bar_color_str)
        bar_sel_color = QColor(bar_selected_color_str)
        text_color = QColor(text_color_str)

        r = QRectF(self.rect())
        # 装饰线宽度固定不变（选中态只改变颜色/透明度）
        current_bar = bar_width

        # 预先计算装饰线矩形（虚影和绘制都需要）
        bar_rect = QRectF(r.left(), r.top(), current_bar, r.height())

        # ── 0. 选中态反色虚影（分别沿竖条和主内容区轮廓绘制，不覆盖间隙）──
        if selected and glow_enabled:
            # 预先计算 main_path 的位置
            _main_left = r.left() + current_bar + bar_gap
            _main_rect = QRectF(_main_left, r.top(), r.width() - current_bar - bar_gap, r.height())
            _c = corner_br
            _pre_main_path = QPainterPath()
            _pre_main_path.moveTo(QPointF(_main_rect.left(), _main_rect.top()))
            _pre_main_path.lineTo(QPointF(_main_rect.right(), _main_rect.top()))
            _pre_main_path.lineTo(QPointF(_main_rect.right(), _main_rect.bottom() - _c))
            _pre_main_path.lineTo(QPointF(_main_rect.right() - _c, _main_rect.bottom()))
            _pre_main_path.lineTo(QPointF(_main_rect.left(), _main_rect.bottom()))
            _pre_main_path.closeSubpath()

            ghost_color = QColor(border_color)
            ghost_color.setAlphaF(glow_alpha)

            # 竖条虚影（仅向左/上/下扩展，不向右侵入间隙）
            bar_ghost = bar_rect.adjusted(-glow_spread, -glow_spread, 0, glow_spread)
            painter.fillRect(bar_ghost, QBrush(ghost_color))

            # 主内容区虚影（仅向右/上/下扩展，不向左侵入间隙）
            gc = corner_br + glow_spread * 0.5
            main_ghost = _main_rect.adjusted(0, -glow_spread, glow_spread, glow_spread)
            mgp = QPainterPath()
            mgp.moveTo(QPointF(main_ghost.left(), main_ghost.top()))
            mgp.lineTo(QPointF(main_ghost.right(), main_ghost.top()))
            mgp.lineTo(QPointF(main_ghost.right(), main_ghost.bottom() - gc))
            mgp.lineTo(QPointF(main_ghost.right() - gc, main_ghost.bottom()))
            mgp.lineTo(QPointF(main_ghost.left(), main_ghost.bottom()))
            mgp.closeSubpath()
            painter.fillPath(mgp, QBrush(ghost_color))

        # ── 1. 左侧装饰竖条（矩形，无切角）──
        bar_path = QPainterPath()
        bar_path.addRect(bar_rect)

        # 竖条填充色
        if selected:
            bar_fill = bar_sel_color
        elif hover:
            bar_fill = QColor(bar_color)
            bar_fill.setAlphaF(0.75)
        else:
            bar_fill = QColor(bar_color)
            bar_fill.setAlphaF(0.5)
        painter.fillPath(bar_path, QBrush(bar_fill))

        # ── 2. 主内容区背景（右下角切角，与竖条之间有间隙）──
        main_left = r.left() + current_bar + bar_gap  # ← 关键：加间隙
        main_rect = QRectF(
            main_left, r.top(),
            r.width() - current_bar - bar_gap, r.height()
        )
        main_path = QPainterPath()
        c = corner_br
        main_path.moveTo(QPointF(main_rect.left(), main_rect.top()))
        main_path.lineTo(QPointF(main_rect.right(), main_rect.top()))
        main_path.lineTo(QPointF(main_rect.right(), main_rect.bottom() - c))
        main_path.lineTo(QPointF(main_rect.right() - c, main_rect.bottom()))
        main_path.lineTo(QPointF(main_rect.left(), main_rect.bottom()))
        main_path.closeSubpath()

        # 背景透明度：selected+hover > selected > hover > 普通
        if selected and hover:
            bg_color.setAlphaF(0.92)
            h, s, l = bg_color.getHslF()[0], bg_color.getHslF()[1], bg_color.getHslF()[2]
            bg_color.setHslF(h, s, min(l + 0.12, 1.0))
        elif selected:
            bg_color.setAlphaF(0.85)
        elif hover:
            bg_color.setAlphaF(0.82)
            h, s, l = bg_color.getHslF()[0], bg_color.getHslF()[1], bg_color.getHslF()[2]
            bg_color.setHslF(h, s, min(l + 0.08, 1.0))
        else:
            bg_color.setAlphaF(0.75)
        painter.fillPath(main_path, QBrush(bg_color))

        # ── 3. 边框描边（选中+hover 增强发光）──
        if selected and hover:
            glow_pen = QPen(QColor(border_color), 2.5)
            glow_pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
            painter.setPen(glow_pen)
        else:
            border_pen = QPen(border_color, 1.5)
            painter.setPen(border_pen)
        painter.drawPath(main_path)
        painter.drawPath(bar_path)

        # ── 4. 文字（不受外部 scale 影响，始终原始大小）──
        if text:
            painter.save()
            painter.resetTransform()  # 重置缩放，文字不随标签放大
            painter.setPen(text_color)
            font_size = tm.space("nav.font_size", 13)
            from PySide6.QtGui import QFont, QFontMetrics
            # 导航标签字体：Iceberg（英文），中文 fallback 到 YaHei UI
            font = QFont("Iceberg", font_size, QFont.Weight.Bold)
            painter.setFont(font)

            fm = QFontMetrics(font)
            text_x = main_rect.left() + inner_pad
            # 垂直居中：基线位置 = 矩形中心 + 字体上升高度的一半
            text_y = main_rect.center().y() + fm.ascent() / 2 - fm.descent() / 2
            painter.drawText(QPointF(text_x, text_y), text)
            painter.restore()

        # ── 5. 扫描线纹理叠加（传入复合裁剪区域）──
        combined_clip = QPainterPath()
        combined_clip.addPath(bar_path)
        combined_clip.addPath(main_path)
        self._draw_scanlines(painter, clip_path=combined_clip)

    def _draw_scanlines(
        self,
        painter: "QPainter",
        clip_path: "QPainterPath | None" = None,
    ) -> None:
        """绘制扫描线纹理（全局横纹叠加）。

        在组件背景之上、文字/边框之前调用，增加层次感。
        参考：Cyberpunk 2077 全局暗色水平横纹。

        Args:
            painter: 已初始化的 QPainter
            clip_path: 可选裁剪路径（如切角区域），仅在该区域内绘制横纹。
                       为 None 时使用控件完整矩形。
        """
        from PySide6.QtGui import QColor, QPen, QPainterPath
        from PySide6.QtCore import Qt, QPointF, QRectF
        from core.tokens.manager import TokenManager

        tm = TokenManager.instance()

        # Token 控制
        enabled = tm.get("scanline.enabled", True)
        if not enabled:
            return

        spacing = int(tm.space("scanline.spacing", 2))      # 横纹间距（像素）
        line_alpha = float(tm.get("scanline.alpha", 0.06))   # 横纹透明度 [0,1]
        color_str = str(tm.get("scanline.color", "#000000"))

        if spacing < 1:
            return

        scan_color = QColor(color_str)
        scan_color.setAlphaF(line_alpha)
        pen = QPen(scan_color)
        pen.setWidth(1)
        painter.setPen(pen)

        # 裁剪到指定区域（切角等）
        if clip_path is not None:
            painter.save()
            painter.setClipPath(clip_path)
        else:
            painter.save()
            path = self._chamfered_path(QRectF(self.rect()), 0, mode="br")
            painter.setClipPath(path)

        r = self.rect()
        y = r.top()
        while y <= r.bottom():
            painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            y += spacing

        painter.restore()
