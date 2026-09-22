# 价格查询架构重构设计

> **目的**:替换当前 `core/services/market_price_service.py` + `core/price_service.py` 混合的两套实现,建立清晰的分层架构和状态机,提供完整的 UI 反馈。
>
> **状态**: ✅ **已实现并通过测试** · 2026-08-07
>
> 实施记录: 见底部 §11「实现记录」段
>
> **前置问题**(已修复,详见 [price_query_architecture_issues.md](./price_query_architecture_issues.md)):
> 1. ✅ `fetch_wm_items()` 失败不缓存 → 每次都重试 3 次 × 15s = 51s
> 2. ✅ `core/price_service.py` 3s timeout → WM v2 实际 7-15s,100% 失败
> 3. ✅ `core/price_service.py:59` `WM_API_STATS` 用 v1 → 已 deprecated
> 4. ✅ UI 无任何加载/失败反馈 → 用户无法感知状态
> 5. ✅ `PriceFetcher` 线程 + EventEmitter 自建机制,易出错

---

## 1. 设计目标

| 目标 | 描述 |
|------|------|
| **清晰分层** | Infrastructure → Service → State → Page,单向依赖 |
| **完整状态机** | 用户在 UI 上能感知 7 种状态,每种有明确反馈 |
| **快速失败** | 网络挂时不重试到天荒地老,30s 冷却 + 手动重试 |
| **优雅降级** | WM API 挂时自动走 DB 中文/拼音搜索 |
| **单一数据源** | State 单例持有所有缓存,Page 只读 |
| **类型安全** | 关键路径加类型注解,Service 输入输出明确 |

---

## 2. 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│  L2  Page (prices_page.py)                                    │
│  - 纯 UI 组装: 搜索框 + 下拉 + 表格 + 状态条                 │
│  - 订阅 PriceQueryState.signals.*, 转发到 UI                  │
│  - 不持有业务逻辑,不发网络请求                                │
└──────────────────────────────────────────────────────────────┘
                          ↓ 依赖 (允许)
┌──────────────────────────────────────────────────────────────┐
│  L-State  PriceQueryState (core/state/price_query_state.py) │
│  - 单例 QObject,跨页面共享                                   │
│  - 状态机: IDLE / LOADING / READY / DEGRADED / FAILED         │
│  - 子状态: SEARCHING / QUERYING / PRICE_READY / PRICE_FAILED  │
│  - 缓存: 全物品列表 + 当前搜索结果                            │
│  - Signal: state_changed, progress, error, search_updated     │
└──────────────────────────────────────────────────────────────┘
                          ↓ 依赖 (允许)
┌──────────────────────────────────────────────────────────────┐
│  L-Service  三个独立 service                                  │
│  1. WmItemsRepository    - 全物品列表 (下载+缓存+重试+冷却) │
│  2. PriceFetcher         - 单物品价格 (订单 API)             │
│  3. SearchCoordinator    - 搜索协调 (WM+DB 融合)             │
└──────────────────────────────────────────────────────────────┘
                          ↓ 依赖 (允许)
┌──────────────────────────────────────────────────────────────┐
│  L-Infrastructure  HttpClient (core/services/http_client.py) │
│  - 统一 requests.Session                                     │
│  - 重试策略: 指数退避 1s/2s/4s,最多 3 次                     │
│  - 超时: connect=5s, read=10s                                │
│  - 错误归一化: NetworkError / TimeoutError / ApiError         │
└──────────────────────────────────────────────────────────────┘
```

### 2.1 依赖关系（严格单向）

```
Page
  ↓
State (PriceQueryState)
  ↓
Service (3 个,只依赖 Infrastructure)
  ↓
Infrastructure (HttpClient)
```

**禁止**:
- Service 依赖 Page
- Service 依赖 State 直接读写(只通过 State 的公开 API)
- Page 直接调 Service,必须经 State 中转
- Infrastructure 依赖其他任何层

---

## 3. 状态机设计

### 3.1 状态枚举

```python
class PriceQueryStatus(str, Enum):
    """价格查询顶层状态。"""
    IDLE = "idle"               # 初始态
    LOADING = "loading"         # 加载全物品列表中
    READY = "ready"             # 列表就绪,搜索可用
    DEGRADED = "degraded"       # 列表加载失败,降级到 DB 搜索
    FAILED = "failed"           # 完全失败,搜索不可用

