# WARFRAME-RELIC 项目开发规范（AI 协作指令）

> **这是本项目的唯一权威规范文件**。每次开始工作前必须完整阅读。
> 不需要记忆任何内容，但写代码时必须能在这里找到答案。
> 详细设计文档见: `docs/ui-framework-design.md` 和 `docs/ui-refactor-analysis.md`

---

## 零、快速自查卡（写完代码后逐条检查）

> 如果你赶时间，至少检查这 10 条。每条不通过 = 代码不合格。

```
□ 1. 新文件在 core/ 子目录下，不在根目录
□ 2. 没有 from PySide6 / import QtWidgets 出现在 services/ 文件中
□ 3. 新代码用 PySide6（不是 PyQt6），没有 pyqtSignal/pyqtSlot
□ 4. 没有出现 #XXXXXX 或 rgb(...) 形式的硬编码颜色
□ 5. 没有出现 setStyleSheet( 字符串
□ 6. 没有出现数字 26/34/38 这种非 4 的倍数的尺寸值
□ 7. 组件类继承了正确的 Qt 原生控件（不是从 QWidget 零开始）
□ 8. paintEvent 中先画自定义背景，再调 super().paintEvent()
□ 9. __init__ 中显式调用 目标基类.__init__()，不是 super().__init__()
□ 10. 没有修改 panel_builder.py / management_panel.py / panel_styles.py
□ 11. 文件头有层级声明注释，说明这个文件属于哪一层
```

---

## 一、项目概况

- **类型**: PySide6 桌面应用（Warframe 遗物辅助工具）
- **当前状态**: 正在进行 UI 重构（从旧架构迁移到新 Design System）
- **技术栈**: Python 3.12 + PySide6 + QPainter 自绘组件
- **入口文件（旧系统）**: `main.py`
- **入口文件（新系统）**: `app_shell.py` — 独立入口，开发期与旧系统完全隔离
- **核心目录**: `core/`
- **设计风格**: Cyberpunk Chamfered（科幻切角）— 切角矩形 + 霓虹外发光 + 角落装饰线

---

## 二、当前重构阶段

**正在执行: 从零搭建新 UI，渐进式迁移。详见 `docs/ui-refactor-analysis.md`**

四步走进度:
- **Phase 0**: 提取纯逻辑到 `core/services/` （进行中）
- **Phase 1**: 搭建新 UI 骨架 (`core/tokens/`, `core/widgets/`, `core/app_shell.py`)
- **Phase 2**: 逐页实现 `core/pages/`
- **Phase 3**: 切换主入口，废弃旧代码

**关键原则**: 旧代码 (`panel_builder.py`, `management_panel.py`, `panel_styles.py`) **只读不写**。

### Qt 框架选型（铁律）

> **新代码必须用 PySide6，旧代码用 PyQt6，两者不能混用。**

