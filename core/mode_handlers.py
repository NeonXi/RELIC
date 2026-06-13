"""
功能模式处理器 —— 从 AppCore 拆分出来的功能处理逻辑。

职责：
- 出入库状态查询 (_handle_check_status)
- 遗物内容查询 (_handle_query_parts)
- 翻译 (_handle_translate)

所有处理器接收必要的运行时状态作为参数，避免循环依赖。
"""

from typing import Optional
from pathlib import Path
from core.constants import (
    COLOR_VAULTED, COLOR_AVAILABLE, COLOR_UNKNOWN,
    COLOR_GOLD, COLOR_SILVER, COLOR_COPPER, FALLBACK_COLOR,
)
from core.annotation import Annotation
from core.recognizers.item_name import match_and_translate
from data.ui_strings import S


# ---- 精炼标签过滤正则 ----
import re

_REFINEMENT_RE = re.compile(
    r'\s*[\[(（【]?\s*(完好|优良|优异|无瑕|卓越|光辉|INTACT|EXCEPTIONAL|FLAWLESS|RADIANT)\s*[\])）】]?\s*$',
    re.IGNORECASE
)


def strip_refinement(name: str) -> str:
    """去除遗物名称末尾的精炼标签，返回基础名称。"""
    return _REFINEMENT_RE.sub('', name).strip()


# ================================================================
# 出入库状态查询
# ================================================================

def handle_check_status(last_relics, relic_db, last_region, dpi, overlay):
    """出入库查询：识别遗物 → 标注出入库状态。"""
    print(f"[诊断-出入库] last_relics={len(last_relics)}, region={last_region}, dpi={dpi}", flush=True)
    annotations = []

    for name, box in last_relics:
        base_name = strip_refinement(name)
        sx = int(last_region[0] + box[0][0] / dpi)
        sy = int(last_region[1] + box[0][1] / dpi - 28)
        info = relic_db.find(base_name)
        print(f"[诊断-出入库] name='{name}' -> base='{base_name}' -> info={'有' if info else 'None'}", flush=True)
        if info:
            if info.get('vaulted', False):
                color, label = COLOR_VAULTED, f"{base_name} [{S('overlay', 'relic_vaulted')}]"
            else:
                color, label = COLOR_AVAILABLE, f"{base_name} [{S('overlay', 'relic_available')}]"
        else:
            color, label = COLOR_UNKNOWN, f"{base_name} [?]"
        annotations.append(Annotation.create(label, sx, sy, duration_ms=8000, color=color))

    overlay.show_annotations_stream(
        annotations, auto_hide_ms=8000, interval_ms=30, batch_size=2)
    overlay.display(
        S.format("overlay", "annotations_shown", count=len(annotations)), auto_hide_ms=5000)


# ================================================================
# 遗物内容查询
# ================================================================

def handle_query_parts(last_relics, relic_db, last_region, dpi, overlay):
    """遗物内容查询：匹配遗物内容 → 标注掉落物品 + 稀有度颜色。"""
    annotations = []
    matched = 0
    unmatched_names = []

    for name, box in last_relics:
        base_name = strip_refinement(name)
        sx = int(last_region[0] + box[0][0] / dpi)
        sy = int(last_region[1] + box[0][1] / dpi - 28)
        info = relic_db.find(base_name)
        if not info:
            unmatched_names.append(base_name)
            annotations.append(
                Annotation.create(S.format("overlay", "relic_no_parts_info", name=base_name),
                                  sx, sy, duration_ms=10000, color=FALLBACK_COLOR))
            continue

        matched += 1
        parts = info.get('parts', [])
        vaulted = info.get('vaulted', False)
        status_color = COLOR_VAULTED if vaulted else COLOR_AVAILABLE
        status = S("overlay", "relic_vaulted") if vaulted else S("overlay", "relic_available")

        lines = [f"{base_name} [{status}]"]
        line_colors = [status_color]
        sorted_parts = sorted(parts, key=lambda p: p.get('chance', 0))
        chances = sorted(set(p.get('chance', 0) for p in sorted_parts))
        extra_lines, extra_colors = _map_rarity_colors(chances, sorted_parts)
        lines.extend(extra_lines)
        line_colors.extend(extra_colors)
        label = "\n".join(lines)
        annotations.append(Annotation.create(label, sx, sy, duration_ms=10000, color=status_color, line_colors=line_colors))

    overlay.show_annotations_stream(
        annotations, auto_hide_ms=10000, interval_ms=35, batch_size=1)

    return matched, total, unmatched_names


