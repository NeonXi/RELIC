"""
[L-Service] RecognitionPipelineService — 物品识别管线服务

从截图到价格的完整链路编排：
  图像预处理(饱和度压制) → OCR识别(RapidOCR) → 分组拼接 → 纠错匹配(DB) → 价格查询(WM API)

依赖: Python 标准库 + cv2 + numpy + rapidocr_onnxruntime + data/warframe.db
禁止: PySide6 / QtWidgets / QtGui (Signal 除外)
返回: dict / list (原始类型, 绝不返回 Qt 对象)

用法:
    from core.services.recognition_pipeline_service import RecognitionPipelineService

    svc = RecognitionPipelineService()
    result = svc.process_image(image)  # np.ndarray (BGR)
    # result:
    #   {
    #       'items': [
    #           {
    #               'raw_text': str,          # OCR 原始文本
    #               'corrected_text': str,     # 纠错后文本
    #               'en_name': str,            # 英文名
    #               'zh_name': str,            # 中文名
    #               'slug': str,               # WM slug
    #               'match_method': str,       # 匹配方式
    #               'price': dict | None,      # 价格数据
    #               'box': list,               # 包围盒坐标
    #           }, ...
    #       ],
    #       'timings': dict,         # 各阶段耗时(ms)
    #       'total_ms': float,        # 总耗时
#   }
"""

from __future__ import annotations

import re
import sqlite3
import time
from pathlib import Path

import cv2
import numpy as np


