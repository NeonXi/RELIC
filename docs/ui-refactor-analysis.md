# UI 重构决策分析报告

> 日期: 2026-06-09 | 目的: 回答「是否应该从零搭建 UI 再搬入逻辑」这一架构问题

---

## 零、新代码放哪里？（先回答这个问题）

### ❌ 不应该在根目录建文件

你的项目根目录现在长这样：

```
WARFRAME-RELIC/
├── main.py              # 入口
├── dev_runner.py        # 开发启动
├── core/                # 核心模块（现有代码都在这）
├── data/                # 数据层
├── market_query/        # 独立子窗口
├── recognizers/         # OCR
├── assets/              # 图标资源
├── docs/                # 文档
└── tests/               # 测试
```

根目录只放**入口文件和配置**。新 UI 代码如果散落在根目录，会和 `main.py`、`dev_runner.py` 混在一起，非常混乱。

### ✅ 正确做法：在 core/ 下新建目录

```
core/
├── tokens/              # ★ 新建：Token 系统（颜色 + 尺寸）
│   ├── __init__.py
│   ├── manager.py       #   TokenManager 单例
│   └── resolver.py      #   解析引擎 (@引用 / 函数)
│
├── widgets/             # ★ 新建：Cyber Widget 组件库
│   ├── __init__.py
│   ├── base.py          #   CyberWidgetMixin (切角/动画/状态机)
│   ├── button.py        #   切角按钮 (solid/outlined/ghost)
│   ├── input.py         #   切角输入框
│   ├── card.py          #   切角卡片容器
│   ├── group_box.py     #   切角分组框 (替代 QGroupBox)
│   ├── nav_item.py      #   导航项组件
│   ├── list_item.py     #   列表项组件
│   ├── badge.py         #   小标签/徽章
│   ├── toggle.py        #   开关切换
│   ├── progress_bar.py  #   进度条
│   ├── tooltip.py       #   气泡提示
│   └── scroll_area.py   #   自定义滚动区域
│
├── pages/               # ★ 新建：L2 页面（每个导航项一个文件）
│   ├── __init__.py
│   ├── base_page.py     #   PageBase 基类
│   ├── toggles_page.py  #   功能开关页
│   ├── status_page.py   #   数据总览页
│   ├── items_page.py    #   物品查询页
│   ├── triggers_page.py #   触发器页
│   ├── prices_page.py   #   价格数据页
│   ├── hotkeys_page.py  #   快捷键页
│   ├── theme_page.py    #   主题换肤页
│   ├── reset_page.py    #   紧急重置页
│   ├── preset_page.py   #   语言预设页
│   └── about_page.py    #   关于页面
│
├── sections/            # ★ 新建：L3 功能区块组件
│   ├── __init__.py
│   ├── feature_toggles_section.py
│   ├── data_stats_section.py
│   ├── item_search_section.py
│   ├── trigger_cards_section.py
│   ├── price_region_section.py
│   ├── hotkey_list_section.py
│   └── about_info_section.py
│
├── services/            # ★ 新建：从 panel_builder.py 提取的纯逻辑
│   ├── __init__.py
│   ├── toggle_service.py      #   功能开关 CRUD
│   ├── stats_service.py       #   数据库统计查询
│   ├── item_search_service.py #   物品搜索过滤
│   ├── trigger_service.py     #   触发器 CRUD
│   └── pipeline_bridge.py     #   数据管道 UI 桥接
│
├── app_shell.py         # ★ 新建：L0+L1 外壳（窗口框架 + 导航栏）
│
├── management_panel.py  # ← 保留但标记 deprecated（过渡期仍用）
├── panel_builder.py     # ← 保留但标记 deprecated（过渡期仍用）
├── panel_styles.py      # ← 保留但标记 deprecated
├── stylesheet.py        # ← 降级为 fallback
├── theme_config.py      # ← 降级为 TokenManager 薄包装
├── update_panel.py      # ← 保留不动
├── hotkey_config.py     # ← 保留不动
└── ...                  #   其他现有文件不变
```

**关键原则**：
- 所有**新代码**放在 `core/` 下的新建目录中
- **旧代码一个字不改**，直到新系统完全就绪
- 新旧代码通过 `import` 共享纯逻辑层（如 `hotkey_config.py`）
- 最终删除旧文件时，直接删文件夹就行，不会影响新代码

---

## 一、现状诊断：耦合程度量化

### 1.1 核心文件规模

| 文件 | 行数 | 职责 |
|------|------|------|
| `core/panel_builder.py` | **2820 行** | UI 构建 + 业务逻辑 + 事件处理 + 内联样式 |
| `core/management_panel.py` | **358 行** | 窗口管理 + 信号转发 + 热键/主题/退出逻辑 |
| `core/panel_styles.py` | ~400 行 | 内联样式刷新方法 |
| `core/theme_config.py` | ~200 行 | 主题配置 |
| 合计 | **~3800 行** | 全部集中在 UI 层 |

### 1.2 panel_builder.py 内部构成（问题最严重的文件）

```
panel_builder.py (2820行)
├── BlockWheelFilter          (行 54-62)    →  事件过滤器组件定义
├── CrosshairPicker           (行 63-172)   →  十字准星取点控件 (含 paintEvent)
├── PanelBuilderMixin         (行 174-2820) →  主 Mixin 类
│   ├── _setup_ui()           (行 196-380)  →  整体布局搭建 + 导航栏构建
│   ├── _build_*_group() ×10  (行 396-2582) →  10个功能区块的 UI 构建方法
│   │   ├── _build_feature_toggles_group     →  功能开关 (UI+保存逻辑)
│   │   ├── _build_data_overview_group       →  数据总览 (UI+统计刷新)
│   │   ├── _build_item_index_group          →  物品查询 (UI+搜索逻辑+结果渲染)
│   │   ├── _build_trigger_group             →  触发器 (UI+CRUD逻辑, 最复杂)
│   │   ├── _build_price_group               →  价格数据 (UI+区域选择+更新)
│   │   ├── _build_hotkey_group              →  快捷键 (UI+保存/重置)
│   │   ├── _build_reset_group               →  紧急重置 (UI+操作)
│   │   ├── _build_theme_group               →  主题换肤入口
│   │   ├── _build_about_group               →  关于页面 (UI+外部链接)
│   │   └── _build_language_preset_group     →  语言预设切换
│   ├── _on_*() 事件处理器 ×20+              →  业务逻辑直接写在 handler 里
│   ├── _build_log_panel / _build_theme_slide_panel  →  辅助面板
│   └── 辅助方法若干 (_reg_text, _apply_word_wrap 等)
```

