"""
[L-Service] 构建 market_items 表（新版本）

从 items 表中提取所有可交易物品，根据规则生成 warframe.market slug 并填充到 market_items 表。
额外从 Relics.json 补充 Prime 部件蓝图等 All.json 不含的物品。
从 data/build_market_items.py 迁移而来。

## AI 硬约束 — 修改本文件前必读
归属层:    [L-Service] (core/services/)
允许依赖:  Python 标准库 + data/* + core.hotkey_config 等纯模块
禁止依赖:  PySide6 / QtWidgets / QtGui / QtCore(Signal 除外)
           core.widgets/* / core.pages/* / core.recognizers/*
必读规范:  .trae/rules/开发规范.md §6.2

本文件相关红线:
- 禁止 import PySide6 → Service 是纯逻辑,不能碰 UI
- 禁止返回 Qt 对象 → 只能返回 dict / list / str / int / bool
- 禁止在 Service 中发信号调用 widget → 状态走 core.state / EventBus
- 禁止未捕获的 IO/网络异常冒泡 → 必须 try/except 降级
- 禁止在 Service 中持有 widget 引用

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.2。
"""

import json
import sqlite3
import time
from typing import Optional, Callable


# 数据库/外部仓库路径(打包/开发环境自适应,见 core.paths)
from core.paths import app_root as _app_root, ensure_user_file as _ensure_db_file
_DB_PATH = _ensure_db_file("warframe.db")
_RELICS_JSON = _app_root() / "external" / "warframe-items_sparse" / "data" / "json" / "Relics.json"


def _name_to_slug(en_name: str) -> str:
    """将英文物品名转换为 warframe.market slug。"""
    slug = en_name.lower()
    slug = slug.replace('\n', ' ').replace('\r', '')
    slug = slug.replace("'", "")
    slug = slug.replace('"', '')
    slug = slug.replace(" & ", "_")
    slug = slug.replace("&", "")
    slug = slug.replace(" ", "_")
    slug = slug.replace("-", "_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def build_market_items(log_callback: Optional[Callable] = None,
                        conn: Optional[sqlite3.Connection] = None) -> dict:
    """从 items 表构建 market_items 表。

    Args:
        log_callback: 可选日志回调 (msg: str)
        conn: 可选的已有数据库连接（复用，不关闭）
    Returns:
        统计字典 {'inserted': N, 'skipped': N, 'elapsed': N}
    """
    start_time = time.time()

    def _log(msg: str):
        if log_callback:
            log_callback(msg)

    own_conn = conn is None
    if own_conn:
        if not _DB_PATH.exists():
            _log(f"错误: 数据库不存在: {_DB_PATH}")
            return {'inserted': 0, 'skipped': 0, 'elapsed': 0}
        conn = sqlite3.connect(str(_DB_PATH))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=OFF")

    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_items (
                id              INTEGER PRIMARY KEY,
                slug            TEXT NOT NULL UNIQUE,
                en_name         TEXT NOT NULL,
                zh_name         TEXT DEFAULT '',
                item_unique     TEXT DEFAULT '',
                item_type       TEXT DEFAULT '',
                is_tradable     INTEGER DEFAULT 0,
                is_prime        INTEGER DEFAULT 0,
                zh_pinyin       TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mktitems_slug ON market_items(slug)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mktitems_en ON market_items(en_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mktitems_zh ON market_items(zh_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mktitems_unique ON market_items(item_unique)")

        conn.execute("DELETE FROM market_items")
        _log("已清空旧数据")

        cur = conn.execute("""
            SELECT rowid, unique_name, name, zh_name, type, tradable, is_prime, zh_pinyin
            FROM items WHERE tradable = 1
        """)
        rows = cur.fetchall()
        _log(f"找到 {len(rows)} 个可交易物品")

        inserted = 0
        skipped = 0
        slug_set = set()
        batch = []

        for row in rows:
            item_id, unique_name, en_name, zh_name, item_type, tradable, is_prime, zh_pinyin = row
            if not en_name:
                skipped += 1
                continue

            slug = _name_to_slug(en_name)
            if slug in slug_set:
                suffix = unique_name.split('/')[-1].lower().replace(' ', '_').replace("'", "")
                if suffix and suffix != slug:
                    alt_slug = f"{slug}_{suffix}"
                    if alt_slug not in slug_set:
                        slug = alt_slug
                    else:
                        skipped += 1
                        continue
                else:
                    skipped += 1
                    continue

            slug_set.add(slug)
            batch.append((
                item_id, slug, en_name, zh_name or '', unique_name,
                item_type, tradable, is_prime, zh_pinyin or '',
            ))
            if len(batch) >= 500:
                conn.executemany("""
                    INSERT INTO market_items
                        (id, slug, en_name, zh_name, item_unique, item_type, is_tradable, is_prime, zh_pinyin)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, batch)
                inserted += len(batch)
                batch.clear()

        if batch:
            conn.executemany("""
                INSERT INTO market_items
                    (id, slug, en_name, zh_name, item_unique, item_type, is_tradable, is_prime, zh_pinyin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, batch)
            inserted += len(batch)

        # ★ 补充: 从 Relics.json 提取 All.json 不含的物品（Prime 部件蓝图等）
        supplemental = 0
        if _RELICS_JSON.exists():
            existing_slugs = set(r[0] for r in conn.execute("SELECT slug FROM market_items").fetchall())
            relic_batch = []
            with open(_RELICS_JSON, 'r', encoding='utf-8') as f:
                relics_data = json.load(f)
            seen = set()
            for relic in relics_data:
                for rw in relic.get('rewards', []):
                    item_data = rw.get('item', {})
                    wm = item_data.get('warframeMarket', {})
                    slug = wm.get('urlName', '')
                    en_name = item_data.get('name', '')
                    unique_name = item_data.get('uniqueName', '')
                    if not slug or not en_name or slug in existing_slugs or slug in seen:
                        continue
                    seen.add(slug)
                    is_prime = 1 if 'Prime' in en_name else 0
                    relic_batch.append((
                        None, slug, en_name, '', unique_name,
                        '', 1, is_prime, '',
                    ))
            if relic_batch:
                conn.executemany("""
                    INSERT OR IGNORE INTO market_items
                        (id, slug, en_name, zh_name, item_unique, item_type, is_tradable, is_prime, zh_pinyin)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, relic_batch)
                supplemental = len(relic_batch)
                _log(f"  Relics.json 补充: {supplemental} 条 (Prime 部件蓝图等)")

        conn.commit()
        total_inserted = inserted + supplemental
        elapsed = round(time.time() - start_time, 1)
        _log(f"完成: 基础 {inserted} 条 + 补充 {supplemental} 条 = {total_inserted} 条, 跳过 {skipped} 条, 耗时 {elapsed}s")
        return {'inserted': total_inserted, 'supplemental': supplemental, 'skipped': skipped, 'elapsed': elapsed}

    finally:
        if own_conn:
            conn.close()