class SearchSubStatus(str, Enum):
    """搜索子状态(独立信号)。"""
    IDLE = "search_idle"
    SEARCHING = "searching"     # 用户输入后搜索中
    SEARCH_FAILED = "search_failed"

class QuerySubStatus(str, Enum):
    """价格查询子状态。"""
    IDLE = "query_idle"
    QUERYING = "querying"       # 拉订单中
    QUERY_FAILED = "query_failed"
    QUERY_READY = "query_ready"
```

### 3.2 状态转换图

```
                       ┌──────────────┐
                       │     IDLE     │ ← 应用启动
                       └──────┬───────┘
                              │ warm_start()
                              ▼
              ┌───────────────────────────┐
              │         LOADING          │
              └──────┬─────────────┬─────┘
                  成功│            │失败
                     ▼            ▼
            ┌──────────────┐  ┌──────────────┐
            │    READY     │  │  DEGRADED    │ ← 30s 冷却
            └──────┬───────┘  └──────┬───────┘
                   │                 │ retry_requested()
                   │                 ▼
                   │          ┌──────────────┐
                   │          │    FAILED    │ ← 完全失败
                   │          │ (有重试按钮) │
                   │          └──────────────┘
                   │
                   │ 任意状态下,可触发搜索
                   ▼
            ┌─────────────────────────────┐
            │         SEARCHING            │
            │  (顶层状态不变,只发信号)     │
            └─────────────────────────────┘
                   │
              成功│  │失败
                  ▼  ▼
       ┌────────────────────────────┐
       │  子状态: SEARCH_READY /    │
       │         SEARCH_FAILED       │
       └────────────────────────────┘
                  │
                  │ 用户点选下拉项
                  ▼
       ┌────────────────────────────┐
       │        QUERYING             │
       │  (顶层状态不变,只发信号)   │
       └────────────┬───────────────┘
              成功  │  │ 失败
                    ▼  ▼
       ┌────────────────────────────┐
       │  子状态: QUERY_READY /      │
       │         QUERY_FAILED        │
       └────────────────────────────┘
```

### 3.3 关键不变式

- **顶层状态**：`IDLE` → `LOADING` → `READY|FAILED|DEGRADED` 不可逆（`FAILED` 可手动重试回到 `LOADING`）
- **子状态独立**：搜索/查询的子状态不影响顶层状态
- **DEGRADED 含义**：列表加载失败,但 DB 可用 → 走 DB 阶段搜索
- **30s 冷却**：失败后 30s 内不再自动重试,需用户点"重试"按钮

---

## 4. 详细设计

### 4.1 `core/services/http_client.py` (Infrastructure)

```python
"""
[L-Infrastructure] HttpClient — 统一 HTTP 客户端

依赖: requests
职责: 统一网络层,处理重试/超时/错误归一化
"""

class HttpError(Exception):
    """网络层错误基类。"""
    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)

class NetworkError(HttpError):
    """网络层错误(连接失败/DNS/SSL等)。"""

class TimeoutError(HttpError):
    """超时错误。"""

class ApiError(HttpError):
    """API 业务错误(HTTP 4xx/5xx)。"""

class HttpClient:
    """统一 HTTP 客户端(单例)。"""
    
    def __init__(
        self,
        max_retries: int = 3,
        retry_backoff: list[float] = [1.0, 2.0, 4.0],  # 指数退避
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
    ):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "WARFRAME-RELIC/1.0",
            "Accept": "application/json",
            "Platform": "pc",
            "Language": "zh-hans",
        })
        self._max_retries = max_retries
        self._retry_backoff = retry_backoff
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
    
    def get_json(self, url: str, **kwargs) -> dict:
        """GET 请求,返回 JSON。错误归一化为 HttpError 子类。
        
        重试策略:
        - NetworkError / TimeoutError: 指数退避重试,最多 max_retries 次
        - ApiError (4xx/5xx): 4xx 不重试,5xx 重试
        - 其他: 不重试,直接抛
        """
        ...
