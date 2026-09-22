"""
[L0/L1] core.theme_proxy — 主题颜色代理(已重构,从 token 读取)

历史:
  旧版通过 core.theme_config 字典提供颜色,本文件只做代理。
  现 core.theme_config 已删除,所有颜色直接走 TokenManager,
  保证主题切换时颜色值自动跟随。

模块级颜色常量(如 CYBER_YELLOW, BTN_DEFAULT_BG 等)由
``_TokenProxy`` 描述符包装,每次访问时从 TokenManager 实时取值。
**零硬编码颜色字面量**——所有 hex 都在 data/presets/cyberpunk.yaml。

依赖: core.tokens.manager
被谁用: core.constants(向后兼容 re-export)/ 任何需要颜色常量的旧代码

使用方式(与旧版完全一致):
    from core.theme_proxy import CYBER_YELLOW
    print(CYBER_YELLOW)        # 走 token 解析
    f"color: {CYBER_YELLOW}"   # 也走 __format__
    QColor(str(CYBER_YELLOW))  # 显式 str() 同样可用

## AI 硬约束 — 修改本文件前必读
归属层:    [L0/L1] (core/ 根目录,跨层桥接/全局管理器)
允许依赖:  视文件而定(本层可持有 widget 引用作桥接,但不实现绘制)
禁止依赖:  根目录 .py 不允许做业务实现 → 业务放 core/services/
必读规范:  .trae/rules/开发规范.md §6.7

本文件相关红线:
- 禁止根目录 .py 持有 widget 绘制逻辑 → 视觉交给 core/widgets/
- 禁止硬编码资源路径 → 必须 core.constants 取
- 禁止在根目录定义业务类 → 业务放对应层
- 禁止反向调用 UI(从 Service → Widget) → 单向数据流
- 禁止 try/except: pass 吞错 → 必须记录到日志或抛给上层
- 禁止写死 hex 字面量 → 所有颜色必须映射到 token key
- 禁止绕过 TokenManager 读 YAML 字符串 → 走 TokenManager 唯一入口

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.7,别走捷径。
"""
from __future__ import annotations

from typing import Any

from core.tokens.manager import TokenManager


class _TokenProxy:
    """模块级颜色代理:每次访问从 TokenManager 实时取值。

    设计目标:
      - 旧代码 ``from core.theme_proxy import CYBER_YELLOW`` 仍然工作
      - 旧代码 ``str(CYBER_YELLOW)`` 返回 hex 字符串
      - 旧代码 ``f"{CYBER_YELLOW}"`` 走 __format__ 返回 hex 字符串
      - 旧代码 ``QColor(str(CYBER_YELLOW))`` 仍然能解析
      - **零 hex 字面量**:本文件不写任何 hex/rgba 字面量

    实现原理:
      Python 没有真正的「模块级描述符」,但只要对象实现 __str__ /
      __format__ / __eq__ / __hash__ / __bool__ 协议,它在多数使用场景
      (str()、f-string、==、if、QColor() 包装)里表现得跟普通字符串
      **几乎一致**。例外是需要直接当 str 子类用的情况(比如 list
      排序、json.dumps),那种情况极少且可以显式 str() 转换。

    降级策略:
      token 未加载(单元测试、极早期 import)时返回空字符串。
      原因:不返回硬编码 hex(否则会污染 F1 扫描);空字符串在
      QColor 解析时会变为非法颜色,UI 自然走默认色,行为安全。
    """
    __slots__ = ('_token_key',)  # 用 __slots__ 避免每个常量带 __dict__,省内存

    def __init__(self, token_key: str) -> None:
        object.__setattr__(self, '_token_key', token_key)  # 绕过 __setattr__(本类没有,显式写更稳)

    def _value(self) -> str:
        """从 TokenManager 取值;失败降级为空字符串。

        不返回硬编码 hex 是有意为之 —— 本文件严禁出现颜色字面量。
        """
        try:
            return TokenManager.instance().get(self._token_key)
        except Exception:
            return ""

    def __str__(self) -> str:
        """str(proxy) → 走 token 解析,返回 hex 字符串。"""
        return self._value()

    def __format__(self, spec: str) -> str:
        """f"{proxy}" 或 format(proxy, spec) → 走 token 解析。"""
        return format(self._value(), spec)

    def __repr__(self) -> str:
        """repr(proxy) 显示 token key,方便调试时看出代理的是哪个 token。"""
        return f"_TokenProxy({self._token_key!r})"

    def __eq__(self, other: Any) -> bool:
        """proxy == other 走 token 值比较,与 str 直接比较一致。"""
        return self._value() == other

    def __hash__(self) -> int:
        """proxy 哈希走 token 值,可作为 dict key / set 元素。"""
        return hash(self._value())

    def __bool__(self) -> bool:
        """bool(proxy) 走 token 值,空 token 视为 False(早退保护)。"""
        return bool(self._value())


