"""
[L-Service] ItemService — 物品查询服务。

依赖: Python 标准库 + sqlite3（warframe.db）+ pypinyin（可选）
禁止: PySide6 / QtWidgets / QtGui
返回: dict / list / bool / str（原始数据类型）

从 warframe.db 统一数据库提供全物品搜索、联想、翻译、分类查询。
整合原 data/item_index.py 和 data/market_items.py 的核心业务逻辑。

数据源:
  - items 表 → 全物品基础信息（name, zh_name, type, category, tradable 等）
  - market_items 表 → 可交易物品 + slug 映射 + 遗物来源
  - game_translations 表 → 多语言翻译

用法:
    from core.services.item_service import ItemService
    svc = ItemService()

    # 搜索
    results = svc.search("Forma", limit=50)

    # 联想（自动检测中/英/拼音）
    suggestions = svc.suggest("for", limit=20)

    # 翻译
    info = svc.translate("Forma")

    # 分类列表
    cats = svc.get_categories()
"""

import logging
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ===== 路径 =====
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_PATH = DATA_DIR / "warframe.db"

# ===== 拼音支持 =====
try:
    from pypinyin import pinyin as _pinyin_fn, Style
    _HAS_PYPINYIN = True
except ImportError:
    _HAS_PYPINYIN = False


# ============================================================
# 遗物精炼过滤常量
# ============================================================
_REFINEMENT_TAGS = {"Intact", "Exceptional", "Flawless", "Radiant"}
_RELIC_ERAS = {"Lith", "Meso", "Neo", "Axi", "Requiem", "Vanguard"}