class RecognitionPipelineService:
    """物品识别管线：截图 → OCR → 匹配 → 价格。"""

    # ★ 单例：RapidOCR 引擎（避免每次截图都重建 ONNX 模型）
    _ocr_engine = None
    _ocr_engine_lock = None

    def __init__(self):
        # 数据库路径(打包/开发环境自适应,见 core.paths)
        from core.paths import ensure_user_file
        self._db_path: Path = ensure_user_file("warframe.db")
        self._cn_part_map: dict[str, str] = {}  # {中文部件名: 英文部件名}
        self._cn_part_map_loaded: bool = False
        # ★ 线程本地 DB 连接（避免跨线程复用导致 sqlite3.ProgrammingError）
        import threading
        self._thread_local = threading.local()

        # ★ 实例级缓存：避免同一批次识别时重复全表扫描
        self._full_item_map_cache: dict[str, str] | None = None  # {中文全名: 英文全名}
        self._full_item_map_loaded: bool = False

        # 饱和度压制参数
        self.sat_low_thresh: int = 40
        self.val_high_thresh: int = 180
        self.suppress_factor: float = 0.3

    def shutdown(self):
        """关闭缓存的资源（应用退出时调用）。

        清理线程本地 DB 连接和 OCR 引擎单例。
        注意: thread_local 的 conn 无法跨线程关闭，仅清理当前线程的连接。
        """
        # 关闭当前线程的 DB 连接（如果存在）
        conn = getattr(self._thread_local, 'conn', None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._thread_local.conn = None

        # 清理 OCR 引擎单例（类级别）
        if RecognitionPipelineService._ocr_engine is not None:
            try:
                # RapidOCR 没有显式 close 方法，置空让 GC 回收
                RecognitionPipelineService._ocr_engine = None
            except Exception:
                pass

    @classmethod
    def _get_ocr_engine(cls):
        """获取或创建 RapidOCR 单例（线程安全懒加载）。"""
        if cls._ocr_engine is not None:
            return cls._ocr_engine

        if cls._ocr_engine_lock is None:
            import threading
            cls._ocr_engine_lock = threading.Lock()

        with cls._ocr_engine_lock:
            if cls._ocr_engine is not None:
                return cls._ocr_engine
            from rapidocr_onnxruntime import RapidOCR
            from core.constants import (
                RAPIDOCR_TEXT_SCORE, RAPIDOCR_BOX_THRESH,
                RAPIDOCR_DET_LIMIT_SIDE_LEN, RAPIDOCR_DET_LIMIT_TYPE,
            )
            cls._ocr_engine = RapidOCR(
                text_score=RAPIDOCR_TEXT_SCORE,
                box_thresh=RAPIDOCR_BOX_THRESH,
                det_limit_side_len=RAPIDOCR_DET_LIMIT_SIDE_LEN,
                det_limit_type=RAPIDOCR_DET_LIMIT_TYPE,
                det_model_path=None,
            )
        return cls._ocr_engine

    # ════════════════════════════════════
    #  公开接口
    # ════════════════════════════════════

    def process_image(self, image: np.ndarray, verbose: bool = False) -> dict:
        """
        处理单张图片，返回识别结果和价格。

        Args:
            image: BGR 格式的 numpy 数组（来自 dxcam/GDI 截图）
            verbose: 是否输出详细日志到控制台（调试用，默认开启）

        Returns:
            {
                'items': [...],      # 物品列表（含价格）
                'timings': {...},    # 耗时统计
                'total_ms': float,   # 总耗时
            }
        """
        t_start = time.perf_counter()
        timings = {}

        if verbose:
            print("\n" + "=" * 60)
            print("  RecognitionPipeline - 物品识别管线")
            print("=" * 60)

        h, w = image.shape[:2]
        if verbose:
            print(f"\n[输入] 尺寸: {w}x{h} | dtype={image.dtype} | shape={image.shape}")

        # Stage 1-3: 图像预处理
        t0 = time.perf_counter()
        processed, scale = self._preprocess_image(image)
        t1 = time.perf_counter()
        timings['preprocess'] = (t1 - t0) * 1000
        if verbose:
            ph, pw = processed.shape[:2]
            print(f"\n[Stage 1-3] 图像预处理 (饱和度背景压制)")
            print(f"           缩放: {scale:.2f}x → {pw}x{ph}")
            print(f"           耗时: {timings['preprocess']:.1f}ms")

        # Stage 4: OCR 识别
        t2 = time.perf_counter()
        ocr_lines = self._run_ocr(processed, scale)
        t3 = time.perf_counter()
        timings['ocr'] = (t3 - t2) * 1000
        if verbose:
            print(f"\n[Stage 4] OCR 识别 (RapidOCR)")
            print(f"           耗时: {timings['ocr']:.1f}ms")
            print(f"           识别到 {len(ocr_lines)} 行原始文本:")
            for i, (text, box, score) in enumerate(ocr_lines):
                sc = f"{score:.3f}" if isinstance(score, (int, float)) else str(score)
                print(f"             [{i+1}] \"{text}\" (置信度={sc})")

        if not ocr_lines:
            if verbose:
                print(f"\n[结果] 未检测到文字 | 总耗时: {(time.perf_counter()-t_start)*1000:.0f}ms")
            return {'items': [], 'timings': timings, 'total_ms': (time.perf_counter() - t_start) * 1000}

        # Stage 5: 分组拼接
        t4 = time.perf_counter()
        grouped_items = self._group_ocr_lines(ocr_lines)
        t5 = time.perf_counter()
        timings['grouping'] = (t5 - t4) * 1000
        if verbose:
            print(f"\n[Stage 5] 分组拼接 (X坐标聚类)")
            print(f"           耗时: {timings['grouping']:.1f}ms")
            print(f"           分组后: {len(grouped_items)} 个物品:")
            for i, item in enumerate(grouped_items):
                print(f"             [物品{i+1}] \"{item['merged_text']}\" ({item['line_count']}行)")

        if not grouped_items:
            if verbose:
                print(f"\n[结果] 分组后无物品 | 总耗时: {(time.perf_counter()-t_start)*1000:.0f}ms")
            return {'items': [], 'timings': timings, 'total_ms': (time.perf_counter() - t_start) * 1000}

        # Stage 6-7: 纠错 + 数据库匹配
        t6 = time.perf_counter()
        matched_items = self._correct_and_match(grouped_items)
        t7 = time.perf_counter()
        timings['match'] = (t7 - t6) * 1000
        if verbose:
            print(f"\n[Stage 6-7] 纠错与数据库匹配")
            print(f"           耗时: {timings['match']:.1f}ms")
            for i, m in enumerate(matched_items):
                raw = m['raw_text']
                corrected = m['corrected_text']
                en = m.get('en_name', '?')
                zh = m.get('zh_name', '?')
                slug = m.get('slug', '?')
                method = m.get('match_method', '?')

                if method == 'discarded':
                    print(f"           ⊘ [{i+1}] \"{raw}\" → 已丢弃(非交易物品)")
                    continue

                status = "✓" if en != '?' else "✗"
                print(f"           {status} [{i+1}] \"{raw}\"")
                if corrected != raw:
                    print(f"               → 纠错: \"{corrected}\"")
                print(f"               → 匹配: [{method}] {en} | {zh}")
                print(f"               → slug: {slug}")

        # Stage 8: 价格查询
        t8 = time.perf_counter()
        priced_items = self._query_prices(matched_items)
        t9 = time.perf_counter()
        timings['price_query'] = (t9 - t8) * 1000
        if verbose:
            print(f"\n[Stage 8] 价格查询 (warframe.market)")
            print(f"           耗时: {timings['price_query']:.1f}ms")
            for i, item in enumerate(priced_items):
                en = item.get('en_name', '?')
                method = item.get('match_method', '')
                if method == 'discarded':
                    print(f"           ⊘ [{i+1}] {en} — 已跳过")
                    continue
                price_info = item.get('price')
                if price_info:
                    min_p = price_info.get('min_price', 0)
                    total = price_info.get('total_ingame', 0)
                    top10 = price_info.get('top10', [])
                    print(f"           ✓ [{i+1}] {en}")
                    print(f"               最低: {min_p}p | 在线卖家: {total} | TOP{len(top10)}:")
                    for rank, o in enumerate(top10, 1):
                        print(f"                 #{rank:2d}  {o['platinum']:>4}p  x{o['quantity']}  ({o['ingame_name']})")
                else:
                    print(f"           ✗ [{i+1}] {en} — 查询失败或无数据")

        total_ms = (time.perf_counter() - t_start) * 1000
        if verbose:
            matched_n = sum(1 for i in priced_items if i.get('en_name') != '?')
            priced_n = sum(1 for i in priced_items if i.get('price') is not None)
            print(f"\n{'='*60}")
            print(f"  总耗时: {total_ms:.0f}ms")
            print(f"  物品: {len(priced_items)} | 匹配: {matched_n} | 有价: {priced_n}")
            print(f"  详细耗时:")
            for name, ms in timings.items():
                if ms > 0:
                    bar_len = int(ms / total_ms * 30) if total_ms > 0 else 0
                    bar = "█" * max(bar_len, 1)
                    print(f"    {name:20s} {ms:7.1f}ms  {bar}")
            print(f"{'='*60}\n")

        return {
            'items': priced_items,
            'timings': timings,
            'total_ms': total_ms,
        }

    # ════════════════════════════════════
    #  Stage 1-3: 图像预处理
    # ════════════════════════════════════

    def _preprocess_image(self, image: np.ndarray) -> tuple[np.ndarray, float]:
        """
        图像预处理：上采样 + 饱和度背景压制。

        Returns:
            (处理后的灰度图, 缩放倍数)
        """
        h, w = image.shape[:2]

        # 上采样到目标宽度
        target_w = 2400
        scale = min(target_w / w, 6.0) if w < target_w else 1.0
        if scale > 1.0:
            big = cv2.resize(image, (int(w * scale), int(h * scale)),
                             interpolation=cv2.INTER_CUBIC)
        else:
            big = image.copy()

        # 饱和度背景压制
        if len(big.shape) == 3:
            hsv = cv2.cvtColor(big, cv2.COLOR_BGR2HSV)
            s_ch, v_ch = cv2.split(hsv)[1], cv2.split(hsv)[2]
            mask = self._create_sat_mask(s_ch, v_ch)
            gray = self._suppress_bg(v_ch, mask)
        else:
            gray = big.copy()

        return gray, scale

    @staticmethod
    def _create_sat_mask(s_ch: np.ndarray, v_ch: np.ndarray) -> np.ndarray:
        """基于 HSV 饱和度/亮度创建文字区域掩码。"""
        s_norm = s_ch.astype(np.float32) / 255.0
        v_norm = v_ch.astype(np.float32) / 255.0
        low_sat = s_norm < 0.157  # sat_low_thresh/255
        high_val = v_norm > 0.706  # val_high_thresh/255
        text_region = np.logical_or(low_sat, high_val).astype(np.float32)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        text_region = cv2.dilate(text_region, kernel, iterations=1)
        text_region = cv2.erode(text_region, kernel, iterations=1)
        return cv2.GaussianBlur(text_region, (5, 5), 1.0)

    def _suppress_bg(self, v_ch: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """基于掩码压暗背景，保留文字区域。"""
        suppressed = (v_ch.astype(np.float32) *
                      (mask + (1 - mask) * self.suppress_factor))
        return np.clip(suppressed, 0, 255).astype(np.uint8)

    # ════════════════════════════════════
    #  Stage 4: OCR 识别
    # ════════════════════════════════════

    @staticmethod
    def _run_ocr(gray_image: np.ndarray, scale: float) -> list[tuple]:
        """
        用 RapidOCR 识别文字（使用缓存的引擎单例）。

        Returns:
            [(text, box, score), ...]  box 坐标已还原到原始尺寸
        """
        engine = RecognitionPipelineService._get_ocr_engine()
        result, _ = engine(gray_image)

        ocr_lines = []
        if result:
            for item in result:
                if len(item) != 3:
                    continue
                box, text, score = item
                if not isinstance(text, str):
                    continue
                text = text.strip()
                if not text:
                    continue
                if scale > 1.0:
                    box = [[p[0] / scale, p[1] / scale] for p in box]
                ocr_lines.append((text, box, score))

        return ocr_lines

    # ════════════════════════════════════
    #  Stage 5: 分组拼接
    # ════════════════════════════════════

    def _group_ocr_lines(self, ocr_lines: list) -> list[dict]:
        """
        将 OCR 行按「WF UI 列布局」分组为物品。

        WF 遗物内含物界面是网格布局：每列 = 1 个物品，每列可有 1~3 行文字。
        分组策略（两阶段）:

          Phase 1 — 列聚类:
            基于 X 区间重叠率将行分配到各"列"。
            同一列的文字在 X 轴上高度重叠（x_left/x_right 接近），
            不同列之间 X 区间几乎不重叠。

          Phase 2 — 列内合并:
            同一列内按 Y 坐标排序，拼接文本。
        """
        if not ocr_lines:
            return []
        if len(ocr_lines) == 1:
            text, box, score = ocr_lines[0]
            return [{'merged_text': text, 'lines': ocr_lines, 'box': box}]

        # ── 计算每行空间特征 ──
        line_info = []
        for idx, (text, box, score) in enumerate(ocr_lines):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            line_info.append({
                'idx': idx, 'text': text, 'box': box, 'score': score,
                'x_center': sum(xs) / len(xs),
                'y_top': min(ys), 'y_bottom': max(ys),
                'x_left': min(xs), 'x_right': max(xs),
                'width': max(xs) - min(xs),
            })

        # ══ Phase 1: X 区间重叠列聚类 ══
        # 按 x_left 排序，然后用区间重叠率决定是否开启新列
        line_info.sort(key=lambda l: l['x_left'])

        columns: list[list] = []  # 每个 element 是一列的行列表
        current_col = [line_info[0]]

        for i in range(1, len(line_info)):
            curr = line_info[i]
            prev_col_right = max(l['x_right'] for l in current_col)

            # 计算与当前列的重叠率
            # overlap = intersection / min(width_curr, col_width)
            intersection = max(0, min(curr['x_right'], prev_col_right) - max(curr['x_left'], min(l['x_left'] for l in current_col)))
            denom = min(curr['width'], max(l['x_right'] for l in current_col) - min(l['x_left'] for l in current_col))
            overlap_ratio = intersection / denom if denom > 0 else 0

            # ★ 核心判断: 重叠率 > 30% → 同列; 否则开新列
            # WF UI 中不同列之间的间隙通常 > 列宽度的 50%
            if overlap_ratio > 0.30:
                current_col.append(curr)
            else:
                columns.append(current_col)
                current_col = [curr]

        columns.append(current_col)

        # ══ Phase 2: 列内合并（先拼接再规范化空格）══
        #
        # 策略: 两步走
        #   Step 1 — 全拼接: 将列内所有行连成一条字符串（截断词边界直接合并）
        #   Step 2 — 插空格: 在已知的 WF 物品名分词位置插入空格
        #
        # 优势: 不需要逐对判断"该不该加空格"，只需知道"哪里应该有空格"
        #
        # 例: ["Titania Prime头", "部神经光元蓝图"]
        #   Step 1 → "Titania Prime头部神经光元蓝图"
        #   Step 2 → "Titania Prime 头部神经光元蓝图" (在 Prime 后加空格)
        result = []
        for col in columns:
            col.sort(key=lambda l: l['y_top'])

            # ── Step 1: 截断点合并（无空格）──
            raw_parts = [col[0]['text']]
            for j in range(1, len(col)):
                prev = raw_parts[-1]
                curr = col[j]['text']
                mi = self._detect_midword_merge(prev, curr)
                if mi:
                    p_trim, mw, c_trim = mi
                    raw_parts[-1] = prev[:p_trim] + mw + curr[c_trim:]
                else:
                    raw_parts[-1] += curr  # 正常换行也无空格，Step 2 统一处理

            raw_merged = ''.join(raw_parts)

            # ── Step 2: 规范化空格 ──
            merged_text = self._normalize_item_spacing(raw_merged)

            all_pts = [p for l in col for p in l['box']]
            merged_box = [
                [min(p[0] for p in all_pts), min(p[1] for p in all_pts)],
                [max(p[0] for p in all_pts), min(p[1] for p in all_pts)],
                [max(p[0] for p in all_pts), max(p[1] for p in all_pts)],
                [min(p[0] for p in all_pts), max(p[1] for p in all_pts)],
            ]

            result.append({
                'merged_text': merged_text,
                'lines': [(l['text'], l['box'], l['score']) for l in col],
                'box': merged_box,
                'line_count': len(col),
            })

        # ══ 后处理：拼接散落的 "图"/"蓝图" 到以 "蓝" 结尾的组 ══
        # WF UI 中 "蓝图" 常被 OCR 拆成 "蓝" + "图" 两行，且 X 坐标偏移导致未归入同一组
        result = self._merge_orphan_blueprint_suffixes(result)

        # ══ 后处理：拼接 UI 截断产生的跨组碎片 ══
        # WF 长物品名被 UI 截断换行后，OCR 识别为独立的碎片组
        # 例: "Titania Prime头" + "部神经光元蓝图" → 应合并为同一物品
        result = self._merge_truncated_fragments(result)

        return result

    @staticmethod
    def _detect_midword_merge(prev_text: str, next_text: str) -> tuple[int, str, int] | None:
        """检测 prev/next 之间是否存在 WF UI 截断词边界，返回合并信息。

        WF UI 在长物品名换行时可能在任意中文字符处截断。
        例: "Titania Prime头" + "部神经光元蓝图"
            → 截断点在 "头"|"部" 之间
            → 返回 (prev_trim_len, merged_word, next_trim_len)
            → 调用方用: prev[:p_trim] + merged_word + next[c_trim:]
            → 结果: "Titania Prime" + "头部" + "神经光元蓝图"

        Returns:
            (p_trim, merged_word, c_trim) 或 None（非截断，正常加空格）
            p_trim: prev 末尾需截掉的字符数（即 prev 末尾的截断残留）
            merged_word: 拼接后的完整词（替换截断点两侧的碎片）
            c_trim: next 开头需跳过的字符数（已并入 merged_word）
        """
        if not prev_text or not next_text:
            return None

        # 提取 prev 末尾连续中文 和 next 开头连续中文
        prev_tail = ''
        for ch in reversed(prev_text):
            if '\u4e00' <= ch <= '\u9fff':
                prev_tail = ch + prev_tail
            else:
                break

        next_head = ''
        for ch in next_text:
            if '\u4e00' <= ch <= '\u9fff':
                next_head += ch
            else:
                break

        if not prev_tail or not next_head:
            return None

        # ── 策略1: 字典验证（最可靠）──
        from core.mode_handlers import _get_merged_cn_to_en
        part_dict = _get_merged_cn_to_en()

        # 尝试: prev_tail 取后 1~2 字 + next_head 取前 1~3 字 → 组合查字典
        best_match = None
        for p_len in range(min(2, len(prev_tail)), 0, -1):
            prefix = prev_tail[-p_len:] if p_len > 0 else ''
            for n_len in range(1, min(4, len(next_head)) + 1):
                candidate = prefix + next_head[:n_len]
                if candidate in part_dict:
                    # 找到已知词！记录最长的匹配
                    if best_match is None or len(candidate) > len(best_match[1]):
                        best_match = (p_len, candidate, n_len)

        if best_match:
            # prev_text = [非中文前缀][prev_tail]
            # 截断点在 prev_tail 最后 p_len 个字符处
            # 保留: 前缀 + prev_tail 中不参与截断的部分
            prefix_len = len(prev_text) - len(prev_tail)          # 非中文前缀长度
            keep_tail_chars = len(prev_tail) - best_match[0]       # tail 中保留的字符数
            p_trim = prefix_len + keep_tail_chars                  # prev 截断到此位置
            c_trim = best_match[2]                                 # next 开头跳过(已含在 merged_word)
            return (p_trim, best_match[1], c_trim)

        # ── 策略2: 模式匹配兜底（仅对明显截断模式）──
        # "XXXPrime单字" + "中文..." → 只合并单字边界
        if re.search(r'Prime[\s]?[\u4e00-\u9fff]$', prev_text, re.IGNORECASE):
            # prev 以 Prime+单个中文结尾，next 以中文开头
            # 合并这 1+1 或 1+2 个字
            p_last = 1  # prev 末尾取 1 个中文
            n_first = min(2, len(next_head))  # next 开头取 1~2 个中文
            prefix_len = len(prev_text) - len(prev_tail)
            p_trim = prefix_len + (len(prev_tail) - p_last)
            merged = prev_tail[-p_last:] + next_head[:n_first]
            return (p_trim, merged, n_first)

        # ── 策略3: 蓝图后缀合并 ──
        # prev 以 "蓝" 结尾 + next 以 "图"/"蓝图" 开头
        if (prev_tail.endswith('蓝')
                and next_head.startswith('图')):
            prefix_len = len(prev_text) - len(prev_tail)
            keep_tail = len(prev_tail) - 1  # 保留除 "蓝" 外的所有 tail 字符
            p_trim = prefix_len + keep_tail
            c_trim = 2 if next_head.startswith('蓝图') else 1
            return (p_trim, '蓝图', c_trim)

        return None

    @staticmethod
    def _normalize_item_spacing(raw: str) -> str:
        """对全拼接后的原始文本，在 WF 物品名的正确分词位置插入空格。

        输入: 无空格的拼接结果（如 "TitaniaPrime头部神经光元蓝图"）
        输出: 规范化空格的物品名（如 "Titania Prime 头部神经光元蓝图"）

        WF 物品名结构: [{英文名}] [Prime] [{中文部件名}] [蓝图]
        空格插入规则（按顺序应用）:

          1. 英文名/Prime 之间: "XXXPrime" → "XXX Prime"
          2. 英文名(非Prime)/中文之间: "Forma蓝图" → "Forma 蓝图"
          3. Prime/部件之间:   "Prime头部" → "Prime 头部"
          4. 清理多余空格
        """
        s = raw

        # ── 规则1: 英文字母和 "Prime" 之间的空格 ──
        # 用负向先行断言代替 \b（Python 中 \w 含中文，\b 在中英文间不匹配）
        # 匹配: 字母 + "Prime" + (非字母或结尾)
        s = re.sub(r'([a-zA-Z])(?=Prime(?![a-zA-Z]))', r'\1 ', s, flags=re.IGNORECASE)

        # ── 规则2: 英文名(非 Prime) 和 中文之间的空格 ──
        # 匹配: 连续英文字母 + 中文 (中间无空格)
        # 例: "Forma蓝图" → "Forma 蓝图", "SevagothPrime系统" → 已被规则1处理过
        # 注意: 排除已被规则1处理的情况 (避免重复)
        s = re.sub(r'([a-zA-Z]{2,})([\u4e00-\u9fff])', r'\1 \2', s)

        # ── 规则2b: 中文部件名(≥2字) 和 "蓝图" 之间的空格 ──
        # 武器/战甲部件名通常是 2~5 个中文字，后接 "蓝图"
        # 例: "枪管蓝图" → "枪管 蓝图", "头部神经光元蓝图" → "头部神经光元 蓝图"
        s = re.sub(r'([\u4e00-\u9fff]{2,5})(蓝图)', r'\1 \2', s)

        # ── 规则3: "Prime" 和中文部件之间的空格 ──
        # (规则2可能已覆盖，但保险起见再处理一次 Prime 特例)
        s = re.sub(r'(Prime)([\u4e00-\u9fff])', r'\1 \2', s, flags=re.IGNORECASE)

        # ── 规则4: 清理多余空格 ──
        s = re.sub(r' {2,}', ' ', s).strip()

        return s

    @staticmethod
    def _merge_orphan_blueprint_suffixes(groups: list[dict]) -> list[dict]:
        """将散落的 "图"/"蓝图"/"Blueprint" 行拼接到相邻的物品组。

        场景:
        - OCR 拆行: ["Baruuk Prime 蓝", "图"] → 合并为 "Baruuk Prime 蓝图"
        - 同一行被拆: ["Ash Prime", "蓝图"] → 合并为 "Ash Prime 蓝图"
        """
        if len(groups) < 2:
            return groups

        # ══ 第一轮：找孤儿组（仅含蓝图/图/Blueprint 的单行组）══
        orphan_indices = []
        for i, g in enumerate(groups):
            t = g['merged_text'].strip()
            # 中文孤儿: 图 / 蓝图
            # 英文孤儿: Blueprint (大小写)
            clean = re.sub(r'\s+', '', t).lower()
            if clean in ('图', '蓝图', 'blueprint'):
                orphan_indices.append(i)

        if not orphan_indices:
            return groups

        # 找目标组：以 "蓝" 结尾（不含完整蓝图）或以 Prime 名称结尾的组
        target_indices = []
        for i, g in enumerate(groups):
            if i in orphan_indices:
                continue
            t = g['merged_text'].strip()
            if (t.endswith('蓝') and '蓝图' not in t and 'Blueprint' not in t) or \
               re.search(r'\bPrime\s*$', t, re.IGNORECASE):
                target_indices.append(i)

        if not target_indices or not orphan_indices:
            return groups

        # 按 Y 坐标匹配：孤儿组应该紧挨在目标组下方或旁边
        merged = set()
        for ti in target_indices:
            tgt_box = groups[ti]['box']
            tgt_bottom = max(p[1] for p in tgt_box)
            tgt_cx = sum(p[0] for p in tgt_box) / 4

            best_oi = None
            best_dist = float('inf')
            for oi in orphan_indices:
                if oi in merged:
                    continue
                orb_box = groups[oi]['box']
                orb_top = min(p[1] for p in orb_box)
                orb_cx = sum(p[0] for p in orb_box) / 4

                # 垂直距离近 + 水平对齐
                v_dist = abs(orb_top - tgt_bottom)
                h_dist = abs(orb_cx - tgt_cx)
                dist = v_dist + h_dist * 0.3
                if dist < best_dist and v_dist < 150:  # 垂直方向放宽到 150px
                    best_dist = dist
                    best_oi = oi

            if best_oi is not None:
                # 合并：目标组的文本 + 孤儿组的文本
                groups[ti]['merged_text'] += ' ' + groups[best_oi]['merged_text'].strip()
                groups[ti]['lines'].extend(groups[best_oi]['lines'])
                groups[ti]['line_count'] += groups[best_oi]['line_count']

                # 合并包围盒
                ob = groups[best_oi]['box']
                tb = groups[ti]['box']
                groups[ti]['box'] = [
                    [min(tb[0][0], ob[0][0]), min(tb[0][1], ob[0][1])],
                    [max(tb[1][0], ob[1][0]), min(tb[1][1], ob[1][1])],
                    [max(tb[2][0], ob[2][0]), max(tb[2][1], ob[2][1])],
                    [min(tb[3][0], ob[3][0]), max(tb[3][1], ob[3][1])],
                ]
                merged.add(best_oi)

        # 移除已合并的孤儿组
        return [g for i, g in enumerate(groups) if i not in merged]

    @staticmethod
    def _merge_truncated_fragments(groups: list[dict]) -> list[dict]:
        """拼接 WF UI 截断产生的跨组碎片。

        场景: 长物品名被游戏 UI 截断换行，OCR 识别为独立的碎片组。
        例:
          "Titania Prime头" + "部神经光元蓝图" → 合并为 "Titania Prime 头部神经光元蓝图"
          "Titania Prime蓝" + "图" → 合并为 "Titania Prime 蓝图"  (此场景由 _merge_orphan_blueprint_suffixes 覆盖)
          "Titania Prime机" + "体蓝图" → 合并为 "Titania Prime 机体蓝图"

        策略:
          1. 找"前缀碎片组": 文本以截断模式结尾 (Prime+单字/部件词开头/以 蓝 结尾)
          2. 找"后缀碎片组": 文本以续接模式开头 (部/体/图 等部件词)
          3. 按 Y 坐标相邻 + X 坐标对齐匹配，合并匹配对
        """
        if len(groups) < 2:
            return groups

        import re as _re

        # ── 截断模式：前缀碎片特征 ──
        #   "XXXPrime头", "XXXPrime蓝", "XXXPrime机"  (Prime + 单个中文字)
        #   "XXX 蓝"  (以 蓝 结尾但不含完整 蓝图)
        PREFIX_TRUNC_RE = _re.compile(
            r'.*Prime[\s]?[\u4e00-\u9fff]$'      # ...Prime + 单个中文
            r'|.*\b蓝$'                             # 以 蓝 结尾（不含完整蓝图）
            r'|.*\b机体$'                           # 以 机体 结尾
            , _re.IGNORECASE
        )

        # ── 续接模式：后缀碎片特征 ──
        #   "部XXX", "体XXX", "图" (以 部/体/图 开头的中文行)
        SUFFIX_START_RE = _re.compile(
            r'^[\u4e00-\u9fff]*[部体图]'           # 部/体/图 开头
            r'|^Blueprint$'                         # 英文 Blueprint 孤儿
            , _re.IGNORECASE
        )

        # 标记前缀/后缀碎片组
        prefix_indices = []
        suffix_indices = []
        for i, g in enumerate(groups):
            t = g['merged_text'].strip()
            if PREFIX_TRUNC_RE.match(t) and g['line_count'] == 1:
                prefix_indices.append(i)
            elif SUFFIX_START_RE.match(t) and g['line_count'] == 1:
                suffix_indices.append(i)

        if not prefix_indices or not suffix_indices:
            return groups

        # 按 Y 坐标匹配：后缀碎片应该紧挨在前缀碎片下方
        merged = set()
        for pi in prefix_indices:
            if pi in merged:
                continue
            pbox = groups[pi]['box']
            p_bottom = max(p[1] for p in pbox)
            p_cx = sum(p[0] for p in pbox) / 4

            best_si = None
            best_dist = float('inf')
            for si in suffix_indices:
                if si in merged or si == pi:
                    continue
                sbox = groups[si]['box']
                s_top = min(p[1] for p in sbox)
                s_cx = sum(p[0] for p in sbox) / 4

                v_dist = abs(s_top - p_bottom)
                h_dist = abs(s_cx - p_cx)
                dist = v_dist + h_dist * 0.5

                # 阈值: 垂直 < 120px, 水平 < 组宽度的 50%
                p_width = max(p[0] for p in pbox) - min(p[0] for p in pbox)
                if dist < best_dist and v_dist < 120 and h_dist < max(p_width * 0.5, 40):
                    best_dist = dist
                    best_si = si

            if best_si is not None:
                # 合并: 前缀文本 + 后缀文本（去掉重复的首字）
                p_text = groups[pi]['merged_text'].strip()
                s_text = groups[best_si]['merged_text'].strip()

                # 去重: 如果前缀末字和后缀首字相同（如 "头"+"部" 不去重，但 "蓝"+"图" 可能需要处理）
                # 这里简单拼接，空格修复在后续步骤完成
                groups[pi]['merged_text'] = f"{p_text} {s_text}"
                groups[pi]['lines'].extend(groups[best_si]['lines'])
                groups[pi]['line_count'] += groups[best_si]['line_count']

                # 合并包围盒
                sb = groups[best_si]['box']
                pb = groups[pi]['box']
                groups[pi]['box'] = [
                    [min(pb[0][0], sb[0][0]), min(pb[0][1], sb[0][1])],
                    [max(pb[1][0], sb[1][0]), min(pb[1][1], sb[1][1])],
                    [max(pb[2][0], sb[2][0]), max(pb[2][1], sb[2][1])],
                    [min(pb[3][0], sb[3][0]), max(pb[3][1], sb[3][1])],
                ]
                merged.add(best_si)

        return [g for i, g in enumerate(groups) if i not in merged]

    # ════════════════════════════════════
    #  Stage 6-7: 纠错 + DB 匹配
    # ════════════════════════════════════

    def _correct_and_match(self, grouped_items: list) -> list[dict]:
        """
        对分组后的 OCR 文本做纠错 + 数据库匹配。
        流程: 正则清理 → 中文部件名映射(DB) → 精确/模糊匹配
        """
        conn = self._open_db()
        try:
            cn_part_map = self._load_cn_part_map(conn)
        except Exception:
            cn_part_map = {}

        # ★ 合并手动部件映射（覆盖 DB 未收录的词：如 蓝图→Blueprint）
        from core.mode_handlers import _get_merged_cn_to_en
        for cn, en in _get_merged_cn_to_en().items():
            if cn not in cn_part_map:
                cn_part_map[cn] = en

        results = []
        for item in grouped_items:
            raw = item['merged_text']

            # ★ 丢弃 Forma 等非交易物品
            if self._is_discard_item(raw):
                results.append({
                    'raw_text': raw,
                    'corrected_text': raw,
                    'box': item.get('box'),
                    'en_name': '(已丢弃)',
                    'zh_name': '(已丢弃)',
                    'slug': '',
                    'match_method': 'discarded',
                })
                continue

            corrected = self._regex_correct(raw)

            # ★ 翻译流程（数据驱动，无需硬编码武器名）:
            #   1. 从 prime_parts 加载 {中文全名: 英文全名} 自动映射
            #   2. 尝试直接匹配（OCR 输出 → DB 中文记录 → 对应英文名）
            #   3. 匹配不到时，用部件词/手动字典兜底翻译
            full_map = self._load_full_item_map(conn)
            en_text = self._try_db_translate(corrected, full_map, cn_part_map)

            match = self._db_lookup(en_text, raw, conn)
            results.append({
                'raw_text': raw,
                'corrected_text': en_text,
                'box': item.get('box'),
                **match,
            })

        return results

    @staticmethod
    def _regex_correct(text: str) -> str:
        """正则修复常见 OCR 字符错误 + 中英文边界空格修复。"""
        t = text.strip()

        # ★ 0. 中英文边界补空格（OCR 常丢失中英文之间的空格）
        # "Ash Prime头部" → "Ash Prime 头部"
        # "神经光元Blueprint" → "神经光元 Blueprint"
        # "陨蜓Prime蓝" → "陨蜓 Prime 蓝"
        t = re.sub(r'([a-zA-Z0-9])([\u4e00-\u9fff])', r'\1 \2', t)
        t = re.sub(r'([\u4e00-\u9fff])([a-zA-Z0-9])', r'\1 \2', t)

        corrections = [
            # Prime 变体
            (r'PNme', 'Prime'), (r'Pnme', 'Prime'), (r'Prine', 'Prime'),
            (r'Priime', 'Prime'), (r'Prrme', 'Prime'),
            # Blueprint 英文变体
            (r'Bueprint', 'Blueprint'), (r'Bluerint', 'Blueprint'), (r'Bluepnnt', 'Blueprint'),
            # 中文蓝图合并
            (r'蓝图\s*图', '蓝图'),
            (r'蓝\s*图', '蓝图'),
            # ★ 尾部孤立的 "蓝" → "蓝图"（WF 物品名以蓝结尾必然是蓝图）
            (r'蓝$', '蓝图'),
            # 其他部件词
            (r'Neuroptcs', 'Neuroptics'), (r'Systens', 'Systems'),
            (r'Chasss', 'Chassis'), (r'Recever', 'Receiver'),
            (r'Barrel', 'Barrel'),
        ]
        for pattern, replacement in corrections:
            t = re.sub(pattern, replacement, t, flags=re.IGNORECASE)
        # 清理多余空格
        t = re.sub(r'\s{2,}', ' ', t).strip()
        return t

    @staticmethod
    def _is_discard_item(text: str) -> bool:
        """判断是否应丢弃的物品（如 Forma）。"""
        return bool(re.search(r'\bforma\b', text, re.IGNORECASE))

    def _load_cn_part_map(self, conn) -> dict[str, str]:
        """从 prime_parts 表加载 {中文部件名: 英文部件名} 映射。懒加载缓存。"""
        if self._cn_part_map_loaded:
            return self._cn_part_map

        if not conn:
            self._cn_part_map_loaded = True
            return {}

        try:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT DISTINCT en_name, zh_name FROM prime_parts "
                "WHERE zh_name != '' AND en_name != ''"
            ).fetchall()

            mapping: dict[str, str] = {}
            for en_name, zh_name in rows:
                en_after = self._after_prime(en_name)
                zh_after = self._after_prime(zh_name)
                if not en_after or not zh_after:
                    continue
                en_parts = en_after.split()
                zh_parts = zh_after.split()
                for i, zh_w in enumerate(zh_parts):
                    if not all('\u4e00' <= ch <= '\u9fff' for ch in zh_w):
                        continue
                    if i < len(en_parts):
                        en_w = en_parts[i]
                        if zh_w not in mapping or len(zh_w) > len(mapping.get(zh_w, '')):
                            mapping[zh_w] = en_w

            self._cn_part_map = {k: v for k, v in mapping.items() if v}
            self._cn_part_map_loaded = True
            return self._cn_part_map
        except Exception:
            self._cn_part_map_loaded = True
            return {}

    @staticmethod
    def _after_prime(name: str) -> str:
        """返回字符串中 'Prime' 之后的部分。"""
        idx = name.find('Prime')
        if idx < 0:
            return ''
        return name[idx + len('Prime'):].strip()

    def _load_full_item_map(self, conn) -> dict[str, str]:
        """从 prime_parts 表加载 {中文全名: 英文全名} 完整映射（带实例级缓存）。

        数据源: prime_parts 表的 zh_name / en_name 字段（572 条有中文记录）
        用途: 将 OCR 中文输出翻译为英文，用于 DB 查询匹配

        缓存策略:
          - 首次调用时全表扫描并缓存结果
          - 后续调用直接返回缓存，避免重复 DB 查询
          - 适用于同一批次多物品识别场景（process_image 内多次调用）

        与 _load_cn_part_map 的区别:
          _load_cn_part_map  → 只提取 Prime 后的部件词 (如 "上弓臂"→"Upper Limb")
          _load_full_item_map → 保留完整名称 (如 "大久和弓 Prime 上弓臂"→"Daikyu Prime Upper Limb")
        """
        # ★ 返回缓存（避免同批次重复全表扫描）
        if self._full_item_map_loaded and self._full_item_map_cache is not None:
            return self._full_item_map_cache

        if not conn:
            self._full_item_map_loaded = True
            self._full_item_map_cache = {}
            return {}

        try:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT en_name, zh_name FROM prime_parts "
                "WHERE zh_name != '' AND en_name != ''"
            ).fetchall()

            mapping: dict[str, str] = {}
            for en_name, zh_name in rows:
                # 规范化: 统一空格，便于匹配
                zh_norm = re.sub(r'\s+', ' ', zh_name).strip()
                en_norm = re.sub(r'\s+', ' ', en_name).strip()
                if zh_norm and en_norm:
                    mapping[zh_norm] = en_norm

            # ★ 写入缓存
            self._full_item_map_cache = mapping
            self._full_item_map_loaded = True
            return mapping
        except Exception:
            self._full_item_map_loaded = True
            self._full_item_map_cache = {}
            return {}

    def _try_db_translate(self, text: str, full_map: dict[str, str],
                          cn_part_map: dict[str, str]) -> str:
        """数据驱动的中文→英文翻译：优先使用 DB 映射，兜底用字典。

        策略（按优先级）:
          1. 精确匹配: OCR 文本 == DB zh_name
          2. 去空格匹配: 去掉所有空格后相等（处理 OCR 空格不一致）
          3. 包含匹配: OCR 是 DB 名的子集/超集（处理截断/多余字符）
          4. 兜底翻译: 手动字典 + 部件词替换
        """
        if not text:
            return text

        norm = re.sub(r'\s+', ' ', text).strip()
        no_space = re.sub(r'\s', '', text).lower()

        # ── 策略1: 精确匹配 ──
        if norm in full_map:
            return full_map[norm]

        # ── 策略2: 去空格匹配 ──
        for zh_name, en_name in full_map.items():
            if re.sub(r'\s', '', zh_name).lower() == no_space:
                return en_name

        # ── 策略3: 包含匹配（OCR 可能多/少字符）──
        best_match = None
        best_score = 0
        for zh_name, en_name in full_map.items():
            zh_ns = re.sub(r'\s', '', zh_name).lower()
            if no_space in zh_ns or zh_ns in no_space:
                score = min(len(no_space), len(zh_ns)) / max(len(no_space), len(zh_ns))
                if score > best_score:
                    best_score = score
                    best_match = en_name
        if best_match and best_score >= 0.8:
            return best_match

        # ── 策略4: 兜底翻译（手动字典 + 部件词）──
        from core.mode_handlers import _translate_cn_to_en
        result = _translate_cn_to_en(text)
        result = self._apply_cn_part_map(result, cn_part_map)
        return result

    @staticmethod
    def _apply_cn_part_map(text: str, cn_part_map: dict[str, str]) -> str:
        """用数据库映射表替换中文部件名为英文。"""
        if not cn_part_map:
            return text
        t = text
        for cn, en in sorted(cn_part_map.items(), key=lambda x: len(x[0]), reverse=True):
            t = t.replace(cn, f' {en} ')
        return re.sub(r'\s{2,}', ' ', t).strip()

    def _db_lookup(self, corrected: str, raw_text: str, conn) -> dict:
        """在数据库中查找匹配的物品记录。"""
        if not conn:
            return {'en_name': '?', 'zh_name': '?', 'slug': '?', 'match_method': 'no_db'}

        cur = conn.cursor()
        corrected_lower = corrected.lower().strip()

        # 策略1: market_items 精确匹配
        row = cur.execute(
            "SELECT en_name, zh_name, slug FROM market_items "
            "WHERE LOWER(en_name) = ? LIMIT 1",
            (corrected_lower,)
        ).fetchone()
        if row:
            return {'en_name': row[0], 'zh_name': row[1], 'slug': row[2],
                    'match_method': 'exact'}

        # 策略2: market_items LIKE 模糊
        row = cur.execute(
            "SELECT en_name, zh_name, slug FROM market_items "
            "WHERE LOWER(en_name) LIKE ? LIMIT 1",
            (f"%{corrected_lower}%",)
        ).fetchone()
        if row:
            return {'en_name': row[0], 'zh_name': row[1], 'slug': row[2],
                    'match_method': 'like'}

        # 策略3: 分词包含匹配
        words = set(corrected_lower.replace('-', ' ').split())
        if words:
            placeholders = ' AND '.join(['LOWER(en_name) LIKE ?'] * len(words))
            params = tuple(f"%{w}%" for w in words)
            row = cur.execute(
                f"SELECT en_name, zh_name, slug FROM market_items WHERE {placeholders} LIMIT 10",
                params
            ).fetchall()
            if len(row) == 1:
                r = row[0]
                return {'en_name': r[0], 'zh_name': r[1], 'slug': r[2],
                        'match_method': 'word_match'}
            elif row:
                best = min(row, key=lambda x: len(x[0]))
                return {'en_name': best[0], 'zh_name': best[1], 'slug': best[2],
                        'match_method': f'word_match({len(row)}→1)'}

        # 策略4: 核心词匹配（取最长的英文单词）
        core_words = [w for w in sorted(words, key=len, reverse=True) if len(w) >= 3]
        for cw in core_words[:3]:
            row = cur.execute(
                "SELECT en_name, zh_name, slug FROM market_items "
                "WHERE LOWER(en_name) LIKE ? LIMIT 3",
                (f"%{cw}%",)
            ).fetchall()
            if row:
                best = min(row, key=lambda x: len(x[0]))
                return {'en_name': best[0], 'zh_name': best[1], 'slug': best[2],
                        'match_method': f'core_word({cw})'}

        # 策略5: prime_parts 兜底
        pp_row = cur.execute(
            "SELECT en_name, zh_name, slug FROM prime_parts "
            "WHERE LOWER(en_name) = ? LIMIT 1",
            (corrected_lower,)
        ).fetchone()
        if pp_row:
            return {'en_name': pp_row[0], 'zh_name': pp_row[1], 'slug': pp_row[2],
                    'match_method': 'pp_exact'}
        pp_fuzzy = cur.execute(
            "SELECT en_name, zh_name, slug FROM prime_parts "
            "WHERE LOWER(en_name) LIKE ? LIMIT 3",
            (f"%{corrected_lower}%",)
        ).fetchall()
        if len(pp_fuzzy) == 1:
            r = pp_fuzzy[0]
            return {'en_name': r[0], 'zh_name': r[1], 'slug': r[2],
                    'match_method': 'pp_fuzzy'}
        elif len(pp_fuzzy) > 1:
            best = min(pp_fuzzy, key=lambda x: len(x[0]))
            return {'en_name': best[0], 'zh_name': best[1], 'slug': best[2],
                    'match_method': f'pp_fuzzy({len(pp_fuzzy)}→1)'}

        return {'en_name': '?', 'zh_name': '?', 'slug': '?', 'match_method': 'no_match'}

    # ════════════════════════════════════
    #  Stage 8: 价格查询
    # ════════════════════════════════════

    def _query_prices(self, matched_items: list) -> list:
        """用 slug 查询 warframe.market 价格。"""
        from core.services.market_price_service import get_market_price_service

        svc = get_market_price_service()
        results = []
        for item in matched_items:
            result = dict(item)
            slug = item.get('slug', '')
            if slug and slug != '?':
                try:
                    price_data = svc.query_price(slug)
                    result['price'] = price_data
                except Exception:
                    result['price'] = None
            else:
                result['price'] = None
            results.append(result)
        return results

    # ════════════════════════════════════
    #  工具方法
    # ════════════════════════════════════

    def _open_db(self) -> sqlite3.Connection | None:
        """打开数据库连接（线程本地：每个线程独立连接，避免跨线程复用报错）。"""
        # 优先返回当前线程已缓存的连接
        conn = getattr(self._thread_local, 'conn', None)
        if conn is not None:
            return conn

        if not self._db_path.exists():
            return None
        try:
            conn = sqlite3.connect(str(self._db_path))
            self._thread_local.conn = conn
            return conn
        except Exception:
            return None