### 1.3 耦合点统计

| 耦合类型 | 数量 | 示例 |
|---------|------|------|
| **内联 setStyleSheet** | **~100 处** | `f"color: {theme.text_dim}; font-size: 11px;"` |
| **直接引用 theme.* 属性** | **~80 处** | `theme.cyber_yellow`, `theme.border`, `theme.card_bg` |
| **业务逻辑嵌入 UI 方法** | **20+ 处** | `_on_feature_toggle_changed()` 里直接调用 `save_feature_toggles()` |
| **样式硬编码数值** | **~50 处** | `"font-size: 11px"`, `"padding: 6px 12px"`, `"border-radius: 4px"` |
| **控件创建与信号连接混在一起** | **每处都有** | `btn = QPushButton(); btn.clicked.connect(lambda: self._save_xxx())` |

### 1.4 典型耦合代码示例

```python
# ❌ panel_builder.py 第 517-521 行: 样式、控件创建、业务语义全部揉在一起
self._btn_update_base.setStyleSheet(
    f"QPushButton {{ background-color: {theme.cyber_yellow}; color: {COLOR_BLACK}; "
    f"border: none; border-radius: 4px; padding: 6px 16px; font-size: 13px; }}"
    f"QPushButton:hover {{ background-color: {theme.cyber_cyan]; }}"
    f"QPushButton:disabled {{ background-color: {theme.text_dim}; color: {COLOR_DARK_GRAY}; }}")

# ❌ panel_builder.py 第 456-467 行: UI 回调里直接操作数据持久化
def _on_feature_toggle_changed(self, key: str, state):
    self._feature_toggles[key] = bool(state)
    if save_feature_toggles(self._feature_toggles):      # ← 直接调持久化
        self.feature_toggles_changed.emit(self._feature_toggles)
        self._add_log('ok', f'功能开关已更新: {...}')    # ← 直接写日志
        self._refresh_toggle_button_styles()                # ← 直接触发UI刷新
    else:
        self._add_log('error', S("feature_toggle", "save_failed"))

# ❌ panel_builder.py 第 687-800 行: 搜索逻辑(140行)嵌在 UI 构建方法旁边
def _on_items_search_changed(self, text: str):
    # ... 140 行搜索、过滤、高亮、结果渲染逻辑 ...
```

---

## 二、两种重构路径对比

### 路径 A: 在现有代码上逐步改造（渐进式）

```
现状代码 ──→ 小步修改每个 _build_* 方法 ──→ 替换为 Cyber Widget ──→ 完成
```

**做法**: 保持 panel_builder.py 的结构不动，逐个把 QSS 控件替换成自绘 CyberWidget，同时把内联样式抽到 token。

**优点**:
- 每一步都可以运行测试，风险低
- 不需要一次性重写大量代码
- 可以边做边用，用户无感知

**缺点**:
- **结构债务不消除**: 2820 行的大文件依然存在，只是换了皮
- **改造过程痛苦**: 每改一个 `_build_*` 都要在一坨旧代码里小心翼翼地动刀
- **容易引入回归 bug**: 改 A 处影响了 B 处（因为所有东西都在一个类里）
- **新框架被旧结构拖累**: Design Token / 六层架构无法真正落地，因为容器还是旧的
- **心理负担大**: 开发者每打开 panel_builder.py 都要面对 2800+ 行

**结论**: 适合小改动（换个颜色、调个间距），不适合架构级重建。

---

### 路径 B: 从零搭建 UI 骨架，再迁移逻辑（推倒重来）

```
新建干净的 UI 骨架 ──→ 把纯逻辑代码搬进来 ──→ 逐个实现 CyberWidget 页面 ──→ 完成
```

**做法**:
1. 先建一个全新的、空的 Application Shell（L0-L5 骨架）
2. 把 panel_builder.py 中的**纯逻辑代码**提取为独立的 Service/Controller
3. 新 UI 通过信号/接口调用这些逻辑层
4. 旧的 panel_builder.py 最终整体废弃

**优点**:
- **彻底消除结构债务**: 新代码从第一天就遵循六层架构和 Token 规范
- **开发体验好**: 每个文件职责清晰，打开就知道改哪里
- **新旧隔离**: 旧代码完全不动，新代码独立开发，互不影响
- **Design System 天然落地**: 因为是从骨架开始建的，Token/Space/Motion 全部原生集成
- **可测试性飞跃**: 逻辑层脱离 UI 后可以单独写单元测试

**缺点**:
- 前期需要投入时间搭骨架（约 1-2 天）
- 有一个"双系统并存"的过渡期
- 需要仔细识别哪些是"纯逻辑"、哪些是"UI 相关"

**结论**: 适合这次你要做的全面 UI 重构。

---

## 三、推荐方案：路径 B（从零搭建）+ 渐进迁移

### 3.1 四步走 — 大白话版

---

#### Phase 0: 「搬家」— 把逻辑从 UI 里掏出来

**一句话解释**: `panel_builder.py` 现在是一个 **2820 行的大杂烩**，里面有 UI 创建、有样式字符串、有业务逻辑、有数据保存。Phase 0 要做的就是：**把里面所有"不碰 UI 控件"的代码单独拎出来，放到新文件里。**

**打个比方**:
> 想象你有一个房间（panel_builder.py），里面同时放着：
> - 厨具（UI 控件创建）
> - 食谱书（业务逻辑：怎么保存开关、怎么搜索物品）
> - 装修材料（100 处 setStyleSheet 样式字符串）
>
> Phase 0 就是把**食谱书**搬到另一个房间（services/），厨房和装修材料先不管。
> 这样以后重装厨房（换 UI）时，不会把食谱书也一起拆了。

**具体做什么**:

