"""
[L-Service] 市场价格查询服务 (market_price_service.py)

通过 warframe.market API 查询实时价格数据。
整合原 data/market_items.py 的价格查询逻辑。

用法:
    from core.services.market_price_service import MarketPriceService
    svc = MarketPriceService()

    # 单个物品价格
    price = svc.query_price("forma_blueprint")

    # 批量查询
    prices = svc.query_batch(["forma_blueprint", "lex_prime_receiver"])

    # WM 物品列表 + 混合搜索
    items = fetch_wm_items()
    results = search_wm_items("aka", db_path, item_service)
"""

import json
import sqlite3
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

# ===== WM API 配置 =====
WM_API_ITEMS = "https://api.warframe.market/v2/items"
WM_API_ORDERS = "https://api.warframe.market/v2/orders/item"
REQUEST_TIMEOUT = 5
MAX_WORKERS = 4


class MarketPriceService:
    """warframe.market 价格查询服务。

    提供单个/批量物品的实时价格查询，
    自动过滤非在线卖家，按价格排序返回最低价。
    """

    def __init__(self, timeout: int = REQUEST_TIMEOUT):
        self._timeout = timeout

    # ── HTTP 工具 ──

    @staticmethod
    def _http_get(url: str, timeout: int = REQUEST_TIMEOUT) -> dict:
        """HTTP GET 请求，返回 JSON。"""
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json",
            "Platform": "pc",
            "Language": "zh",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # ── 单个物品价格 ──

    def query_price(self, url_name: str) -> Optional[dict]:
        """查询单个物品的 warframe.market 实时价格。

        获取该物品所有 sell 订单，仅统计状态为 "ingame" 的卖家，
        返回前 10 个最低单价。

        Args:
            url_name: warframe.market API slug

        Returns:
            {
                "url_name": str,
                "total_ingame": int,
                "top10": [{"platinum": int, "quantity": int, "ingame_name": str}, ...],
                "min_price": int,
                "avg_price": float,
            }
            或 None（查询失败或无数据）
        """
        url = f"{WM_API_ORDERS}/{url_name}?order_type=sell"
        try:
            data = self._http_get(url, self._timeout)
        except Exception as e:
            print(f"[market_price] API 请求失败: {url_name} - {e}")
            return None

        orders = data.get("payload", {}).get("orders", [])
        if not orders and isinstance(data.get("data"), list):
            orders = data["data"]

        sell_orders = []
        for o in orders:
            order_type = o.get("order_type") or o.get("type", "")
            user = o.get("user", {})
            if order_type == "sell" and user.get("status", "") == "ingame":
                platinum = o.get("platinum", 0)
                if platinum and platinum > 0:
                    sell_orders.append({
                        "platinum": platinum,
                        "quantity": o.get("quantity", 1),
                        "ingame_name": user.get("ingame_name", ""),
                    })

        if not sell_orders:
            return None

        sell_orders.sort(key=lambda x: x["platinum"])

        top10 = sell_orders[:10]
        total_ingame = len(sell_orders)

        return {
            "url_name": url_name,
            "total_ingame": total_ingame,
            "top10": top10,
            "min_price": top10[0]["platinum"] if top10 else 0,
            "avg_price": round(
                sum(o["platinum"] * o["quantity"] for o in top10) /
                sum(o["quantity"] for o in top10), 1
            ) if top10 else 0,
        }

    # ── 批量查询 ──

    def query_batch(
        self,
        url_names: list[str],
        max_workers: int = MAX_WORKERS,
    ) -> dict[str, dict]:
        """批量查询多个物品的价格。

        使用线程池并发请求，结果字典 key 为 url_name。

        Args:
            url_names: url_name 列表
            max_workers: 最大并发数

        Returns:
            {url_name: price_result, ...}
        """
        results = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.query_price, name): name for name in url_names}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    if result:
                        results[name] = result
                except Exception as e:
                    print(f"[market_price] query_batch 异常: {name} - {e}")
        return results

    # ── 格式化输出 ──

    @staticmethod
    def format_price_summary(price_data: dict) -> str:
        """将价格数据格式化为可读字符串。

        Args:
            price_data: query_price() 的返回值

        Returns:
            格式化字符串，如 "最低 15p | 均价 18p | 在线卖家 42"
        """
        if not price_data:
            return "无价格数据"
        min_p = price_data.get("min_price", 0)
        avg_p = price_data.get("avg_price", 0)
        ingame = price_data.get("total_ingame", 0)
        return f"最低 {min_p}p | 均价 {avg_p:.1f}p | 在线卖家 {ingame}"

    @staticmethod
    def format_top_sellers(price_data: dict, max_show: int = 3) -> list[str]:
        """提取前 N 个卖家的简要信息。

        Returns:
            ["15p x5 @Player1", "16p x3 @Player2", ...]
        """
        if not price_data or not price_data.get("top10"):
            return []
        lines = []
        for o in price_data["top10"][:max_show]:
            lines.append(f"{o['platinum']}p x{o['quantity']} @{o['ingame_name']}")
        return lines