def _map_rarity_colors(chances, sorted_parts):
    """根据概率排名分配稀有度颜色。"""
    if len(chances) >= 3:
        chance_to_color = {chances[0]: COLOR_GOLD, chances[1]: COLOR_SILVER, chances[2]: COLOR_COPPER}
    elif len(chances) == 2:
        chance_to_color = {chances[0]: COLOR_GOLD, chances[1]: COLOR_COPPER}
    else:
        chance_to_color = {chances[0]: COLOR_SILVER}

    lines, colors = [], []
    for p in sorted_parts:
        ch = p.get('chance', 0)
        clr = chance_to_color.get(ch, COLOR_SILVER)
        prefix = "●" if ch == chances[0] else ("◦" if len(chances) > 1 and ch == chances[-1] else "◈")
        lines.append(f"  {prefix} {p['name']}")
        colors.append(clr)
    return lines, colors


# ================================================================
# 翻译
# ================================================================

def handle_translate(last_items, last_region, dpi, overlay):
    """翻译：OCR 文本 → 匹配数据库 → 标注中文名。"""
    if not last_items:
        overlay.display(S("overlay", "no_text_detected"), auto_hide_ms=3000)
        return

    translated = match_and_translate(last_items)
    if not translated:
        overlay.display(S("overlay", "translate_failed"), auto_hide_ms=3000)
        return

    annotations = []
    print(f"[显示-翻译] ===== 渲染 {len(translated)} 条翻译标注 =====", flush=True)
    for item in translated:
        en_name = item.get('en_name', item.get('ocr_text', ''))
        zh_name = item.get('zh_name', '')
        quality = item.get('match_quality', 'none')
        box = item['box']
        sx = int(last_region[0] + box[0][0] / dpi)
        sy = int(last_region[1] + box[0][1] / dpi - 28)

        if quality == 'exact':
            color = COLOR_AVAILABLE
        elif quality in ('prefix', 'contains'):
            color = COLOR_VAULTED
        else:
            color = COLOR_UNKNOWN

        label = S.format("overlay", "translate_label_fmt", zh_name=zh_name, en_name=en_name) if (zh_name and zh_name != en_name) else en_name

        print(f"[显示-翻译] OCR=\"{item.get('ocr_text')}\" | 匹配=\"{en_name}\" | zh=\"{zh_name}\" | "
              f"quality={quality} | 坐标=({sx},{sy}) | 显示文字=\"{label}\"", flush=True)

        annotations.append(Annotation.create(label, sx, sy, duration_ms=10000, color=color))

    overlay.show_annotations_stream(
        annotations, auto_hide_ms=10000, interval_ms=35, batch_size=1)

    matched = sum(1 for t in translated if t.get('match_quality', 'none') != 'none')
    overlay.display(
        S.format("overlay", "translate_summary", total=len(translated), matched=matched),
        auto_hide_ms=6000)

    return len(translated), matched


# ================================================================
# 价格查询（CTRL+T）
# ================================================================

# 价格查询专用噪声过滤（不影响遗物识别的 TextCorrector）
_PRICE_NOISE = set("|\\/=[]【】\"',.=-~!()<>{}@#$%^&*")
_PRICE_JUNK_RE = re.compile(r'^[0-9OoIil]+$')  # 纯数字/形近字 → 丢弃