```
原来 panel_builder.py 里的这段代码：

    def _on_feature_toggle_changed(self, key: str, state):
        self._feature_toggles[key] = bool(state)
        if save_feature_toggles(self._feature_toggles):   # ← 这是纯逻辑
            self.feature_toggles_changed.emit(...)          # ← 发信号
            self._add_log('ok', ...)                         # ← 写日志
            self._refresh_toggle_button_styles()             # ← 这才是 UI 操作

变成两个文件：

# core/services/toggle_service.py  （纯逻辑，不碰任何 Qt 控件）
class ToggleService:
    def __init__(self):
        self._toggles = load_feature_toggles()

    def set_toggle(self, key: str, state: bool) -> dict:
        """返回 {'success': True, 'toggles': {...}} 或 {'success': False, 'error': '...'}"""
        self._toggles[key] = bool(state)
        if save_feature_toggles(self._toggles):
            return {'success': True, 'toggles': dict(self._toggles)}
        return {'success': False, 'error': 'save_failed'}

    def get_all(self) -> dict:
        return dict(self._toggles)

# core/pages/toggles_page.py  （将来 Phase 2 写的，只管 UI）
# 这里调用 toggle_service，拿到结果后更新按钮状态
```

**怎么判断哪些该搬？** 用这个简单的过滤规则：

| 代码特征 | 该搬？ | 理由 |
|---------|--------|------|
| `save_feature_toggles()` / `load_hotkeys()` | ✅ 搬 | 纯文件 I/O |
| `item_index.search(text)` | ✅ 搬 | 纯数据查询 |
| 字符串处理 / 列表过滤 / 字典操作 | ✅ 搬 | 纯 Python 逻辑 |
| `setStyleSheet(...)` | ❌ 不搬 | UI 样式 |
| `setText(...)` / `setTitle(...)` | ❌ 不搬 | UI 更新 |
| `addWidget(...)` / `setLayout(...)` | ❌ 不搬 | UI 布局 |
| `.clicked.connect(lambda: ...)` | ❌ 不搬 | UI 信号连接 |

**这一步的产出物**:
- `core/services/` 下 5~6 个纯 Python 文件
- 每个文件可以被 `import` 后独立测试（不需要启动 Qt 窗口）
- `panel_builder.py` **原封不动**，只是以后新代码不再引用它里面的逻辑方法

**风险**: 极低。因为完全不改动旧代码，只是"复制+整理"到新文件。

---

#### Phase 1: 「搭架子」— 建新的空壳窗口

**一句话解释**: 用新架构（L0-L5 六层模型 + Design Token）搭一个**空的**主窗口。它长得像最终产品，但里面的页面全是占位符。

**打个比方**:
> 盖房子。Phase 0 是把家具（逻辑）搬到仓库。Phase 1 是打地基、立框架、砌墙、装门窗。
> 此时房子是毛坯房 — 有房间分隔、有窗户位置，但里面空无一物。

**具体做什么**:

```
这一步要创建的文件（按顺序）：

① core/tokens/          ← 先做这个，后面的所有组件都依赖它
   ├── manager.py       TokenManager 单例（加载 YAML、解析 @ 引用）
   └── resolver.py      解析引擎（lighten/darken/mix/opacity 函数）

② data/presets/
   └── cyberpunk.yaml   完整的四层 token 定义（从设计文档复制过来）

③ core/widgets/base.py  CyberWidgetMixin 基类
   - paintEvent 模板（切角矩形绘制）
   - 状态管理（hover/focused/pressed/disabled）
   - Token 读取接口（self.token("button.solid.bg")）
   - 动画过渡基础

④ core/app_shell.py     L0 + L1 外壳
   - 新的主窗口类 AppShell（替代 ManagementPanel）
   - 左侧导航栏（用 QListWidget 或自绘 NavList）
   - 右侧内容区 QScrollArea
   - 导航切换逻辑（点左边 → 右边显示对应 Page）

⑤ core/pages/base_page.py  PageBase 基类
   - 所有页面的公共接口
   - 自动注册到导航系统
   - 生命周期：on_enter / on_leave / on_theme_change

⑥ 一个 Demo 页面（比如 about_page.py 先做，因为它最简单）
   - 验证整个链条跑通：
     YAML 加载 → Token 解析 → CyberWidgetMixin 绘制 → Page 显示在 AppShell 中
```

**这一步结束时的样子**:
```
用户打开程序 → 看到一个新窗口 → 左边有导航栏（10 个项）→ 右边是空白或占位页
点击导航项 → 可以切换（但内容是空的或只有 "Coming Soon" 文字）
切换主题预设 → 所有 token 实时更新
```

**关键里程碑**: 你能在一个**全新的窗口**中看到切角按钮、正确的颜色、正确的间距。这意味着基础设施全部就绪。

**风险**: 中等。主要工作量在 TokenManager 和 CyberWidgetMixin 上。但这些都是纯新建，不影响旧代码。

---

#### Phase 2: 「填装修」— 逐个实现功能页面

**一句话解释**: Phase 1 给了你一个毛坯房。现在每个星期（或每几天）**装修一个房间**。做完一个就能用一个。

**打个比方**:
> 毛坯房盖好了。这周装修客厅（功能开关页），下周装修厨房（物品查询页）。
> 每装修完一个房间就可以在那里面活动，不用等全部装修完才能住人。

**具体做什么**（以「功能开关」页面为例）：

```
实现 toggles_page.py 的完整过程：

Step 1: 在 pages/toggles_page.py 创建页面类
    class TogglesPage(PageBase):
        """功能开关页面"""

Step 2: 用 CyberWidget 组装 UI（不再是 raw Qt 控件）
    self.title = CyberLabel("功能开关", style="heading")
    self.hint = CyberLabel("开启或关闭各项辅助功能...", style="hint")

    # 用 CyberToggle 替代 Checkable Button
    self.toggle_ocr = CyberToggle(label="OCR 识别", default=True)
    self.toggle_auto_price = CyberToggle(label="自动查价", default=True)
    ...

Step 3: 连接 Phase 0 提取的 Service
    self.toggle_service = ToggleService()   # 从 services 导入

    self.toggle_ocr.toggled.connect(
        lambda on: self._handle_toggle("ocr", on)
    )

    def _handle_toggle(self, key, state):
        result = self.toggle_service.set_toggle(key, state)  # 调纯逻辑
        if result['success']:
            self.show_success(f'已更新')
        else:
            self.show_error(result['error'])

Step 4: 测试
    - 打开新窗口 → 导航到「功能开关」→ 看到 6 个 Toggle 开关
    - 点击一个 → 状态保存到文件 → 刷新后状态保持
    - 切换 cyberpunk/daylight 预设 → 颜色实时变化
    - 全部通过 → 这个页面算完成 → 开始下一个
```

