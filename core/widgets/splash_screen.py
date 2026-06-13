"""
CyberSplashScreen — 赛博风格开启动画。

动画流程：
1. 蓝色(cyan)像素随机出现，逐渐拼成字形
2. 蓝色约一半时，橙色像素开始随机填充
3. 橙色覆盖全部像素
4. 脉冲波动 → 淡出

两种模式:
  - Standalone: 无 parent → 独立顶层窗口，屏幕居中
  - Embedded:  有 parent → 作为子 widget 嵌入父窗口，fill 整个父窗口
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path
from typing import Optional, Callable

from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont, QFontMetrics, QPainterPath,
)
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF

from core.widgets.base import CyberWidgetMixin


# ── RELIC 像素字型定义 (16x20 网格 per 字母) ──
# 超粗实心风格，笔画宽度 4-5 格，内部几乎填满
_PIXEL_FONT_DEFAULT: dict[str, list[list[int]]] = {
    "R": [
        [0,0,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,1,1,1,1,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,1,1,1,1,0,0],
        [0,1,1,1,0,0,0,0,0,0,1,1,1,1,0,0],
        [0,1,1,1,0,0,0,0,0,0,1,1,1,1,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,0,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,0,0,0,0,0],
        [0,1,1,1,0,0,1,1,1,1,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,1,1,1,1,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,1,1,1,1,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,1,1,1,1,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,1,1,1,1,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,1,1,1,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    ],
    "E": [
        [0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,0,1,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    ],
    "L": [
        [0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0],
        [0,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    ],
    "I": [
        [0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,0,0,0,1,1,1,1,1,1,1,1,0,0,0,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,1,1,1,1,1,1,1,1,1,1,1,1,1,1,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    ],
    "C": [
        [0,0,0,1,1,1,1,1,1,1,1,1,1,0,0,0],
        [0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0],
        [0,1,1,1,1,0,0,0,0,0,0,0,1,1,1,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,1,1,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,1,1,1,0,0,0,0,0,0,0,0,0,1,1,0],
        [0,1,1,1,1,0,0,0,0,0,0,0,1,1,1,0],
        [0,0,1,1,1,1,1,1,1,1,1,1,1,1,0,0],
        [0,0,0,1,1,1,1,1,1,1,1,1,1,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
        [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
        [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1],
    ],
}


# ── 外部像素字体 JSON 路径（打包后可写） ──
_PIXEL_FONT_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "pixel_font.json"


def _load_pixel_font() -> dict[str, list[list[int]]]:
    """加载像素字体数据：优先从外部 JSON 读取，否则使用内置默认值。

    外部文件 data/pixel_font.json 由像素字体编辑器生成，
    打包后该路径位于可写的 data/ 目录下。
    """
    try:
        if _PIXEL_FONT_JSON_PATH.exists():
            with open(_PIXEL_FONT_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 校验基本结构
            if isinstance(data, dict) and all(
                k in ("R", "E", "L", "I", "C") and isinstance(v, list)
                for k, v in data.items()
            ):
                return data
    except Exception:
        pass
    return _PIXEL_FONT_DEFAULT


# 公开的像素字体变量（供 pixel_font_editor 等模块引用）
_PIXEL_FONT = _load_pixel_font()


def get_pixel_font_json_path() -> Path:
    """获取像素字体外部 JSON 文件路径。"""
    return _PIXEL_FONT_JSON_PATH


def reload_pixel_font():
    """重新加载像素字体数据（编辑器保存后调用）。"""
    global _PIXEL_FONT
    _PIXEL_FONT = _load_pixel_font()







class _Pixel:
    """单个像素块的状态。"""

    __slots__ = ("gx", "gy", "visible", "alpha", "scale",
                 "color_phase", "appear_order", "pulse_offset")

    # color_phase: 0=隐藏, 1=蓝色(cyan), 2=橙色(orange)
    def __init__(self, gx: int, gy: int):
        self.gx = gx
        self.gy = gy
        self.visible = False
        self.alpha = 0.0
        self.scale = 0.0
        self.color_phase = 0
        self.appear_order = 0   # 蓝色出现顺序
        self.pulse_offset = 0.0


class CyberSplashScreen(QWidget, CyberWidgetMixin):
    """赛博风格启动画面。"""

    DEFAULT_DURATION_MS = 3000
    PIXEL_SIZE = 4
    PIXEL_GAP = 1
    LETTER_GAP_CELLS = 4
    WAVE_SPEED = 2.5

    # 动画时间分配 (占总时长比例)
    BLUE_RATIO = 0.35       # 蓝色出现阶段
    ORANGE_RATIO = 0.30     # 橙色填充阶段
    PULSE_RATIO = 0.25      # 脉冲波动
    FADE_MS = 400            # 淡出固定时长

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        enabled: bool = True,
        duration_ms: int | None = None,
        on_finished: Optional[Callable[[], None]] = None,
    ):
        QWidget.__init__(self, parent)
        CyberWidgetMixin.__init__(self)

        self._enabled = enabled
        self._duration_ms = duration_ms or self.DEFAULT_DURATION_MS
        self._on_finished = on_finished
        self._embedded = parent is not None

        if self._embedded:
            # Embedded mode: fill parent, no separate window
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.raise_()
        else:
            # Standalone mode: top-level frameless window centered on screen
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

            screen = QApplication.primaryScreen().geometry()
            w = int(screen.width() * 0.55)
            h = int(screen.height() * 0.45)
            x = (screen.width() - w) // 2
            y = (screen.height() - h) // 2
            self.setGeometry(x, y, w, h)

        # 构建像素
        self._pixels: list[_Pixel] = []
        self._grid_w = 0
        self._grid_h = 0
        self._build_pixels()

        # 预计算随机出现顺序
        self._blue_order: list[int] = []   # 蓝色出现顺序 (像素索引)
        self._orange_order: list[int] = [] # 橙色出现顺序
        self._prepare_appear_order()

        # 动画状态
        self._phase = "blue"   # blue -> orange -> pulse -> fade -> done
        self._start_time: float = 0.0
        self._frame = 0

        # 阶段时间节点 (ms)
        dur = self._duration_ms
        fade = self.FADE_MS
        self._t_blue_end = dur * self.BLUE_RATIO
        self._t_orange_end = self._t_blue_end + dur * self.ORANGE_RATIO
        self._t_pulse_end = dur - fade
        self._t_fade_end = dur

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(16)

    # ── 构建像素网格 ──

    def _build_pixels(self) -> None:
        text = "RELIC"
        gap = self.LETTER_GAP_CELLS

        char_cols = [len(_PIXEL_FONT[ch][0]) for ch in text]

        char_offsets: list[int] = []
        x = 0
        for i, cols in enumerate(char_cols):
            char_offsets.append(x)
            x += cols
            if i < len(char_cols) - 1:
                x += gap

        self._grid_w = x
        self._grid_h = max(len(_PIXEL_FONT[ch]) for ch in text)

        for ch_idx, ch in enumerate(text):
            glyph = _PIXEL_FONT[ch]
            ox = char_offsets[ch_idx]
            for row in range(len(glyph)):
                for col in range(len(glyph[row])):
                    if glyph[row][col] == 1:
                        px = _Pixel(gx=ox + col, gy=row)
                        px.pulse_offset = ch_idx * 4 + (row + col) * 0.3
                        self._pixels.append(px)

    def _prepare_appear_order(self) -> None:
        """生成随机出现顺序。"""
        n = len(self._pixels)
        # 蓝色：全部像素的随机顺序
        blue = list(range(n))
        random.shuffle(blue)
        self._blue_order = blue
        # 橙色：全部像素的随机顺序（与蓝色不同）
        orange = list(range(n))
        random.shuffle(orange)
        self._orange_order = orange
        # 给每个像素标记蓝色出现序号
        for rank, idx in enumerate(blue):
            self._pixels[idx].appear_order = rank

    # ── 控制 ──

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._enabled:
            if self._on_finished:
                self._on_finished()
            return
        self._start_time = time.perf_counter()
        self._timer.start()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._embedded and self._pixels:
            self._pixels.clear()
            self._build_pixels()
            self._prepare_appear_order()

    # ── 动画帧 ──

    def _tick(self) -> None:
        now = time.perf_counter()
        elapsed = (now - self._start_time) * 1000

        if self._phase == "blue":
            self._update_blue(elapsed)
            if elapsed >= self._t_blue_end:
                self._phase = "orange"

        elif self._phase == "orange":
            self._update_orange(elapsed)
            if elapsed >= self._t_orange_end:
                self._phase = "pulse"

        elif self._phase == "pulse":
            self._update_pulse(elapsed)
            if elapsed >= self._t_pulse_end:
                self._phase = "fade"

        elif self._phase == "fade":
            self._update_fade(elapsed)
            if elapsed >= self._t_fade_end:
                self._phase = "done"
                self._timer.stop()
                if self._on_finished:
                    self._on_finished()
                if not self._embedded:
                    self.close()
                return

        self.update()
        self._frame += 1

    def _update_blue(self, elapsed_ms: float) -> None:
        """蓝色像素随机出现阶段。"""
        n = len(self._pixels)
        if n == 0:
            return
        # 当前应出现的像素数量
        progress = elapsed_ms / self._t_blue_end  # 0~1
        count = int(progress * n)
        count = min(count, n)

        for rank in range(count):
            idx = self._blue_order[rank]
            px = self._pixels[idx]
            if px.color_phase < 1:
                px.color_phase = 1
                px.visible = True
                px.alpha = 0.0
                px.scale = 0.0

        # 对刚出现的像素做渐入动画
        for px in self._pixels:
            if px.color_phase == 1 and px.scale < 1.0:
                px.alpha = min(1.0, px.alpha + 0.12)
                px.scale = min(1.0, px.scale + 0.12)

    def _update_orange(self, elapsed_ms: float) -> None:
        """橙色像素随机填充阶段。"""
        n = len(self._pixels)
        if n == 0:
            return
        # 先确保所有蓝色已出现
        for px in self._pixels:
            if px.color_phase == 0:
                px.color_phase = 1
                px.visible = True
                px.alpha = 1.0
                px.scale = 1.0
            elif px.color_phase == 1 and px.scale < 1.0:
                px.alpha = min(1.0, px.alpha + 0.12)
                px.scale = min(1.0, px.scale + 0.12)

        # 橙色填充进度
        progress = (elapsed_ms - self._t_blue_end) / (self._t_orange_end - self._t_blue_end)
        count = int(progress * n)
        count = min(count, n)

        for rank in range(count):
            idx = self._orange_order[rank]
            px = self._pixels[idx]
            if px.color_phase < 2:
                px.color_phase = 2

        # 橙色像素渐入
        for px in self._pixels:
            if px.color_phase == 2 and px.alpha < 1.0:
                px.alpha = min(1.0, px.alpha + 0.15)

    def _update_pulse(self, elapsed_ms: float) -> None:
        """脉冲波动。"""
        t_sec = (elapsed_ms - self._t_orange_end) / 1000
        for px in self._pixels:
            if not px.visible:
                continue
            wave = math.sin(t_sec * self.WAVE_SPEED + px.pulse_offset)
            target = 0.6 + 0.4 * (wave * 0.5 + 0.5)  # 0.6 ~ 1.0
            px.alpha += (target - px.alpha) * 0.12

    def _update_fade(self, elapsed_ms: float) -> None:
        """淡出。"""
        progress = (elapsed_ms - self._t_pulse_end) / self.FADE_MS
        for px in self._pixels:
            px.alpha *= (1 - progress * 0.1)

    # ── 绘制 ──

    def paintEvent(self, event) -> None:
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

            # 深空背景
            painter.fillRect(self.rect(), QColor(8, 8, 26, 240))

            self._draw_border_decor(painter)

            if not self._pixels:
                return

            # 居中
            ps = self.PIXEL_SIZE
            pg = self.PIXEL_GAP
            cell = ps + pg
            total_w = self._grid_w * cell
            total_h = self._grid_h * cell
            ox = (self.width() - total_w) // 2
            oy = (self.height() - total_h) // 2

            # 颜色
            cyan = self.token_color("accent.secondary")   # 蓝色
            orange = self.token_color("semantic.warning")  # 橙色

            for px in self._pixels:
                if not px.visible or px.alpha < 0.01:
                    continue

                actual = ps * px.scale
                shrink = (ps - actual) / 2
                rx = ox + px.gx * cell + shrink
                ry = oy + px.gy * cell + shrink

                # 根据阶段选色
                if px.color_phase >= 2:
                    c = QColor(orange)
                else:
                    c = QColor(cyan)
                c.setAlphaF(max(0.0, min(1.0, px.alpha)))

                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(c)
                painter.drawRect(QRectF(rx, ry, actual, actual))

            self._draw_subtitle(painter)

        except Exception as e:
            print(f"[SplashScreen] paintEvent error: {e}", flush=True)

    def _draw_border_decor(self, painter: QPainter) -> None:
        accent = self.token_color("accent.secondary")
        accent.setAlphaF(0.15)
        pen = QPen(accent, 1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        sz = 24
        r = self.rect()
        corners = [
            (r.topLeft(), QPointF(sz, 0), QPointF(0, sz)),
            (r.topRight(), QPointF(-sz, 0), QPointF(0, sz)),
            (r.bottomLeft(), QPointF(sz, 0), QPointF(0, -sz)),
            (r.bottomRight(), QPointF(-sz, 0), QPointF(0, -sz)),
        ]
        for origin, dx, dy in corners:
            path = QPainterPath()
            path.moveTo(origin.x() + dx.x(), origin.y())
            path.lineTo(origin)
            path.lineTo(origin.x(), origin.y() + dy.y())
            painter.drawPath(path)

    def _draw_subtitle(self, painter: QPainter) -> None:
        accent = self.token_color("semantic.warning")
        accent.setAlphaF(0.6)
        painter.setPen(accent)
        font = QFont("Iceberg", 11)
        painter.setFont(font)

        text = "WARFRAME RELIC — SYSTEM INITIALIZING"
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(text)
        tx = (self.width() - tw) // 2
        ty = self.height() - 36
        painter.drawText(int(tx), int(ty), text)
