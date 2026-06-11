"""
CyberRelicTooltip — 赛博风格遗物信息悬浮窗。

鼠标悬停在遗物条目上时弹出的详细信息面板，展示：
- 标题栏：遗物名称 + 入库状态
- 遗物内含物品：按稀有度着色（金/银/铜）+ 掉落概率
- 掉落来源：按来源类型分组（任务/赏金等）

数据结构::

    relic_info = {
        'name': 'Axi S20 Intact',
        'vaulted': False,
        'parts': [
            {'name': 'Forma Blueprint',  'rarity': 'Rare',    'chance': 2.0},
            {'name': 'Braton Prime Rec.', 'rarity': 'Uncommon', 'chance': 11.0},
            ...
        ],
    }

    sources = [
        {'location': '金星 - 夺取 (歼灭)', 'source_type': 'missionRewards',
         'chance': 100, 'rotation': ''},
        ...
    ]

使用方式::

    tip = CyberRelicTooltip()
    tip.set_data(relic_info=relic_info, sources=sources)
    tip.show_at(widget, pos)
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath,
    QFont, QFontMetrics,
)
from PySide6.QtCore import Qt, QRectF, QPointF

from core.widgets.base import CyberWidgetMixin


# ── 稀有度颜色映射（token key）──
_RARITY_TOKENS = {
    "Rare":     "alias.rarity.gold",
    "Uncommon": "alias.rarity.silver",
    "Common":   "alias.rarity.copper",
}

_RARITY_LABELS = {
    "Rare":     "黄金",
    "Uncommon": "白银",
    "Common":   "青铜",
}

# 来源类型中文映射
_SOURCE_TYPE_CN = {
    "missionRewards":   "任务奖励",
    "bountyRewards":    "赏金奖励",
    "sortieRewards":    "突击奖励",
    "keyRewards":       "钥匙奖励",
    "transientRewards": "临时奖励",
    "syndicates":       "集团奖励",
}


class CyberRelicTooltip(CyberWidgetMixin, QFrame):
    """赛博风格遗物信息悬浮窗。"""

    def __init__(self, parent: Optional[QWidget] = None):
        QFrame.__init__(self, parent, Qt.WindowType.ToolTip)
        CyberWidgetMixin.__init__(self)

        self._relic_info: dict | None = None
        self._sources: list[dict] = []

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Tool |
            Qt.WindowType.NoDropShadowWindowHint
        )

        # 布局
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(1, 1, 1, 1)  # 给边框留空间
        self._layout.setSpacing(0)

        self.setStyleSheet("QFrame { background: transparent; }")
        self.setObjectName("CyberRelicTooltip")

    def set_data(self, relic_info: dict | None = None, sources: list[dict] | None = None):
        """设置显示数据。

        Args:
            relic_info: RelicDB.find() 返回的遗物信息
            sources: DropSourceIndex.query() 返回的掉落来源列表
        """
        self._relic_info = relic_info
        self._sources = sources or []
        self.adjustSize()

    def show_at(self, target_widget: QWidget, offset: tuple[int, int] = (12, 8)):
        """在目标控件附近定位并显示，自动约束在屏幕范围内。

        Args:
            target_widget: 锚点控件
            offset: 相对锚点的偏移 (dx, dy)
        """
        from PySide6.QtWidgets import QApplication

        gp = target_widget.mapToGlobal(QPointF(0, target_widget.height()).toPoint())
        x = gp.x() + offset[0]
        y = gp.y() + offset[1]

        # 先调整大小确保 sizeHint 生效
        self.adjustSize()
        w = self.width()
        h = self.height()

        # 获取屏幕可用区域
        screen = QApplication.screenAt(gp)
        if not screen:
            screen = QApplication.primaryScreen()
        if screen:
            scr_rect = screen.availableGeometry()

            # 右边界：超出则左移
            if x + w > scr_rect.right():
                x = scr_rect.right() - w
            # 左边界：仍超则贴左边
            if x < scr_rect.left():
                x = scr_rect.left() + 4

            # 下边界：超出则翻到锚点上方
            if y + h > scr_rect.bottom():
                y = target_widget.mapToGlobal(QPointF(0, 0)).toPoint().y() - h - offset[1]
            # 上边界：仍超则贴顶部
            if y < scr_rect.top():
                y = scr_rect.top() + 4

        self.move(x, y)
        self.show()
        self.raise_()

    # ── 尺寸计算 ──

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(340, self._calc_height())

    def _calc_height(self) -> int:
        """根据实际内容计算精确高度（与绘制逻辑完全一致）。"""
        h = 38  # 标题栏
        if self._relic_info and self._relic_info.get('parts'):
            parts = self._relic_info['parts']
            h += 26  # 区段标题
            h += len(parts) * 21  # 每行部件
            h += 12  # 分隔线 + 间距
        if self._sources:
            import re
            _RELIC_RE = re.compile(
                r'^(Lith|Meso|Neo|Axi|Requiem|Vanguard)\s+\w+\s+'
                r'(?:Relic(?:\s*\([^)]*\))?|Intact|Exceptional|Flawless|Radiant)$',
                re.IGNORECASE,
            )
            filtered = [s for s in self._sources
                        if s.get('source_type', '') != 'relics'
                        and not _RELIC_RE.match(s.get('location', ''))]
            if filtered:
                by_type: dict[str, list[dict]] = {}
                for s in filtered:
                    st = s.get('source_type', '')
                    if st not in by_type:
                        by_type[st] = []
                    by_type[st].append(s)
                h += 26  # 区段标题
                for st, items in by_type.items():
                    h += 17  # 类型标题行
                    h += min(len(items), 5) * 17  # 来源条目
                    if len(items) > 5:
                        h += 15  # "还有 N 条"
                    h += 4   # 类型间距
        return max(h, 100)

    # ── 绘制 ──

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        corner = self.space("components.dialog.corner_size", 14)
        path = self._chamfered_path(QRectF(self.rect()), corner, mode="all")

        # 背景
        bg_color = self.token_color("components.dialog.bg")
        opacity = float(self.token("components.dialog.bg_opacity") or "0.96")
        bg_color.setAlphaF(opacity)
        painter.fillPath(path, QBrush(bg_color))

        # 边框
        border_color = self.token_color("accent.secondary")
        border_width = float(self.token("components.dialog.border_width") or "1.5")
        painter.setPen(QPen(border_color, border_width))
        painter.drawPath(path)

        # 内容绘制
        self._draw_content(painter)

    def _draw_content(self, painter: QPainter):
        """绘制所有内容区域。"""
        from PySide6.QtGui import QLinearGradient

        r = self.rect().adjusted(2, 2, -2, -2)
        y = r.top() + 4

        # ── 1. 标题栏 ──
        y = self._draw_title(painter, r, y)

        # 分隔线
        sep_y = y + 4
        sep_color = QColor(self.token_color("border.subtle"))
        sep_color.setAlphaF(0.3)
        painter.setPen(QPen(sep_color, 1))
        painter.drawLine(int(r.left() + 16), int(sep_y), int(r.right() - 16), int(sep_y))

        y = sep_y + 8

        # ── 2. 遗物内含物品 ──
        if self._relic_info and self._relic_info.get('parts'):
            y = self._draw_parts(painter, r, y)

        # ── 3. 掉落来源 ──
        if self._sources:
            y = self._draw_sources(painter, r, y)

    def _draw_title(self, painter: QPainter, r: QRectF, y: float) -> float:
        """绘制标题栏：遗物名 + 状态标签。"""
        # 遗物名
        title_color = self.token_color("accent.secondary")
        painter.setPen(title_color)
        font = QFont()
        font.setPointSize(self.space("font.md", 14))
        font.setBold(True)
        painter.setFont(font)

        icon_text = "\u25C8"  # ◈
        name = self._relic_info.get('name', '') if self._relic_info else ''
        title_str = f"{icon_text} {name}"
        painter.drawText(int(r.left() + 14), int(y + 18), title_str)

        # 状态标签
        if self._relic_info:
            vaulted = self._relic_info.get('vaulted', False)
            if vaulted:
                status_color = self.token_color("brand.red")  # 红色 — 入库
                status_text = "[已入库]"
            else:
                status_color = self.token_color("brand.green")  # 绿色 — 出库
                status_text = "[出库]"

            fm = QFontMetrics(font)
            title_w = fm.horizontalAdvance(title_str)
            label_x = r.left() + 14 + title_w + 10

            painter.setPen(status_color)
            font2 = QFont()
            font2.setPointSize(self.space("font.xs", 11))
            painter.setFont(font2)
            painter.drawText(int(label_x), int(y + 17), status_text)

        return y + 32

    def _draw_parts(self, painter: QPainter, r: QRectF, y: float) -> float:
        """绘制遗物内含物品列表。"""
        parts = self._relic_info['parts']
        sorted_parts = sorted(parts, key=lambda p: p.get('chance', 0))

        # 按 chance 分配颜色（3档）
        chances = sorted(set(p.get('chance', 0) for p in sorted_parts))
        if len(chances) >= 3:
            color_map = {chances[0]: self.token_color(_RARITY_TOKENS["Rare"]).name(),
                         chances[1]: self.token_color(_RARITY_TOKENS["Uncommon"]).name(),
                         chances[2]: self.token_color(_RARITY_TOKENS["Common"]).name()}
        elif len(chances) == 2:
            color_map = {chances[0]: self.token_color(_RARITY_TOKENS["Rare"]).name(),
                         chances[1]: self.token_color(_RARITY_TOKENS["Common"]).name()}
        else:
            color_map = {chances[0]: self.token_color(_RARITY_TOKENS["Uncommon"]).name()}

        # 区段标题
        section_color = self.token_color(_RARITY_TOKENS["Rare"])  # 金色标题
        painter.setPen(section_color)
        font = QFont()
        font.setPointSize(self.space("font.sm_md", 13))
        font.setBold(True)
        painter.setFont(font)

        # 左侧装饰竖线
        bar_x = r.left() + 14
        bar_h = 12
        painter.fillRect(int(bar_x), int(y + 3), 3, bar_h, QBrush(section_color))

        header = f"遗物内容 ({len(sorted_parts)} 个部件)"
        dim_color = QColor(self.token_color("text.tertiary"))
        sub_font = QFont()
        sub_font.setPointSize(self.space("font.xs", 11))
        fm = QFontMetrics(font)
        main_w = fm.horizontalAdvance("遗物内容 ")
        painter.drawText(int(bar_x + 9), int(y + 17), "遗物内容")

        painter.setPen(dim_color)
        painter.setFont(sub_font)
        painter.drawText(int(bar_x + 9 + main_w), int(y + 17),
                        f"({len(sorted_parts)} 个部件)")

        y += 26

        # 物品列表
        item_font = QFont()
        item_font.setPointSize(self.space("font.sm", 12))
        painter.setFont(item_font)

        for p in sorted_parts:
            ch = p.get('chance', 0)
            dot_clr = QColor(color_map.get(ch, self.token_color("neutral.light").name()))

            # 圆点
            dot_r = 4
            dot_cx = r.left() + 26
            dot_cy = y + 8
            painter.setBrush(QBrush(dot_clr))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(
                int(dot_cx - dot_r), int(dot_cy - dot_r),
                dot_r * 2, dot_r * 2
            )

            # 名称
            text_color = QColor(dot_clr)
            text_color.setAlphaF(0.92)
            painter.setPen(text_color)
            item_name = p.get('name', '')
            # 截断过长名称
            max_name_w = r.width() - 90
            fm_item = QFontMetrics(item_font)
            if fm_item.horizontalAdvance(item_name) > max_name_w:
                item_name = fm_item.elidedText(item_name, Qt.TextElideMode.ElideRight, int(max_name_w))
            painter.drawText(int(r.left() + 38), int(y + 13), item_name)

            # 稀有度 + 概率
            rarity = p.get('rarity', '')
            rarity_cn = _RARITY_LABELS.get(rarity, rarity)
            painter.setPen(dim_color)
            tiny_font = QFont()
            tiny_font.setPointSize(self.space("font.micro", 10))
            painter.setFont(tiny_font)
            suffix = f"{rarity_cn} ({ch:.1f}%)" if ch > 0 else rarity_cn
            painter.drawText(int(r.right() - 80), int(y + 12), suffix)
            painter.setFont(item_font)

            y += 21

        # 底部分隔线
        sep_color = QColor(self.token_color("border.subtle"))
        sep_color.setAlphaF(0.2)
        painter.setPen(QPen(sep_color, 1))
        painter.drawLine(int(r.left() + 16), int(y + 2), int(r.right() - 16), int(y + 2))

        return y + 10

    def _draw_sources(self, painter: QPainter, r: QRectF, y: float) -> float:
        """绘制掉落来源列表（按类型分组）。"""
        # 过滤无效数据（复用老项目逻辑）
        import re
        _RELIC_RE = re.compile(
            r'^(Lith|Meso|Neo|Axi|Requiem|Vanguard)\s+\w+\s+'
            r'(?:Relic(?:\s*\([^)]*\))?|Intact|Exceptional|Flawless|Radiant)$',
            re.IGNORECASE,
        )
        filtered = []
        for s in self._sources:
            st = s.get('source_type', '')
            loc = s.get('location', '')
            if st == 'relics':
                continue
            if _RELIC_RE.match(loc):
                continue
            filtered.append(s)

        if not filtered:
            return y

        # 按类型分组
        by_type: dict[str, list[dict]] = {}
        for s in filtered:
            st = s.get('source_type', '')
            if st not in by_type:
                by_type[st] = []
            by_type[st].append(s)

        # 来源类型颜色（token key）
        type_color_tokens = {
            "missionRewards":   "alias.source_type.mission",
            "bountyRewards":    "alias.source_type.bounty",
            "sortieRewards":    "alias.source_type.sortie",
            "keyRewards":       "alias.source_type.key",
            "transientRewards": "alias.source_type.transient",
            "syndicates":       "alias.source_type.syndicate",
        }
        total = sum(len(v) for v in by_type.values())

        # 区段标题
        accent = self.token_color("accent.primary")
        painter.setPen(accent)
        font = QFont()
        font.setPointSize(self.space("font.sm_md", 13))
        font.setBold(True)
        painter.setFont(font)

        bar_x = r.left() + 14
        painter.fillRect(int(bar_x), int(y + 3), 3, 12, QBrush(accent))
        painter.drawText(int(bar_x + 9), int(y + 17), "掉落来源")

        dim_color = QColor(self.token_color("text.tertiary"))
        sub_font = QFont()
        sub_font.setPointSize(self.space("font.xs", 11))
        painter.setPen(dim_color)
        painter.setFont(sub_font)
        painter.drawText(int(bar_x + 72), int(y + 17), f"({total} 条)")

        y += 26

        # 各类型 + 条目
        for st, items in by_type.items():
            cn_st = _SOURCE_TYPE_CN.get(st, st)
            accent_clr = self.token_color(type_color_tokens.get(st, "neutral.light"))

            # 类型标题
            type_font = QFont()
            type_font.setPointSize(self.space("font.xs", 11))
            type_font.setBold(True)
            painter.setPen(accent_clr)
            painter.setFont(type_font)
            painter.drawText(int(r.left() + 24), int(y + 13),
                           f"{cn_st} ({len(items)})")
            y += 17

            # 来源条目（限制每个类型最多5条）
            item_font = QFont()
            item_font.setPointSize(self.space("font.xs", 11))
            painter.setFont(item_font)
            light_color = QColor(self.token_color("text.primary"))

            for item in items[:5]:
                loc = item.get('location', '?')
                chance = item.get('chance', 0)
                rotation = item.get('rotation', '')

                # 截断过长地点名
                max_loc_w = r.width() - 60
                fm = QFontMetrics(item_font)
                if fm.horizontalAdvance(loc) > max_loc_w:
                    loc = fm.elidedText(loc, Qt.TextElideMode.ElideRight, int(max_loc_w))

                painter.setPen(light_color)
                painter.drawText(int(r.left() + 36), int(y + 12), loc)

                # 概率 / 轮次标签
                suffix_parts = []
                if 0 < chance < 100:
                    suffix_parts.append(f"{chance:.1f}%")
                elif chance >= 100:
                    suffix_parts.append("必定")
                if rotation:
                    suffix_parts.append(f"轮次{rotation}")

                if suffix_parts:
                    muted = QColor(self.token_color("text.disabled"))
                    painter.setPen(muted)
                    tiny = QFont()
                    tiny.setPointSize(self.space("font.xxs", 9))
                    painter.setFont(tiny)
                    suffix = " | ".join(suffix_parts)
                    painter.drawText(int(r.right() - 85), int(y + 11), suffix)
                    painter.setFont(item_font)

                y += 17

            if len(items) > 5:
                more_font = QFont()
                more_font.setPointSize(self.space("font.micro", 10))
                painter.setPen(dim_color)
                painter.setFont(more_font)
                painter.drawText(int(r.left() + 36), int(y + 11),
                               f"... 还有 {len(items) - 5} 条")
                y += 15

            y += 4  # 类型间距

        return y