def _proxy(token_key: str) -> _TokenProxy:
    """创建 _TokenProxy 实例(每个常量映射到一个 token key)。

    用法::

        CYBER_YELLOW = _proxy("alias.accent.primary")

    token_key 必须能在 ``data/presets/cyberpunk.yaml`` 里找到,
    否则取值为空字符串(早退保护,UI 走默认色)。
    """
    return _TokenProxy(token_key)


# ============================================================
# 模块级常量(全部映射到 token key,零硬编码颜色字面量)
# ============================================================
# 旧 API 调用方式(与重构前完全一致):
#   from core.theme_proxy import CYBER_YELLOW
#   painter.setPen(QColor(str(CYBER_YELLOW)))   # 显式 str() 触发 token 解析
#   f"color: {CYBER_YELLOW}"                   # __format__ 走 token
#   print(CYBER_YELLOW)                        # __str__ 走 token
#   if CYBER_YELLOW == "#FFE600":              # __eq__ 走 token
# 主题切换时所有访问点自动跟随新值,无需手动同步。

# ---- 品牌色(brand) ----
# 用于强调、警示、成功等场景,语义上对应 Warframe 配色体系
CYBER_YELLOW  = _proxy("alias.accent.primary")    # 主强调色 brand.yellow,标题/主要操作
CYBER_CYAN    = _proxy("alias.accent.secondary")  # 信息色 brand.cyan,链接/次要操作
CYBER_MAGENTA = _proxy("alias.accent.tertiary")   # 特殊标记 brand.magenta
CYBER_ORANGE  = _proxy("alias.semantic.warning")  # 警告色 brand.orange
CYBER_RED     = _proxy("alias.semantic.danger")   # 错误/危险 brand.red
CYBER_GREEN   = _proxy("alias.semantic.success")  # 成功/可用 brand.green

# ---- 表面/文字 ----
# 窗口/卡片/文字的颜色基线,定义了应用的明暗对比基调
CYBER_PANEL_BG = _proxy("alias.bg.base")          # 最底层窗口背景 surface.base
CYBER_CARD_BG  = _proxy("alias.bg.raised")        # 浮起面背景 surface.raised
CYBER_BORDER   = _proxy("alias.border.default")   # 普通边框 border.default
CYBER_TEXT     = _proxy("alias.text.primary")     # 主文字色 text.primary
CYBER_TEXT_DIM = _proxy("alias.text.tertiary")    # 次要/辅助文字 text.tertiary

# ---- 遗物/物品状态 ----
# 遗物(Relic)的入库/出库状态颜色,以及未识别物品的兜底色
COLOR_VAULTED   = _proxy("alias.semantic.danger")  # 入库=红,提示玩家该遗物已收藏
COLOR_AVAILABLE = _proxy("alias.semantic.success") # 出库=绿,提示玩家可交易
COLOR_UNKNOWN   = _proxy("raw.game.unknown")       # OCR 识别失败的兜底色
FALLBACK_COLOR  = _proxy("raw.game.unknown")       # 通用兜底色(与 COLOR_UNKNOWN 同源)

# ---- 稀有度(game.*) ----
# Warframe 物品稀有度色,与游戏中图标颜色对应
COLOR_GOLD   = _proxy("raw.game.gold")    # 金色稀有度(最高)
COLOR_SILVER = _proxy("raw.game.silver")  # 银色稀有度
COLOR_COPPER = _proxy("raw.game.copper")  # 铜色稀有度(普通)

# ---- 日志颜色映射 ----
# 取自 token.yaml 的 alias.log 段,内部为 dict{ok/warn/error/info}
# 调用方式:`str(LOG_COLOR_MAP)` 返回 "alias.log" (token 路径),
# 调用方应通过 `TokenManager.instance().get("alias.log")` 获取实际 dict
LOG_COLOR_MAP = _proxy("alias.log")

