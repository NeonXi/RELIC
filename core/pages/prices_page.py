"""
[L2] PricesPage — 价格数据页面（warframe.market 实时价格查询）。

依赖: widgets/, services/market_price_service.py
职责: 搜索物品、显示实时价格数据
"""
import json
import urllib.request
import urllib.error
import threading
from threading import Lock
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QTableWidget,
    QTableWidgetItem, QHeaderView, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import QApplication

from core.pages.base_page import PageBase
from core.widgets.line_edit import CyberLineEdit
from core.tokens.manager import TokenManager
from core.services.market_price_service import (
    fetch_wm_items,
    load_zh_name_map,
    search_wm_items,
    translate_wm_name,
    WM_API_ORDERS,
)

# ========== 常量 ==========
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "warframe.db"

STATUS_PRIORITY = {'ingame': 0, 'online': 1, 'away': 2, 'offline': 3}

# 状态显示文案键名（通过 _copy() 取值，不在此硬编码中文）
_STATUS_COPY_KEYS = {
    'ingame': 'prices.status_ingame',
    'online': 'prices.status_online',
    'offline': 'prices.status_offline',
    'away': 'prices.status_away',
}


# ============================================================
#  PriceFetcher — 后台线程查询 WM 价格
# ============================================================

class PriceFetcher(QThread):
    """异步查询 warframe.market 订单，流式逐条发送结果。"""
    progress_update = Signal(int, str)   # (percent, message)
    order_received = Signal(dict)        # 单条订单
    finished = Signal(bool, str)         # (success, message)

    def __init__(self, slug: str, en_name: str):
        super().__init__()
        self._slug = slug
        self._en_name = en_name
        self._lock = Lock()
        self._stop_flag = False

    def stop(self):
        with self._lock:
            self._stop_flag = True

    def _is_stopped(self):
        with self._lock:
            return self._stop_flag

    def run(self):
        try:
            self.progress_update.emit(10, "正在连接 warframe.market...")
            if self._is_stopped():
                return

            url = f"{WM_API_ORDERS}/{self._slug}"
            req = urllib.request.Request(url, headers={
                'Accept': 'application/json',
                'User-Agent': 'WARFRAME-RELIC',
                'Platform': 'pc',
                'Language': 'zh',
            })

            self.progress_update.emit(30, "获取订单数据中...")
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))

            orders = data.get('payload', {}).get('orders', [])
            if not orders and isinstance(data.get('data'), list):
                orders = data['data']

            sell_orders = [o for o in orders if isinstance(o, dict) and (
                o.get('order_type') == 'sell' or o.get('type') == 'sell'
            )]

            self.progress_update.emit(50, "处理卖家信息...")

            sell_orders.sort(key=lambda x: (
                STATUS_PRIORITY.get(x.get('user', {}).get('status', ''), 4),
                int(x.get('platinum', 0) or 0)
            ))

            online = [o for o in sell_orders
                      if o.get('user', {}).get('status') in ('ingame', 'online')]
            offline = [o for o in sell_orders
                       if o.get('user', {}).get('status') not in ('ingame', 'online')]
            limited = online + offline[:50]

            total = len(limited)
            if total == 0:
                self.finished.emit(True, "未找到卖家")
                return

            for i, order in enumerate(limited):
                if self._is_stopped():
                    return
                parsed = self._parse_order(order)
                self.order_received.emit(parsed)
                progress = 70 + int((i + 1) / total * 25)
                self.progress_update.emit(progress, f"已加载 {i + 1}/{total}")

            self.progress_update.emit(100, "完成")
            self.finished.emit(True, f"共找到 {total} 个卖家")

        except urllib.error.HTTPError as e:
            msg = f"HTTP 错误 {e.code}: {e.reason}" if e.code != 404 else "该物品不存在于市场"
            self.finished.emit(False, msg)
        except urllib.error.URLError as e:
            self.finished.emit(False, f"网络错误: {e}")
        except TimeoutError:
            self.finished.emit(False, "网络超时")
        except json.JSONDecodeError:
            self.finished.emit(False, "数据解析错误")
        except Exception as e:
            self.finished.emit(False, f"查询失败: {e}")

    def _parse_order(self, order: dict) -> dict:
        user = order.get('user', {})
        reputation = user.get('reputation', 0)
        if isinstance(reputation, dict):
            reputation = reputation.get('level', 0)

        username = user.get('ingameName') or user.get('ingame_name') or 'Unknown'
        # v2 API 用 'rank' 字段（Mod 为等级，Prime 部件为 0）
        item_level = int(order.get('rank', 0) or 0)

        return {
            'username': str(username),
            'status': str(user.get('status', 'offline')),
            'platinum': int(order.get('platinum', 0) or 0),
            'quantity': int(order.get('quantity', 1) or 1),
            'item_level': item_level,
            'reputation': int(reputation or 0),
        }