# ============================================================
# WM 全物品列表（带缓存）
# ============================================================

_ITEMS_CACHE_LOCK = threading.Lock()
_wm_items_cache: list[tuple[str, str, list[str]]] | None = None


def fetch_wm_items(cache_ok: bool = True) -> list[tuple[str, str, list[str]]]:
    """下载 warframe.market 全物品列表（带缓存）。

    返回 [(name, slug, tags), ...]，过滤掉遗物类物品。
    """
    global _wm_items_cache
    with _ITEMS_CACHE_LOCK:
        if cache_ok and _wm_items_cache is not None:
            return _wm_items_cache
        try:
            req = urllib.request.Request(
                WM_API_ITEMS,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Accept": "application/json",
                    "Platform": "pc",
                }
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            items = data.get("data", [])
            _wm_items_cache = [
                (
                    i.get("i18n", {}).get("en", {}).get("name", ""),
                    i.get("slug", ""),
                    i.get("tags", []),
                )
                for i in items
                if "relic" not in i.get("tags", [])
            ]
            return _wm_items_cache
        except Exception as e:
            print(f"[market_price] WM 物品列表加载失败: {e}")
            return []


def build_slug_map() -> dict[str, str]:
    """构建 {英文名小写: slug} 映射表。"""
    mapping: dict[str, str] = {}
    for name, slug, _tags in fetch_wm_items():
        mapping[name.lower()] = slug
    return mapping


def clear_wm_cache():
    """清空 WM 物品列表缓存（强制下次重新下载）。"""
    global _wm_items_cache
    with _ITEMS_CACHE_LOCK:
        _wm_items_cache = None


# ============================================================
# 部件翻译（DB 提取 + 硬编码兜底，DB 优先）
# ============================================================

_component_zh_cache: dict[str, str] | None = None

# DB 中缺失的部件翻译硬编码兜底（优先级低于 DB 自动提取）
_FALLBACK_COMPONENT_ZH: dict[str, str] = {
    "Set": "套装",
    "Blueprint": "蓝图",
    "Chassis": "机体",
    "Neuroptics": "头部神经光元",
    "Systems": "系统",
    "Blade": "刀刃",
    "Handle": "握柄",
    "Link": "连接器",
    "Guard": "护手",
    "Upper Limb": "上肢",
    "Lower Limb": "下肢",
    "String": "弓弦",
    "Grip": "握柄",
    "Lower Grip": "下握柄",
    "Upper Grip": "上握柄",
    "Head": "头部",
    "Carapace": "甲壳",
    "Cerebrum": "大脑",
    "Cortex": "大脑皮层",
    "Pouch": "卵袋",
    "Elytron": "翅鞘",
    "Buckle": "扣环",
    "Band": "饰带",
    "Ribbon": "缎带",
    "Gauntlet": "护手",
    "Kavat Segment": "库娃模块",
    "Kubrow Egg": "库狛蛋",
    "Kavat Genetic Code": "库娃基因密码",
}