**10 个页面的实现顺序**（按复杂度排序）：

| 顺序 | 页面 | 复杂度 | 原因 |
|------|------|--------|------|
| 1 | about_page (关于) | ★☆☆ | 纯静态展示，无交互逻辑 |
| 2 | toggles_page (功能开关) | ★★☆ | 只有 Toggle + 保存，逻辑简单 |
| 3 | hotkeys_page (快捷键) | ★★☆ | 输入+保存，已有 hotkey_config 支持 |
| 4 | status_page (数据总览) | ★★☆ | 只读展示，读 stats_service |
| 5 | preset_page (语言预设) | ★★☆ | 下拉框+切换，逻辑简单 |
| 6 | reset_page (紧急重置) | ★★★ | 有危险操作确认弹窗 |
| 7 | prices_page (价格数据) | ★★★ | 区域选择+状态显示 |
| 8 | items_page (物品查询) | ★★★★ | 搜索+列表渲染，140行搜索逻辑 |
| 9 | theme_page (主题换肤) | ★★★★ | 颜色选择器+预览+保存 |
| 10 | triggers_page (触发器) | ★★★★★ | 最复杂，CRUD 卡片+动作行 |

**这一步的节奏感**:
- 每完成 1 个页面 → 用户就能在新窗口里用到这个功能
- 不需要等 10 个全做完
- 做到第 5~6 个时，大部分日常功能已经可用了

**风险**: 低到中等。每个页面独立开发，一个出 bug 不影响其他页面。

---

#### Phase 3: 「换门牌」— 切换入口，废弃旧代码

**一句话解释**: 当新窗口的功能覆盖了旧窗口的 **80%+** 时，修改 `main.py` 让它默认启动新窗口。旧代码保留但不维护，稳定运行一段时间后删除。

**打个比方**:
> 你的新房装修好了 80%，可以入住了。今天开始走新门（新窗口）进出。
> 旧房的门锁上但暂时不拆（万一新房有问题还能退回去）。
> 过了 3 个月，确认新房一切正常，才叫人来拆旧房。

**具体做什么**:

```
Step 1: main.py 加一个开关

    # 原来：
    from core.management_panel import ManagementPanel
    panel = ManagementPanel()
    panel.show()

    # 改为：
    import os
    USE_NEW_UI = os.environ.get("USE_NEW_UI", "1") == "1"

    if USE_NEW_UI:
        from core.app_shell import AppShell       # 新窗口
        window = AppShell()
    else:
        from core.management_panel import ManagementPanel  # 旧窗口（回退用）
        window = ManagementPanel()
    window.show()

    用户可以通过环境变量或设置项控制用哪个窗口。

Step 2: 默认设为新窗口
    USE_NEW_UI 默认值改为 "1"
    大部分用户自动使用新 UI

Step 3: 观察期（建议 1-2 周）
    - 收集用户反馈
    - 修复新 UI 的 bug
    - 补齐剩余 20% 功能

Step 4: 删除旧代码
    确认新 UI 稳定后：
    - 删除 management_panel.py
    - 删除 panel_builder.py
    - 删除 panel_styles.py
    - 删除 bg_layer.py
    - 清理 stylesheet.py 中被替代的部分
    - 删除 icon/ 目录（合并到 assets/icons/）
```

**什么时候可以进入 Phase 3?**
- 至少完成前 6 个页面（about/toggles/hotkeys/status/preset/reset）
- 核心工作流完整可用：开关功能 → 查物品 → 看价格 → 设快捷键
- 没有 crash 级别的 bug

---

### 3.2 总体时间线一览

```
Week 1:
├── Phase 0: 提取 services/ (2-3 天)
└── Phase 1a: tokens/ + cyberpunk.yaml + resolver.py (2-3 天)

Week 2:
├── Phase 1b: CyberWidgetMixin + AppShell 外壳 (3-4 天)
└── Phase 1c: Demo 验证（切角按钮显示正确）(1 天)

Week 3-4:  ← Phase 2 开始
├── Page 1-3: about + toggles + hotkeys (每个 1-2 天)
├── Page 4-6: status + preset + reset (每个 1-2 天)

Week 5-6:
├── Page 7-8: prices + items (每个 2-3 天，这两个较复杂)
├── Page 9-10: theme + triggers (每个 2-3 天)

Week 7:
└── Phase 3: 切换入口 + 观察期
```

**注意**: 这不是死板的计划。如果你每天只能投入 2 小时，时间自然拉长。关键是**每个 Phase 的边界清晰**，做到哪算哪，随时可以停。

### 3.3 逻辑提取清单（Phase 0 要做的事）

从 `panel_builder.py` 中可以提取出的**纯逻辑代码**：

| 逻辑模块 | 当前位置 | 提取目标 | 行数估算 |
|---------|---------|---------|---------|
| 功能开关 CRUD | `_on_feature_toggle_changed` | `services/toggle_service.py` | ~30 行 |
| 数据库状态查询 | `_build_data_overview_group` 中统计部分 | `services/stats_service.py` | ~60 行 |
| 物品搜索 & 过滤 | `_on_items_search_changed` (140行) | `services/item_search_service.py` | ~150 行 |
| 触发器 CRUD | `_on_add/delete/toggle_trigger*` | `services/trigger_service.py` | ~200 行 |
| 快捷键保存/重置 | `_on_save/reset_hotkeys` | 已有 `hotkey_config.py`，补充 Controller | ~40 行 |
| 价格区域选择 | `_on_select/set/clear_slot_region` | 已有 `hotkey_config.py`，同上 | ~30 行 |
| 数据管道执行 | `_on_update_base_data` 及 pipeline 回调 | 已有 `data_pipeline.py`，补充 UI Bridge | ~80 行 |
| 日志记录 | `_add_log` 转发 | 已在 `update_panel.py`，无需提取 | 0 |

**关键判断标准**: 如果一段代码**不包含任何 Qt 控件操作**（没有 `setStyleSheet`、`setText`、`addWidget`），它就是纯逻辑。