```

### 4.2 `core/state/price_query_state.py` (State)

```python
"""
[L-State] PriceQueryState — 价格查询全局状态

依赖: PySide6 Signal
职责: 状态机 + 缓存 + 跨页面信号
"""

class PriceQueryState(QObject):
    """价格查询状态机(单例)。"""
    
    # 顶层状态变化
    top_status_changed = Signal(str)  # PriceQueryStatus value
    # 加载进度 (0-100)
    load_progress = Signal(int, str)  # (percent, message)
    # 错误
    error_occurred = Signal(str, str)  # (level, message)
    
    # 搜索
    search_started = Signal()
    search_completed = Signal(list)  # results
    search_failed = Signal(str)  # error message
    
    # 价格查询
    query_started = Signal(str)  # slug
    query_completed = Signal(dict)  # result
    query_failed = Signal(str, str)  # (slug, error)
    
    _instance: "PriceQueryState | None" = None
    
    @classmethod
    def instance(cls) -> "PriceQueryState": ...
    
    def __init__(self):
        super().__init__()
        # 顶层状态
        self._top_status: PriceQueryStatus = PriceQueryStatus.IDLE
        # 缓存
        self._items_cache: list[tuple[str, str, list[str]]] = []
        self._items_cache_time: float = 0
        # 失败冷却
        self._failure_time: float = 0
        self._failure_message: str = ""
        # 搜索
        self._current_search_keyword: str = ""
    
    # ── 顶层状态 API ──
    @property
    def top_status(self) -> PriceQueryStatus: ...
    def is_search_available(self) -> bool:  # READY or DEGRADED
        return self._top_status in (PriceQueryStatus.READY, PriceQueryStatus.DEGRADED)
    
    # ── 缓存 API ──
    def get_items(self) -> list[tuple[str, str, list[str]]]:
        """返回全物品列表(只读副本)。"""
    def is_items_cache_valid(self) -> bool: ...
    def set_items_cache(self, items: list) -> None: ...
    def clear_items_cache(self) -> None: ...
    
    # ── 失败冷却 ──
    def is_in_failure_cooldown(self) -> bool:
        """是否在失败冷却中(默认 30s)。"""
    def get_failure_message(self) -> str: ...
    def record_failure(self, message: str) -> None: ...
    def clear_failure(self) -> None: ...
    
    # ── 状态转移 ──
    def _set_top_status(self, status: PriceQueryStatus) -> None: ...
```

### 4.3 `core/services/wm_items_repository.py` (Service)

```python
"""
[L-Service] WmItemsRepository — WM 全物品列表仓库

依赖: HttpClient, PriceQueryState
职责: 加载 + 缓存 + 状态更新
"""

class WmItemsRepository:
    """WM 全物品列表仓库(单例,无 QObject 继承)。"""
    
    def __init__(self, http: HttpClient, state: PriceQueryState):
        self._http = http
        self._state = state
    
    def warm_cache_async(self) -> None:
        """异步预热缓存(非阻塞,后台线程)。
        
        流程:
        1. 检查冷却期(失败后 30s 内不重试)
        2. 缓存有效 → 直接 return
        3. 否则后台线程跑 fetch_with_retry
        4. 成功 → set_items_cache + READY
        5. 失败 → record_failure + DEGRADED
        """
        ...
    
    def warm_cache_blocking(self, timeout: float = 60.0) -> bool:
        """同步预热(用于测试)。"""
        ...
    
    def refresh(self) -> None:
        """强制刷新(忽略冷却,用户主动点击"重试"时用)。"""
        ...
    
    def _fetch_with_retry(self) -> list[tuple[str, str, list[str]]]:
        """实际下载 + 重试 + 解析。"""
        ...
