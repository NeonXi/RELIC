"""
[L4] PixelFontEditor — 像素字体可视化编辑器。

依赖: PySide6, tokens/
职责: 提供像素字体的可视化编辑、预览、导出功能
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QLabel, QSpinBox, QComboBox,
    QScrollArea, QFrame, QSplitter, QGroupBox,
    QMessageBox, QApplication,
)
from PySide6.QtGui import (
    QPainter, QColor, QPen, QFont,
    QPalette,
)
from PySide6.QtCore import Qt, Signal, QSize, QRectF, QObject

# 引用 splash_screen 的字型数据
from core.widgets.splash_screen import _PIXEL_FONT
from core.tokens.manager import TokenManager

# splash_screen.py 的路径（相对于本文件）
_SPLASH_SCREEN_PATH = Path(__file__).resolve().parent / "splash_screen.py"


def _tc(key: str) -> str:
    """获取 token 颜色 hex 字符串（带容错）。"""
    try:
        return TokenManager.instance().get_qcolor(key).name()
    except Exception:
        # 回退到默认颜色
        _fallbacks = {
            "bg.base": "#0c0c18", "bg.raised": "#1e1e2e",
            "text.primary": "#e0e0e0", "text.secondary": "#c0c0d0",
            "border.subtle": "#33334a", "border.default": "#33334a",
            "accent.primary": "#FFE600", "accent.secondary": "#00ccff",
            "neutral.dark": "#2a2a3e",
        }
        return _fallbacks.get(key, "#888888")


_TM = TokenManager.instance()


def _format_font_code(font_data: dict[str, list[list[int]]]) -> str:
    """将字体数据格式化为 Python 字典代码。"""
    lines = ['_PIXEL_FONT: dict[str, list[list[int]]] = {']
    for ch in font_data:
        grid = font_data[ch]
        lines.append(f'    "{ch}": [')
        for row in grid:
            cells = ",".join(str(c) for c in row)
            lines.append(f"        [{cells}],")
        lines.append("    ],")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _save_font_to_file(font_data: dict[str, list[list[int]]]) -> bool:
    """将字体数据写回 splash_screen.py，返回是否成功。"""
    try:
        src_path = _SPLASH_SCREEN_PATH
        content = src_path.read_text(encoding="utf-8")

        # 定位 _PIXEL_FONT 定义块的起止位置
        start_pattern = re.compile(r"^_PIXEL_FONT:\s*dict\[str,\s*list\[list\[int\]\]\]\s*=\s*\{$", re.MULTILINE)
        match = start_pattern.search(content)
        if not match:
            return False

        start = match.start()
        rest = content[start:]
        # 从 { 开始逐行计算大括号深度，找到匹配的 }
        brace_depth = 0
        end_offset = 0
        in_block = False
        for i, ch in enumerate(rest):
            if ch == "{":
                brace_depth += 1
                in_block = True
            elif ch == "}":
                brace_depth -= 1
                if in_block and brace_depth == 0:
                    end_offset = i + 1
                    break

        if end_offset == 0:
            return False

        # 替换并写回
        new_code = _format_font_code(font_data)
        new_content = content[:start] + new_code + content[start + end_offset:]
        src_path.write_text(new_content, encoding="utf-8")
        return True
    except Exception:
        return False


class _WheelBlocker(QObject):
    """事件过滤器：阻止滚轮事件透传给父组件（QSpinBox / QComboBox）。"""

    def eventFilter(self, obj, event):
        if event.type() == event.Type.Wheel:
            return True  # 吞掉滚轮事件
        return super().eventFilter(obj, event)


_WHEEL_BLOCKER = _WheelBlocker()


class _GridCell(QFrame):
    """单个可点击/拖拽绘制的网格单元格。"""

    def __init__(self, row: int, col: int, parent=None):
        QFrame.__init__(self, parent)
        self.row = row
        self.col = col
        self._on = False
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def on(self) -> bool:
        return self._on

    @on.setter
    def on(self, value: bool):
        if self._on != value:
            self._on = value
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # 背景
        bg = QColor(30, 30, 45) if not self._on else QColor(0, 200, 255)
        painter.fillRect(self.rect(), bg)

        # 边框
        pen = QPen(QColor(60, 60, 80), 1)
        painter.setPen(pen)
        painter.drawRect(0, 0, self.width() - 1, self.height() - 1)

        super().paintEvent(event)


class _GridContainer(QFrame):
    """网格容器 — 处理鼠标拖拽绘制逻辑。"""

    def __init__(self, parent=None):
        QFrame.__init__(self, parent)
        self._cells: list[_GridCell] = []
        self._dragging = False
        self._drag_value: bool | None = None

        self.setMouseTracking(False)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def add_cell(self, cell: _GridCell) -> None:
        self._cells.append(cell)

    def clear_cells(self) -> None:
        self._cells.clear()

    def _cell_at_pos(self, pos) -> _GridCell | None:
        """获取指定位置的单元格。"""
        for c in self._cells:
            if c.geometry().contains(pos):
                return c
        return None

    def _set_cell(self, cell: _GridCell, value: bool) -> None:
        """设置单元格状态并通知父组件。"""
        if cell.on != value:
            cell.on = value
            p = self.parent()
            while p and not hasattr(p, '_on_cell_toggled'):
                p = p.parent()
            if hasattr(p, '_on_cell_toggled'):
                p._on_cell_toggled(cell.row, cell.col, value)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._cell_at_pos(event.pos())
            if cell:
                self._dragging = True
                self._drag_value = not cell.on
                self._set_cell(cell, self._drag_value)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            cell = self._cell_at_pos(event.pos())
            if cell and self._drag_value is not None:
                self._set_cell(cell, self._drag_value)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._drag_value = None


class PixelFontEditor(QDialog):
    """像素字体编辑器对话框。"""

    def __init__(self, parent=None):
        QDialog.__init__(self, parent)
        self.setWindowTitle("像素字体编辑器 — RELIC Splash")
        self.setMinimumSize(900, 650)

        # 深色主题（从 Token 解析颜色）
        _bg_base = _tc("bg.base")
        _bg_raised = _tc("bg.raised")
        _text_pri = _tc("text.primary")
        _text_sec = _tc("text.secondary")
        _text_ter = _tc("alias.text.tertiary")
        _border_sub = _tc("border.subtle")
        _border_def = _tc("border.default")
        _accent_sec = _tc("accent.secondary")
        _accent_pri = _tc("accent.primary")

        self.setStyleSheet(f"""
            QDialog {{ background-color: {_bg_base}; color: {_text_pri}; }}
            QLabel {{ color: {_text_sec}; font-size: {_TM.space('font.body_md', 13)}px; }}
            QPushButton {{
                background-color: {_bg_raised}; color: {_text_pri};
                border: 1px solid {_border_sub}; border-radius: {_TM.space('corner.xs', 4)}px;
                padding: {_TM.space('spacing.xs', 6)}px {_TM.space('spacing.lg', 16)}px;
                font-size: {_TM.space('font.body_md', 13)}px;
            }}
            QPushButton:hover {{ background-color: {_tc('neutral.dark')}; border-color: {_accent_sec}; }}
            QPushButton:pressed {{ background-color: {_bg_base}; }}
            QComboBox {{
                background-color: {_bg_raised}; color: {_text_pri};
                border: 1px solid {_border_sub}; border-radius: {_TM.space('corner.xs', 4)}px;
                padding: {_TM.space('spacing.xs', 5)}px {_TM.space('spacing.sm', 10)}px;
                font-size: {_TM.space('font.body_md', 13)}px;
            }}
            QComboBox::drop-down {{ border: none; width: {_TM.space('height.btn_icon', 24)}px; }}
            QComboBox::down-arrow {{ image: none; }}
            QComboBox QAbstractItemView {{
                background-color: {_bg_raised}; color: {_text_pri};
                selection-background-color: {_accent_pri};
                selection-color: {_text_pri};
                outline: none;
            }}
            QSpinBox {{
                background-color: {_bg_raised}; color: {_text_pri};
                border: 1px solid {_border_sub}; border-radius: {_TM.space('corner.xs', 4)}px;
                padding: {_TM.space('spacing.xs', 4)}px {_TM.space('spacing.sm', 8)}px;
                font-size: {_TM.space('font.body_md', 13)}px;
            }}
            QGroupBox {{
                color: {_text_ter}; font-weight: bold;
                border: 1px solid {_border_def}; border-radius: {_TM.space('corner.sm', 6)}px;
                margin-top: {_TM.space('spacing.sm', 8)}px; padding-top: {_TM.space('spacing.md', 12)}px;
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: {_TM.space('spacing.sm', 10)}px; padding: 0 {_TM.space('spacing.xs', 5)}px; }}
        """)

        # 数据：深拷贝当前字型，避免修改原始数据
        self._font_data: dict[str, list[list[int]]] = {}
        for ch, grid in _PIXEL_FONT.items():
            self._font_data[ch] = [row[:] for row in grid]

        self._current_char = "R"
        self._cells: list[_GridCell] = []

        self._setup_ui()
        self._load_letter("R")

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # ── 顶部工具栏 ──
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("字母:"))
        self._char_combo = QComboBox()
        self._char_combo.addItems(["R", "E", "L", "I", "C"])
        self._char_combo.currentTextChanged.connect(self._on_letter_changed)
        # 下拉列表 hover 颜色（QSS 不可靠时用调色板兜底）
        pal = self._char_combo.palette()
        pal.setColor(QPalette.ColorRole.Highlight, QColor(26, 74, 122))
        pal.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
        self._char_combo.setPalette(pal)
        self._char_combo.installEventFilter(_WHEEL_BLOCKER)
        toolbar.addWidget(self._char_combo)

        toolbar.addSpacing(20)

        toolbar.addWidget(QLabel("行数:"))
        self._rows_spin = QSpinBox()
        self._rows_spin.setRange(8, 32)
        self._rows_spin.setValue(len(_PIXEL_FONT["R"]))
        self._rows_spin.valueChanged.connect(self._on_grid_resize)
        self._rows_spin.installEventFilter(_WHEEL_BLOCKER)
        toolbar.addWidget(self._rows_spin)

        toolbar.addWidget(QLabel("列数:"))
        self._cols_spin = QSpinBox()
        self._cols_spin.setRange(6, 24)
        self._cols_spin.setValue(len(_PIXEL_FONT["R"][0]))
        self._cols_spin.valueChanged.connect(self._on_grid_resize)
        self._cols_spin.installEventFilter(_WHEEL_BLOCKER)
        toolbar.addWidget(self._cols_spin)

        toolbar.addStretch()

        btn_save = QPushButton("保存")
        btn_save.clicked.connect(self._save)
        toolbar.addWidget(btn_save)

        btn_reset = QPushButton("重置当前字母")
        btn_reset.clicked.connect(self._reset_current)
        toolbar.addWidget(btn_reset)

        layout.addLayout(toolbar)

        # ── 主区域：编辑器 + 预览 ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：编辑网格
        edit_group = QGroupBox("编辑网格 (点击切换单元格)")
        edit_layout = QVBoxLayout(edit_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._grid_container = _GridContainer()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(1)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)

        scroll.setWidget(self._grid_container)
        edit_layout.addWidget(scroll)
        splitter.addWidget(edit_group)

        # 右侧：预览面板
        preview_group = QGroupBox("实时预览")
        preview_layout = QVBoxLayout(preview_group)

        self._preview_label = _PreviewLabel()
        self._preview_label.setMinimumHeight(200)
        preview_layout.addWidget(self._preview_label, 1)

        # 预览信息
        info_layout = QHBoxLayout()
        self._info_label = QLabel()
        info_layout.addWidget(self._info_label)
        preview_layout.addLayout(info_layout)

        splitter.addWidget(preview_group)
        splitter.setSizes([600, 300])

        layout.addWidget(splitter, 1)

        # 底部提示
        hint = QLabel("提示: 左键点击切换单元格 | 调整行列后自动扩展/裁剪 | 导出后替换 splash_screen.py 中的 _PIXEL_FONT 数据")
        hint.setStyleSheet(f"color: {_tc('alias.text.tertiary')}; font-size: 11px;")
        layout.addWidget(hint)

    # ── 加载字母到网格 ──

    def _load_letter(self, ch: str) -> None:
        """将指定字母的数据加载到编辑网格。"""
        self._current_char = ch
        grid = self._font_data.get(ch, [])
        rows = len(grid)
        cols = len(grid[0]) if grid else 14

        self._rows_spin.setValue(rows)
        self._cols_spin.setValue(cols)

        self._build_grid(rows, cols, grid)
        self._update_preview()
        self._update_info()

    def _build_grid(self, rows: int, cols: int, data: list[list[int]]) -> None:
        """构建编辑网格。"""
        # 清除旧单元格
        for cell in self._cells:
            cell.deleteLater()
        self._cells.clear()
        self._grid_container.clear_cells()

        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for r in range(rows):
            for c in range(cols):
                cell = _GridCell(r, c, self._grid_container)
                val = data[r][c] if r < len(data) and c < len(data[r]) else 0
                cell.on = bool(val)
                self._cells.append(cell)
                self._grid_container.add_cell(cell)
                self._grid_layout.addWidget(cell, r, c)

    # ── 事件处理 ──

    def _on_cell_toggled(self, row: int, col: int, on: bool) -> None:
        """单元格被切换时更新数据。"""
        ch = self._current_char
        if ch in self._font_data and row < len(self._font_data[ch]):
            if col < len(self._font_data[ch][row]):
                self._font_data[ch][row][col] = 1 if on else 0
        self._update_preview()
        self._update_info()

    def _on_letter_changed(self, text: str) -> None:
        if text:
            self._load_letter(text)

    def _on_grid_resize(self) -> None:
        """网格尺寸变化时重新构建。"""
        rows = self._rows_spin.value()
        cols = self._cols_spin.value()
        ch = self._current_char
        old = self._font_data.get(ch, [])

        new_grid: list[list[int]] = []
        for r in range(rows):
            row_data: list[int] = []
            for c in range(cols):
                if r < len(old) and c < len(old[r]):
                    row_data.append(old[r][c])
                else:
                    row_data.append(0)
            new_grid.append(row_data)

        self._font_data[ch] = new_grid
        self._build_grid(rows, cols, new_grid)
        self._update_preview()
        self._update_info()

    def _reset_current(self) -> None:
        """重置当前字母为原始数据。"""
        ch = self._current_char
        original = _PIXEL_FONT.get(ch, [])
        self._font_data[ch] = [row[:] for row in original]
        self._load_letter(ch)

    # ── 预览 & 信息 ──

    def _update_preview(self) -> None:
        self._preview_label.set_font_data(
            {ch: grid for ch, grid in self._font_data.items()}
        )

    def _update_info(self) -> None:
        ch = self._current_char
        grid = self._font_data.get(ch, [])
        rows = len(grid)
        cols = len(grid[0]) if grid else 0
        total = sum(sum(row) for row in grid)
        total_cells = rows * cols
        self._info_label.setText(
            f"字母: {ch}  |  网格: {rows} x {cols}  |  "
            f"像素点: {total} / {total_cells}  ({total*100//max(total_cells,1)}%)"
        )

    # ── 保存 ──

    def _save(self) -> None:
        """保存字体数据到 splash_screen.py。"""
        ok = _save_font_to_file(self._font_data)
        if ok:
            QMessageBox.information(
                self, "保存成功",
                f"已保存到 splash_screen.py！\n\n"
                f"共 {sum(sum(row) for g in self._font_data.values() for row in g)} 个像素点"
            )
        else:
            QMessageBox.warning(
                self, "保存失败",
                f"无法写入 splash_screen.py，请检查文件权限。"
            )


class _PreviewLabel(QLabel):
    """预览渲染标签。"""

    def __init__(self, parent=None):
        QLabel.__init__(self, parent)
        self._data: dict[str, list[list[int]]] = {}
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(280, 180)

    def set_font_data(self, data: dict[str, list[list[int]]]) -> None:
        self._data = data
        self.update()

    def paintEvent(self, event) -> None:
        if not self._data:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint(0), False)

        painter.fillRect(self.rect(), QColor(15, 15, 25))

        text = "RELIC"
        base_ps = 3      # 基础像素大小
        pg = 0           # 无间距
        letter_gap = 2   # 字母间距（格数）

        # 计算原始总尺寸（以格数为单位）
        raw_w = 0
        max_h = 0
        char_dims: dict[str, tuple[int, int]] = {}
        for ch in text:
            grid = self._data.get(ch, [])
            w = len(grid[0]) if grid else 0
            h = len(grid) if grid else 0
            char_dims[ch] = (w, h)
            raw_w += w + letter_gap
            max_h = max(max_h, h)
        raw_w -= letter_gap

        if raw_w == 0 or max_h == 0:
            return

        # 自适应缩放：确保内容完整显示在预览区域内
        margin = 10
        avail_w = self.width() - margin * 2
        avail_h = self.height() - margin * 2
        scale_x = avail_w / raw_w
        scale_y = avail_h / max_h
        scale = min(scale_x, scale_y)
        ps = max(1, min(round(base_ps * scale), base_ps))  # 缩小时才生效，不放大
        lg_px = round(letter_gap * ps)

        # 计算实际渲染总宽高
        total_w = sum(char_dims[ch][0] * ps + lg_px for ch in text) - lg_px
        render_h = max_h * ps

        ox = round((self.width() - total_w) / 2)
        oy = round((self.height() - render_h) / 2)

        painter.translate(ox, oy)
        cx = 0

        for ch in text:
            grid = self._data.get(ch, [])
            if not grid:
                continue
            cols, rows = char_dims[ch]
            for r in range(rows):
                if r >= len(grid):
                    break
                row = grid[r]
                for c in range(cols):
                    if c >= len(row):
                        break
                    if row[c] == 1:
                        rx = cx + c * ps
                        ry = r * ps
                        painter.fillRect(rx, ry, ps, ps, QColor(255, 140, 0))
            cx += cols * ps + lg_px

        super().paintEvent(event)


class _PixelFontEditorPanel(QFrame):
    """内嵌式像素字体编辑面板（用于嵌入到主题页面中）。"""

    def __init__(self, parent=None):
        QFrame.__init__(self, parent)
        self._font_data: dict[str, list[list[int]]] = {}
        for ch, grid in _PIXEL_FONT.items():
            self._font_data[ch] = [row[:] for row in grid]

        self._current_char = "R"
        self._cells: list[_GridCell] = []
        self._setup_ui()
        self._load_letter("R")

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        # ── 第一行：字符按钮栏（所有字母横排展示）──
        char_row = QHBoxLayout()
        char_row.setSpacing(4)

        self._char_buttons: dict[str, QPushButton] = {}
        self._char_btn_layout = QHBoxLayout()
        self._char_btn_layout.setSpacing(3)
        char_row.addLayout(self._char_btn_layout)

        char_row.addSpacing(6)

        # 增删按钮
        btn_add = QPushButton("+")
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.setFixedSize(24, 24)
        btn_add.setToolTip("添加新字母")
        btn_add.clicked.connect(self._add_letter)
        char_row.addWidget(btn_add)

        btn_del = QPushButton("-")
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.setFixedSize(24, 24)
        btn_del.setToolTip("删除当前字母")
        btn_del.clicked.connect(self._del_letter)
        char_row.addWidget(btn_del)

        char_row.addStretch()
        layout.addLayout(char_row)

        self._rebuild_char_buttons()

        # ── 第二行：行列参数 + 操作按钮 + 信息 ──
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        ctrl_row.addWidget(QLabel("行列:"))
        self._rows_spin = QSpinBox()
        self._rows_spin.setRange(6, 24)
        self._rows_spin.setValue(len(_PIXEL_FONT["R"]))
        self._rows_spin.setFixedWidth(50)
        self._rows_spin.valueChanged.connect(self._on_grid_resize)
        self._rows_spin.installEventFilter(_WHEEL_BLOCKER)
        ctrl_row.addWidget(self._rows_spin)

        self._cols_spin = QSpinBox()
        self._cols_spin.setRange(4, 20)
        self._cols_spin.setValue(len(_PIXEL_FONT["R"][0]))
        self._cols_spin.setFixedWidth(50)
        self._cols_spin.valueChanged.connect(self._on_grid_resize)
        self._cols_spin.installEventFilter(_WHEEL_BLOCKER)
        ctrl_row.addWidget(self._cols_spin)

        ctrl_row.addSpacing(8)

        btn_save = QPushButton("保存")
        btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_save.setFixedWidth(48)
        btn_save.clicked.connect(self._save)
        ctrl_row.addWidget(btn_save)

        btn_reset = QPushButton("重置")
        btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reset.setFixedWidth(48)
        btn_reset.clicked.connect(self._reset_current)
        ctrl_row.addWidget(btn_reset)

        ctrl_row.addStretch()

        self._info_label = QLabel()
        self._info_label.setStyleSheet(f"color: {_tc('alias.text.tertiary')}; font-size: 11px;")
        ctrl_row.addWidget(self._info_label)

        layout.addLayout(ctrl_row)

        # ── 第二行：网格（固定尺寸，不拉伸）──
        grid_frame = QFrame()
        _grid_bg = _tc("bg.base")
        _grid_border = _tc("border.default")
        grid_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {_grid_bg};
                border: 1px solid {_grid_border};
                border-radius: {_TM.space('corner.xs', 4)}px;
            }}
        """)
        grid_outer = QVBoxLayout(grid_frame)
        grid_outer.setContentsMargins(2, 2, 2, 2)
        grid_outer.setSpacing(0)

        # 网格容器：固定尺寸，单元格紧密排列，支持拖拽绘制
        self._grid_container = _GridContainer()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(1)
        self._grid_layout.setContentsMargins(2, 2, 2, 2)

        grid_outer.addWidget(self._grid_container)
        layout.addWidget(grid_frame)

        # ── 第三行：实时预览（放在下面）──
        preview_group = QFrame()
        preview_group.setStyleSheet(f"""
            QFrame {{
                background-color: {_grid_bg};
                border: 1px solid {_grid_border};
                border-radius: {_TM.space('corner.xs', 4)}px;
            }}
        """)
        preview_outer = QVBoxLayout(preview_group)
        preview_outer.setContentsMargins(4, 4, 4, 4)
        preview_outer.setSpacing(2)

        preview_title = QLabel("实时预览")
        preview_title.setStyleSheet(f"color: {_tc('alias.text.disabled')}; font-size: {_TM.space('font.xs', 11)}px; font-weight: bold;")
        preview_outer.addWidget(preview_title)

        self._preview_label = _PreviewLabel()
        self._preview_label.setMinimumHeight(150)
        self._preview_label.setMaximumHeight(220)
        preview_outer.addWidget(self._preview_label)

        layout.addWidget(preview_group)

    # ── 字母增删 ──

    def _rebuild_char_buttons(self) -> None:
        """根据 _font_data 重建字符按钮栏。"""
        # 清除旧按钮
        for btn in self._char_buttons.values():
            btn.deleteLater()
        self._char_buttons.clear()
        while self._char_btn_layout.count():
            item = self._char_btn_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for ch in self._font_data:
            btn = QPushButton(ch)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(28, 24)
            btn.setToolTip(f"编辑字母 {ch}")
            btn.clicked.connect(lambda checked, c=ch: self._load_letter(c))
            self._char_buttons[ch] = btn
            self._char_btn_layout.addWidget(btn)

        self._highlight_active_button()

    def _highlight_active_button(self) -> None:
        """高亮当前选中字母的按钮。"""
        active_color = _tc("alias.accent.secondary")
        inactive_color = _tc("bg.base")
        active_border = _tc("alias.accent.primary")
        inactive_border = _tc("alias.border.default")
        hover_active = _tc("alias.accent.secondary")
        hover_inactive = _tc("alias.bg.raised")
        for ch, btn in self._char_buttons.items():
            is_active = (ch == self._current_char)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {active_color if is_active else inactive_color};
                    color: {_tc("text.primary")};
                    border: 1px solid {active_border if is_active else inactive_border};
                    border-radius: {_TM.space('corner.xs', 4)}px;
                    font-size: {_TM.space('font.body_md', 13)}px;
                    font-weight: {"bold" if is_active else "normal"};
                    padding: {_TM.space('spacing.none', 2)}px {_TM.space('spacing.xs', 6)}px;
                }}
                QPushButton:hover {{
                    background-color: {hover_active if is_active else hover_inactive};
                    border-color: {active_border};
                }}
            """)

    def _add_letter(self) -> None:
        """新增一个空白字母。"""
        existing = set(self._font_data.keys())
        candidates = [chr(c) for c in range(ord('A'), ord('Z') + 1)]
        new_ch = "?"
        for c in candidates:
            if c not in existing:
                new_ch = c
                break
        rows = self._rows_spin.value()
        cols = self._cols_spin.value()
        self._font_data[new_ch] = [[0] * cols for _ in range(rows)]
        self._rebuild_char_buttons()
        self._load_letter(new_ch)

    def _del_letter(self) -> None:
        """删除当前选中的字母。"""
        if len(self._font_data) <= 1:
            return
        ch = self._current_char
        del self._font_data[ch]
        remaining = list(self._font_data.keys())
        self._rebuild_char_buttons()
        if remaining:
            self._load_letter(remaining[0])
        self._update_preview()

    def _load_letter(self, ch: str) -> None:
        self._current_char = ch
        grid = self._font_data.get(ch, [])
        rows = len(grid)
        cols = len(grid[0]) if grid else 14
        self._rows_spin.setValue(rows)
        self._cols_spin.setValue(cols)
        self._build_grid(rows, cols, grid)
        self._highlight_active_button()
        self._update_preview()
        self._update_info()

    def _build_grid(self, rows: int, cols: int, data: list[list[int]]) -> None:
        for cell in self._cells:
            cell.deleteLater()
        self._cells.clear()
        self._grid_container.clear_cells()
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for r in range(rows):
            for c in range(cols):
                cell = _GridCell(r, c, self._grid_container)
                val = data[r][c] if r < len(data) and c < len(data[r]) else 0
                cell.on = bool(val)
                self._cells.append(cell)
                self._grid_container.add_cell(cell)
                self._grid_layout.addWidget(cell, r, c)

        # 固定容器大小 = 网格实际尺寸，防止拉伸
        cw = self._cells[0].width() + 1 if self._cells else 22
        ch_h = self._cells[0].height() + 1 if self._cells else 22
        w = cols * cw + 4
        h = rows * ch_h + 4
        self._grid_container.setFixedSize(w, h)

    def _on_cell_toggled(self, row: int, col: int, on: bool) -> None:
        ch = self._current_char
        if ch in self._font_data and row < len(self._font_data[ch]):
            if col < len(self._font_data[ch][row]):
                self._font_data[ch][row][col] = 1 if on else 0
        self._update_preview()
        self._update_info()

    def _on_grid_resize(self) -> None:
        rows = self._rows_spin.value()
        cols = self._cols_spin.value()
        ch = self._current_char
        old = self._font_data.get(ch, [])
        new_grid = [
            [old[r][c] if r < len(old) and c < len(old[r]) else 0 for c in range(cols)]
            for r in range(rows)
        ]
        self._font_data[ch] = new_grid
        self._build_grid(rows, cols, new_grid)
        self._update_preview()
        self._update_info()

    def _reset_current(self) -> None:
        ch = self._current_char
        original = _PIXEL_FONT.get(ch, [])
        if original:
            self._font_data[ch] = [row[:] for row in original]
        self._load_letter(ch)

    def _update_preview(self) -> None:
        self._preview_label.set_font_data(
            {ch: grid for ch, grid in self._font_data.items()}
        )

    def _update_info(self) -> None:
        ch = self._current_char
        grid = self._font_data.get(ch, [])
        rows = len(grid)
        cols = len(grid[0]) if grid else 0
        total = sum(sum(row) for row in grid)
        tc = rows * cols
        self._info_label.setText(
            f"{ch} | {rows}x{cols} | 像素 {total}/{tc}"
        )

    def _save(self) -> None:
        """保存字体数据到 splash_screen.py。"""
        ok = _save_font_to_file(self._font_data)
        if ok:
            QMessageBox.information(
                self, "保存成功",
                f"已保存到 splash_screen.py！"
            )
        else:
            QMessageBox.warning(
                self, "保存失败",
                f"无法写入 splash_screen.py，请检查文件权限。"
            )


# ── 独立运行入口（对话框模式）──

def run_editor(parent=None) -> None:
    """启动像素字体编辑器。"""
    editor = PixelFontEditor(parent)
    editor.exec()


if __name__ == "__main__":
    app = QApplication([])
    run_editor()