### 3.3 应该保留不动的代码

以下代码**不需要也不应该重写**，它们已经是良好的模块：

| 文件 | 状态 | 说明 |
|------|------|------|
| `core/hotkey_config.py` | ✅ 保留 | 纯数据层，load/save/validate |
| `core/update_panel.py` | ✅ 保留 | 子面板，相对独立 |
| `core/theme_config.py` | ✅ 保留 | 将升级为 TokenManager 的薄包装 |
| `data/data_pipeline.py` | ✅ 保留 | 纯数据处理流水线 |
| `data/item_index.py` | ✅ 保留 | 纯数据索引 |
| `data/market_items.py` | ✅ 保留 | 纯市场数据 |
| `recognizers/*.py` | ✅ 保留 | OCR 识别器，与 UI 无关 |
| `market_query/*` | ✅ 保留 | 独立子窗口，不在本次重构范围 |

### 3.4 需要废弃的代码

| 文件/内容 | 废弃原因 | 替代方案 |
|-----------|---------|---------|
| `panel_builder.py` 全文 | UI+逻辑大杂烩 | 拆分为 pages/ + services/ |
| `panel_styles.py` | 内联样式刷 | Token 系统 + 自绘组件自带样式 |
| `stylesheet.py` 全局 QSS | 与 QPainter 自绘冲突 | 仅保留给未替换的原生控件的 fallback |
| `ManagementPanel` 三Mixin 组合 | 单体 God Class | 新 AppShell + Page 导航架构 |
| `bg_layer.py` | 背景逻辑混在 UI 里 | L0 Shell 统一管理 |

---

## 四、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| Phase 0 提取逻辑时遗漏边界情况 | 功能回归 | 每提取一个模块就跑一遍现有测试套件 |
| 新旧窗口并存期间用户困惑 | 用户体验 | 新窗口默认不启用，通过启动参数/设置开关控制 |
| 迁移周期过长导致代码分裂 | 维护负担 | 设定明确里程碑，每 2 个页面为一个 checkpoint |
| CrosshairPicker 等特殊控件需重绘 | 工作量 | 这些控件本身已经是自绘的，直接搬入 widgets/ 即可 |

---

## 五、最终建议

**采用路径 B：从零搭建。**

理由：

1. **当前耦合度已经超过"可维护"的临界线** — 2820 行单文件 + 100 处内联样式 + UI/逻辑混杂，继续在上面打补丁只会越改越乱。

2. **你的设计文档已经非常完整** — 颜色 Token、空间尺寸、六层架构、组件规范全都定义好了，这正是从零搭建的最佳时机。如果在旧代码上改造，这些设计会被旧结构严重稀释。

3. **真正需要重写的只有 ~2000 行 UI 代码** — 纯逻辑代码（hotkey_config、data_pipeline、recognizers 等）全部保留不动。实际工作量比看起来小得多。

4. **渐进式迁移保证安全** — 不是一次性删掉旧代码，而是新窗口逐步替代旧窗口，每一步都可回退。

**下一步行动**: 如果你认同这个方向，我可以立即开始 Phase 0 的工作 — 从 panel_builder.py 中提取纯逻辑代码为独立 Service。

---

## 六、AI 协作开发协议 — 如何保证全程可控

> 这是本次重构中最重要的一节。它定义了你和 AI 之间的"工作契约"，确保每一步都在你的控制范围内。

### 6.1 核心问题：为什么 AI 会写出不合规的代码？

先说清楚我的弱点，你才能有效防范：

| 弱点 | 表现 | 根因 |
|------|------|------|
| **上下文遗忘** | 写到第 5 个文件时忘了第 1 个文件定的规范 | 对话压缩导致早期内容丢失 |
| **捷径诱惑** | 为了"快速出结果"跳过抽象层，直接写死值 | 被训练成"给出能运行的代码"，而非"给出架构正确的代码" |
| **规范漂移** | 两个文件里对同一概念用了不同的命名/结构 | 没有强制性的统一参考源 |
| **过度工程** | 给简单功能加了不必要的接口/工厂/策略模式 | 过度遵循"最佳实践"而忽视项目实际需求 |
| **复制旧习惯** | 新代码里出现了 `setStyleSheet(f"...")` 这种旧模式 | 从旧代码中学习到了"这个项目是这么写的" |

**关键认知**: 我不会主动违反规范——但我会在**没有被明确提醒**的时候走捷径。所以解决方案不是"信任我"，而是**建立让我无法走捷径的机制**。

### 6.2 协作机制：三层防护网

#### 第一层：写代码前的「计划确认」机制（最重要）

```
你: "开始做 Phase 0，提取 toggle_service"
我: （不会直接写代码）
    → 先列出计划：
      1. 要创建 core/services/__init__.py
      2. 要创建 core/services/toggle_service.py
      3. 从 panel_builder.py 的哪些行提取什么
      4. 提取后的接口设计（方法签名、返回值）
      5. 不动哪些东西

你: 审查计划 → "可以" 或 "这里改一下"
我: 收到确认后才开始写代码
```

**你应该对我说的触发词**：

| 你说的话 | 我会做的事 |
|---------|-----------|
| 「先给我看计划」 | 列出要创建/修改的文件清单 + 每个文件的核心设计 |
| 「这一步的具体方案是什么」 | 停止执行，输出详细方案供审查 |
| 「等一下，先别写」 | 立即停止当前操作，等待进一步指示 |
| 「按 XX 设计文档来」 | 重新引用对应章节作为约束条件 |

**反例（不要这样）**：
```
❌ 你: "帮我写 toggle_service"
   我: 直接写了 → 可能接口不对、可能混入了 UI 逻辑
   你: 看完才发现问题 → 已经写进去了，还要改
```

#### 第二层：写代码中的「约束声明」机制

每次我开始写一个文件时，我会**主动声明约束**。你可以检查这些声明是否正确：

```python
# ── 文件头部约束声明（每个新文件都必须有）──
# 文件: core/services/toggle_service.py
# 层级: Services Layer (纯逻辑，禁止 import PySide6)
# 依赖: core/hotkey_config.py (load/save_feature_toggles)
# 被依赖: core/pages/toggles_page.py (Phase 2)
# 设计依据: docs/ui-framework-design.md 第5章 L3→Service 规则
# 测试: 可通过 python -c "from core.services.toggle_service import *" 验证无 Qt 依赖
```