def _clean_price_items(ocr_results: list) -> list[dict]:
    """价格查询专用轻量清洗：只做基础清理，不做激进字符替换。

    与 TextCorrector 的区别：
    - 不做 s→5, l→1, O→0 等无差别字符替换
    - 只做基础去噪和 Warframe 常见词修复
    - 保留 OCR 原始识别结果
    """
    results = []
    for text, box, score in ocr_results:
        # 基础清洗
        cleaned = text.strip()
        cleaned = ''.join(ch for ch in cleaned if ch not in _PRICE_NOISE)
        cleaned = re.sub(r' {2,}', ' ', cleaned).strip()

        # 过滤纯数字/垃圾
        if not cleaned or _PRICE_JUNK_RE.match(cleaned):
            continue

        results.append({
            'original': text,
            'corrected': cleaned,
            'item_name': cleaned,
            'box': box,
            'score': score,
        })
    return results


def handle_query_price(
    ocr_results: list,
    last_region: tuple,
    dpi: float,
    overlay,
):
    """价格查询：OCR 识别 → 纠错 → WM API 查询 → 显示前 10 个最低价。

    Args:
        ocr_results: OCR 识别结果列表 [(text, box, score), ...]
        last_region: 截图区域 (left, top, right, bottom)
        dpi: DPI 缩放比例
        overlay: Overlay 实例
    """
    from core.services.market_price_service import MarketPriceService, get_market_price_service
    from core.annotation import Annotation
    from data.ui_strings import S
    from core.constants import COLOR_GOLD, COLOR_AVAILABLE, COLOR_UNKNOWN

    if not ocr_results:
        overlay.display(S("overlay", "no_text_detected"), auto_hide_ms=3000)
        return

    # ---- Step 1: 价格查询专用轻量清洗（不破坏原始 OCR 结果） ----
    # 注意：这里不用 TextCorrector（那是遗物识别的纠错逻辑，含 s→5 等激进映射）
    items_to_query = _clean_price_items(ocr_results)
    if not items_to_query:
        overlay.display(S("overlay", "translate_failed"), auto_hide_ms=3000)
        return

    print(f"[价格查询] 提取到 {len(items_to_query)} 个物品: "
          f"{[i['item_name'] for i in items_to_query]}", flush=True)

    # ---- Step 2: 查询 WM API 价格 ----
    svc = get_market_price_service()
    price_annotations = []
    query_count = 0

    for item in items_to_query:
        item_name = item['item_name']
        box = item['box']

        # 计算标注位置（框的上方）
        sx = int(last_region[0] + min(p[0] for p in box) / dpi)
        sy = int(last_region[1] + min(p[1] for p in box) / dpi - 28)

        try:
            # 尝试将物品名转换为 slug（简化版：直接用名称查询）
            url_name = _item_name_to_slug(item_name)

            if not url_name:
                # 无法转换 slug，显示未找到提示
                label = f"{item_name}\n{S('overlay', 'item_no_match_fmt', ocr_text=item_name)}"
                price_annotations.append(
                    Annotation.create(label, sx, sy, duration_ms=10000, color=COLOR_UNKNOWN)
                )
                continue

            # 查询价格
            query_count += 1
            price_data = svc.query_price(url_name)

            if not price_data or not price_data.get('top10'):
                # 无价格数据
                label = f"{item_name}\n{S('overlay', 'item_no_price_fmt', display_name=item_name)}"
                price_annotations.append(
                    Annotation.create(label, sx, sy, duration_ms=10000, color=COLOR_UNKNOWN)
                )
                continue

            # 格式化价格标注（显示前 10 个 ingame 卖家）
            top10 = price_data['top10'][:10]
            lines = [_format_price_header(item_name, price_data)]
            for i, seller in enumerate(top10[:5], 1):  # 先显示前 5 个
                lines.append(f"  {i}. {seller['platinum']}p x{seller['quantity']} @{seller['ingame_name']}")

            if len(top10) > 5:
                lines.append(f"  ... 还有 {len(top10)-5} 个卖家")

            label = '\n'.join(lines)
            color = COLOR_GOLD if price_data['min_price'] < 20 else COLOR_AVAILABLE
            price_annotations.append(
                Annotation.create(label, sx, sy, duration_ms=12000, color=color)
            )

        except Exception as e:
            print(f"[价格查询] {item_name} 查询失败: {e}", flush=True)
            label = f"{item_name}\n查询异常"
            price_annotations.append(
                Annotation.create(label, sx, sy, duration_ms=8000, color=COLOR_UNKNOWN)
            )

    # ---- Step 3: 显示标注 ----
    if price_annotations:
        overlay.show_annotations_stream(
            price_annotations, auto_hide_ms=12000, interval_ms=40, batch_size=1
        )

        summary = S.format("overlay", "price_query_summary",
                           total=len(items_to_query), queried=query_count,
                           results=len(price_annotations))
        overlay.display(summary, auto_hide_ms=8000)
    else:
        overlay.display(S("overlay", "no_price_data"), auto_hide_ms=4000)