| 版本 | Qt 框架 | 文件范围 | 规则 |
|------|---------|---------|------|
| **旧版（运行中）** | **PyQt6** | main.py, management_panel.py, overlay.py, panel_builder.py 等 ~12 个文件 | **只读不写** |
| **新版（重构中）** | **PySide6** | core/app_shell.py, core/pages/*, core/widgets/*, core/state/*, run_new_ui.py 等 | **必须用这个** |

迁移时对照表：

| PyQt6 (旧) → PySide6 (新) |
|-----------|
| `from PyQt6.QtWidgets` → `from PySide6.QtWidgets` |
| `from PyQt6.QtCore` → `from PySide6.QtCore` |
| `from PyQt6.QtGui` → `from PySide6.QtGui` |
| `pyqtSignal(...)` → `Signal(...)` |
| `pyqtSlot(...)` → `Slot(...)` |

**写新文件时如果写了 `PyQt6` 或 `pyqtSignal` = 严重错误。**

---

## 三、目录结构与分层规则

```
core/
├── tokens/          # L-Infrastructure: Token 系统（颜色+尺寸），纯数据，无 Qt 依赖
│   ├── __init__.py
│   ├── manager.py       # TokenManager 单例类（全局入口）
│   ├── resolver.py      # Token 解析引擎（@引用、函数变换）
│   ├── schema.py        # YAML 结构校验
│   └── functions.py     # 颜色函数（lighten/darken/mix/alpha 等）
│
├── widgets/         # L4+L5: Cyber Widget 组件库（自绘控件），只依赖 tokens/
│   ├── __init__.py
│   ├── base.py          # CyberWidgetMixin（切角路径/状态机/发光绘制/Token 访问接口）
│   ├── button.py        # CyberButton(CyberWidgetMixin, QPushButton)
│   ├── input.py         # CyberInput(CyberWidgetMixin, QLineEdit)
│   ├── label.py         # CyberLabel(CyberWidgetMixin, QLabel)
│   ├── toggle.py        # CyberToggle(CyberWidgetMixin, QCheckBox)
│   ├── panel.py         # CyberPanel(CyberWidgetMixin, QFrame)
│   ├── card.py          # CyberCard(CyberWidgetMixin, QFrame)
│   ├── dialog.py        # CyberDialog
│   ├── progress.py      # CyberProgress(CyberWidgetMixin, QProgressBar)
│   ├── combo.py         # CyberCombo(CyberWidgetMixin, QComboBox)
│   ├── icon.py          # CyberIcon
│   └── badge.py         # CyberBadge
│
├── pages/           # L2: 页面（每个导航项一个文件），依赖 widgets/ + services/
│   ├── __init__.py
│   ├── base_page.py     # BasePage 抽象基类
│   ├── toggles_page.py      # 功能开关页
│   ├── db_overview_page.py  # 数据总览页
│   ├── items_page.py        # 物品查询页
│   ├── triggers_page.py     # 辅助触发器页
│   ├── prices_page.py       # 价格数据页
│   ├── hotkeys_page.py      # 快捷键配置页
│   ├── theme_page.py        # 主题换肤页
│   ├── reset_page.py        # 紧急重置页
│   ├── preset_page.py       # 语言预设页
│   └── about_page.py        # 关于作者页
│
├── sections/        # L3: 功能区块组件，被 pages/ 引用
│   ├── __init__.py
│   ├── cyber_section.py     # CyberSection 基类
│   ├── hotkey_section.py    # 快捷键配置区块
│   ├── trigger_section.py   # 触发器配置区块
│   ├── theme_edit_section.py    # 颜色编辑区块
│   ├── theme_bg_section.py      # 背景设置区块
│   ├── db_stats_section.py      # 数据库状态区块
│   ├── item_search_section.py   # 物品搜索区块
│   ├── price_section.py         # 价格查询区块
│   ├── reset_section.py         # 紧急重置区块
│   ├── about_section.py         # 关于作者区块
│   └── preset_section.py        # 语言预设区块
│
├── services/       # 纯逻辑层（从旧代码提取），禁止 import PySide6
│   ├── __init__.py
│   ├── toggle_service.py    # 开关状态管理
│   ├── hotkey_service.py    # 快捷键配置管理
│   ├── item_service.py      # 物品搜索/过滤逻辑
│   ├── price_service.py     # 价格查询逻辑
│   ├── trigger_service.py   # 触发器配置逻辑
│   └── config_service.py    # 配置文件读写
│
├── app_shell.py     # L0+L1: 主窗口外壳（窗口框架 + 导航栏）
│
├── management_panel.py  # ← 旧代码，deprecated，不修改
├── panel_builder.py     # ← 旧代码，deprecated，不修改
├── panel_styles.py      # ← 旧代码，deprecated，不修改
├── theme_config.py      # 保留（向后兼容，逐渐降级为薄包装）
├── theme_proxy.py       # 保留（兼容期过渡，最终废弃）
├── theme_fields.py      # 保留（主题编辑面板用到）
├── theme_panel.py       # 修改：改为编辑 YAML 预设
├── stylesheet.py        # 保留（仅处理未替换的原生控件）
│
data/
├── presets/             # 预设文件（JSON → 迁移为 YAML）
│   ├── cyberpunk.yaml   # ★ 新版赛博朋克预设
│   ├── daylight.yaml    # ★ 新版亮色预设
│   ├── custom.yaml      # ★ 新版用户自定义
│   ├── cyberpunk.json   # (保留兼容，迁移完成后删除)
│   ├── daylight.json    # (保留兼容，迁移完成后删除)
│   └── custom.json      # (保留兼容，迁移完成后删除)
│
docs/
└── ui-framework-design.md   # ★ 完整 Design System 设计文档
└── ui-refactor-analysis.md  # ★ 重构决策分析报告
```

### 层级职责（绝对铁律）

| 层 | 目录 | 职责 | 允许依赖 | 禁止依赖 |
|----|------|------|---------|---------|
| Infrastructure | `tokens/` | Token 解析（颜色/尺寸） | Python 标准库 + PyYAML | Qt |
| Service | `services/` | 业务逻辑（CRUD/搜索/计算） | data/, core/hotkey_config.py 等**纯模块** | **PySide6**, QtWidgets, QtGui |
| Widget | `widgets/` | 自绘控件（绘制+交互+发射信号） | tokens/ | services/, data/, 业务逻辑 |
| Section | `sections/` | 功能区块容器（组装 Widget） | widgets/, services/ | 直接操作数据 |
| Page | `pages/` | 页面（组装 Section + 连接信号） | sections/, widgets/, services/ | setStyleSheet f-string |
| Shell | `app_shell.py` | 窗口框架 + 导航 | pages/ | 业务逻辑 |

### 单向依赖规则（禁止循环依赖）

```
tokens/ ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
   ↑                                                              │
   │  (只读)                                                       │
   │                                                              ↓
widgets/ ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ → pages/
   ↑       ↑                                                      │
   │       │ (组装)                                               │
   │       ↓                                                      ↓
services/ ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ → sections/

禁止事项:
- services/ 不能反向依赖 widgets/pages/shell
- widgets/ 不能调用 services/ 的方法
- 任何层不能平级或向下依赖（如 pages/ 依赖 app_shell/）
```

---

## 四、Design System 规范

### 4.1 颜色：必须使用 Token，禁止硬编码

```python
# ✅ 正确：通过 token 获取颜色
from core.tokens.manager import TokenManager
bg_color = TokenManager.get().resolve("bg.raised")
# 或在 Mixin 子类中：
bg_color = self.token("bg.raised")

text_color = self.token("text.primary")
accent = self.token("accent.primary")

# ❌ 错误：硬编码颜色值
bg_color = "#0E0E24"
text_color = "#E8ECFF"
```

Token 路径格式: `{类别}.{名称}`，例如:
- `raw.brand.yellow`, `alias.accent.primary`
- `semantic.primary`, `semantic.danger`
- `bg.base`, `bg.raised`, `bg.overlay`
- `text.primary`, `text.secondary`, `text.disabled`
- `border.default`, `border.focus`, `border.subtle`

**颜色相关的绝对禁区**：
- 代码中出现 `#` 开头的 6 位或 8 位十六进制颜色值 → 除非是 YAML 预设文件中的定义
- 代码中出现 `QColor(` 后面跟字面量 → 必须用 `self.token()` 包裹
- 代码中出现 `rgb(` 或 `rgba(` → 同上

### 4.2 尺寸：必须使用 Space Token，禁止硬编码数字

```python
# ✅ 正确：通过 space token 获取尺寸
btn_height = self.space("height.btn_md")      # 36
spacing = self.space("spacing.lg")            # 16
corner = self.space("corner.sm")              # 4
font_size = self.space("font.body_md")        # 13

# ❌ 错误：硬编码数字
btn_height = 36
spacing = 16
corner = 4
font_size = 13
```

所有尺寸必须是 **4 的倍数**（4px 基准网格）。常用值:

| 用途 | Token key | 值 | 备注 |
|------|-----------|-----|------|
| 小按钮/输入框 | `height.btn_sm` / `input_sm` | 28 | 最小可点击高度 |
| 中按钮/输入框 | `height.btn_md` / `input_md` | 36 | **默认首选** |
| 大按钮/输入框 | `height.btn_lg` / `input_lg` | 44 | 重要操作用 |
| 图标按钮 | `height.btn_icon` | 32 | 工具栏按钮 |
| 导航项高度 | `height.nav_item` | 40 | 侧边导航 |
| 列表项高度 | `height.list_item` | 44 | 表格行高 |
| 卡片最小高度 | `height.card_min` | 60 | 信息卡片 |
| 开关滑块 | `height.toggle_sw` | 24 | Toggle 高度 |
| 进度条 | `height.progress` | 10 | 进度条厚度 |
| 滚动条 | `height.scrollbar` | 10 | 滚动条宽度 |
| 徽章 | `height.badge` | 20 | 数字角标 |
| 工具提示箭头 | `height.tooltip_arrow` | 8 | Tooltip 三角 |

间距系列:

| 含义 | Token key | 值 | 使用场景 |
|------|-----------|-----|---------|
| 无间距 | `spacing.none` | 0 | 紧贴元素 |
| 极小 | `spacing.xs` | 4 | 图标与文字之间 |
| 小 | `spacing.sm` | 8 | 相关元素之间 |
| 中 | `spacing.md` | 12 | 区块内元素之间 |
| 大 | `spacing.lg` | 16 | 区块之间的间隔 |
| 特大 | `spacing.xl` | 20 | 页面边距 |
| 超大 | `spacing.xxl` | 24 | 大区块分隔 |
| 段落 | `spacing.xxxl` | 32 | 主要章节之间 |

切角大小:

| 场景 | Token key | 值 |
|------|-----------|-----|
| 小切角（输入框/标签） | `corner.xs` | 4 |
| 中等切角（按钮/卡片） | `corner.sm` | 6 |
| 标准切角（面板默认） | `corner.md` | 8 |
| 大切角（对话框/大面板） | `corner.lg` | 12 |

**尺寸相关的绝对禁区**：
- 代码中出现 `setFixedHeight(26)` 或 `34` 或 `38` → 这些不是 4 的倍数，是旧代码的遗留错误值
- 代码中出现 `setContentsMargins(5, ...)` → 5 不是 4 的倍数
- 代码中出现 `border-radius: 7px` → 7 不是 4 的倍数

### 4.3 样式：继承原生控件 + QPainter 最小化自绘，禁止 QSS 内联样式

**核心原则**: 继承 Qt 原生控件（QPushButton / QLineEdit / QFrame），只通过 `paintEvent` 覆盖 QSS 做不到的部分（切角/发光/角落装饰）。Qt 已有的能力（文字渲染、光标、选中、撤销重做、复制粘贴）全部由 `super()` 提供。

```python
# ✅ 正确：继承原生 + 最小自绘
class CyberButton(CyberWidgetMixin, QPushButton):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_chamfered_bg(painter)   # ← 只有这个是自绘的（QSS 做不到）
        super().paintEvent(event)           # ← 文字/点击态/禁用 全交给 Qt

# ❌ 错误：从 QWidget 零开始全部自己画（重复造轮子）
class CyberButton(QWidget):
    def paintEvent(self, event):
        painter.drawText(...)   # ← 自己画文字？Qt 已经做得很好了
                                # 光标呢？选中呢？IME 呢？全得自己实现

# ❌ 错误：setStyleSheet 字符串（旧模式）
self.setStyleSheet(f"""
    QPushButton {{ background-color: {theme.cyber_yellow}; ... }}
""")
```

**如果看到 `setStyleSheet(f"""...""")` 这种模式，99% 是从旧代码复制的错误做法。**

#### 各组件继承目标速查表

| 你要做的组件 | 继承什么 | 自绘什么 | Qt 自动提供 |
|------------|---------|---------|------------|
| 按钮 | QPushButton | 切角背景+发光 | 点击/禁用/快捷键/文字/菜单箭头 |
| 输入框 | QLineEdit | 切角边框+发光 | 光标/选中/撤销/复制粘贴/右键菜单/IME |
| 文本标签 | QLabel | 可选背景 | 文字渲染/自动换行/省略号/对齐 |
| 开关 Toggle | QCheckBox | 切角滑块轨道 | 状态切换/动画/无障碍 |
| 卡片容器 | QFrame | 切角边框+角落装饰 | 布局管理/子控件排列 |
| 分组标题 | QGroupBox | 切角标题栏边框 | 折叠功能/子控件排列 |
| 下拉选择 | QComboBox | 切角外框 | 弹出列表/搜索/选择 |
| 进度条 | QProgressBar | 切角槽+发光填充 | 数值显示/动画 |
| 滚动区域 | QScrollArea | 仅滚动条样式 | 滚动/视口/事件传递 |

### 4.4 切角矩形风格

本项目采用 Cyberpunk Chamfered（科幻切角）UI 风格：
- 所有面板/按钮/卡片使用**切角矩形**（非圆角矩形）
- 关键元素有**霓虹外发光**效果
- 角落可能有**装饰性标记线**
- 这些全部在 `CyberWidgetMixin.paintEvent()` 中用 QPainter 实现（只画 QSS 做不到的部分）

---

## 五、命名规范

| 类型 | 规范 | 示例 | 反例（不要这样写） |
|------|------|------|------------------|
| 文件名 (widgets/) | 小写下划线 | `cyber_button.py` | `CyberButton.py`, `button.py` |
| 文件名 (pages/) | `{功能}_page.py` | `toggles_page.py` | `toggles.py`, `TogglesPage.py` |
| 文件名 (services/) | `{功能}_service.py` | `toggle_service.py` | `toggles.py`, `ToggleService.py` |
| 类名 (Widget) | 大驼峰 + Cyber 前缀 | `CyberButton`, `CyberInput` | `Button`, `MyButton` |
| 类名 (Page) | 大驼峰 + Page 后缀 | `TogglesPage`, `ItemsPage` | `Toggles`, `ItemsView` |
| 类名 (Service) | 大驼峰 + Service 后缀 | `ToggleService`, `ItemSearchService` | `Toggles`, `ItemHelper` |
| 方法 (内部) | 下划线开头 | `_draw_chamfered_bg()` | `drawBg()`, `DrawChamferedBg` |
| 方法 (公开) | 动词或动词短语 | `set_toggle()`, `get_all_items()` | `toggle()`, `items()` |
| Signal 名 | 描述变化的名词短语 | `toggled_data_changed`, `item_selected` | `onToggle`, `signal1` |
| Token 引用 | 点分路径小写字符串 | `"bg.raised"`, `"height.btn_md"` | `"BG_RAISED"`, `"BtnMd"` |

---

## 六、代码模板（每种文件类型的骨架）

### 6.1 widgets/ 文件模板

```python
"""
[L4/L5] Cyber{ComponentName} — {一句话描述做什么}

继承: CyberWidgetMixin + {Qt原生控件}
依赖: core.tokens.manager (仅此一个)
职责: {具体职责}
信号: {发射哪些信号}
"""

from PySide6.QtWidgets import {QT_CLASS}, QApplication
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtCore import Qt, Signal, Slot
from core.widgets.base import CyberWidgetMixin


class Cyber{NAME}(CyberWidgetMixin, {QT_CLASS}):
    """{详细描述}"""

    # ── 自定义信号（如有） ──
    value_changed = Signal(object)  # 根据需要定义参数类型

    def __init__(self, {INIT_PARAMS}, parent=None):
        {QT_CLASS}.__init__(self, parent)  # ⚠️ 显式调用，不用 super()
        # 尺寸全部从 token 取
        h = self.space("height.{SIZE_KEY}")
        if h:
            self.setFixedHeight(h)

    def paintEvent(self, event):
        """固定模式：① QPainter → ② 自绘背景 → ③ super()"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_chamfered_bg(painter)   # 只画 QSS 做不到的部分
        super().paintEvent(event)           # Qt 接管剩余绘制
```

### 6.2 services/ 文件模板

```python
"""
[L-Service] {Name}Service — {一句话描述}

依赖: 纯 Python 标准库 + data/ 模块 + core/hotkey_config.py
禁止: PySide6, QtWidgets, QtGui, QtCore（Signal 除外也不行）
返回: dict / list / bool / str（原始数据类型，不返回 Qt 对象）
"""

import json
import logging
from pathlib import Path
from data.{module} import {something}

logger = logging.getLogger(__name__)


class {Name}Service:
    """{详细描述}"""

    _instance = None

    @classmethod
    def get(cls) -> "{Name}Service":
        """单例访问（可选，按需使用）"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_{resource}(self, *args) -> {return_type}:
        """获取{资源}。{参数说明}"""
        # 纯逻辑，不碰 UI
        pass

    def set_{resource}(self, *args) -> bool:
        """设置{资源}。返回是否成功。"""
        # 纯逻辑，不碰 UI
        pass
```

### 6.3 pages/ 文件模板

```python
"""
[L2] {Name}Page — {导航项名称}页面

依赖: widgets/, sections/, services/
职责: 组装该页面所有 UI 元素并连接信号槽
父类: BasePage (base_page.py)
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout
from core.pages.base_page import BasePage
from core.widgets.button import CyberButton
from core.widgets.panel import CyberPanel
from core.sections.{section}_section import {SectionName}
from core.services.{service}_service import {ServiceName}


class {Name}Page(BasePage):
    """{导航项名称}对应的页面内容"""

    PAGE_ID = "{page_id}"  # 用于导航切换标识
    PAGE_NAME = "{显示名称}"
    NAV_ICON = "{图标名称}"  # 可选

    def __init__(self, parent=None):
        super().__init__(parent)
        self._service = {ServiceName}.get()
        self._setup_ui()

    def _setup_ui(self):
        """构建页面布局。只做 UI 组装，不做业务逻辑。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            self.space("spacing.xxl"),
            self.space("spacing.xxl"),
            self.space("spacing.xxl"),
            self.space("spacing.xxl"),
        )
        layout.setSpacing(self.space("spacing.xl"))

        # 添加 Section
        section = {SectionName}(self)
        layout.addWidget(section)

        # 连接信号
        section.some_signal.connect(self._on_something)

    @Slot(...)
    def _on_something(self, ...):
        """槽函数：接收 Widget 信号，调用 Service，更新 UI。"""
        result = self._service.do_something(...)
        if result:
            self._refresh_ui()

    def _refresh_ui(self):
        """根据最新数据刷新页面显示。"""
        pass

    def on_enter(self):
        """页面被激活时调用（切换到此导航项时）。"""
        self._refresh_ui()

    def on_leave(self):
        """页面被离开时调用（切换到其他导航项时）。"""
        pass
```

### 6.4 sections/ 文件模板

```python
"""
[L3] {Name}Section — {功能区块名称}

依赖: widgets/, services/
职责: 将一组相关 Widget 组织成一个逻辑区块
被谁引用: pages/{xxx}_page.py
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Signal, Slot
from core.widgets.base import CyberWidgetMixin
from core.widgets.button import CyberButton
from core.widgets.input import CyberInput
from core.widgets.label import CyberLabel
from core.services.{service}_service import {ServiceName}


class {Name}Section(QWidget):
    """{功能区块描述}"""

    # 向上发射的信号（给 Page 层连接）
    data_changed = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._service = {ServiceName}.get()
        self._setup_ui()

    def _setup_ui(self):
        """组装内部 Widget。"""
        layout = QVBoxLayout(self)
        layout.setSpacing(self.space("spacing.md"))
        # ... 创建子 Widget 并布局 ...

    def refresh_data(self):
        """由 Page 调用，用最新数据刷新所有子 Widget。"""
        data = self._service.get_xxx()
        self._apply_data(data)

    def _apply_data(self, data):
        """将数据设置到各个 Widget 上。"""
        pass
```

---

## 七、多重继承注意事项（CyberWidgetMixin 使用必读）

本项目使用 **Mixin 模式** 实现组件复用。这是最容易踩坑的地方。

### 7.1 __init__ 必须显式调用目标基类

```python
# ❌ 错误：super() 在多重继承中可能调用到错误的基类
class CyberButton(CyberWidgetMixin, QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)   # 可能调用的是 Mixin 的方法！

# ✅ 正确：明确指定要初始化的基类
class CyberButton(CyberWidgetMixin, QPushButton):
    def __init__(self, text="", parent=None):
        QPushButton.__init__(self, text, parent)   # 明确初始化 QPushButton
```

### 7.2 事件处理必须调用 super()

| 如果忘记调用 | 后果 |
|-------------|------|
| `super().mousePressEvent(event)` | 点击按钮不会发射 `clicked` 信号 |
| `super().paintEvent(event)` | 按钮上没有文字显示 |
| `super().keyPressEvent(event)` | 快捷键失效 |
| `super().focusInEvent(event)` | Tab 聚焦时没有焦点环 |

### 7.3 paintEvent 固定顺序

```
① QPainter(self) + Antialiasing
② _draw_chamfered_bg()     ← 自绘：切角背景 + 外发光
③ super().paintEvent()      ← 原生：文字 / 光标 / 选中 / 边框
步骤 ② 和 ③ 不能颠倒！
```

### 7.4 Mixin 私有属性加 _cyber_ 前缀

避免与 Qt 内部属性冲突：

```python
# 安全
self._cyber_state = "normal"
self._cyber_path_cache = None

# 危险（可能与 Qt 内部属性同名）
self._state = "normal"        # 部分控件可能内部使用
self._hovered = False         # 更危险
```

---

## 八、绝对禁区（违反任何一条 = 代码不合格）

| # | 禁区行为 | 正确做法 | 典型错误示例 |
|---|---------|---------|------------|
| 1 | **services/ 中 import PySide6** | Service 是纯逻辑层 | `from PySide6.QtWidgets import QWidget` |
| 2 | **widgets/ 中读写 JSON/调用 save_\*** | Widget 只管绘制和发信号 | `json.dump(data, open("config.json"))` |
| 3 | **pages/ 中使用 setStyleSheet f-string** | 用 Token + CyberWidgetMixin 自绘 | `self.setStyleSheet(f"bg: {{color}}")` |
| 4 | **硬编码颜色/尺寸/字号** | 全部走 token/space | `#FFE600`, `28`, `13` |
| 5 | **在一个方法里混合 UI 操作和业务逻辑** | Widget 发信号，Page 连接 Service | `_on_click()` 里既改 UI 又存文件 |
| 6 | **修改旧代码文件** | 旧代码只读 | 编辑 `panel_builder.py` |
| 7 | **在根目录创建 .py 文件** | 全部在 core/ 子目录下 | 创建 `my_widget.py` |
| 8 | **复制旧代码内联样式字符串** | 新文件全新实现 | 复制 `setStyleSheet(f"""...""")` |
| 9 | **Widget 直接调用 Service 再自己更新其他 Widget** | 单向数据流：Widget→Signal→Page→Service→Page→Widget | Toggle 里直接调 service 并更新别的 widget |
| 10 | **从 QWidget 零开始自绘** | 继承原生控件 + Mixin | `class MyBtn(QWidget):` 然后自己画文字 |

---

## 九、协作流程要求

### 9.1 每次收到任务时的标准流程

```
Step 1: 声明约束（必须首先做）
  → "我将修改/创建以下文件:"
  → "文件属于 Layer X，允许依赖 Y，禁止依赖 Z"

Step 2: 输出计划（不直接写代码）
  → 列出方案要点
  → 说明涉及哪些文件、各自改什么
  → 等待用户确认后再动手

Step 3: 写代码（带约束声明注释）
  → 每个文件头部写清所属层和依赖
  → 遵循上述所有规范

Step 4: 自检报告
  → 运行「零、快速自查卡」10 条
  → 报告结果：通过/不通过及原因
```

### 9.2 紧急制动话术

当你感觉偏离轨道时，使用以下话术：

| 话术 | 触发场景 | 效果 |
|------|---------|------|
| 「停」 | 发现我在做不该做的事 | 立即停止当前操作 |
| 「回到设计文档」 | 我的做法与文档矛盾 | 我重新读取 docs/ 中的规范 |
| 「给我看所有 import」 | 怀疑非法依赖 | 一秒暴露耦合问题 |
| 「回退，用更简单的方案」 | 过度工程 | 撤销，重新想更简单的方式 |
| 「这个文件属于哪一层」 | 层级混乱 | 强制我回答并自我纠正 |

### 9.3 常见错误快速诊断

| 现象 | 可能原因 | 检查方式 |
|------|---------|---------|
| 按钮点击没反应 | 忘了 `super().mousePressEvent()` | 搜索 `def mousePressEvent` 看有没有 `super()` |
| 按钮没文字 | 忘了 `super().paintEvent()` 或顺序反了 | 搜索 `def paintEvent` 看顺序 |
| 启动就崩 | `__init__` 用了 `super()` 而非显式调用基类 | 搜索 `__init__` 里的 `super()` |
| 颜色不对 | 硬编码了颜色或 token 路径打错 | 搜索 `#[0-9a-f]` 和 `QColor(` |
| 尺寸奇怪 | 写了非 4 的倍数 | 搜索 `setFixedHeight\((?!self\.)` |
| IDE 报 import 错误 | 跨层依赖了不该依赖的模块 | 检查文件头的依赖声明 |

---

## 十、参考文档索引

| 文档 | 定位 | 何时查阅 |
|------|------|---------|
| `docs/ui-framework-design.md` | **纯新系统规范**（颜色Token/空间尺寸/六层架构/组件规范/动效/a11y/图标/暗亮模式/性能预算/走查清单/MRO注意事项/Token错误处理/视觉测试） | 设计新组件、定义 Token、遇到视觉问题时 |
| `docs/ui-refactor-analysis.md` | **承上启下的重构报告**（旧代码分析/迁移映射表/四步走方案/信号桥接/Phase检查清单） | 迁移旧代码时查阅常量对照表、规划任务时判断优先级 |
| `data/presets/cyberpunk.yaml` | 新版主题预设文件（YAML 格式，含 color + space tokens） | 定义新 token 时参考现有值 |
| `.trae/rules/规范.md` | 本文件（你正在读的这个） | **每次写代码前** |

### 两份文档的分工

```
ui-framework-design.md          ui-refactor-analysis.md
┌─────────────────────┐        ┌──────────────────────────┐
│  "新系统应该怎么做"   │        │  "从旧到新怎么迁"         │
│                     │        │                          │
│ • Token 规范         │ ←迁移→ │ • 附录 A: 兼容映射表      │
│ • 组件继承规则       │        │ • 旧代码耦合诊断           │
│ • 六层架构职责       │        │ • 四步走 Phase 0~3       │
│ • 切角几何参数       │        │ • 信号桥接方案            │
│ • 性能预算 / 走查    │        │ • Phase 验收检查清单       │
└─────────────────────┘        └──────────────────────────┘
     纯规范，无旧代码引用              含旧代码信息，过渡期用
```---

## 十二、文档体系规范（三层文档，各司其职）

> **核心原则：文档必须与代码同步。过时的文档比没有文档更危险。**

### 12.1 三层文档定义

| 层级 | 文件 | 性质 | 更新时机 | 维护者 | 用途 |
|------|------|------|---------|--------|------|
| **A. 契约文档** | `docs/ui-framework-design.md` | 规范（该做什么） | 重大架构变更时 | PM + 架构师 | 唯一权威设计规范，定义所有"应该怎样" |
| **B. 落地文档** | `docs/architecture.md` | 记录（实际做了什么） | 每个 Phase 完成后 | 开发者 | 真实项目快照：文件结构、已实现接口、与设计的差异 |
| **C. API 文档** | 代码内 docstring + 类型注解 | 参考（怎么用） | 随每次代码提交 | 开发者 | IDE 可读的接口说明、参数、返回值、示例 |

### 12.2 各层写入规则

#### A 层 — ui-framework-design.md（契约）
- **只写**：设计原则、Token 规范、分层规则、命名约定、迁移策略
- **不写**：具体实现细节、行数统计、临时方案
- **何时更新**：当架构决策发生变更时（如新增一种 Widget 类型、修改信号命名规范）
- **更新流程**：先改文档 → 再改代码 → 提交时附带文档变更

#### B 层 — docs/architecture.md（落地快照）
- **只写**：已完成的事实（当前文件树、已实现的方法签名列表、模块依赖图）
- **不写**：计划、TODO、理想状态
- **何时更新**：每个 Phase 结束验收通过后，作为 Phase 收尾动作
- **更新流程**：
  1. 运行 `tree /F core\tokens core\widgets ...` 获取真实文件结构
  2. 从代码提取公开接口清单（方法/信号/属性）
  3. 对比设计文档，记录差异
  4. 更新"最后更新"时间戳和 commit hash

#### C 层 — 代码 docstring（自描述）
- **每个公开类和方法必须有**：用途说明 + Args/Returns + Raises + 示例（如有必要）
- **引用契约文档**：类级 docstring 末尾加 `See Also: ui-framework-design.md §章节号`
- **可执行示例**：使用 doctest 格式写的示例可通过 `pytest --doctest` 自动验证

### 12.3 差异追踪（当实现偏离设计时）

在 `docs/architecture.md` 底部维护「设计偏差日志」：

```markdown
## 设计偏差日志

| 日期 | 设计文档章节 | 设计说 | 实际做了 | 原因 | 影响 |
|------|------------|--------|---------|------|------|
| MM-DD | §X.X | xxx | yyy | 原因分析 | 无/需反向更新 |
```

**规则**：
- 发现偏差时**立即记录**，不允许偷偷偏移不报告
- 如果偏差是合理的改进 → 在下个 Phase 同步更新设计文档（A层）
- 如果偏差是偷懒妥协 → 标记为技术债务，排期修复

### 12.4 Phase 结束时的文档同步仪式

```
Phase N 验收通过后，按顺序执行：

1️⃣  更新 docs/architecture.md
    - 替换文件结构为当前 tree 输出
    - 补充本阶段实现的接口清单
    - 记录本阶段的设计偏差

2️⃣  检查是否需要更新 ui-framework-design.md
    - 有架构变更？→ 更新对应章节
    - 无变更？→ 不动（保持稳定）

3️⃣  提交代码时附带文档变更
    git commit -m "Phase N complete: {做了什么}

    docs: update architecture.md (structure + interfaces)
    docs: sync design spec §X.X ({如有变更})"
```

### 12.5 禁止事项

```
❌ 写完代码不更新任何文档就提交
❌ 在落地文档中写"计划在未来实现xxx"（那是 TODO 不是落地文档）
❌ 复制粘贴设计文档的内容到落地文档（两处维护必然不一致）
❌ 代码中的 docstring 与实际行为不符
❌ 删除或重命名公开方法但不更新 docstring
```

---

**当对规范有疑问时，以上述文档为准，不要凭记忆或猜测。如果文档之间有矛盾，以 `ui-framework-design.md` 为最高优先级。**