# ============================================================
#  PricesPage — 价格查询主页面
# ============================================================

class PricesPage(PageBase):
    page_id = "prices"
    page_title = ""
    page_icon = "nav_prices"

    def __init__(self):
        self._suppress_search = False                   # 防止 setText 触发重复搜索
        self._zh_name_map: dict[str, str] = load_zh_name_map(DB_PATH)
        self._cache_ready = False
        super().__init__()
        self.page_title = self._copy("nav.prices", "价格数据")
        self._price_fetcher: PriceFetcher | None = None
        self._search_timer = QTimer()
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._do_search)

    # ════════════════════════════════════
    #  主内容构建
    # ════════════════════════════════════

    def build_content(self) -> QWidget:
        _cp = self._copy
        _co = self._color
        _fs = self._font_size

        container = QWidget()
        self._root_layout = QVBoxLayout(container)
        self._root_layout.setContentsMargins(
            self._spacing("lg", 20), self._spacing("sm", 8),
            self._spacing("lg", 20), self._spacing("lg", 20)
        )
        self._root_layout.setSpacing(self._spacing("xs", 4))

        # ── 标题 ──
        title = QLabel(_cp("prices.title", "市场价格监控"))
        title.setFont(QFont("Iceberg", _fs("lg_xl", 18)))
        title.setStyleSheet(f"color: {_co('accent.primary')}; padding: 4px 0;")
        self._root_layout.addWidget(title)

        desc = QLabel(_cp("prices.desc", "Prime 物品在 warframe.market 的实时价格查询"))
        desc.setStyleSheet(
            f"color: {_co('text.tertiary')}; "
            f"font-size: {_fs('sm', 12)}px; padding: 0 0 12px 0;"
        )
        desc.setWordWrap(True)
        self._root_layout.addWidget(desc)

        # ── 搜索区域 ──
        self._build_search_area()

        # ── 统计摘要 ──
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(
            f"color: {_co('alias.text.tertiary')}; "
            f"font-size: {_fs('xs', 11)}px; padding: 4px 0;"
        )
        self._summary_label.hide()
        self._root_layout.addWidget(self._summary_label)

        # ── 结果表格 ──
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            _cp("prices.col_seller", "卖家"),
            _cp("prices.col_status", "状态"),
            _cp("prices.col_price", "价格"),
            _cp("prices.col_quantity", "数量"),
            _cp("prices.col_rank", "等级"),
            _cp("prices.col_reputation", "声望"),
        ])
        self._build_table_style()
        for col in range(6):
            self._table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().hide()
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._root_layout.addWidget(self._table, 1)

        # ── 状态标签 ──
        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            f"color: {_co('alias.text.tertiary')}; "
            f"font-size: {_fs('xs', 11)}px; padding: 4px 0;"
        )
        self._root_layout.addWidget(self._status_label)

        # 后台预加载 WM API 缓存，避免首次搜索卡顿
        self._warm_cache()

        return container

    # ════════════════════════════════════
    #  缓存预热
    # ════════════════════════════════════

    def _warm_cache(self):
        """后台线程预加载 WM API 物品列表，避免首次输入卡顿。"""
        class CacheWarmer(QThread):
            done = Signal()

            def run(self):
                fetch_wm_items()  # 触发下载 + 缓存
                self.done.emit()

        self._cache_warmer = CacheWarmer()
        self._cache_warmer.done.connect(self._on_cache_ready)
        self._cache_warmer.start()

    def _on_cache_ready(self):
        """缓存就绪。"""
        self._cache_ready = True

    # ════════════════════════════════════
    #  搜索区域
    # ════════════════════════════════════

    def _build_search_area(self):
        _cp = self._copy
        _co = self._color
        _fs = self._font_size

        search_card = QWidget()
        _search_accent = TokenManager.instance().get_qcolor("accent.secondary")
        search_card.setStyleSheet(
            f"background-color: rgba({_search_accent.red()}, {_search_accent.green()}, {_search_accent.blue()}, 0.03); "
            f"border-bottom: 1px solid {_co('alias.border.default')}; "
            f"padding: {self._spacing('spacing.xs', 8)}px 0;"
        )

        layout = QVBoxLayout(search_card)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)

        # 搜索输入行
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self._search_input = CyberLineEdit(
            placeholder=_cp("prices.ph_search", "输入物品名称搜索 (中文/英文/拼音)...")
        )
        self._search_input.setFixedHeight(self._spacing("height.input", 36))
        self._search_input.textChanged.connect(self._on_search_text_changed)
        input_row.addWidget(self._search_input, stretch=1)

        layout.addLayout(input_row)

        # 下拉结果列表
        self._dropdown = QListWidget()
        self._dropdown.setMaximumHeight(250)
        self._dropdown.setStyleSheet(self._dropdown_style())
        self._dropdown.itemClicked.connect(self._on_dropdown_item_clicked)
        self._dropdown.hide()
        layout.addWidget(self._dropdown)

        self._root_layout.insertWidget(3, search_card)

        # 键盘导航
        self._search_input.returnPressed.connect(self._on_enter_pressed)
        self._search_input.installEventFilter(self)

    def _dropdown_style(self) -> str:
        bg = self._color("surface.raised")
        text = self._color("text.primary")
        border = self._color("alias.border.default")
        accent = self._color("accent.primary")
        hover_bg = self._color("neutral.dark")
        _grid_color = TokenManager.instance().get_qcolor("border.subtle")

        return f"""
            QListWidget {{
                background-color: {bg};
                color: {text};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 4px;
                outline: none;
            }}
            QListWidget::item {{
                padding: 8px 12px;
                border-bottom: 1px solid rgba({_grid_color.red()}, {_grid_color.green()}, {_grid_color.blue()}, 0.15);
            }}
            QListWidget::item:hover {{
                background-color: {hover_bg};
            }}
            QListWidget::item:selected {{
                background-color: {hover_bg};
                color: {accent};
            }}
        """

    def eventFilter(self, obj, event):
        if obj == self._search_input and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Down:
                if self._dropdown.isVisible():
                    cur = self._dropdown.currentRow()
                    if cur < self._dropdown.count() - 1:
                        self._dropdown.setCurrentRow(cur + 1)
                    elif cur == -1 and self._dropdown.count() > 0:
                        self._dropdown.setCurrentRow(0)
                return True
            elif event.key() == Qt.Key.Key_Up:
                if self._dropdown.isVisible():
                    cur = self._dropdown.currentRow()
                    if cur > 0:
                        self._dropdown.setCurrentRow(cur - 1)
                return True
            elif event.key() == Qt.Key.Key_Escape:
                self._dropdown.hide()
                return True
        return super().eventFilter(obj, event)

    # ════════════════════════════════════
    #  表格样式
    # ════════════════════════════════════

    def _build_table_style(self):
        bg = self._color("panel.bg")
        text = self._color("text.primary")
        accent = self._color("accent.primary")
        header_bg = self._color("surface.raised")
        border = self._color("alias.border.default")
        hover_bg = self._color("neutral.dark")
        _grid_color = TokenManager.instance().get_qcolor("border.subtle")

        self._table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {bg};
                color: {text};
                border: none;
                gridline-color: rgba({_grid_color.red()}, {_grid_color.green()}, {_grid_color.blue()}, 0.12);
                outline: none;
            }}
            QTableWidget::item {{
                padding: 8px 10px;
                border: none;
                outline: none;
            }}
            QTableWidget::item:hover {{
                background-color: {hover_bg};
            }}
            QTableWidget::item:selected {{
                background-color: {hover_bg};
            }}
            QHeaderView::section {{
                background-color: {header_bg};
                color: {accent};
                padding: 8px 10px;
                border: none;
                border-bottom: 1px solid {border};
                font-weight: bold;
            }}
            QTableCornerButton::section {{
                background-color: {header_bg};
                border: none;
            }}
        """)

    # ════════════════════════════════════
    #  搜索逻辑
    # ════════════════════════════════════

    def _on_search_text_changed(self, text: str):
        if self._suppress_search:
            return
        if text.strip():
            self._search_timer.start(150)
        else:
            self._dropdown.hide()

    def _do_search(self):
        keyword = self._search_input.text().strip()
        if not keyword:
            return

        results = self._search_items(keyword)
        self._show_dropdown(results)

    def _search_items(self, keyword: str) -> list[dict]:
        """搜索物品：调用服务层混合搜索（WM API + 本地 DB）。"""
        return search_wm_items(keyword, DB_PATH, self._zh_name_map)

    def _show_dropdown(self, items: list[dict]):
        self._dropdown.clear()
        if not items:
            self._dropdown.hide()
            return

        for item in items:
            zh = item.get('zh_name', '')
            en = item['name']
            display = f"{zh}  ({en})" if zh and zh != en else en
            list_item = QListWidgetItem(display)
            list_item.setData(Qt.ItemDataRole.UserRole, item)
            self._dropdown.addItem(list_item)

        self._dropdown.setMaximumHeight(min(len(items) * 40, 250))
        self._dropdown.show()

    def _on_enter_pressed(self):
        if self._dropdown.isVisible():
            item = self._dropdown.currentItem()
            if item:
                self._on_dropdown_item_clicked(item)

    def _on_dropdown_item_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self._dropdown.hide()
            zh = data.get('zh_name', '')
            display = f"{zh} ({data['name']})" if zh and zh != data['name'] else data['name']
            self._suppress_search = True
            self._search_input.setText(display)
            self._suppress_search = False
            self._on_query_price(data)

    # ════════════════════════════════════
    #  价格查询流程
    # ════════════════════════════════════

    def _on_query_price(self, item_data: dict):
        name = item_data['name']
        slug = item_data['slug']

        # 清旧数据
        self._table.setRowCount(0)
        self._summary_label.hide()
        self._status_label.setText(self._copy("prices.status_querying", "正在查询..."))

        # 取消旧请求
        if self._price_fetcher and self._price_fetcher.isRunning():
            self._price_fetcher.stop()
            self._price_fetcher.wait(2000)

        self._price_fetcher = PriceFetcher(slug, name)
        self._price_fetcher.progress_update.connect(self._on_progress)
        self._price_fetcher.order_received.connect(self._on_order)
        self._price_fetcher.finished.connect(self._on_fetch_done)
        self._price_fetcher.start()

    def _on_progress(self, percent: int, message: str):
        self._status_label.setText(message)

    def _on_order(self, order: dict):
        row = self._table.rowCount()
        self._table.insertRow(row)

        # 卖家名
        username = order.get('username', 'Unknown')
        uname_item = QTableWidgetItem(username)
        uname_item.setData(Qt.ItemDataRole.UserRole, username)
        uname_item.setForeground(QColor(self._color('accent.secondary')))
        uname_item.setFlags(uname_item.flags() | Qt.ItemFlag.ItemIsSelectable)
        uname_item.setToolTip(self._copy("prices.tip_copy_username", "点击复制用户名"))
        self._table.setItem(row, 0, uname_item)

        # 状态
        status = order.get('status', 'offline')
        status_text = self._copy(_STATUS_COPY_KEYS.get(status, ''), status)
        status_item = QTableWidgetItem(status_text)
        status_color = self._status_color(status)
        status_item.setForeground(QColor(status_color))
        self._table.setItem(row, 1, status_item)

        # 价格
        platinum = order.get('platinum', 0)
        price_item = QTableWidgetItem(str(platinum))
        price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, 2, price_item)

        # 数量
        qty = order.get('quantity', 1)
        qty_item = QTableWidgetItem(str(qty))
        qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, 3, qty_item)

        # 等级
        level = order.get('item_level', 0)
        level_item = QTableWidgetItem(f"{level} ●{'●' * (level - 1)}" if level > 0 else "-")
        level_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, 4, level_item)

        # 声望
        rep = order.get('reputation', 0)
        rep_item = QTableWidgetItem(str(rep))
        rep_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, 5, rep_item)

    def _status_color(self, status: str) -> str:
        return {
            'ingame':  self._color('brand.green'),
            'online':  self._color('accent.secondary'),
            'offline': self._color('text.tertiary'),
            'away':    self._color('alias.text.tertiary'),
        }.get(status, self._color('text.tertiary'))

    def _on_fetch_done(self, success: bool, message: str):
        self._status_label.setText(message)

        if not success and self._table.rowCount() == 0:
            # 错误信息显示在表格中
            self._table.setRowCount(1)
            self._table.setColumnCount(1)
            self._table.setHorizontalHeaderLabels([""])
            err_item = QTableWidgetItem(message)
            err_item.setForeground(QColor(self._color('semantic.warning')))
            err_item.setFlags(err_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(0, 0, err_item)
            return

        # 更新摘要
        self._update_summary()

    def _update_summary(self):
        row_count = self._table.rowCount()
        if row_count == 0:
            return

        prices = []
        for r in range(row_count):
            item = self._table.item(r, 2)
            if item:
                try:
                    prices.append(int(item.text()))
                except ValueError:
                    pass

        if not prices:
            return

        prices.sort()
        min_p = prices[0]
        max_p = prices[-1]
        median_p = prices[len(prices) // 2]
        avg_p = sum(prices) / len(prices)

        self._summary_label.setText(
            self._copy("prices.summary_format",
                "共 {count} 个卖家  |  最低 {min_p}p  |  "
                "中位 {median_p}p  |  均价 {avg_p:.1f}p  |  最高 {max_p}p",
                count=row_count, min_p=min_p, median_p=median_p,
                avg_p=avg_p, max_p=max_p)
        )
        self._summary_label.show()

    def _on_cell_clicked(self, row: int, col: int):
        if col == 0:
            item = self._table.item(row, col)
            if item:
                username = item.data(Qt.ItemDataRole.UserRole)
                if username:
                    whisper = f"/w {username}"
                    QApplication.clipboard().setText(whisper)
                    self._status_label.setText(
                        self._copy("prices.status_copied", "已复制悄悄话: {text}", text=whisper)
                    )

    # ════════════════════════════════════
    #  页面生命周期
    # ════════════════════════════════════

    def on_page_leave(self):
        if self._price_fetcher and self._price_fetcher.isRunning():
            self._price_fetcher.stop()