**如果我在写代码过程中没有带这样的声明，你可以立即叫停**：

| 你的检查手段 | 发现问题的时机 |
|-------------|--------------|
| 看 `import` 行有没有 PySide6 | 写完立即看 |
| 看有没有 `setStyleSheet` / `setText` | 写完搜索一下 |
| 看文件是不是放在了约定的目录 | 看文件路径 |
| 看方法返回的是数据还是直接操作了控件 | 看方法签名和实现 |

#### 第三层：写完后的「合规自检」机制

每次完成一个文件或一个 Phase，我会自动运行这份检查清单：

```
□ 文件位置正确？（在 core/services/ 而不是根目录）
□ 没有 import PySide6 / QtWidgets / QtGui？（纯逻辑文件）
□ 所有颜色来自 token 引用？没有硬编码 #XXXXXX？
□ 所有尺寸来自 space token？没有硬编码数字？
□ 类/方法的命名符合设计文档约定？
□ 没有从旧代码 copy-paste 带 setStyleSheet 的片段？
□ 有 docstring 说明职责和依赖关系？
□ 可以在不启动 Qt 的情况下 import 并调用？（纯逻辑验证）
```

**你也可以随时要求我运行检查**：

| 你说的话 | 我会做的事 |
|---------|-----------|
| 「跑一遍合规检查」 | 逐条检查上面的清单，报告结果 |
| 「这段代码符合设计文档吗」 | 对照 ui-framework-design.md 逐项核对 |
| 「有没有耦合到不该耦合的东西」 | 分析 import 关系图，找出异常依赖 |

### 6.3 具体场景：如何防止常见违规

#### 场景 A: 防止我在 Service 里混入 UI 操作

```
违规示例（你要防止的）:

# core/services/toggle_service.py
def set_toggle(self, key, state):
    ...
    # ❌ 这里偷偷加了一行 UI 操作
    some_label.setText("已更新")   ← 绝不允许！

预防措施:
1. 我写完后，你搜一下文件里有没有 setText / setStyleSheet / addWidget
2. 或者要求我："写完跑一下 import 检查，确认没有 PySide6"
```

#### 场景 B: 防止我在 Widget 里写业务逻辑

```
违规示例:

# core/widgets/button.py
def mousePressEvent(self, event):
    ...
    # ❌ 按钮点击后直接保存配置文件
    save_feature_toggles(...)      ← 业务逻辑不应该在这里！
    self._add_log('ok', '已保存')  ← 日志也不应该在这里！

正确做法:
def mousePressEvent(self, event):
    ...
    self.clicked.emit()            # ← 只发射信号，不管外面怎么处理

# 在 page 层连接信号:
self.btn.clicked.connect(self._handle_toggle)

def _handle_toggle(self):
    result = self.toggle_service.set_toggle(...)  # ← 业务逻辑在 page/service 层
```

**判断口诀**:
> Widget 只管「长什么样 + 发射事件」
> Service 只管「数据处理 + 返回结果」
> Page 负责「组装 Widget + 连接 Service + 更新显示」

#### 场景 C: 防止我复制旧代码的坏习惯

```
违规示例:

# 我从 panel_builder.py 复制了一段过来
btn.setStyleSheet(f"""
    QPushButton {{
        background-color: {theme.cyber_yellow};
        color: {COLOR_BLACK};
        border: none;
        border-radius: 4px;         ← 硬编码数字！
        padding: 6px 16px;          ← 硬编码数字！
        font-size: 13px;            ← 硬编码数字！
    }}
""")

正确做法（用 Token）:
bg = self.token("button.solid.bg")
fg = self.token("button.solid.fg")
radius = self.space("corner.md")
padding_h = self.space("spacing.lg")
font_size = self.space("font.body")
# 然后在 paintEvent 中使用这些解析后的值
```

**预防措施**: 如果看到 `f"` 开头的多行样式字符串，99% 是从旧代码复制的。立即叫停。

### 6.4 推荐的协作节奏

```
每一次交互的理想流程:

┌──────────────────────────────────────────────────────┐
│  ① 你下达任务                                         │
│     "开始 Phase 0，提取 toggle_service"              │
└────────────────────┬─────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────┐
│  ② 我输出计划（不写代码）                              │
│     - 创建哪些文件                                     │
│     - 每个文件的类/方法设计                             │
│     - 从哪里提取、提取什么                              │
│     - 约束声明                                        │
└────────────────────┬─────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────┐
│  ③ 你审查计划                                         │
│     - 文件位置对不对？                                  │
│     - 接口设计合不合理？                                │
│     - 有没有遗漏或多余的？                              │
│     → "可以开始" 或 "修改 XXX"                         │
└────────────────────┬─────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────┐
│  ④ 我写代码（带约束声明）                               │
│     - 每个文件头部的注释说明                             │
│     - 遵循命名/结构/分层规范                            │
└────────────────────┬─────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────┐
│  ⑤ 我自检 + 报告                                      │
│     - 合规清单逐项勾选                                  │
│     - import 关系图                                    │
│     - 与设计文档的差异说明（如果有）                     │
└────────────────────┬─────────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────────┐
│  ⑥ 你最终确认                                         │
│     - 看代码 / 跑测试 / 试运行                          │
│     → "没问题，下一步" 或 "这里需要改"                  │
└──────────────────────────────────────────────────────┘
```

### 6.5 你的「紧急制动」话术

当你觉得事情在偏离轨道时，用这些话可以立即把我拉回来：

| 话术 | 效果 |
|------|------|
| **「停，先回到设计文档」** | 我会停止当前操作，重新读取 ui-framework-design.md 相关章节，校准方向 |
| **「这不符合第 X 章的规定」** | 我会去查那章内容，对比当前代码，列出差异 |
| **「你在写哪一层的代码？它应该只做一件事」** | 我会声明当前层级职责，并检查是否越界 |
| **「这个文件不应该依赖那个文件」** | 我会分析依赖关系图并修正 |
| **「给我看你写的所有 import 语句」** | 快速暴露非法耦合（比如 Service 里 import 了 PySide6） |
| **「回退，用更简单的方案」** | 我会撤销复杂做法，用最简实现 |
| **「把你的推理过程写出来」** | 我会把"为什么这样写"的理由列出来，方便你发现推理漏洞 |