```

### 4.4 `core/services/price_fetcher.py` (Service)

```python
"""
[L-Service] PriceFetcher — 单物品价格查询

依赖: HttpClient, PriceQueryState
职责: 单物品订单 API 查询 + 解析
"""

@dataclass
class PriceResult:
    """单个物品的价格查询结果。"""
    slug: str
    name: str
    min_platinum: int | None      # 最低卖价
    max_platinum: int | None      # 最高卖价
    avg_platinum: float | None    # 加权均价
    sell_orders: list[dict]       # 卖单列表
    online_count: int             # ingame/online 的订单数
    total_count: int              # 总订单数
    fetched_at: float             # 时间戳

class PriceFetcher:
    """单物品价格查询器(单例)。"""
    
    def __init__(self, http: HttpClient, state: PriceQueryState):
        self._http = http
        self._state = state
    
    def fetch_async(self, slug: str, name: str = "") -> None:
        """异步查询(后台线程,结果通过 state.query_completed/failed 通知)。"""
        ...
    
    def fetch_blocking(self, slug: str, name: str = "") -> PriceResult:
        """同步查询(测试用)。"""
        ...
```

### 4.5 `core/services/search_coordinator.py` (Service)

```python
"""
[L-Service] SearchCoordinator — 搜索协调器

依赖: WmItemsRepository, PriceQueryState
职责: 协调 WM API + DB 搜索
"""

class SearchCoordinator:
    """搜索协调器(单例)。"""
    
    def __init__(self, repo: WmItemsRepository, state: PriceQueryState):
        self._repo = repo
        self._state = state
    
    def search_async(self, keyword: str) -> None:
        """异步搜索。结果通过 state.search_completed/failed 通知。
        
        策略:
        - 顶层状态 READY: WM API 阶段 + DB 阶段 + 战甲扩展
        - 顶层状态 DEGRADED: 仅 DB 阶段(中文/拼音)
        - 其他: 不响应
        """
        ...
    
    def search_blocking(self, keyword: str) -> list[dict]:
        """同步搜索(测试用)。"""
        ...
    
    def _search_wm(self, kw: str) -> list[dict]: ...
    def _search_db(self, kw: str) -> list[dict]: ...
    def _expand_frame_parts(self, base_slugs: set[str]) -> list[dict]: ...
```

### 4.6 `core/pages/prices_page.py` (Page)

```python
"""
[L2] PricesPage — 价格查询页面(纯 UI)

依赖: PriceQueryState (单例)
职责: UI 渲染 + 信号订阅
"""

class PricesPage(PageBase):
    def __init__(self) -> None:
        super().__init__()
        # 订阅 State 信号
        PriceQueryState.instance().top_status_changed.connect(self._on_top_status)
        PriceQueryState.instance().load_progress.connect(self._on_load_progress)
        PriceQueryState.instance().error_occurred.connect(self._on_error)
        PriceQueryState.instance().search_started.connect(self._on_search_started)
        PriceQueryState.instance().search_completed.connect(self._on_search_completed)
        PriceQueryState.instance().search_failed.connect(self._on_search_failed)
        PriceQueryState.instance().query_started.connect(self._on_query_started)
        PriceQueryState.instance().query_completed.connect(self._on_query_completed)
        PriceQueryState.instance().query_failed.connect(self._on_query_failed)
    
    def on_enter(self) -> None:
        """进入页面:启动异步预热。"""
        WmItemsRepository.instance().warm_cache_async()
    
    def _on_top_status(self, status: str) -> None:
        """顶层状态变化:更新顶部状态条。"""
        # IDLE/LOADING/READY/DEGRADED/FAILED → UI 反馈
        ...
    
    def _on_search_text_changed(self, text: str) -> None:
        """用户输入:300ms debounce 后异步搜索。"""
        self._search_timer.start(300)
    
    def _do_search(self) -> None:
        """debounce 触发:调 SearchCoordinator。"""
        kw = self._search_input.text().strip()
        if not kw:
            self._dropdown.hide()
            return
        SearchCoordinator.instance().search_async(kw)
    
    def _on_search_completed(self, results: list) -> None:
        """搜索完成:更新下拉项。"""
        # 如果 DEGRADED,显示"(网络不通,仅 DB 搜索)"
        ...
