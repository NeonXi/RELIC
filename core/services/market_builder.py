"""
[L-Service] 构建 market_items 表（新版本）

从 items 表中提取所有可交易物品，根据规则生成 warframe.market slug 并填充到 market_items 表。
从 data/build_market_items.py 迁移而来。
"""

import sqlite3
import time
from pathlib import Path
from typing import Optional, Callable


_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "warframe.db"


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

        conn.commit()
        elapsed = round(time.time() - start_time, 1)
        _log(f"完成: 插入 {inserted} 条, 跳过 {skipped} 条, 耗时 {elapsed}s")
        return {'inserted': inserted, 'skipped': skipped, 'elapsed': elapsed}

    finally:
        if own_conn:
            conn.close()