def _build_component_map_from_db(db_path: str | Path) -> dict[str, str]:
    """从 warframe.db 现有数据中提取英文→中文部件翻译。

    扫描所有 zh_name ≠ name 的物品，对比英文名和中文名中的差异词，
    记录出现 ≥2 次的词对（如 Blueprint→蓝图, Chassis→机体 等）。
    仅作为 DB 无中文名时的兜底方案。
    """
    global _component_zh_cache
    if _component_zh_cache is not None:
        return _component_zh_cache

    mapping: dict[str, dict[str, int]] = {}
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT name, zh_name FROM items WHERE zh_name != name AND zh_name != '' LIMIT 5000"
        )
        for en_name, zh_name in cur.fetchall():
            en_words = en_name.split()
            zh_words = zh_name.split()
            if len(en_words) == len(zh_words):
                for ew, zw in zip(en_words, zh_words):
                    if ew != zw:
                        mapping.setdefault(ew, {}).setdefault(zw, 0)
                        mapping[ew][zw] += 1
        conn.close()
    except Exception as e:
        print(f"[market_price] 部件翻译提取失败: {e}")
        _component_zh_cache = {}
        return _component_zh_cache

    result: dict[str, str] = {}
    for ew, candidates in mapping.items():
        best = max(candidates, key=lambda k: candidates[k])
        if candidates[best] >= 2:
            result[ew] = best

    _component_zh_cache = result
    if result:
        print(f"[market_price] 从 DB 提取了 {len(result)} 条部件翻译")
    return result


def get_component_map(db_path: str | Path) -> dict[str, str]:
    """获取 DB 提取 + 硬编码兜底的合并翻译表。DB 优先，缺失的用硬编码补。"""
    merged = dict(_FALLBACK_COMPONENT_ZH)
    merged.update(_build_component_map_from_db(db_path))
    return merged


def translate_components(en_name: str, db_path: str | Path) -> str:
    """翻译物品名称中的部件后缀。DB 数据优先，DB 无对应词时用硬编码兜底。

    使用最长匹配优先（处理多词 key 如 "Upper Limb" → "上肢"）。
    """
    comp_map = get_component_map(db_path)
    if not comp_map:
        return en_name
    words = en_name.split(' ')
    sorted_keys = sorted(comp_map.keys(), key=lambda k: -len(k.split(' ')))
    result = []
    i = 0
    while i < len(words):
        matched = False
        for key in sorted_keys:
            kw = key.split(' ')
            n = len(kw)
            if i + n <= len(words) and words[i:i + n] == kw:
                result.append(comp_map[key])
                i += n
                matched = True
                break
        if not matched:
            result.append(words[i])
            i += 1
    return ' '.join(result)


def translate_wm_name(
    en_name: str,
    zh_name_map: dict[str, str],
    db_path: str | Path,
) -> str:
    """翻译 WM 物品名称为中文。DB 映射优先，再按部件后缀翻译。

    对于 WM 名称如 "Akarius Prime Set"（DB 只有 "Akarius Prime"→"阿利乌双枪 Prime"）：
    先匹配 DB 中可翻译的最长前缀，剩余部分用部件翻译表处理。

    Args:
        en_name: WM 英文物品名
        zh_name_map: {en_name_lower: zh_name} 映射表
        db_path: warframe.db 路径
    """
    key = en_name.lower()
    # 1. 直接映射（DB 中有独立中文名）
    if key in zh_name_map:
        zh = zh_name_map[key]
        if zh != en_name:
            return zh

    # 2. 前缀匹配：从后往前缩短，找最长可翻译的前缀
    words = en_name.split()
    for cut in range(len(words) - 1, 0, -1):
        prefix = ' '.join(words[:cut]).lower()
        if prefix in zh_name_map:
            zh_prefix = zh_name_map[prefix]
            suffix = ' '.join(words[cut:])
            zh_suffix = translate_components(suffix, db_path)
            return f"{zh_prefix} {zh_suffix}"

    # 3. 部件后缀翻译（e.g. Gauss Prime Systems Blueprint → Gauss Prime 系统 蓝图）
    return translate_components(en_name, db_path)