```

---

## 5. UI 反馈规范

### 5.1 顶部状态条（常驻）

| 状态 | 文本 | 图标 | 颜色 | 交互 |
|------|------|------|------|------|
| IDLE | "就绪" | ● | 默认 | 无 |
| LOADING | "加载物品列表中... 67%" | ⟳ | 蓝 | 无 |
| READY | "就绪 · 3065 个物品" | ✓ | 绿 | 无 |
| DEGRADED | "网络问题 · 仅中文搜索" | ⚠ | 黄 | 点"重试" |
| FAILED | "加载失败 · 点击重试" | ✗ | 红 | 点"重试" |

### 5.2 搜索框（输入时）

| 状态 | 反馈 |
|------|------|
| SEARCHING | 右侧 spinner 转 |
| SEARCH_READY | 下拉项展示 |
| SEARCH_FAILED | 下拉: "搜索失败: <原因>" |
| 空结果 | 下拉: "未匹配到 '<kw>'" |

### 5.3 状态行（页面底部）

| 状态 | 反馈 |
|------|------|
| QUERYING | "查询 Rhino Prime 套装..." + 进度条 |
| QUERY_READY | "均价 70p · 50 条卖单 · 30 秒前" |
| QUERY_FAILED | "查询失败: 网络超时 [重试]" |

### 5.4 Toast 通知

| 事件 | Toast |
|------|-------|
| DEGRADED | 黄色 toast: "网络问题,功能受限" |
| FAILED | 红色 toast: "加载失败,请稍后重试" |
| QUERY_FAILED | 红色 toast: "价格查询失败" |

---

## 6. 配置常量

```python
# core/services/http_client.py
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = [1.0, 2.0, 4.0]  # 指数退避(秒)
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 10.0

# core/state/price_query_state.py
FAILURE_COOLDOWN_SECONDS = 30  # 失败后 30s 冷却
LOAD_PROGRESS_EMIT_INTERVAL = 0.2  # 进度信号最多 200ms 一次

# core/services/wm_items_repository.py
WM_API_ITEMS_URL = "https://api.warframe.market/v2/items"
WM_ITEMS_PAGE_SIZE = 0  # 0 = 一次拿全部(WM v2 一次返回全量)
_EXCLUDED_TAGS = frozenset({'glyph', 'skin', 'helmet', 'animation', 'relic', 'mod'})

# core/services/price_fetcher.py
WM_ORDERS_URL = "https://api.warframe.market/v2/orders/item"
WM_STATS_URL = "https://api.warframe.market/v2/orders/item/{slug}/statistics"
PRICE_FETCH_TIMEOUT = 15.0