### 6.6 最有效的单条规则

如果上面所有机制你都记不住，只需要记住一条：

> **在我写任何代码之前，先让我回答：「这个文件属于哪一层？它的单一职责是什么？它允许依赖谁、禁止依赖谁？」**
>
> 如果我答不上来或者答案模糊，就不要让我写。

这条规则能挡住 90% 的违规行为。因为一旦明确了层级和职责，大部分耦合错误自然就不会发生。

### 6.7 本次重构的「绝对禁区」

以下行为在任何阶段都**严格禁止**，如果我做了你可以直接拒绝：

| # | 禁区行为 | 正确做法 |
|---|---------|---------|
| 1 | 在 `services/` 文件中 `import PySide6` | Service 只用 Python 标准库 + 项目 data/core 纯模块 |
| 2 | 在 `widgets/` 文件中读写 JSON/调用 save_* | Widget 只管绘制和发射信号 |
| 3 | 在 `pages/` 文件中写 `setStyleSheet` f-string | 用 Token + CyberWidgetMixin 自绘 |
| 4 | 硬编码颜色值 `#FFE600` / 尺寸值 `28` / 字号 `13` | 全部从 token 读取 |
| 5 | 把两个不同层级的职责放在同一个方法里 | 拆分：Widget 管 UI，Service 管逻辑，Page 管连接 |
| 6 | 修改现有的 `panel_builder.py` / `management_panel.py` | 旧代码只读不写，直到 Phase 3 |
| 7 | 在根目录创建新的 .py 文件 | 全部在 `core/` 子目录下 |
| 8 | copy 旧代码中的内联样式字符串到新文件 | 新文件用全新的 Token 方式 |

---

## 七、新旧系统共存期：信号桥接方案

> Phase 0-2 期间，新旧两套 UI 可能同时运行。如何保证数据一致性？

### 7.1 核心原则：Service 是唯一数据源

```
┌──────────────────────────────────────────────────────┐
│                   Service 层（纯逻辑）                  │
│           core/services/toggle_service.py             │
│                                                       │
│  ← 旧 UI 调用（Phase 0-2: panel_builder.py）          │
│  → 新 UI 调用（Phase 1+: pages/toggles_page.py）       │
│                                                       │
│  Service 不关心谁在调用它，只负责返回正确的数据          │
└──────────────────────────────────────────────────────┘
```

**关键点**：
- Service **不发射 Qt Signal**（它不依赖 PySide6）
- Service 的方法返回数据（dict / list / bool），由调用方决定怎么处理
- 如果需要"通知变化"，Service 返回一个标志位，由 UI 层决定是否刷新

### 7.2 数据流向规范

```
用户操作 → Widget 发射信号 → Page 的槽函数接收 → 调用 Service 方法 → Service 返回结果 → Page 更新 Widget
```

**错误做法**（直接耦合）：

```python
# ❌ Widget 直接调用 Service 然后自己更新另一个 Widget
class CyberToggle(CyberWidgetMixin, QCheckBox):
    def _on_toggled(self, checked):
        ToggleService().save_toggle(self._key, checked)
        # 然后自己去更新别的控件... 耦合！
```

**正确做法**（单向数据流）：

```python
# ✅ Widget 只发信号，不管别人怎么响应
class CyberToggle(CyberWidgetMixin, QCheckBox):
    toggled_data_changed = Signal(str, bool)  # (key, value)

    def _on_toggled(self, checked):
        self.toggled_data_changed.emit(self._key, checked)

# ✅ Page 层连接信号到 Service
class TogglesPage(BasePage):
    def _setup_ui(self):
        for key, config in self._toggle_configs:
            toggle = CyberToggle(key)
            toggle.toggled_data_changed.connect(self._on_toggle_changed)

    @Slot(str, bool)
    def _on_toggle_changed(self, key, value):
        success = ToggleService().set_toggle(key, value)
        if success:
            self._refresh_related_widgets(key)   # 只刷新受影响的 widget
```

### 7.3 共存期的状态同步方案

当新旧窗口同时存在时：

| 场景 | 同步方式 |
|------|---------|
| 用户在新窗口改了开关 | Service 保存 → 旧窗口下次读取时自动拿到新值（因为都读同一个 JSON 文件） |
| 用户在旧窗口改了开关 | Service 保存 → 新窗口通过定时轮询或 `QFileSystemWatcher` 检测文件变化并刷新 |
| 主题切换 | TokenManager.emit(`preset_changed`) → 所有注册的 CyberWidget 自动 `update()` |

**不需要**实时双向同步。两个窗口读同一个数据源就够了。

### 7.4 Phase 过渡检查清单

每个 Phase 结束时验证：