class ItemService:
    """物品查询服务。

    单例模式，提供线程安全的数据库访问接口。
    每次操作独立获取连接，避免跨请求状态污染。
    """

    # ── 翻译缓存（类级别，全局共享）──
    _zh_cache: dict[str, str] | None = None   # normalized_key → zh_text

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DB_PATH
        # 首次实例化时预加载翻译缓存
        if self._zh_cache is None:
            conn = self._get_conn()
            if conn:
                try:
                    self._ensure_zh_cache(conn)
                finally:
                    self._close(conn)

    @classmethod
    def _ensure_zh_cache(cls, conn: sqlite3.Connection):
        """首次调用时加载所有中英翻译到内存缓存。

        三路来源：
        1. game_translations.key（~35K 条路径 key）→ 短名作索引
        2. game_translations.en（英文原名）→ 补充 items 表未收录的物品
        3. items 表（~3K 条）→ 精确 name → zh_name（权威最高）
        """
        if cls._zh_cache is not None:
            return
        cls._zh_cache = {}

        try:
            # ── 1. game_translations：短 key 索引 ──
            for row in conn.execute("SELECT key, zh FROM game_translations WHERE zh != ''"):
                short = row[0].rsplit('/', 1)[-1] if '/' in row[0] else row[0]
                k = short.replace(' ', '').lower()
                zh = row[1]
                if k not in cls._zh_cache or k.endswith('name'):
                    cls._zh_cache[k] = zh

            # ── 2. game_translations.en：补充 items 表未收录的物品名 ──
            for row in conn.execute(
                "SELECT en, zh FROM game_translations "
                "WHERE en != '' AND zh != '' AND en != zh "
                "AND length(en) < 80 AND length(zh) < 200"
            ):
                k = row[0].replace(' ', '').lower()
                zh = row[1]
                if len(k) > 1 and not k.isdigit() and k not in cls._zh_cache:
                    cls._zh_cache[k] = zh

            # ── 3. items 表：精确 name → zh_name（权威最高，覆盖前两路）──
            for row in conn.execute(
                "SELECT name, zh_name FROM items WHERE zh_name != '' AND zh_name != name"
            ):
                k = row[0].replace(' ', '').lower()
                zh = row[1]
                cls._zh_cache[k] = zh
        except Exception:
            pass

    def _translate_item(self, name: str) -> str:
        """在内存缓存中查找单个物品名的中文翻译。

        优先 O(1) 精确匹配（items 表直接命中），其次全扫描（<3ms/item）。
        对 Blueprint / String / Grip 等组件后缀自动剥离重试。
        """
        if not self._zh_cache:
            return ''
        cache = self._zh_cache
        norm = name.replace(' ', '').lower()

        # ── 0. O(1) 精确匹配（items 表键值）──
        if norm in cache:
            zh = cache[norm]
            if len(zh) < 100 and not zh.endswith('。'):
                return zh

        # ── 1. 组件后缀回退（Blueprint/String/Grip/Barrel/...）──
        _COMPONENT_SUFFIXES = (
            ' blueprint', ' string', ' grip', ' barrel', ' receiver',
            ' stock', ' blade', ' handle', ' link', ' pouch',
            ' gauntlet', ' casing',
            ' chassis', ' neuroptics', ' systems',
            ' lower limb', ' upper limb', ' head',
        )
        for suffix in _COMPONENT_SUFFIXES:
            if name.lower().endswith(suffix):
                stripped_norm = name[:-len(suffix)].replace(' ', '').lower()
                if stripped_norm in cache:
                    zh = cache[stripped_norm]
                    if len(zh) < 100 and not zh.endswith('。'):
                        return zh

        # ── 2. 全扫描（game_translations 带前缀的 key）──
        norms_to_scan = [norm]
        for suffix in _COMPONENT_SUFFIXES:
            if name.lower().endswith(suffix):
                norms_to_scan.append(name[:-len(suffix)].replace(' ', '').lower())

        for n in norms_to_scan:
            best = None
            for k, zh in cache.items():
                if n in k:
                    if len(zh) < 100 and not zh.endswith('。'):
                        if k.endswith('name'):
                            return zh
                        if best is None:
                            best = zh
            if best:
                return best

        return ''

    # ── 连接管理 ──

    def _get_conn(self) -> Optional[sqlite3.Connection]:
        """获取数据库连接，失败返回 None。"""
        if not self._db_path.exists():
            return None
        try:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception:
            return None

    @staticmethod
    def _close(conn: sqlite3.Connection):
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    # ── 数据转换 ──

    @staticmethod
    def _row_to_dict(row) -> dict:
        """SQLite Row → dict。"""
        if row is None:
            return {}
        return dict(row)

    def _format_item(self, row: dict) -> dict:
        """统一物品格式输出。"""
        return {
            'id': row.get('rowid', 0),
            'unique_name': row.get('unique_name', ''),
            'en_name': row.get('name', ''),
            'zh_name': row.get('zh_name', ''),
            'category': row.get('category', ''),
            'item_type': row.get('type', ''),
            'is_tradable': bool(row.get('tradable', 0)),
            'is_prime': bool(row.get('is_prime', 0)),
            'rarity': row.get('rarity', ''),
            'mr_requirement': row.get('mr_requirement', 0),
            'image_name': row.get('image_name', ''),
            'description_zh': row.get('description_zh', ''),
            'description_en': row.get('description', ''),
        }

    def _format_market_item(self, row: dict) -> dict:
        """市场物品格式输出。"""
        import json
        source_relics = row.get('source_relics', '[]')
        if isinstance(source_relics, str):
            try:
                source_relics = json.loads(source_relics)
            except (json.JSONDecodeError, TypeError):
                source_relics = []
        return {
            'id': row.get('id', 0),
            'en_name': row.get('en_name', ''),
            'zh_name': row.get('zh_name', ''),
            'slug': row.get('slug', ''),
            'item_type': row.get('item_type', ''),
            'is_tradable': bool(row.get('is_tradable', 0)),
            'is_prime': bool(row.get('is_prime', 0)),
            'source_relics': source_relics,
            'source_rarity': row.get('source_rarity', ''),
        }

    # ============================================================
    # 搜索 API
    # ============================================================

    def search(
        self,
        query: str = "",
        search_field: str = "all",
        category: str = None,
        item_type: str = None,
        is_prime: bool = None,
        is_tradable: bool = None,
        limit: int = 9999,
    ) -> list[dict]:
        """全物品搜索。

        Args:
            query: 关键词（空字符串返回全部）
            search_field: 搜索字段 — "all" | "zh" | "en" | "unique"
            category: 物品分类筛选（如 "Primary", "Relics"）
            item_type: 类型筛选
            is_prime: 是否 Prime 物品
            is_tradable: 是否可交易
            limit: 返回数量上限

        Returns:
            [item_dict, ...]
        """
        conn = self._get_conn()
        if conn is None:
            return []

        try:
            sql = "SELECT * FROM items WHERE 1=1"
            params = []

            if query:
                q = query.strip()
                if search_field == "zh":
                    sql += " AND zh_name LIKE ?"
                    params.append(f"%{q}%")
                elif search_field == "en":
                    sql += " AND name LIKE ?"
                    params.append(f"%{q}%")
                elif search_field == "unique":
                    sql += " AND unique_name LIKE ?"
                    params.append(f"%{q}%")
                else:  # all
                    sql += " AND (zh_name LIKE ? OR name LIKE ? OR unique_name LIKE ?)"
                    params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

            if category:
                sql += " AND category = ?"
                params.append(category)

            if item_type:
                sql += " AND type = ?"
                params.append(item_type)

            if is_prime is not None:
                sql += " AND is_prime = ?"
                params.append(int(is_prime))

            if is_tradable is not None:
                sql += " AND tradable = ?"
                params.append(int(is_tradable))

            sql += " ORDER BY category, zh_name LIMIT ?"
            params.append(limit)

            cur = conn.execute(sql, params)
            results = [self._format_item(self._row_to_dict(r)) for r in cur.fetchall()]
            results = self._filter_relic_refinements(results)
            return results
        finally:
            self._close(conn)

    # ============================================================
    # 联想 API（三级匹配：精确 > 前缀 > 包含）
    # ============================================================

    def suggest(self, query: str, limit: int = 9999) -> list[dict]:
        """实时输入联想。

        自动检测输入语言：
          - 中文 → 搜索中文名
          - 英文 → 搜索英文名 + 拼音
          - 精确匹配 > 前缀匹配 > 包含匹配 > 拼音匹配

        Args:
            query: 用户输入
            limit: 返回数量上限

        Returns:
            [{zh_name, en_name, category, match_quality, match_field}, ...]
        """
        if not query or not query.strip():
            return []

        q = query.strip()
        conn = self._get_conn()
        if conn is None:
            return []

        try:
            results = []
            seen = set()

            if self._is_chinese(q):
                self._search_by_field(conn, q, "zh_name", "zh", results, seen, limit)
            else:
                self._search_by_field(conn, q, "name", "en", results, seen, limit)
                self._search_by_pinyin(conn, q, results, seen, limit)

            # 按匹配质量排序
            quality_order = {"exact": 0, "prefix": 1, "contains": 2}
            results.sort(key=lambda x: quality_order.get(x.get("match_quality", ""), 99))
            results = self._filter_relic_refinements(results)
            return results[:limit]
        finally:
            self._close(conn)

    def _search_by_field(
        self,
        conn: sqlite3.Connection,
        q: str,
        field: str,
        match_field_label: str,
        results: list,
        seen: set,
        limit: int,
    ):
        """在指定字段上执行三级匹配搜索。"""
        is_cn = (field == "zh_name")

        # 第1级：精确匹配
        remain = limit - len(results)
        if remain <= 0:
            return

        if is_cn:
            rows = conn.execute(
                f"SELECT zh_name, name AS en_name, category, unique_name FROM items "
                f"WHERE {field} = ? LIMIT ?", (q, remain)
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT zh_name, name AS en_name, category, unique_name FROM items "
                f"WHERE LOWER({field}) = ? LIMIT ?", (q.lower(), remain)
            ).fetchall()
        for r in rows:
            key = (r["en_name"] + r["zh_name"]).lower()
            if key not in seen:
                seen.add(key)
                results.append({
                    "zh_name": r["zh_name"], "en_name": r["en_name"],
                    "category": r["category"], "unique_name": r["unique_name"],
                    "match_quality": "exact",
                    "match_field": match_field_label,
                })

        # 第2级：前缀匹配
        remain = limit - len(results)
        if remain <= 0:
            return

        if is_cn:
            p_pat, p_excl = f"{q}%", q
            rows = conn.execute(
                f"SELECT zh_name, name AS en_name, category, unique_name FROM items "
                f"WHERE {field} LIKE ? AND {field} != ? "
                f"ORDER BY {field} LIMIT ?", (p_pat, p_excl, remain)
            ).fetchall()
        else:
            p_pat, p_excl = f"{q.lower()}%", q.lower()
            rows = conn.execute(
                f"SELECT zh_name, name AS en_name, category, unique_name FROM items "
                f"WHERE LOWER({field}) LIKE ? AND LOWER({field}) != ? "
                f"ORDER BY {field} LIMIT ?", (p_pat, p_excl, remain)
            ).fetchall()
        for r in rows:
            key = (r["en_name"] + r["zh_name"]).lower()
            if key not in seen:
                seen.add(key)
                results.append({
                    "zh_name": r["zh_name"], "en_name": r["en_name"],
                    "category": r["category"], "unique_name": r["unique_name"],
                    "match_quality": "prefix",
                    "match_field": match_field_label,
                })

        # 第3级：包含匹配
        remain = limit - len(results)
        if remain <= 0:
            return

        if is_cn:
            p_cont, p_excl = f"%{q}%", f"{q}%"
            rows = conn.execute(
                f"SELECT zh_name, name AS en_name, category, unique_name FROM items "
                f"WHERE {field} LIKE ? AND {field} NOT LIKE ? "
                f"ORDER BY {field} LIMIT ?", (p_cont, p_excl, remain)
            ).fetchall()
        else:
            p_cont, p_excl = f"%{q.lower()}%", f"{q.lower()}%"
            rows = conn.execute(
                f"SELECT zh_name, name AS en_name, category, unique_name FROM items "
                f"WHERE LOWER({field}) LIKE ? AND LOWER({field}) NOT LIKE ? "
                f"ORDER BY {field} LIMIT ?", (p_cont, p_excl, remain)
            ).fetchall()
        for r in rows:
            key = (r["en_name"] + r["zh_name"]).lower()
            if key not in seen:
                seen.add(key)
                results.append({
                    "zh_name": r["zh_name"], "en_name": r["en_name"],
                    "category": r["category"], "unique_name": r["unique_name"],
                    "match_quality": "contains",
                    "match_field": match_field_label,
                })

    def _search_by_pinyin(self, conn, q: str, results: list, seen: set, limit: int):
        """拼音搜索（从 items 表的 zh_pinyin 字段）。

        优先返回 zh_pinyin 前缀匹配的结果，再返回包含匹配的结果。
        """
        remain = limit - len(results)
        if remain <= 0:
            return
        try:
            q_lower = q.lower()

            # 第1步：前缀匹配（zh_pinyin 以查询词开头）
            if remain > 0:
                rows = conn.execute(
                    "SELECT zh_name, name AS en_name, category, unique_name FROM items "
                    "WHERE zh_pinyin LIKE ? ORDER BY zh_pinyin LIMIT ?",
                    (f"{q_lower}%", remain)
                ).fetchall()
                for r in rows:
                    key = (r["en_name"] + r["zh_name"]).lower()
                    if key not in seen:
                        seen.add(key)
                        results.append({
                            "zh_name": r["zh_name"], "en_name": r["en_name"],
                            "category": r["category"], "unique_name": r["unique_name"],
                            "match_quality": "contains",
                            "match_field": "py",
                        })

            # 第2步：包含匹配（zh_pinyin 包含查询词但非前缀）
            remain = limit - len(results)
            if remain > 0:
                rows = conn.execute(
                    "SELECT zh_name, name AS en_name, category, unique_name FROM items "
                    "WHERE zh_pinyin LIKE ? AND zh_pinyin NOT LIKE ? "
                    "ORDER BY zh_pinyin LIMIT ?",
                    (f"%{q_lower}%", f"{q_lower}%", remain)
                ).fetchall()
                for r in rows:
                    key = (r["en_name"] + r["zh_name"]).lower()
                    if key not in seen:
                        seen.add(key)
                        results.append({
                            "zh_name": r["zh_name"], "en_name": r["en_name"],
                            "category": r["category"], "unique_name": r["unique_name"],
                            "match_quality": "contains",
                            "match_field": "py",
                        })
        except Exception:
            pass  # 表可能没有 zh_pinyin 列

    # ============================================================
    # 翻译 API
    # ============================================================

    def translate(self, name: str) -> Optional[dict]:
        """精确翻译（中→英 或 英→中）。

        Args:
            name: 物品名称（中文或英文）

        Returns:
            item_dict 或 None
        """
        conn = self._get_conn()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT * FROM items WHERE zh_name = ? OR name = ? LIMIT 1",
                (name, name)
            ).fetchone()
            if row:
                return self._format_item(self._row_to_dict(row))
            return None
        finally:
            self._close(conn)

    # ============================================================
    # 分类 & 统计 API
    # ============================================================

    def get_categories(self) -> list[dict]:
        """获取所有物品分类及数量。

        Returns:
            [{"name": "Primary", "count": 123}, ...]
        """
        conn = self._get_conn()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                "SELECT category, COUNT(*) as cnt FROM items "
                "GROUP BY category ORDER BY cnt DESC"
            ).fetchall()
            return [{"name": r[0], "count": r[1]} for r in rows]
        finally:
            self._close(conn)

    def get_types_for_category(self, category: str) -> list[str]:
        """获取某分类下的所有 type 值。"""
        conn = self._get_conn()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                "SELECT DISTINCT type FROM items WHERE category = ? ORDER BY type",
                (category,)
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            self._close(conn)

    def get_stats(self) -> dict:
        """获取数据库统计信息。"""
        if not self._db_path.exists():
            return {
                "exists": False, "total": 0, "has_cn": 0,
                "categories": {}, "db_size": 0, "db_mtime": "",
            }
        try:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            cur = conn.cursor()

            total = cur.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            has_cn = cur.execute(
                "SELECT COUNT(*) FROM items WHERE zh_name != '' AND zh_name != name"
            ).fetchone()[0]

            cat_rows = cur.execute(
                "SELECT category, COUNT(*) FROM items GROUP BY category ORDER BY COUNT(*) DESC"
            ).fetchall()
            categories = dict(cat_rows)

            updated_at = ""
            source = ""
            try:
                meta_rows = cur.execute("SELECT key, value FROM db_meta").fetchall()
                for key, value in meta_rows:
                    if key == "build_time":
                        updated_at = value
                    elif key == "source":
                        source = value
            except Exception:
                pass

            weapon_cats = {"Primary", "Secondary", "Melee", "Arch-Gun", "Arch-Melee"}
            weapon_total = sum(categories.get(c, 0) for c in weapon_cats)
            weapon_detail = {c: categories.get(c, 0) for c in weapon_cats if categories.get(c, 0)}

            conn.close()
            stat = os.stat(self._db_path)
            return {
                "exists": True,
                "total": total,
                "has_cn": has_cn,
                "categories": categories,
                "weapon_total": weapon_total,
                "weapon_detail": weapon_detail,
                "source": source,
                "updated_at": updated_at,
                "db_size": stat.st_size,
                "db_mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception as e:
            return {"exists": False, "error": str(e)}

    def check_db_status(self) -> dict:
        """检查数据库完整性。"""
        if not self._db_path.exists():
            return {"status": "missing", "action": "will_create_on_first_update"}
        try:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            conn.close()
            if total == 0:
                return {"status": "empty", "action": "rebuild_recommended"}
            return {"status": "ok", "total": total}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ============================================================
    # 市场物品搜索（从 market_items 表）
    # ============================================================

    def search_market(
        self,
        query: str,
        limit: int = 20,
        include_source_relics: bool = True,
    ) -> list[dict]:
        """搜索可交易市场物品。

        支持中英文模糊搜索，包含遗物来源信息。

        Args:
            query: 搜索关键词
            limit: 返回数量上限
            include_source_relics: 是否解析遗物来源 JSON

        Returns:
            [market_item_dict, ...]
        """
        conn = self._get_conn()
        if conn is None:
            return []

        try:
            q = query.strip()
            has_chinese = bool(re.search(r"[\u4e00-\u9fff]", q))

            if has_chinese:
                conditions = ["zh_name LIKE ?"]
                params = [f"%{ch}%" for ch in re.findall(r"[\u4e00-\u9fff]", q)]
                if len(params) > 1:
                    conditions = [f"zh_name LIKE ?" for _ in params]
                else:
                    params = [f"%{q}%"]
            else:
                words = q.lower().split()
                conditions = []
                params = []
                for w in words:
                    if len(w) >= 2:
                        conditions.append("(en_name LIKE ? OR slug LIKE ?)")
                        params.extend([f"%{w}%", f"%{w}%"])
                if not conditions:
                    conditions.append("(en_name LIKE ? OR slug LIKE ?)")
                    params.extend([f"%{q}%", f"%{q}%"])

            sql = (
                f"SELECT * FROM market_items "
                f"WHERE {' AND '.join(conditions)} LIMIT {limit}"
            )
            cur = conn.execute(sql, params)
            results = [
                self._format_market_item(self._row_to_dict(r)) for r in cur.fetchall()
            ]
            return results
        finally:
            self._close(conn)

    def get_market_item_by_slug(self, slug: str) -> Optional[dict]:
        """通过 slug 精确查找市场物品。"""
        conn = self._get_conn()
        if conn is None:
            return None
        try:
            row = conn.execute(
                "SELECT * FROM market_items WHERE slug = ? LIMIT 1", (slug,)
            ).fetchone()
            if row:
                return self._format_market_item(self._row_to_dict(row))
            return None
        finally:
            self._close(conn)

    # ============================================================
    # 遗物精炼过滤
    # ============================================================

    # ── 掉落来源 / 遗物内容 ──

    def get_drop_sources(self, item_name: str, unique_name: str = "", max_results: int = 40) -> list[dict]:
        """查询物品的掉落来源（所有类型，含中文化）。

        优先通过 unique_name 精确匹配，其次用 item_name LIKE 模糊匹配。

        Args:
            item_name: 物品英文名
            unique_name: 物品唯一标识（如 /Lotus/Powersuits/...），可选
            max_results: 最大返回条数

        Returns:
            [{location, rarity, chance, rotation?, source_type}, ...]
            按 chance 降序排列
        """
        conn = self._get_conn()
        if not conn:
            return []

        try:
            import re
            sources = []
            name_key = item_name.strip().lower()

            # ── 如果没传 unique_name，从 items 表反查 ──
            matched_unique = unique_name.strip() if unique_name else ""
            if not matched_unique:
                row = conn.execute(
                    "SELECT unique_name FROM items WHERE LOWER(name)=? OR LOWER(zh_name)=? LIMIT 1",
                    (name_key, name_key)
                ).fetchone()
                if row and row["unique_name"]:
                    matched_unique = row["unique_name"]

            # ── 生成 LIKE 匹配键（支持 "xxx" 匹配 "xxx (Framename)"）──
            like_keys = {name_key}
            stripped = re.sub(r'\s*\([^)]*\)\s*$', '', name_key).strip()
            if stripped and stripped != name_key:
                like_keys.add(stripped)
            if name_key.endswith(' blueprint'):
                base = name_key[:-len(' blueprint')].strip()
                if base:
                    like_keys.add(base)

            def _match_name(col: str) -> str:
                """生成 LIKE 条件（item_name 列），匹配所有 like_keys。"""
                return ' OR '.join(f'LOWER({col}) LIKE ?' for _ in like_keys)

            def _match_unique(col: str) -> str:
                """精确匹配 unique_name 列。"""
                return f'{col}=?'

            def _name_params():
                return tuple(f'%{k}%' for k in like_keys)

            def _unique_params():
                return (matched_unique,)

            def _match_drop_type(col: str) -> str:
                """匹配 drop_type：精确相等 或 后跟括号后缀（如 'Razorwing Blitz (Titania)'）。"""
                parts = []
                for k in like_keys:
                    parts.append(f"LOWER({col}) = ?")
                    parts.append(f"LOWER({col}) LIKE ?")
                return ' OR '.join(parts)

            def _drop_type_params():
                params = []
                for k in like_keys:
                    params.append(k)
                    params.append(f"{k} (%")
                return tuple(params)

            # 1) 物品掉落（item_drops，按 unique_name + drop_type 双重匹配）
            if matched_unique:
                try:
                    cond = f"{_match_unique('unique_name')} AND ({_match_drop_type('drop_type')})"
                    params = _unique_params() + _drop_type_params()
                    for row in conn.execute(f"""
                        SELECT drop_type, location, rarity, chance
                        FROM item_drops WHERE {cond}
                    """, params).fetchall():
                        loc = f"{row['drop_type']} | {row['location']}" if row['location'] else row['drop_type'] or '?'
                        sources.append({
                            'location': loc,
                            'rarity': row['rarity'] or '',
                            'chance': row['chance'] or 100,
                            'source_type': 'itemDrops',
                        })
                except Exception:
                    pass

            # 2) 遗物奖励
            try:
                if matched_unique:
                    cond = _match_unique('rr.item_unique')
                    params = _unique_params()
                else:
                    cond = _match_name('rr.item_name')
                    params = _name_params()
                for row in conn.execute(f"""
                    SELECT r.tier, r.relic_name, rr.item_name,
                           rr.rarity, rr.chance
                    FROM relic_rewards rr
                    JOIN relics r ON rr.relic_id = r.id
                    WHERE {cond}
                """, params).fetchall():
                    tier = row['tier'] or ''
                    rname = row['relic_name'] or ''
                    sources.append({
                        'location': f"{tier} {rname}",
                        'rarity': row['rarity'] or '',
                        'chance': row['chance'] or 0,
                        'source_type': 'relics',
                    })
            except Exception:
                pass

            # 3) 任务奖励
            try:
                if matched_unique:
                    cond = _match_unique('mr.item_unique')
                    params = _unique_params()
                else:
                    cond = _match_name('mr.item_name')
                    params = _name_params()
                for row in conn.execute(f"""
                    SELECT p.name AS planet, mn.node_name,
                           mr.item_name, mr.rarity, mr.chance, mr.rotation
                    FROM mission_rewards mr
                    JOIN mission_nodes mn ON mr.node_id = mn.id
                    JOIN planets p ON mn.planet_id = p.id
                    WHERE {cond}
                """, params).fetchall():
                    sources.append({
                        'location': f"{row['planet']} - {row['node_name']}",
                        'rarity': row['rarity'] or '',
                        'chance': row['chance'] or 0,
                        'rotation': row['rotation'] or '',
                        'source_type': 'missionRewards',
                    })
            except Exception:
                pass

            # 4) 赏金奖励
            try:
                if matched_unique:
                    cond = _match_unique('item_unique')
                    params = _unique_params()
                else:
                    cond = _match_name('item_name')
                    params = _name_params()
                for row in conn.execute(f"""
                    SELECT source, bounty_level, item_name,
                           rarity, chance, rotation
                    FROM bounty_rewards
                    WHERE {cond}
                """, params).fetchall():
                    level = row['bounty_level'] or '?'
                    sources.append({
                        'location': f"{row['source']} Lv{level}",
                        'rarity': row['rarity'] or '',
                        'chance': row['chance'] or 0,
                        'rotation': row['rotation'] or '',
                        'source_type': row['source'] or 'bountyRewards',
                    })
            except Exception:
                pass

            # 5) 突击奖励
            try:
                if matched_unique:
                    cond = _match_unique('item_unique')
                    params = _unique_params()
                else:
                    cond = _match_name('item_name')
                    params = _name_params()
                for row in conn.execute(f"""
                    SELECT item_name, rarity, chance FROM sortie_rewards
                    WHERE {cond}
                """, params).fetchall():
                    sources.append({
                        'location': '突击奖励',
                        'rarity': row['rarity'] or '',
                        'chance': row['chance'] or 0,
                        'source_type': 'sortieRewards',
                    })
            except Exception:
                pass

            # 6) 集团奖励
            try:
                if matched_unique:
                    cond = _match_unique('item_unique')
                    params = _unique_params()
                else:
                    cond = _match_name('item_name')
                    params = _name_params()
                for row in conn.execute(f"""
                    SELECT syndicate_name, item_name, rarity, chance
                    FROM syndicate_rewards WHERE {cond}
                """, params).fetchall():
                    sources.append({
                        'location': f"购买: {row['syndicate_name']}",
                        'rarity': row['rarity'] or '',
                        'chance': row['chance'] or 100,
                        'source_type': 'syndicates',
                    })
            except Exception:
                pass

            # 7) 蓝图掉落（mod_drops / enemy_mod_tables 已移除：item_drops 已包含综合概率）
            try:
                if matched_unique:
                    cond = _match_unique('blueprint_unique')
                    params = _unique_params()
                else:
                    cond = _match_name('blueprint_name')
                    params = _name_params()
                for row in conn.execute(f"""
                    SELECT blueprint_name, enemy_name, rarity, chance
                    FROM blueprint_drops WHERE {cond}
                """, params).fetchall():
                    sources.append({
                        'location': f"敌人: {row['enemy_name']}",
                        'rarity': row['rarity'] or '',
                        'chance': row['chance'] or 0,
                        'source_type': 'blueprintLocations',
                    })
            except Exception:
                pass

            # 10) 敌人蓝图表
            try:
                if matched_unique:
                    cond = _match_unique('blueprint_unique')
                    params = _unique_params()
                else:
                    cond = _match_name('blueprint_name')
                    params = _name_params()
                for row in conn.execute(f"""
                    SELECT blueprint_name, enemy_name, rarity, chance
                    FROM enemy_bp_tables WHERE {cond}
                """, params).fetchall():
                    sources.append({
                        'location': f"敌人掉落表: {row['enemy_name']}",
                        'rarity': row['rarity'] or '',
                        'chance': row['chance'] or 0,
                        'source_type': 'blueprintLocations',
                    })
            except Exception:
                pass

            # 11) 临场/钥匙奖励
            for tname, src_type in [('transient_rewards', 'transientRewards'), ('key_rewards', 'keyRewards')]:
                try:
                    if matched_unique:
                        cond = _match_unique('item_unique')
                        params = _unique_params()
                    else:
                        cond = _match_name('item_name')
                        params = _name_params()
                    for row in conn.execute(f"""
                        SELECT item_name, rarity, chance FROM {tname} WHERE {cond}
                    """, params).fetchall():
                        label = '临场奖励' if src_type == 'transientRewards' else '钥匙奖励'
                        sources.append({
                            'location': label,
                            'rarity': row['rarity'] or '',
                            'chance': row['chance'] or 0,
                            'source_type': src_type,
                        })
                except Exception:
                    pass

            # 去重（同一来源+稀有度只保留最高概率） + 排序
            deduped = {}
            for s in sources:
                loc_key = (s.get('location', ''), s.get('rotation', ''), s.get('rarity', ''))
                if loc_key not in deduped or s.get('chance', 0) > deduped[loc_key].get('chance', 0):
                    deduped[loc_key] = s

            results = sorted(deduped.values(), key=lambda x: x.get('chance', 0), reverse=True)
            return results[:max_results]

        finally:
            self._close(conn)

    def get_relic_contents(self, relic_name: str) -> dict:
        """查询遗物的内含物品列表及元信息。

        Args:
            relic_name: 遗物名称，如 "Axi A1" 或 "Axi A1 Intact"

        Returns:
            {
                'vaulted': bool,
                'tier': str,
                'relic_name': str,
                'state': str,
                'contents': [{item_name, rarity, chance, wm_url_name?, item_unique?}, ...]
            }
            contents 按 rarity 排序：Common < Uncommon < Rare < Legendary
        """
        conn = self._get_conn()
        if not conn:
            return {'vaulted': False, 'tier': '', 'relic_name': '', 'state': '', 'contents': []}

        try:
            key = relic_name.strip()

            # 查询遗物基本信息（含 vaulted）
            relic_row = None
            # 精确匹配
            for row in conn.execute("""
                SELECT id, tier, relic_name, state, vaulted FROM relics
                WHERE (tier || ' ' || relic_name = ?
                   OR tier || ' ' || relic_name || ' ' || state = ?)
                LIMIT 1
            """, (key, key)).fetchall():
                relic_row = dict(row)
                break

            if not relic_row and len(key.split()) >= 2:
                parts = key.split()
                base = ' '.join(parts[:2])
                for row in conn.execute("""
                    SELECT id, tier, relic_name, state, vaulted FROM relics
                    WHERE state='Intact' AND (tier || ' ' || relic_name = ?)
                    LIMIT 1
                """, (base,)).fetchall():
                    relic_row = dict(row)
                    break

            if not relic_row:
                return {'vaulted': False, 'tier': '', 'relic_name': '', 'state': '', 'contents': []}

            relic_id = relic_row['id']

            rows = conn.execute("""
                SELECT item_name, rarity, chance, wm_url_name, item_unique
                FROM relic_rewards WHERE relic_id = ?
                ORDER BY
                    CASE rarity
                        WHEN 'Rare' THEN 0
                        WHEN 'Uncommon' THEN 1
                        WHEN 'Common' THEN 2
                        WHEN 'Legendary' THEN 3
                        ELSE 99
                    END,
                    chance
            """, (relic_id,)).fetchall()

            # 内存翻译（缓存命中，微秒级）
            self._ensure_zh_cache(conn)
            contents = []
            for r in rows:
                d = dict(r)
                zh = self._translate_item(d['item_name'])
                d['zh_name'] = zh if zh else ''
                contents.append(d)

            return {
                'vaulted': bool(relic_row.get('vaulted', 0)),
                'tier': relic_row.get('tier', ''),
                'relic_name': relic_row.get('relic_name', ''),
                'state': relic_row.get('state', ''),
                'contents': contents,
            }

        finally:
            self._close(conn)

    def get_relic_drop_locations(self, relic_name: str) -> list[dict]:
        """查询遗物自身的掉落途径（从哪些任务节点掉落）。

        Args:
            relic_name: 遗物名称，如 "Axi A1"

        Returns:
            (locations: [{planet, node_name, game_mode, rotation, chance}, ...], total: int)
            locations 最多 40 条
        """
        conn = self._get_conn()
        if not conn:
            return [], 0

        try:
            parts = relic_name.strip().split()
            if len(parts) < 2:
                return [], 0
            base = f"{parts[0]} {parts[1]}"  # e.g. "Axi S2"
            # 加空格防 LIKE 'Axi S2%' 误匹配 Axi S20 等
            pattern = f"{base} %"

            # 检查是否已入库
            try:
                row = conn.execute(
                    "SELECT vaulted FROM relics WHERE tier=? AND relic_name=? AND state='Intact' LIMIT 1",
                    (parts[0], parts[1])
                ).fetchone()
                if row and row["vaulted"]:
                    return [], 0  # 已入库遗物不显示掉落途径
            except Exception:
                pass

            results = []
            try:
                for row in conn.execute("""
                    SELECT p.name AS planet, mn.node_name, mn.game_mode,
                           mr.rotation, mr.chance
                    FROM mission_rewards mr
                    JOIN mission_nodes mn ON mr.node_id = mn.id
                    JOIN planets p ON mn.planet_id = p.id
                    WHERE mr.item_name LIKE ?
                """, (f"{pattern}%",)).fetchall():
                    results.append({
                        'planet': row['planet'] or '',
                        'node_name': row['node_name'] or '',
                        'game_mode': row['game_mode'] or '',
                        'rotation': row['rotation'] or '',
                        'chance': row['chance'] or 0,
                    })
            except Exception:
                pass

            # 去重（相同 planet+node+rotation）
            deduped = {}
            for r in results:
                dk = (r['planet'], r['node_name'], r['rotation'])
                if dk not in deduped:
                    deduped[dk] = r

            sorted_locs = sorted(deduped.values(),
                          key=lambda x: (x['planet'], x['node_name']))
            return sorted_locs[:40], len(sorted_locs)

        finally:
            self._close(conn)

    @staticmethod
    def _is_chinese(text: str) -> bool:
        """判断文本是否包含中文。"""
        for ch in text:
            if "\u4e00" <= ch <= "\u9fff" or "\u3400" <= ch <= "\u4dbf":
                return True
        return False

    @staticmethod
    def _filter_relic_refinements(results: list[dict]) -> list[dict]:
        """过滤遗物精炼版本，只保留 Intact（最基础版本）。

        遗物在 items 表中有 4 个精炼状态（Intact/Exceptional/Flawless/Radiant），
        搜索结果只需保留 Intact 版本，避免同一遗物重复出现。
        """
        if not results:
            return results

        filtered = []
        for r in results:
            en_name = r.get("en_name", "")
            words = en_name.split()
            if (len(words) >= 3
                    and words[0] in _RELIC_ERAS
                    and words[-1] in _REFINEMENT_TAGS):
                if words[-1] != "Intact":
                    continue
            filtered.append(r)
        return filtered


# ============================================================
# 便捷单例
# ============================================================
_item_service_instance = None


def get_item_service() -> ItemService:
    """获取 ItemService 单例。"""
    global _item_service_instance
    if _item_service_instance is None:
        _item_service_instance = ItemService()
    return _item_service_instance
