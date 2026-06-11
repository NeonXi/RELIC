"""
AppShell — 新 UI 主窗口框架 (L0 + L1)。

替代旧的 ManagementPanel，作为新架构的顶层容器：
  - L0: 窗口外壳（背景、尺寸、DPI）
  - L1: 导航栏 + 内容区（左侧导航 + 右侧页面栈）

结构::

  ┌──────────────────────────────────────────────┐
  │  AppShell (L0 窗口)                          │
  │ ┌────────┬───────────────────────────────────┐│
  │ │        │                                   ││
  │ │ NavBar │   Content Area (L2~L5 Pages)     ││
  │ │ (L1)   │   QStackedWidget                 ││
  │ │        │                                   ││
  │ │        │                                   ││
  │ └────────┴───────────────────────────────────┘│
  └──────────────────────────────────────────────┘

使用方式::

    from core.app_shell import AppShell
    shell = AppShell()
    shell.show()
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QScrollArea, QSizePolicy,
    QListWidgetItem, QFrame, QLabel,
)
from PySide6.QtCore import Qt, QSize, Signal, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QBrush

from core.tokens.manager import TokenManager
from core.widgets.base import CyberWidgetMixin


# ══════════════════════════════════════════════
#  导航项定义（与旧 panel_builder.py 保持一致）
# ══════════════════════════════════════════════

NAV_ITEMS = [
    ("toggles",     "功能开关"),
    ("db_overview", "数据总览"),
    ("items",       "物品查询"),
    ("triggers",    "辅助触发器"),
    ("prices",      "价格数据"),
    ("theme",       "主题换肤"),
    ("preset",      "语言预设"),
    ("about",       "关于作者"),
]

# 页面类映射（懒导入，避免循环依赖）
_PAGE_CLASS_MAP = {
    "toggles":     "core.pages.toggles_page:TogglesPage",
    "db_overview": "core.pages.status_page:StatusPage",
    "items":       "core.pages.items_page:ItemsPage",
    "triggers":    "core.pages.triggers_page:TriggersPage",
    "prices":      "core.pages.prices_page:PricesPage",
    "theme":       "core.pages.theme_page:ThemePage",
    "preset":      "core.pages.preset_page:PresetPage",
    "about":       "core.pages.about_page:AboutPage",
}


# ══════════════════════════════════════════════
#  赛博朋克导航标签组件
# ══════════════════════════════════════════════

class NavTab(QFrame, CyberWidgetMixin):
    """赛博朋克风格导航标签。

    左侧装饰竖条 + 右下角切角主内容区。
    支持 hover / selected 态切换。
    """

    clicked = Signal(str)

    def __init__(self, nav_id: str, label: str, parent=None):
        super().__init__(parent)
        CyberWidgetMixin.__init__(self)
        self._nav_id = nav_id
        self._nav_label = label
        self._selected = False
        self._hover = False
        self.setMouseTracking(True)
        self.setFixedHeight(TokenManager.instance().space("nav.item_height", 36))

    def set_selected(self, selected: bool):
        self._selected = selected
        self.update()

    @property
    def nav_id(self) -> str:
        return self._nav_id

    # ---- 事件 ----

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, event):
        self._hover = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._nav_id)

    # ---- 绘制 ----

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # hover 时视觉放大 1.08 倍，不改变实际布局大小
        if self._hover:
            cx, cy = self.width() / 2, self.height() / 2
            painter.translate(cx, cy)
            painter.scale(1.04, 1.04)
            painter.translate(-cx, -cy)
        self._draw_nav_tab(painter, text=self._nav_label, selected=self._selected, hover=self._hover)


# ══════════════════════════════════════════════
#  AppShell 主窗口
# ══════════════════════════════════════════════

class AppShell(QMainWindow):
    """新 UI 主窗口框架。

    职责：
    - 窗口管理（标题、尺寸、背景色）
    - 左侧导航栏构建与切换
    - 右侧内容区页面栈管理
    - 页面注册与生命周期调度
    """

    def __init__(self, *, show_splash: bool = True, app=None):
        super().__init__()
        self._tm = TokenManager.instance()
        self._qt_app = app

        # 页面缓存 {page_id: PageBase instance}
        self._pages: dict = {}
        # 当前页面 ID
        self._current_id: str = ""

        # ── 截图OCR管线服务 ──
        self._pipeline_svc = None

        # ── 辅助触发器引擎 ──
        self._trigger_manager = self._create_trigger_manager()

        self._setup_window()
        self._register_fonts()

        # ── 开启动画 ──
        if show_splash:
            self._show_splash_and_build()
        else:
            self._build_ui()
            self._register_pages()
            self._start_pipeline()
            self._switch_to(NAV_ITEMS[0][0])

    # ══════════════════════════════════
    #  窗口设置
    # ══════════════════════════════════

    def _setup_window(self):
        """设置窗口属性。"""
        self.setWindowTitle("WARFRAME-RELIC")
        self.setMinimumSize(860, 640)

        # 深空背景
        bg_str = self._tm.get("surface.base", "#08081A")
        self.setStyleSheet(f"""
            QMainWindow {{
                background-color: {bg_str};
            }}
        """)

    # ══════════════════════════════════
    #  字体注册
    # ══════════════════════════════════

    def _register_fonts(self):
        """注册内嵌字体（必须在创建任何 UI 之前调用）。"""
        from core import fonts
        registered = fonts.register_all()
        if registered:
            print(f"[AppShell] 内嵌字体已加载: {', '.join(registered)}", flush=True)

    # ══════════════════════════════════
    #  开启动画
    # ══════════════════════════════════

    def _show_splash_and_build(self) -> None:
        """先显示主窗口 + 构建完整 UI，再用透明 overlay 跑启动动画。"""
        from core.widgets.splash_screen import CyberSplashScreen

        # 1. 显示主窗口
        self.show()

        # 2. 构建完整 UI
        print("[Splash] 开始构建 UI...", flush=True)
        self._build_ui()
        self._register_pages()
        self._start_pipeline()
        self._switch_to(NAV_ITEMS[0][0])
        print(f"[Splash] UI 构建完成, 页面数={len(self._pages)}", flush=True)

        # 3. 覆盖启动动画（父控件 = AppShell 自身，fill 整个窗口）
        self._splash = CyberSplashScreen(
            parent=self, enabled=True,
            on_finished=self._on_splash_finished)
        self._splash.setGeometry(0, 0, self.width(), self.height())
        # 窗口大小变化时同步 overlay
        _orig_resize = self.resizeEvent
        def _sync_resize(event):
            _orig_resize(event)
            if self._splash:
                self._splash.resize(event.size())
        self.resizeEvent = _sync_resize
        self._splash_orig_resize = _orig_resize
        self._splash.show()

    def _on_splash_finished(self) -> None:
        """动画结束回调：销毁 overlay，展示 UI。"""
        print(f"[AppShell] 动画结束, 销毁 overlay", flush=True)
        if self._splash:
            self._splash.close()
            self._splash.deleteLater()
        self._splash = None
        if hasattr(self, '_splash_orig_resize'):
            self.resizeEvent = self._splash_orig_resize

    def _create_trigger_manager(self):
        """创建辅助触发器引擎。"""
        import sys
        try:
            from core.trigger_manager import TriggerManager

            def _log(msg: str, log_type: str, source: str):
                sys.stderr.write(f"[{source}] [{log_type}] {msg}\n")
                sys.stderr.flush()

            mgr = TriggerManager(log_func=_log)
            mgr.set_ui_focus_check(self._has_ui_focus)
            mgr.start()
            sys.stderr.write(f"[AppShell] TriggerManager 创建成功 | running={mgr.is_running}\n")
            sys.stderr.flush()
            return mgr
        except Exception:
            import traceback
            sys.stderr.write(f"[AppShell] TriggerManager 创建失败:\n")
            traceback.print_exc(file=sys.stderr)
            sys.stderr.flush()
            return None

    def _has_ui_focus(self) -> bool:
        """检查当前是否有 UI 控件拥有焦点（用于防误触）。"""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return False
        fw = app.focusWidget()
        return fw is not None

    def _start_pipeline(self) -> None:
        """启动截图OCR管线服务。"""
        try:
            if self._qt_app is None:
                from PySide6.QtWidgets import QApplication
                self._qt_app = QApplication.instance()
            if self._qt_app:
                from core.services.screenshot_pipeline import ScreenshotPipelineService
                self._pipeline_svc = ScreenshotPipelineService(self._qt_app)
                self._pipeline_svc.start()
                print(f"[AppShell] 截图管线已启动", flush=True)
        except Exception as e:
            print(f"[AppShell] 截图管线启动失败: {e}", flush=True)

    # ══════════════════════════════════
    #  UI 构建
    # ══════════════════════════════════

    def _build_ui(self):
        """构建整体布局：导航栏 + 内容区。"""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 左侧导航栏 ──
        self._nav_container = self._build_nav_bar()
        main_layout.addWidget(self._nav_container)

        # ── 右侧内容区 ──
        self._content_stack = QStackedWidget()
        self._content_stack.setStyleSheet("background-color: transparent;")
        main_layout.addWidget(self._content_stack, stretch=1)

    def _build_nav_bar(self) -> QWidget:
        """构建左侧导航栏。"""
        container = QWidget()
        container.setFixedWidth(self._tm.space("nav.bar_container_width", 148))

        nav_bg_str = self._tm.get("bg.base", "#08081A")
        border_str = self._tm.get("border.subtle", "#334477")

        container.setStyleSheet(f"""
            QWidget#navContainer {{
                background-color: {nav_bg_str};
                border-right: 1px solid {border_str};
            }}
        """)
        container.setObjectName("navContainer")

        layout = QVBoxLayout(container)
        layout.setContentsMargins(
            self._tm.space("spacing.sm", 8),
            self._tm.space("spacing.lg", 16),
            self._tm.space("spacing.sm", 8),
            self._tm.space("spacing.sm", 8),
        )
        layout.setSpacing(self._tm.space("spacing.md", 12))
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 品牌标题
        brand_title = QLabel("WF RELIC")
        font_size = self._tm.space("font.lg", 16)
        title_font = QFont("Alibaba PuHuiTi 3", font_size, QFont.Weight.Normal)
        brand_title.setFont(title_font)
        accent_color = self._tm.get("accent.primary", "#FFE600")
        brand_title.setStyleSheet(f"""
            color: {accent_color};
            padding: {self._tm.space('spacing.sm', 8)}px 0;
            border: none;
        """)
        brand_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(brand_title)

        # 分隔线
        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {border_str};")
        layout.addWidget(divider)

        layout.addSpacing(self._tm.space("spacing.md", 12))

        # 导航标签列表
        self._nav_tabs: list[NavTab] = []
        for nav_id, label in NAV_ITEMS:
            tab = NavTab(nav_id, label)
            tab.clicked.connect(self._on_nav_clicked)
            layout.addWidget(tab)
            self._nav_tabs.append(tab)

        layout.addStretch()

        return container

    # ══════════════════════════════════
    #  页面注册与管理
    # ══════════════════════════════════

    def _register_pages(self):
        """注册所有页面到内容栈。"""
        print(f"[AppShell] 开始注册页面 (共 {len(NAV_ITEMS)} 个)...", flush=True)
        for nav_id, _label in NAV_ITEMS:
            print(f"[AppShell]   正在创建: {nav_id} ...", flush=True)
            page = self._create_page(nav_id)
            if page is not None:
                page.set_app_shell(self)
                self._pages[nav_id] = page
                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                accent = self._tm.get("accent.secondary", "#00FFFF")
                sub = self._tm.get("border.subtle", "#334477")
                text_dim = self._tm.get("text.dim", "#556688")
                scroll.setStyleSheet(f"""
                    QScrollArea {{
                        border: none;
                        background-color: transparent;
                    }}
                    QScrollBar:vertical {{
                        background: transparent;
                        width: 8px;
                        margin: 0;
                    }}
                    QScrollBar::handle:vertical {{
                        background: {sub};
                        border-radius: 4px;
                        min-height: 30px;
                    }}
                    QScrollBar::handle:vertical:hover {{
                        background: {accent};
                    }}
                    QScrollBar::add-line:vertical,
                    QScrollBar::sub-line:vertical {{
                        height: 0;
                        border: none;
                    }}
                    QScrollBar::add-page:vertical,
                    QScrollBar::sub-page:vertical {{
                        background: transparent;
                    }}
                """)
                scroll.setWidget(page)
                self._content_stack.addWidget(scroll)

        print(f"[AppShell] 页面注册完成: {list(self._pages.keys())}", flush=True)

    def _create_page(self, nav_id: str):
        """通过懒导入创建页面实例。"""
        class_path = _PAGE_CLASS_MAP.get(nav_id)
        if not class_path:
            return None

        module_path, class_name = class_path.rsplit(":", 1)
        try:
            import importlib
            import traceback
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
            instance = cls()
            print(f"[AppShell] 页面 '{nav_id}' 创建成功", flush=True)
            return instance
        except Exception as e:
            print(f"[AppShell] 创建页面 '{nav_id}' 失败: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return None

    # ══════════════════════════════════
    #  导航切换
    # ══════════════════════════════════

    def _on_nav_clicked(self, nav_id: str):
        """导航项被点击。"""
        self._switch_to(nav_id)

    def _switch_to(self, nav_id: str):
        """切换到指定页面。"""
        print(f"[AppShell] _switch_to('{nav_id}'), current='{self._current_id}'", flush=True)

        if nav_id == self._current_id:
            return

        # 旧页面离开
        if self._current_id and self._current_id in self._pages:
            old_page = self._pages[self._current_id]
            old_page.on_leave()

        # 更新导航选中态
        for tab in self._nav_tabs:
            tab.set_selected(tab.nav_id == nav_id)

        # 切换内容栈
        page_idx = self._page_index(nav_id)
        print(f"[AppShell]   page_index={page_idx}, total={self._content_stack.count()}, pages={list(self._pages.keys())}", flush=True)
        if page_idx >= 0:
            self._content_stack.setCurrentIndex(page_idx)
        else:
            print(f"[AppShell]   警告: 页面 '{nav_id}' 未找到!", flush=True)

        # 新页面进入
        self._current_id = nav_id
        if nav_id in self._pages:
            new_page = self._pages[nav_id]
            new_page.on_enter()

    def _page_index(self, nav_id: str) -> int:
        """获取页面在 stack 中的索引。"""
        for i in range(self._content_stack.count()):
            scroll = self._content_stack.widget(i)
            widget = scroll.widget() if hasattr(scroll, 'widget') else None
            if widget and hasattr(widget, 'page_id') and widget.page_id == nav_id:
                return i
        return -1

    @property
    def pipeline(self):
        """获取截图OCR管线服务实例。"""
        return self._pipeline_svc