# ============================================================
# 混合搜索（WM API + 本地 DB）
# ============================================================

# 不应出现在价格搜索结果中的标签
_EXCLUDED_TAGS = frozenset({'glyph', 'skin', 'helmet', 'animation', 'relic', 'mod'})


def search_wm_items(
    keyword: str,
    db_path: str | Path,
    zh_name_map: dict[str, str],
) -> list[dict]:
    """混合搜索：WM API (英文名/slug) + 本地 DB (中文/拼音)，交叉合并。

    搜索结果自动附加 zh_name 翻译字段。

    Returns:
        [{"name": str, "slug": str, "tags": list[str], "zh_name": str}, ...]
    """
    kw = keyword.lower()
    slug_map = build_slug_map()
    seen: set[str] = set()
    results: list[dict] = []

    # ── 1. WM API 英文匹配 ──
    for name, slug, tags in fetch_wm_items():
        if any(t in _EXCLUDED_TAGS for t in tags):
            continue
        if kw in name.lower() or kw in slug.lower():
            if slug not in seen:
                seen.add(slug)
                results.append({'name': name, 'slug': slug, 'tags': tags})

    # ── 2. 本地 DB 中文/拼音匹配 → 交叉查 WM slug ──
    propagation_prefixes: set[str] = set()
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            """SELECT zh_name, name FROM items
               WHERE (zh_name LIKE ? OR name LIKE ? OR zh_pinyin LIKE ?)
               LIMIT 30""",
            (f"%{kw}%", f"%{kw}%", f"%{kw}%"),
        )
        for zh_name_db, en_name_db in cur.fetchall():
            slug = slug_map.get(en_name_db.lower(), '')
            if slug and slug not in seen:
                seen.add(slug)
                results.append({'name': en_name_db, 'slug': slug, 'tags': []})
            # 战甲本体（非套装/蓝图/部件）→ 扩展匹配其 Prime 部件
            if not any(t in en_name_db.lower()
                       for t in (' set', ' blueprint', ' chassis', ' neuroptics', ' systems')):
                if 'prime' in slug.lower() and '_' not in slug.lower().replace('_prime', '').strip('_'):
                    propagation_prefixes.add(slug + '_')
        conn.close()
    except Exception as e:
        print(f"[market_price] DB 搜索失败: {e}")

    # ── 3. 扩展匹配：战甲 → 纳入其所有部件 ──
    for name, slug, tags in fetch_wm_items():
        if slug in seen:
            continue
        for prefix in propagation_prefixes:
            if slug.startswith(prefix):
                if any(t in _EXCLUDED_TAGS for t in tags):
                    continue
                seen.add(slug)
                results.append({'name': name, 'slug': slug, 'tags': tags})
                break

    # 排序：套装优先 → 蓝图优先
    results.sort(key=lambda x: (
        not ('set' in x.get('tags', [])),
        not ('blueprint' in x.get('tags', [])),
        x['name'],
    ))

    # 附加中文名
    for r in results:
        r['zh_name'] = translate_wm_name(r['name'], zh_name_map, db_path)

    return results[:20]


# ============================================================
# DB 中文名映射加载
# ============================================================

def load_zh_name_map(db_path: str | Path) -> dict[str, str]:
    """从 items 表加载 {en_name_lower: zh_name} 映射（仅翻译不同的条目）。

    Args:
        db_path: warframe.db 路径
    """
    mapping: dict[str, str] = {}
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT name, zh_name FROM items WHERE zh_name != name AND zh_name != ''")
        for en_name, zh_name in cur.fetchall():
            mapping[en_name.lower()] = zh_name
        conn.close()
    except Exception as e:
        print(f"[market_price] 中文名映射加载失败: {e}")
    return mapping


# ============================================================
# 便捷单例
# ============================================================
_market_price_instance = None


def get_market_price_service() -> MarketPriceService:
    """获取 MarketPriceService 单例。"""
    global _market_price_instance
    if _market_price_instance is None:
        _market_price_instance = MarketPriceService()
    return _market_price_instance