```
□ Phase 0 结束:
  - services/ 下所有文件可以独立 import 并运行测试
  - 旧代码功能不受影响
  - 没有 PySide6 import 泄漏进 services/

□ Phase 1 结束:
  - AppShell 可以启动并显示空导航栏
  - Demo 窗口中 CyberButton 可见且可点击
  - TokenManager 加载 YAML 无报错

□ Phase 2 结束（每完成一个页面后）:
  - 该页面的所有功能在新窗口中可用
  - 与旧窗口同一功能的输出一致
  - 单元测试全部通过
  - G3 人工走查清单全过

□ Phase 3 结束:
  - main.py 默认启动 AppShell
  - 旧 ManagementPanel 仍可通过参数启动（回退）
  - 删除的废弃文件不影响任何功能

---

## 附录 A: 兼容映射表（迁移过渡用）

> **来源**: 从 `ui-framework-design.md` 附录 C 迁移至此。
> **用途**: Phase 0~2 期间，将旧代码中的常量/写法替换为新 Token 时查阅。
> **生命周期**: Phase 3 结束后可删除。

### A.1 颜色常量映射（theme_proxy.py → Token）

| 旧常量 (`theme_proxy.py`) | 旧值示例 | 新 Token 路径 | 说明 |
|---------------------------|---------|--------------|------|
| `CYBER_YELLOW` | `#FFE600` | `raw.brand.yellow` / `alias.accent.primary` | 品牌黄 |
| `CYBER_CYAN` | `#00F0FF` | `raw.brand.cyan` / `alias.accent.secondary` | 品牌青 |
| `CYBER_MAGENTA` | `#FF00E5` | `raw.brand.magenta` / `alias.accent.tertiary` | 品牌品红 |
| `CYBER_ORANGE` | `#FF6B00` | `raw.brand.orange` | 品牌橙 |
| `CYBER_RED` | `#FF3366` | `raw.brand.red` / `alias.semantic.danger` | 品牌红/危险 |
| `CYBER_GREEN` | `#00FF88` | `raw.brand.green` / `alias.semantic.success` | 品牌绿/成功 |
| `PANEL_BG` / `CYBER_PANEL_BG` | `#0E0E24` | `raw.surface.base` / `semantic.bg.base` | 面板背景 |
| `CARD_BG` / `CYBER_CARD_BG` | `#16163A` | `raw.surface.raised` / `semantic.bg.raised` | 卡片背景 |
| `CYBER_BORDER` / `SUBTLE_BORDER` | `#2A2A5A` | `raw.border.default` / `semantic.border.default` | 边框色 |
| `CYBER_TEXT` | `#E8ECFF` | `alias.text.primary` / `semantic.text.primary` | 主文字 |
| `CYBER_TEXT_DIM` / `MUTED_TEXT` | `#8888AA` | `alias.text.secondary` / `semantic.text.secondary` | 次要文字 |
| `LIGHT_TEXT` | `#FFFFFF` | `alias.text.on_accent` | 强调色上的文字 |
| `COLOR_DARK_GRAY` | `#555577` | `alias.text.disabled` / `semantic.text.disabled` | 禁用文字 |
| `COLOR_BLACK` | `#000000` | `raw.elevation.black` | 纯黑 |
| `BTN_DEFAULT_BG` | `#FFE600` | `components.button.solid.fill` | 按钮默认背景 |
| `BTN_DEFAULT_TEXT` | `#0E0E24` | `components.button.solid.text` | 按钮默认文字 |
| `BTN_DEFAULT_BORDER` | `transparent` | `components.button.solid.border` | 按钮默认边框 |
| `BTN_HOVER_BG` | `#FFF000` | `components.button.solid.hover.fill` | 按钮 hover 背景 |
| `BTN_HOVER_TEXT` | `#0E0E24` | `components.button.solid.hover.text` | 按钮 hover 文字 |
| `BTN_PRESSED_BG` | `#CCB800` | `components.button.solid.pressed.fill` | 按钮 pressed 背景 |
| `BTN_DISABLED_BG` | `#333355` | `components.button.solid.disabled.fill` | 按钮禁用背景 |
| `BTN_DISABLED_TEXT` | `#666688` | `components.button.solid.disabled.text` | 按钮禁用文字 |
| `LABEL_DEFAULT` | `#AAAACC` | `semantic.text.label` | 标签文字 |
| `OVERLAY_BG_COLOR` | `rgba(14,14,36,0.85)` | `semantic.overlay.bg` | 遮罩背景 |
| `PROGRESS_GRADIENT_START/MID/END` | 渐变色组 | `components.progress.gradient.*` | 进度条渐变 |
| `COLOR_GOLD/SILVER/COPPER` | 遗物稀有度色 | `raw.game.gold/silver/copper` | 游戏数据颜色 |
| `COLOR_VAULTED` | 红色 | `alias.semantic.danger` | 已入库(不可获取) |
| `COLOR_AVAILABLE` | 绿色 | `alias.semantic.success` | 可出库 |
| `BRAND_BILIBILI/GITHUB` | 外部品牌色 | `raw.external.bilibili/github` | 第三方品牌 |
| `STATUS_ONLINE/INGAME/OFFLINE/AWAY` | 在线状态色 | `semantic.status.*` | 状态指示 |

### A.2 尺寸/样式常量映射

| 旧写法（硬编码或变量） | 旧值 | 新 Space Token | 说明 |
|----------------------|------|---------------|------|
| `setFixedHeight(28)` | 28px | `space("height.btn_sm")` | 小按钮/小输入框 |
| `setFixedHeight(34)` | 34px ❌ | `space("height.btn_md")` → 36 | **违规值，归并到 36** |
| `setFixedHeight(38)` | 38px ❌ | `space("height.btn_lg")` → 44 | **违规值，归并到 44** |
| `setFixedHeight(40)` | 40px | `space("height.nav_item")` | 导航项高度 |
| `setFixedHeight(56)` | 56px | `space("height.card_min") * 1 + spacing` | 卡片最小高度 |
| `setContentsMargins(8, 8, 8, 8)` | 8px | `space("spacing.md")` | 标准内边距 |
| `setSpacing(4)` | 4px | `space("spacing.xs")` | 最小间距 |
| `setSpacing(12)` | 12px | `space("spacing.lg")` | 大间距 |
| `border-radius: 4px` | 4px | `space("corner.sm")` | 小切角 |
| `border-radius: 6px` | 6px | `space("corner.md")` | 中等切角 |
| `font-size: 13px` | 13px | `space("font.size.body_md")` | 默认字号 |
| `font-size: 11px` | 11px | `space("font.size.body_xs")` | 小号字体 |
| `QFont().setPointSize(10)` | 10pt | `space("font.size.caption")` | 最小字号 |
| `setMinimumWidth(200)` | 200px | `space("width.input_lg")` 或自定义 | 输入框宽度 |

### A.3 API 调用模式映射

| 旧模式（禁止） | 新模式（必须） | 所在文件 |
|---------------|--------------|---------|
| `from core.theme_proxy import CYBER_YELLOW; color = CYBER_YELLOW` | `from core.tokens.manager import TokenManager; color = TokenManager.get().resolve("accent.primary")` | 所有新文件 |
| `self.setStyleSheet(f"background: {theme.cyber_yellow}")` | `paintEvent 中 painter.fillPath(path, QColor(self.token("bg.raised")))` | widgets/ |
| `theme_config.load_preset(name)` + 手动 sync | `TokenManager.get().load_preset(name)` | 启动入口 |
| `panel_styles.refresh_panel_style(panel)` | 自动：token 变更时 emit signal → widget.update()` | 废弃 |