# core/services/search_coordinator.py
SEARCH_DEBOUNCE_MS = 300  # 已在 Page 层 debounce,这里是后端节流
SEARCH_MAX_RESULTS = 20
```

---

## 7. 向后兼容策略

| 旧 API | 新替代 | 处理 |
|--------|--------|------|
| `market_price_service.fetch_wm_items()` | `WmItemsRepository.instance().warm_cache_blocking()` | 保留旧函数,内部转调新 API,加 deprecation warning |
| `market_price_service.search_wm_items()` | `SearchCoordinator.instance().search_blocking()` | 保留旧函数,加 deprecation warning |
| `price_service.query_price()` | `PriceFetcher.instance().fetch_blocking()` | 保留旧函数,加 deprecation warning |
| `price_service._fetch_price_from_api()` | 删除 | 直接删除(私有 API) |
| `prices_page.PriceFetcher` 内部线程 | 删除 | 用 `PriceFetcher.instance().fetch_async()` |

---

## 8. 文件清单

### 新增
- `core/services/http_client.py` (~150 行)
- `core/services/wm_items_repository.py` (~120 行)
- `core/services/price_fetcher.py` (~180 行)
- `core/services/search_coordinator.py` (~200 行)
- `core/state/price_query_state.py` (~200 行)
- `core/services/di.py` (依赖注入容器,~50 行)
- `docs/price_query_architecture.md` (本文件)

### 重写
- `core/pages/prices_page.py` (从 800+ 行 → 400 行)

### 修改
- `core/price_service.py` (标记 deprecated,内部转调新 API)
- `core/services/market_price_service.py` (标记 deprecated,内部转调新 API)
- `data/presets/cyberpunk.yaml` (加 i18n key)
- `requirements.txt` (加 requests)

### 不动
- `core/services/recognition_pipeline_service.py` (CTRL+T 流程用 price_service,通过兼容层自动迁移)
- `core/mode_handlers.py`
- `core/recognizers/matcher.py`

---

## 9. 实施步骤

1. **基础设施**: 加 requests 依赖 + 写 http_client + 单元测试
2. **State**: 写 price_query_state.py
3. **Service**: 写 3 个 service + di.py
4. **Page**: 重写 prices_page.py
5. **兼容**: 旧 service 标记 deprecated,转调新 API
6. **i18n**: 加 cyberpunk.yaml key
7. **测试**: 3 个集成测试(成功/失败/UI 状态)
8. **冒烟**: 启动 app + 切页 + 搜 + 选 + 查价 + 关闭

---

## 10. 风险与回退

| 风险 | 缓解 |
|------|------|
| 网络层重写引入新 bug | 旧 `urllib` 版本作为 fallback,新 `requests` 版本并行跑 1 周 |
| State 单例全局污染 | State 只在 PricesPage 注入,其他页面不接触 |
| 异步线程 + Qt 信号交互出错 | 严格遵守"非主线程只发信号,主线程收信号" |
| i18n key 漏改 | 写脚本 grep 所有字符串,确认都过 i18n |

---

**待用户审批的设计决策**:
- [x] 网络层: requests + HttpClient
- [x] 状态机位置: core/state/price_query_state.py
- [x] Service 拆分: 3 个独立 service
- [x] 失败策略: 30s 冷却 + 手动重试 + DB 降级

---

## 11. 实现记录(2026-08-07)

### 11.1 实际产出

| 文件 | 状态 | 行数 | 职责 |
|------|------|------|------|
| [http_client.py](file:///d:/MyProgram/WARFRAME-RELIC/core/services/http_client.py) | ✅ 新增 | 290 | requests.Session 复用 + 重试 + 错误归一化 |
| [wm_items_repository.py](file:///d:/MyProgram/WARFRAME-RELIC/core/services/wm_items_repository.py) | ✅ 新增 | 234 | 全物品列表(缓存+冷却+异步预热) |
| [price_fetcher.py](file:///d:/MyProgram/WARFRAME-RELIC/core/services/price_fetcher.py) | ✅ 新增 | 337 | 单物品价格查询(异步+同步) |
| [search_coordinator.py](file:///d:/MyProgram/WARFRAME-RELIC/core/services/search_coordinator.py) | ✅ 新增 | 315 | 搜索协调(W M + DB + 战甲扩展) |
| [price_query_state.py](file:///d:/MyProgram/WARFRAME-RELIC/core/state/price_query_state.py) | ✅ 新增 | 315 | 状态机单例 + 缓存 + 失败冷却 |
| [prices_page.py](file:///d:/MyProgram/WARFRAME-RELIC/core/pages/prices_page.py) | ✅ 重写 | ~650 | 状态机驱动的 UI 层 |
| [market_price_service.py](file:///d:/MyProgram/WARFRAME-RELIC/core/services/market_price_service.py) | ⚠️ deprecated | 443 | 保留为向后兼容入口 |
| [price_service.py](file:///d:/MyProgram/WARFRAME-RELIC/core/price_service.py) | ⚠️ deprecated | 480 | 保留为向后兼容入口 |

**简化**:原计划 [di.py](file:///d:/MyProgram/WARFRAME-RELIC/core/services/di.py) 依赖注入容器取消,改用各 Service 的 `instance()` 单例方法,更轻量。

### 11.2 测试结果

| 测试 | 状态 | 关键数据 |
|------|------|---------|
| [_test_http_client.py](file:///d:/MyProgram/WARFRAME-RELIC/_test_http_client.py) | ✅ 通过 | 覆盖成功/超时/SSL/4xx 不重试/5xx 重试 |
| [_test_integration_success.py](file:///d:/MyProgram/WARFRAME-RELIC/_test_integration_success.py) | ✅ 通过 | 1612 个物品 · 1138 卖单 · 均价 80.7p |
| [_test_integration_degraded.py](file:///d:/MyProgram/WARFRAME-RELIC/_test_integration_degraded.py) | ✅ 通过 | 模拟离线 → DEGRADED · DB 阶段正常 |
| [_test_integration_ui_feedback.py](file:///d:/MyProgram/WARFRAME-RELIC/_test_integration_ui_feedback.py) | ✅ 通过 | 9 个信号链路 + 7 个 Page 槽函数 |
| [_test_final_smoke.py](file:///d:/MyProgram/WARFRAME-RELIC/_test_final_smoke.py) | ✅ 通过 | 启动→切页→搜→选→查价→复制→关闭 完整链路 |

### 11.3 实施中修复的 bug

1. **DB 路径错误**:`warframe_items.db`(0 字节空文件) → 改为 `warframe.db`(139MB 真实数据)
2. **网络超时太短**:旧 3s 100% 超时 → 改为 connect=5s + read=10s + 指数退避重试
3. **search_blocking 没填充 zh_name**:`_search_worker` 和 `search_blocking` 重复维护 zh 翻译逻辑 → 抽出 `_post_process` 共享
4. **Token key 错误**:`alias.semantic.error` 不存在 → 改为 `alias.semantic.danger`(yaml 实际定义)
5. **summary_format 缺字段**:模板需要 `{median_p}`,`prices_page._populate_summary` 没传 → 加 `median_p=weighted_avg` + try/except 兼容
6. **页面创建失败导致导航失联**:`_create_page` 失败 return None → 返回 `PlaceholderErrorPage` 占位,导航不丢

### 11.4 用户使用指南

#### 进入价格页时
- 顶部状态条自动从 **IDLE → LOADING**,显示 "加载物品列表中... 67%"
- 第一次拉全物品列表约 5-25s(WM v2 完整列表 1612 个物品)
- 加载完成:状态条 → **READY**,显示 "就绪 · 1612 个物品"
- 加载失败:状态条 → **DEGRADED**(黄色 + 重试按钮),搜索仍可用(降级到 DB 阶段)

#### 搜索
- 输入框输入后 300ms debounce 触发搜索
- 下拉框显示 searching → 结果/无结果/错误
- 降级状态下结果带 `⚠降级` 标记

#### 选物品查价
- 点击下拉项触发价格查询
- 状态行显示 "正在查询 X..."
- 完成:表格填入卖单 + 摘要(最低/中位/均价/最高)
- 点击 seller 列复制密语到剪贴板(状态行反馈)

#### 失败处理
- 网络挂:状态条 → DEGRADED,搜索仍可用(只搜中文)
- 查询某物品失败:状态行红字 + 不影响其他物品查询
- 用户点重试按钮:忽略冷却,强制重新加载

### 11.5 维护指南

#### 新增搜索数据源
```python
# 1. 在 SearchCoordinator._search_all_phases 加新阶段
# 2. 在 PriceQueryState 不用动(只读已有信号)
# 3. 跑 _test_integration_success.py 验证
```

#### 调整 UI 反馈
- 状态条:改 `_StatusBar.update_status()` 分支
- 下拉样式:改 `prices_page._on_search_completed` 里的 item 渲染
- i18n:在 `data/presets/cyberpunk.yaml` 加 `prices.*` key

#### 排查问题
1. 看顶部状态条 → 判断顶层状态
2. 看状态行 → 判断当前操作
3. 看 `data/logs/cd_assist_debug.log` → 完整 trace
4. 看 `cd_assist_debug.log` + `state.*` 字段 → 信号链路