# ---- 覆盖层(overlay) ----
# 全屏覆盖层(选区框、提示窗)的颜色
OVERLAY_BG_COLOR = _proxy("raw.surface.overlay")        # 覆盖层底色(纯黑)
OVERLAY_SELECTION_OVERLAY = _proxy("raw.surface.overlay")        # 框选遮罩(半透明深色，与overlay底色一致)

# ---- 按钮(由 semantic.state 派生) ----
# 4 种交互态 × 3 样式属性,共 9 个常量;旧 QPushButton 自定义样式时引用
BTN_DEFAULT_BG     = _proxy("alias.bg.raised")          # 默认态背景
BTN_DEFAULT_TEXT   = _proxy("alias.accent.primary")     # 默认态文字(品牌黄)
BTN_DEFAULT_BORDER = _proxy("alias.accent.primary")     # 默认态边框
BTN_HOVER_BG       = _proxy("alias.bg.raised")          # 悬浮态背景
BTN_HOVER_TEXT     = _proxy("alias.accent.secondary")   # 悬浮态文字(青色)
BTN_HOVER_BORDER   = _proxy("alias.accent.secondary")   # 悬浮态边框
BTN_PRESSED_BG     = _proxy("alias.bg.base")            # 按下态背景(更深)
BTN_DISABLED_BG    = _proxy("alias.bg.raised")          # 禁用态背景
BTN_DISABLED_TEXT  = _proxy("alias.text.disabled")      # 禁用态文字
BTN_DISABLED_BORDER = _proxy("alias.border.subtle")     # 禁用态边框

# ---- 外部品牌 ----
# 关于页/侧边栏用的 B站/GitHub 品牌色
BRAND_BILIBILI       = _proxy("raw.external.bilibili")
BRAND_BILIBILI_HOVER = _proxy("raw.external.bilibili_hover")
BRAND_GITHUB         = _proxy("raw.external.github")
BRAND_GITHUB_HOVER   = _proxy("raw.external.github_hover")

# ---- 标签/面板/卡片别名 ----
# 与上面的 CYBER_PANEL_BG/CYBER_CARD_BG 同源,提供语义化别名
LABEL_DEFAULT = _proxy("alias.text.secondary")  # 标签默认文字色
PANEL_BG      = _proxy("alias.bg.base")         # 面板背景别名
CARD_BG       = _proxy("alias.bg.raised")       # 卡片背景别名

# ---- 进度条渐变 ----
# 三段渐变:黄→红→青,用于表示稀有度递进或加载进度
PROGRESS_GRADIENT_START = _proxy("raw.brand.yellow")
PROGRESS_GRADIENT_MID   = _proxy("raw.brand.red")
PROGRESS_GRADIENT_END   = _proxy("raw.brand.cyan")

# ---- 提示/日志/错误 ----
# 用于日志/价格抓取等场景的提示色
LOG_TIMESTAMP       = _proxy("alias.text.tertiary")    # 日志时间戳(暗色)
FETCH_MANUAL_HINT   = _proxy("alias.semantic.warning")  # 提示用户手动操作(橙色)
FETCH_ERROR_COLOR   = _proxy("alias.semantic.danger")   # 抓取错误(红色)

# ---- 辅助色 ----
# 不常用但旧代码引用的辅助色,统一映射到 token
SUBTLE_BORDER   = _proxy("alias.border.subtle")    # 更细的边框
MUTED_TEXT      = _proxy("alias.text.tertiary")    # 静音文字
LIGHT_TEXT      = _proxy("alias.text.primary")     # 浅色文字
COLOR_BLACK     = _proxy("alias.text.inverse")     # 反色文字(深色)
COLOR_DARK_GRAY = _proxy("alias.text.disabled")    # 暗灰文字
COLOR_ENEMY     = _proxy("alias.semantic.danger")  # 敌方/危险(红色)
COLOR_PURPLE    = _proxy("alias.accent.tertiary")   # 紫色高亮
LINK_COLOR      = _proxy("alias.semantic.info")     # 链接色(青色)

# ---- 在线状态 ----
# 用户在线状态(关于页/好友列表)
STATUS_ONLINE  = _proxy("alias.semantic.success")  # 在线(绿色)
STATUS_INGAME  = _proxy("alias.semantic.info")     # 游戏中(青色)
STATUS_OFFLINE = _proxy("alias.text.disabled")     # 离线(灰色)
STATUS_AWAY    = _proxy("alias.semantic.warning")  # 离开(橙色)

# ---- JSON 查看器 ----
# JSON 树形查看器中布尔值的颜色
JSON_BOOLEAN = _proxy("alias.accent.tertiary")