def _item_name_to_slug(item_name: str) -> Optional[str]:
    """将物品名转换为 warframe.market slug。

    基于数据库模糊匹配：
      - 将 OCR 文本拆分为关键词（中文字符 + 英文单词）
      - 在 market_items 表中查找包含最多关键词的物品
      - 返回最佳匹配的 slug

    Args:
        item_name: OCR 识别文本（可能乱序，如 "蓝图 Ash Prime 系统"）

    Returns:
        URL slug 或 None
    """
    if not item_name:
        return None

    matched = _fuzzy_match_from_db(item_name)
    if matched:
        print(f"[价格查询] 模糊匹配: \"{item_name}\" → \"{matched['name']}\" "
              f"(slug={matched['slug']}, score={matched['score']:.2f})", flush=True)
        return matched['slug']

    # DB 无匹配时回退到简单转换
    slug = item_name.lower()
    slug = slug.replace("'", "")
    slug = slug.replace(" & ", "_")
    slug = slug.replace("&", "")
    slug = slug.replace(" ", "_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def _fuzzy_match_from_db(ocr_text: str) -> Optional[dict]:
    """基于数据库的模糊匹配：从 OCR 乱序文本找到正确的遗物物品名和 slug。

    数据源：relic_rewards 表（遗物内含物品）
    算法：
      1. 将 OCR 文本拆分为关键词 token
      2. 从 relic_rewards 加载所有唯一物品名
      3. 对每个候选计算关键词覆盖率
      4. 返回最佳匹配的物品名 + 自动生成的 slug

    Args:
        ocr_text: OCR 原始文本（如 "蓝图 Ash Prime 系统"）

    Returns:
        {'name': str, 'slug': str, 'score': float} 或 None
    """
    import sqlite3

    tokens = _tokenize_ocr(ocr_text)
    if not tokens or len(tokens) < 2:
        return None

    db_path = _find_db_path()
    if not db_path:
        return None

    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # ★ 从 relic_rewards 查询所有唯一遗物物品名
        cur.execute("""
            SELECT DISTINCT item_name
            FROM relic_rewards
            WHERE item_name IS NOT NULL AND item_name != ''
              AND item_name NOT LIKE '%Kuva%'
              AND item_name NOT LIKE '%Forma%'
        """)
        candidates = [r[0] for r in cur.fetchall()]
        conn.close()

        if not candidates:
            print(f"[价格查询] 遗物表无数据", flush=True)
            return None

        best_match = None
        best_score = 0.0

        ocr_lower = ocr_text.lower()
        merged_tokens = _merge_chinese_tokens(tokens)
        merged_set = set(t.lower() for t in merged_tokens)

        for item_name in candidates:
            name_lower = item_name.lower()

            # 关键词覆盖率
            matched = sum(1 for t in merged_set if t in name_lower)
            coverage = matched / max(len(merged_set), 1)

            # 字符级覆盖度
            chars_in_ocr = sum(1 for c in name_lower if c in ocr_lower)
            char_ratio = chars_in_ocr / max(len(name_lower), 1)

            score = coverage * 0.6 + char_ratio * 0.4

            if score > best_score and coverage >= 0.35:
                best_score = score
                best_match = {
                    'name': item_name,
                    'slug': _name_to_slug_simple(item_name),
                    'score': score,
                }

        return best_match

    except Exception as e:
        print(f"[价格查询] 模糊匹配 DB 错误: {e}", flush=True)
        return None


def _name_to_slug_simple(name: str) -> str:
    """简单 slug 生成（与 WM API 规则一致）。"""
    if not name:
        return ''
    slug = name.lower().replace("'", "").replace(" & ", "_").replace("&", "")
    slug = slug.replace(" ", "_").replace("-", "_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")


def _merge_chinese_tokens(tokens: list[str]) -> list[str]:
    """合并相邻的中文字符为词组。

    ["蓝", "图", "Ash", "Prime", "系", "统"]
    → ["蓝图", "Ash", "Prime", "系统"]
    """
    result = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if len(t) == 1 and '\u4e00' <= t <= '\u9fff':
            # 中文字符：向后合并连续中文
            merged = t
            j = i + 1
            while j < len(tokens) and len(tokens[j]) == 1 and '\u4e00' <= tokens[j] <= '\u9fff':
                merged += tokens[j]
                j += 1
            result.append(merged)
            i = j
        else:
            result.append(t)
            i += 1
    return result


def _tokenize_ocr(text: str) -> list[str]:
    """将 OCR 文本拆分为关键词 token。

    规则：
      - 中文逐字拆分（每个汉字一个 token）
      - 英文按空格拆分为单词
      - 过滤单字符噪声（纯数字/标点）
      - 过滤常见停用词

    Examples:
        "蓝图 Ash Prime 系统" → ["蓝图", "Ash", "Prime", "系统"]
        "Atlas Prime 机体 蓝图" → ["Atlas", "Prime", "机体", "蓝图"]
    """
    import re

    text = text.strip()
    if not text:
        return []

    # 停用词（OCR 常见但无意义的词/字）
    STOP_WORDS = {'o', '0', 'l', 'i', '|', '-', '_', 'x', 'a'}

    tokens = []
    current_word = []
    is_chinese_phase = False

    for ch in text:
        if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f':
            # 中文字符：如果之前有英文单词，先保存
            if current_word:
                word = ''.join(current_word).strip()
                if word and len(word) > 1 and word.lower() not in STOP_WORDS:
                    tokens.append(word)
                current_word = []
            tokens.append(ch)  # 中文逐字
            is_chinese_phase = True
        elif ch.isalpha() or ch == "'":
            current_word.append(ch)
            is_chinese_phase = False
        elif ch.isspace():
            if current_word:
                word = ''.join(current_word).strip()
                if word and len(word) > 1 and word.lower() not in STOP_WORDS:
                    tokens.append(word)
                current_word = []
        else:
            # 数字或符号：作为分隔符处理
            if current_word:
                word = ''.join(current_word).strip()
                if word and len(word) > 1 and word.lower() not in STOP_WORDS:
                    tokens.append(word)
                current_word = []

    # 处理末尾残留
    if current_word:
        word = ''.join(current_word).strip()
        if word and len(word) > 1 and word.lower() not in STOP_WORDS:
            tokens.append(word)

    return tokens


def _find_db_path() -> Optional[Path]:
    """查找项目数据库文件路径。"""
    from pathlib import Path

    candidates = [
        Path('data/warframe.db'),
        Path('data/relic_data.db'),
    ]
    for p in candidates:
        if p.exists():
            return p.resolve()
    return None


def _format_price_header(item_name: str, price_data: dict) -> str:
    """格式化价格标题行。"""
    from data.ui_strings import S

    min_p = price_data.get('min_price', 0)
    avg_p = price_data.get('avg_price', 0)
    total_ingame = price_data.get('total_ingame', 0)

    return (f"{item_name} [{S('overlay', 'price_ingame_sellers', count=total_ingame)}]\n"
            f"  最低 {min_p}p | 均价 {avg_p:.1f}p")

