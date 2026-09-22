"""
OCR 图像处理管线可视化调试工具

用法:
    python core/diagnostics/debug_ocr_pipeline.py [图片路径或文件夹]

功能:
    1. 显示 OCR 管线每一步的中间图像（原始→上采样→预处理→OCR输入）
    2. 在最终图像上绘制检测框和识别文字
    3. 输出每一步的详细参数和耗时
    4. 中间图像保存到 debug_output/ 文件夹

示例:
    # 调试单张图片
    python core/diagnostics/debug_ocr_pipeline.py test_ocr/Banshee Prime 头部神经光元 蓝图.png

    # 调试文件夹内所有图片
    python core/diagnostics/debug_ocr_pipeline.py test_ocr/

    # 不带参数则自动扫描 test_ocr/
    python core/diagnostics/debug_ocr_pipeline.py
"""

import os
import re
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np


# ============================================================
#  配置
# ============================================================

DEBUG_OUTPUT = PROJECT_ROOT / "debug_output"
TEST_DIR = PROJECT_ROOT / "test_ocr"


# ============================================================
#  核心调试逻辑
# ============================================================

def load_image(image_path: Path) -> np.ndarray | None:
    """读取图片（兼容中文路径）。"""
    img_data = np.fromfile(str(image_path), dtype=np.uint8)
    img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
    return img


def save_debug_image(stage: str, img: np.ndarray, output_dir: Path):
    """保存调试中间图（兼容中文路径）。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000 % 100000)
    path = output_dir / f"{ts}_{stage}.png"
    ext = '.png'
    success, buf = cv2.imencode(ext, img)
    if success:
        buf.tofile(str(path))
        print(f"       保存: {path.name}")
    else:
        print(f"       [!] 保存失败: {stage}")


class PipelineDebugger:
    """OCR 管线可视化调试器。

    拦截 BaseOCR 的每个处理步骤，保存中间结果图像。
    使用 HSV 饱和度通道进行背景压制。
    """

    def __init__(self):
        self.stages = []          # [(stage_name, image), ...]
        self.timings = {}         # {stage_name: ms}
        self.output_dir = DEBUG_OUTPUT

        # ── 饱和度压制参数（可调）──
        self.sat_low_thresh = 40      # 低于此值视为低饱和度（可能是白色文字）
        self.val_high_thresh = 180    # 高于此值视为高亮度（可能是白色文字）
        self.suppress_factor = 0.3    # 背景压制系数（0=全黑，1=不变）

    def debug_pipeline(self, image: np.ndarray) -> dict:
        """
        完整运行 OCR 管线并记录每一步。

        Returns:
            {
                'stages': [(name, image_path), ...],
                'timings': {name: ms},
                'ocr_result': list,
                'final_image': np.ndarray (带标注),
            }
        """
        from core.constants import (
            OCR_COLOR_FILTER_ENABLED, OCR_COLOR_FILTER_LOWER, OCR_COLOR_FILTER_UPPER,
        )

        print("\n" + "=" * 60)
        print("  OCR 图像处理管线 - 逐步调试 (饱和度背景压制版) v2")
        print("=" * 60 + "\n")

        h, w = image.shape[:2]
        print(f"[原始图像] 尺寸: {w}x{h}")

        # ── Stage 0: 原始图像 ──
        self._save_stage("00_original", image)

        # ── Stage 1: 自适应上采样 ──
        t0 = time.perf_counter()
        scale = self._calculate_adaptive_scale(w, h)
        if scale > 1.0:
            big = self._resize_fast(image, scale)
        else:
            big = image.copy()
        t1 = time.perf_counter()

        bh, bw = big.shape[:2]
        print(f"\n[Stage 1] 自适应上采样")
        print(f"         缩放倍数: {scale:.2f}x")
        print(f"         输出尺寸: {bw}x{bh}")
        print(f"         耗时: {(t1-t0)*1000:.1f}ms")
        self.stages.append(("01_upscaled", big))
        self._save_stage("01_upscaled", big)
        self.timings['upscale'] = (t1-t0)*1000

        current = big

        # ── Stage 2: 颜色过滤（如果启用）──
        from core.constants import OCR_COLOR_FILTER_ENABLED, OCR_COLOR_FILTER_LOWER, OCR_COLOR_FILTER_UPPER
        if OCR_COLOR_FILTER_ENABLED and len(current.shape) == 3:
            t2 = time.perf_counter()
            filtered = self._filter_by_color(current, OCR_COLOR_FILTER_LOWER, OCR_COLOR_FILTER_UPPER)
            t3 = time.perf_counter()
            print(f"\n[Stage 2] HSV 颜色过滤")
            print(f"         范围: {OCR_COLOR_FILTER_LOWER} ~ {OCR_COLOR_FILTER_UPPER}")
            print(f"         耗时: {(t3-t2)*1000:.1f}ms")
            self.stages.append(("02_color_filtered", filtered))
            self._save_stage("02_color_filtered", filtered)
            self.timings['color_filter'] = (t3-t2)*1000
            current = filtered

        # ════════════════════════════════════
        #  ★ 核心改进：HSV 饱和度通道背景压制
        # ════════════════════════════════════
        t4 = time.perf_counter()

        if len(current.shape) == 3:
            # 转换到 HSV 颜色空间
            hsv = cv2.cvtColor(current, cv2.COLOR_BGR2HSV)
            h_ch, s_ch, v_ch = cv2.split(hsv)

            print(f"\n[Stage 3] HSV 饱和度通道分析")
            print(f"         S通道范围: [{s_ch.min()}, {s_ch.max()}]")
            print(f"         V通道范围: [{v_ch.min()}, {v_ch.max()}]")

            # 生成饱和度掩码：识别"可能的文字区域"
            sat_mask = self._create_saturation_mask(s_ch, v_ch)

            text_pixels = int(sat_mask.sum())
            total_pixels = sat_mask.size
            print(f"         文字区域占比: {text_pixels}/{total_pixels} ({text_pixels/total_pixels*100:.1f}%)")

            # 基于掩码压制背景
            suppressed = self._suppress_background(v_ch, sat_mask)

            gray = suppressed
        else:
            gray = current.copy()
            sat_mask = np.ones_like(gray, dtype=np.float32)

        t5 = time.perf_counter()
        print(f"         耗时: {(t5-t4)*1000:.1f}ms")
        self._save_stage("03_saturation_suppress", gray)
        # 同时保存饱和度掩码用于调试
        self._save_stage("03b_sat_mask", (sat_mask * 255).astype(np.uint8))
        self.timings['saturation_suppress'] = (t5-t4)*1000

        # ── 直接用饱和度处理结果送入 OCR ──
        ocr_input = gray

        # ── OCR 推理 ──
        t10 = time.perf_counter()
        from rapidocr_onnxruntime import RapidOCR
        from core.constants import RAPIDOCR_TEXT_SCORE, RAPIDOCR_BOX_THRESH
        from core.constants import RAPIDOCR_DET_LIMIT_SIDE_LEN, RAPIDOCR_DET_LIMIT_TYPE

        ocr_engine = RapidOCR(
            text_score=RAPIDOCR_TEXT_SCORE,
            box_thresh=RAPIDOCR_BOX_THRESH,
            det_limit_side_len=RAPIDOCR_DET_LIMIT_SIDE_LEN,
            det_limit_type=RAPIDOCR_DET_LIMIT_TYPE,
            det_model_path=None,
        )
        result, _ = ocr_engine(ocr_input)
        t11 = time.perf_counter()
        print(f"\n[Stage 6] OCR 推理 (RapidOCR)")
        print(f"         text_score={RAPIDOCR_TEXT_SCORE}, box_thresh={RAPIDOCR_BOX_THRESH}")
        print(f"         耗时: {(t11-t10)*1000:.1f}ms")

        # 解析 OCR 结果
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
                # 缩放坐标回原始尺寸
                if scale > 1.0:
                    box = [[p[0]/scale, p[1]/scale] for p in box]
                ocr_lines.append((text, box, score))

        print(f"\n         识别到 {len(ocr_lines)} 行原始文本:")
        for i, (text, box, score) in enumerate(ocr_lines):
            print(f"           [{i+1}] \"{text}\" (置信度={score})")

        # ════════════════════════════════════
        #  ★ 分组拼接：将属于同一物品的多行文字合并
        # ════════════════════════════════════
        try:
            grouped_items = self._group_ocr_lines(ocr_lines)
            print(f"\n         分组后: {len(grouped_items)} 个物品")
            for i, item in enumerate(grouped_items):
                print(f"           [物品{i+1}] \"{item['merged_text']}\" ({len(item['lines'])}行)")
        except Exception as e:
            import traceback
            print(f"\n         [!] 分组失败: {e}")
            traceback.print_exc()
            grouped_items = []

        self.timings['ocr_inference'] = (t11-t10)*1000
        self.timings['grouping'] = 0  # 分组很快，忽略
        self._save_stage("04_ocr_input", ocr_input)

        # ════════════════════════════════════
        #  ★ 纠错匹配：正则清理 + 数据库精确匹配
        # ════════════════════════════════════
        t12 = time.perf_counter()
        matched_items = self._correct_and_match(grouped_items)
        t13 = time.perf_counter()
        self.timings['correct_and_match'] = (t13-t12)*1000

        print(f"\n[Stage 7] 纠错与数据库匹配")
        print(f"         耗时: {(t13-t12)*1000:.1f}ms")
        for i, m in enumerate(matched_items):
            raw = m['raw_text']
            corrected = m['corrected_text']
            en = m.get('en_name', '?')
            zh = m.get('zh_name', '?')
            slug = m.get('slug', '?')
            method = m.get('method', '?')
            status = "✓" if en != '?' else "✗"
            print(f"           {status} [{i+1}] \"{raw}\"")
            if corrected != raw:
                print(f"               → 纠错: \"{corrected}\"")
            print(f"               → 匹配: [{method}] {en} | {zh}")
            print(f"               → slug: {slug}")

        # ════════════════════════════════════
        #  ★ Stage 8: 价格查询（warframe.market API）
        # ════════════════════════════════════
        t14 = time.perf_counter()
        priced_items = self._query_prices(matched_items)
        t15 = time.perf_counter()
        self.timings['price_query'] = (t15-t14)*1000

        print(f"\n[Stage 8] 价格查询 (warframe.market)")
        print(f"         耗时: {(t15-t14)*1000:.1f}ms")
        for i, item in enumerate(priced_items):
            en = item.get('en_name', '?')
            price_info = item.get('price', None)
            if price_info:
                min_p = price_info.get('min_price', 0)
                total = price_info.get('total_ingame', 0)
                top10 = price_info.get('top10', [])
                print(f"           ✓ [{i+1}] {en}")
                print(f"               最低: {min_p}p | 在线卖家: {total} | 显示TOP{len(top10)}:")
                for rank, o in enumerate(top10, 1):
                    print(f"                 #{rank:2d}  {o['platinum']:>4}p  x{o['quantity']}  ({o['ingame_name']})")
            else:
                print(f"           ✗ [{i+1}] {en} — 查询失败或无数据")

        # ── Stage 9: 最终可视化（带分组+纠错+价格标注）──
        final_vis = self._draw_final_result(image, ocr_lines, grouped_items, priced_items, scale)
        self.stages.append(("07_final_visualization", final_vis))
        self._save_stage("07_final", final_vis)

        total_time = (t11 - t0) * 1000
        print(f"\n{'='*60}")
        print(f"  总耗时: {total_time:.0f}ms")
        print(f"  详细耗时:")
        for name, ms in self.timings.items():
            if ms > 0:
                bar = "█" * int(ms/total_time*30)
                print(f"    {name:20s} {ms:7.1f}ms  {bar}")
        print(f"{'='*60}\n")

        return {
            'stages': self.stages,
            'timings': self.timings,
            'ocr_lines': ocr_lines,
            'grouped_items': grouped_items,
            'matched_items': matched_items,
            'priced_items': priced_items,
            'final_image': final_vis,
        }

    # ---- 饱和度背景压制核心方法 ----

    def _create_saturation_mask(self, s_channel: np.ndarray, v_channel: np.ndarray) -> np.ndarray:
        """
        基于饱和度和亮度通道创建文字区域掩码。

        Warframe UI 特点：
          - 物品名通常是白色/浅色文字 → 低饱和度 + 高亮度
          - 背景（深色面板/彩色装饰）→ 高饱和度 或 低亮度

        策略：
          - 低饱和度 AND 高亮度 → 文字区域（保留）
          - 其他 → 背景区域（压制）

        Args:
            s_channel: HSV 的 S 通道（饱和度）
            v_channel: HSV 的 V 通道（亮度）

        Returns:
            float32 掩码，1.0=文字区域，0.0=背景区域
        """
        # 归一化到 0-1
        s_norm = s_channel.astype(np.float32) / 255.0
        v_norm = v_channel.astype(np.float32) / 255.0

        # 条件1：低饱和度（白色/灰色文字特征）
        low_sat = s_norm < (self.sat_low_thresh / 255.0)

        # 条件2：高亮度（文字通常较亮）
        high_val = v_norm > (self.val_high_thresh / 255.0)

        # 文字区域 = 低饱和度 OR 高亮度（宽松条件，避免漏掉文字）
        text_region = np.logical_or(low_sat, high_val).astype(np.float32)

        # 形态学平滑：去除小噪点，连接相邻文字像素
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        text_region = cv2.dilate(text_region, kernel, iterations=1)
        text_region = cv2.erode(text_region, kernel, iterations=1)

        # 高斯模糊让过渡更自然
        text_region = cv2.GaussianBlur(text_region, (5, 5), 1.0)

        return text_region

    def _suppress_background(self, v_channel: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """
        基于掩码压制背景亮度。

        文字区域保持原样，背景区域压暗。

        Args:
            v_channel: V 通道（亮度）
            mask: 文字区域掩码 (0-1 float)

        Returns:
            处理后的灰度图
        """
        # 将 mask 扩展到与 v_channel 相同维度
        if len(mask.shape) == 2 and mask.dtype != np.float32:
            mask = mask.astype(np.float32)

        # 背景压制：v_new = v * (mask + (1-mask) * suppress_factor)
        # 即：文字区 * 1.0 + 背景区 * suppress_factor
        suppressed = (v_channel.astype(np.float32) *
                     (mask + (1 - mask) * self.suppress_factor))

        # 转回 uint8
        result = np.clip(suppressed, 0, 255).astype(np.uint8)

        return result

    # ---- 辅助方法（复制自 BaseOCR） ----

    @staticmethod
    def _calculate_adaptive_scale(width: int, height: int) -> float:
        TARGET_WIDTH = 2400
        if width >= TARGET_WIDTH:
            return 1.0
        scale = TARGET_WIDTH / width
        return min(scale, 6.0)

    @staticmethod
    def _resize_fast(img: np.ndarray, scale: float) -> np.ndarray:
        h, w = img.shape[:2]
        new_w, new_h = int(w * scale), int(h * scale)
        return cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    @staticmethod
    def _filter_by_color(img: np.ndarray, lower: tuple, upper: tuple) -> np.ndarray:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8))
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
        filtered = cv2.bitwise_and(img, img, mask=mask)
        return cv2.addWeighted(img, 0.7, filtered, 0.3, 0)

    def _save_stage(self, stage: str, img: np.ndarray):
        save_debug_image(stage, img, self.output_dir)

    # ---- 分组拼接核心方法 ----

    def _group_ocr_lines(self, ocr_lines: list) -> list[dict]:
        """
        将 OCR 识别的多行文字按空间位置分组，合并为物品名。

        Warframe 遗物界面特点：
          - 物品横向排列（左→右）
          - 每个物品名可能跨多行（中文名换行）
          - 同一物品的行在 X 轴上对齐（水平位置接近）

        策略：
          1. 计算每行的 X 中心坐标
          2. 用 X 坐标聚类：X 中心接近的行属于同一物品
          3. 组内按 Y 排序，拼接文字
        """
        if not ocr_lines:
            return []
        if len(ocr_lines) == 1:
            text, box, score = ocr_lines[0]
            return [{'merged_text': text, 'lines': ocr_lines, 'box': box}]

        # 1. 计算每行的 X 中心坐标和 Y 坐标
        line_info = []
        for idx, (text, box, score) in enumerate(ocr_lines):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x_center = sum(xs) / len(xs)
            y_top = min(ys)
            x_left = min(xs)
            x_right = max(xs)
            line_info.append({
                'idx': idx,
                'text': text,
                'box': box,
                'score': score,
                'x_center': x_center,
                'y_top': y_top,
                'x_left': x_left,
                'x_right': x_right,
                'width': x_right - x_left,
            })

        # 2. 按 X 中心坐标排序
        line_info.sort(key=lambda l: l['x_center'])

        print(f"\n         [分组调试] 各行 X 坐标 (按X排序后):")
        for li in line_info:
            print(f"             \"{li['text'][:20]}\"  X中心={li['x_center']:.0f}  Y={li['y_top']:.0f}  宽={li['width']:.0f}")

        # 3. 贪心分组：X 中心距离小于阈值的归为一组
        groups = []  # 每组是 [line_info, ...]
        current_group = [line_info[0]]

        # 动态阈值：基于平均宽度来判断是否同一物品
        avg_width = sum(l['width'] for l in line_info) / len(line_info)
        x_threshold = avg_width * 0.6  # 同一物品的行 X 中心差距不超过 60% 平均宽度
        print(f"         [分组调试] avg_width={avg_width:.0f}, x_threshold={x_threshold:.0f}")

        for i in range(1, len(line_info)):
            prev_x = current_group[-1]['x_center']
            curr_x = line_info[i]['x_center']
            dist = abs(curr_x - prev_x)

            # 如果 X 中心距离小于阈值，归入当前组
            if dist < x_threshold:
                current_group.append(line_info[i])
                print(f"             → 合并: \"{line_info[i]['text'][:15]}\" (距前={dist:.0f} < {x_threshold:.0f})")
            else:
                groups.append(current_group)
                current_group = [line_info[i]]
                print(f"             → 新组: \"{line_info[i]['text'][:15]}\" (距前={dist:.0f} >= {x_threshold:.0f})")

        groups.append(current_group)

        # 4. 组内按 Y 排序并拼接文字
        result = []
        for group in groups:
            # 按 Y 从上到下排序
            group.sort(key=lambda l: l['y_top'])

            # 拼接文字
            merged_text = " ".join(l['text'] for l in group)

            # 合并包围盒（取所有行的最小外接矩形）
            all_box_points = [p for l in group for p in l['box']]
            merged_box = [
                [min(p[0] for p in all_box_points), min(p[1] for p in all_box_points)],
                [max(p[0] for p in all_box_points), min(p[1] for p in all_box_points)],
                [max(p[0] for p in all_box_points), max(p[1] for p in all_box_points)],
                [min(p[0] for p in all_box_points), max(p[1] for p in all_box_points)],
            ]

            lines_in_group = [(l['text'], l['box'], l['score']) for l in group]
            result.append({
                'merged_text': merged_text,
                'lines': lines_in_group,
                'box': merged_box,
                'line_count': len(group),
            })

        return result

    def _draw_grouped_result(
        self, original: np.ndarray, ocr_lines: list, grouped_items: list, scale: float
    ) -> np.ndarray:
        """在原图上绘制分组后的 OCR 结果。"""
        vis = original.copy()
        h, w = vis.shape[:2]

        # 每个分组用不同颜色
        group_colors = [
            (0, 255, 0),     # 绿
            (255, 100, 0),   # 蓝
            (0, 180, 255),   # 橙
            (200, 0, 255),   # 紫
            (0, 255, 200),   # 青
            (80, 220, 0),    # 黄绿
            (255, 150, 0),   # 浅蓝
            (180, 0, 200),   # 粉紫
        ]

        for gi, item in enumerate(grouped_items):
            color = group_colors[gi % len(group_colors)]

            # 绘制每个分组的所有原始检测框
            for text, box, score in item['lines']:
                pts = np.array(box, dtype=np.int32)
                cv2.polylines(vis, [pts], True, color, 1, cv2.LINE_AA)

            # 绘制分组外接框
            merged_box = item['box']
            mpts = np.array(merged_box, dtype=np.int32)
            cv2.polylines(vis, [mpts], True, color, 2, cv2.LINE_AA)

            # 在分组框上方标注合并后的完整名称
            label = f"[{gi+1}] {item['merged_text']}"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.55
            thickness = 1

            (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)

            bx = int(merged_box[0][0])
            by = int(merged_box[0][1]) - th - 10
            if by < 5:
                by = int(merged_box[2][1]) + 8

            # 半透明背景
            overlay = vis.copy()
            cv2.rectangle(overlay, (bx-2, by-2), (bx + tw + 4, by + th + baseline + 2),
                         (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.6, vis, 0.4, 0, vis)

            # 文字
            cv2.putText(vis, label, (bx, by + th), font, font_scale, color,
                       thickness, cv2.LINE_AA)

        # 右上角信息面板
        info = f"Items: {len(grouped_items)} | Lines: {len(ocr_lines)}"
        cv2.putText(vis, info, (w-350, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)

        return vis

    # ---- 纠错与数据库匹配 ----

    def _correct_and_match(self, grouped_items: list) -> list[dict]:
        """
        对分组后的 OCR 文本做纠错 + 数据库匹配。

        流程:
          1. 正则清理（常见 OCR 字符错误: PNme→Prime 等）
          2. 从 prime_parts 表加载 zh→en 部件名映射
          3. 中文部件名 → 英文替换
          4. 精确/模糊匹配 market_items.en_name
        """
        import sqlite3

        db_path = PROJECT_ROOT / "data" / "warframe.db"
        conn = None
        if db_path.exists():
            try:
                conn = sqlite3.connect(str(db_path))
            except Exception:
                pass

        # ── 从 prime_parts 表构建 {中文部件名: 英文部件名} 映射 ──
        cn_part_map = self._load_cn_part_map(conn)
        if cn_part_map:
            print(f"         部件映射表 ({len(cn_part_map)} 条):")
            for zh, en in sorted(cn_part_map.items(), key=lambda x: len(x[0])):
                print(f"           {zh} → {en}")

        results = []
        for item in grouped_items:
            raw_text = item['merged_text']
            # Step 1: 字符级正则纠错
            corrected = self._regex_correct(raw_text)
            # Step 2: 中文部件名 → 英文替换（来自 prime_parts 表）
            en_text = self._apply_cn_part_map(corrected, cn_part_map)
            # Step 3: 数据库匹配
            match = self._db_lookup(en_text, raw_text, conn)

            results.append({
                'raw_text': raw_text,
                'corrected_text': en_text,
                **match,
            })

        if conn:
            conn.close()
        return results

    @staticmethod
    def _load_cn_part_map(conn) -> dict[str, str]:
        """从 prime_parts 表加载 {zh部件词: en部件词} 映射。

        策略：每行记录的 en_name/zh_name 中，"Prime" 之后的部分就是部件名，
        按位置一一配对。
        例如：
          en: "Banshee Prime Neuroptics Blueprint"
          zh: "Banshee Prime 头部神经光元 蓝图"
          → Prime 之后: ["Neuroptics","Blueprint"] ↔ ["头部神经光元","蓝图"]
          → {"头部神经光元":"Neuroptics", "蓝图":"Blueprint"}
        """
        if not conn:
            return {}
        try:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT DISTINCT en_name, zh_name FROM prime_parts "
                "WHERE zh_name != '' AND en_name != ''"
            ).fetchall()

            mapping = {}  # {zh_word: en_word}
            for en_name, zh_name in rows:
                # 提取 "Prime" 之后的部件部分
                en_after = PipelineDebugger._after_prime(en_name)
                zh_after = PipelineDebugger._after_prime(zh_name)

                if not en_after or not zh_after:
                    continue

                en_parts = en_after.split()
                zh_parts = zh_after.split()

                # 按位置配对（WF 命名规则保证顺序一致）
                for i, zh_w in enumerate(zh_parts):
                    if not all('\u4e00' <= ch <= '\u9fff' for ch in zh_w):
                        continue  # 跳过非纯汉字（如 "Prime"）
                    if i < len(en_parts):
                        en_w = en_parts[i]
                        # 长的优先（如 "头部神经光元" 优先于 "神经光元"）
                        if zh_w not in mapping or len(zh_w) > len(mapping.get(zh_w, '')):
                            mapping[zh_w] = en_w

            return {k: v for k, v in mapping.items() if v}
        except Exception as e:
            print(f"         [!] 加载部件映射失败: {e}")
            return {}

    @staticmethod
    def _after_prime(name: str) -> str:
        """返回字符串中 'Prime' 之后的部分。"""
        idx = name.find('Prime')
        if idx < 0:
            return ''
        rest = name[idx + len('Prime'):].strip()
        return rest

    @staticmethod
    def _apply_cn_part_map(text: str, cn_part_map: dict[str, str]) -> str:
        """用数据库映射表替换文本中的中文部件名为英文。"""
        if not cn_part_map:
            return text
        t = text
        for cn, en in sorted(cn_part_map.items(), key=lambda x: len(x[0]), reverse=True):
            t = t.replace(cn, f' {en} ')  # 替换时加空格避免粘连
        return re.sub(r'\s{2,}', ' ', t).strip()  # 清理多余空格

    @staticmethod
    def _regex_correct(text: str) -> str:
        """用正则修复常见 OCR 识别错误。"""
        t = text.strip()
        # 只处理字符级 OCR 错误（中文翻译由 _apply_cn_part_map / prime_parts 表接管）
        corrections = [
            # Prime 变体
            (r'PNme', 'Prime'),
            (r'Pnme', 'Prime'),
            (r'Prine', 'Prime'),
            (r'Priime', 'Prime'),
            (r'Prrme', 'Prime'),
            # Blueprint 英文变体
            (r'Bueprint', 'Blueprint'),
            (r'Bluerint', 'Blueprint'),
            (r'Bluepnnt', 'Blueprint'),
            # 中文重复清理（OCR 可能拆行导致 "蓝图 图"）
            (r'蓝图\s*图', '蓝图'),
            (r'蓝\s*图', '蓝图'),
            # Neuroptics / Systems 等英文变体
            (r'Neuroptcs', 'Neuroptics'),
            (r'Neuroptic', 'Neuroptics'),
            (r'Systms', 'Systems'),
            (r'System(?=\s|$)', 'Systems'),
            (r'Chasss', 'Chassis'),
            (r'Chasis', 'Chassis'),
            (r'Recever', 'Receiver'),
            (r'Reciver', 'Receiver'),
            # 字符混淆: I/l/1
            (r'(?<=[A-Za-z])1(?=[a-z])', 'l'),
            (r'(?<=[A-Z])l(?= [A-Z])', 'I'),
            # 多余空格
            (r'\s{2,}', ' '),
        ]
        for pattern, replacement in corrections:
            t = re.sub(pattern, replacement, t, flags=re.IGNORECASE)
        return t.strip()

    def _db_lookup(self, corrected: str, raw_text: str, conn) -> dict:
        """
        在数据库中查找匹配的物品。

        匹配策略:
          1. 精确匹配 en_name (大小写不敏感)
          2. 分词包含匹配 (所有英文单词都在目标中)
          3. 中文包含匹配 (zh_name 或 zh_pinyin 包含关键词)
        """
        if not conn:
            return {'en_name': '?', 'zh_name': '?', 'slug': '?', 'method': 'no_db'}

        cur = conn.cursor()

        # ── 基础诊断: 数据库里有没有这些数据? ──
        test_q = f"%{corrected.split()[0] if corrected else ''}%"
        db_sample = cur.execute(
            "SELECT en_name FROM market_items WHERE LOWER(en_name) LIKE ? LIMIT 2",
            (test_q.lower(),)
        ).fetchall()
        print(f"               [db] 查询 \"{corrected}\" → LIKE '{test_q}' → {len(db_sample)}条")
        if db_sample:
            print(f"                   样本: {[r[0] for r in db_sample]}")

        # 也查一下 market_items 总数和 prime_parts 里有没有
        total = cur.execute("SELECT COUNT(*) FROM market_items").fetchone()[0]
        pp_count = cur.execute("SELECT COUNT(*) FROM prime_parts").fetchone()[0]
        pp_sample = cur.execute(
            "SELECT en_name, zh_name FROM prime_parts WHERE LOWER(en_name) LIKE ? LIMIT 2",
            (f"%{corrected.lower().split()[0] if corrected else ''}%",)
        ).fetchall()
        print(f"               [db] market_items={total}条, prime_parts={pp_count}条")
        if pp_sample:
            print(f"                   prime_parts样本: {[(r[0], r[1]) for r in pp_sample]}")

        # ── 策略1: 精确匹配 en_name ──
        corrected_lower = corrected.lower().strip()
        row = cur.execute(
            "SELECT en_name, zh_name, slug FROM market_items WHERE LOWER(en_name) = ? LIMIT 1",
            (corrected_lower,)
        ).fetchone()
        if row:
            return {'en_name': row[0], 'zh_name': row[1], 'slug': row[2], 'method': 'exact_en'}
        # debug: 查一下有没有近似的
        similar = cur.execute(
            "SELECT en_name FROM market_items WHERE LOWER(en_name) LIKE ? LIMIT 3",
            (f"%{corrected_lower.split()[-1] if corrected_lower else ''}%",)
        ).fetchall()
        if similar:
            print(f"               [db] 近似结果: {[r[0] for r in similar]}")

        # ── 策略2: 分词包含匹配 ──
        words = corrected_lower.split()
        if len(words) >= 2:
            # 至少要有 Prime 或 Blueprint 这类关键标识才走分词匹配
            has_key_word = any(w in ('prime', 'blueprint', 'receiver', 'barrel',
                                     'neuroptics', 'systems', 'chassis',
                                     'blade', 'handle', 'grip', 'stock',
                                     'head', 'guard', 'string')
                               for w in words)
            if has_key_word:
                # 构建 LIKE 条件：每个单词都要出现在 en_name 中
                conditions = " AND ".join(["LOWER(en_name) LIKE ?"] * len(words))
                params = [f"%{w}%" for w in words]
                row = cur.execute(
                    f"SELECT en_name, zh_name, slug FROM market_items WHERE {conditions} LIMIT 5",
                    params
                ).fetchall()
                if len(row) == 1:
                    r = row[0]
                    return {'en_name': r[0], 'zh_name': r[1], 'slug': r[2], 'method': 'word_include'}
                elif len(row) > 1:
                    # 多个结果，选最短的（最精确）
                    best = min(row, key=lambda x: len(x[0]))
                    return {'en_name': best[0], 'zh_name': best[1], 'slug': best[2],
                            'method': f'word_include({len(row)}→1)'}
                else:
                    print(f"               [db] 策略2: 分词{words}无匹配")
        else:
            print(f"               [db] 策略2跳过: 词数={len(words)}, words={words}")

        # ── 策略3: 中文包含匹配 ──
        # 用原始文本中的中文部分去查 zh_name / zh_pinyin
        cn_parts = re.findall(r'[\u4e00-\u9fff]+', raw_text)
        if cn_parts:
            cn_keyword = ''.join(cn_parts)
            for col in ['zh_name', 'zh_pinyin']:
                row = cur.execute(
                    f"SELECT en_name, zh_name, slug FROM market_items WHERE {col} LIKE ? LIMIT 1",
                    (f"%{cn_keyword}%",)
                ).fetchone()
                if row:
                    return {'en_name': row[0], 'zh_name': row[1], 'slug': row[2], 'method': f'cn_{col}'}
            print(f"               [db] 策略3: 中文'{cn_keyword}'在{cn_parts}中无匹配")

        # ── 策略4: 宽松匹配（只保留核心关键词）──
        # 提取核心词: 物品名(去掉部件后缀) + Prime
        core_words = [w for w in words if w not in
                     ('blueprint', 'receiver', 'barrel', 'neuroptics',
                      'systems', 'chassis', 'blade', 'handle', 'grip')]
        if core_words and 'prime' in words:
            conditions = " AND ".join(["LOWER(en_name) LIKE ?"] * len(core_words))
            params = [f"%{w}%" for w in core_words]
            row = cur.execute(
                f"SELECT en_name, zh_name, slug FROM market_items WHERE {conditions} AND LOWER(en_name) LIKE '%prime%' LIMIT 3",
                params
            ).fetchall()
            if row:
                best = min(row, key=lambda x: len(x[0]))
                return {'en_name': best[0], 'zh_name': best[1], 'slug': best[2],
                        'method': 'core_match'}

        # ── 策略5: prime_parts 表兜底（market_items 可能为空）──
        pp_row = cur.execute(
            "SELECT en_name, zh_name, slug FROM prime_parts WHERE LOWER(en_name) = ? LIMIT 1",
            (corrected_lower,)
        ).fetchone()
        if pp_row:
            return {'en_name': pp_row[0], 'zh_name': pp_row[1], 'slug': pp_row[2],
                    'method': 'pp_exact'}
        # prime_parts 模糊匹配
        pp_fuzzy = cur.execute(
            "SELECT en_name, zh_name, slug FROM prime_parts WHERE LOWER(en_name) LIKE ? LIMIT 3",
            (f"%{corrected_lower}%",)
        ).fetchall()
        if len(pp_fuzzy) == 1:
            r = pp_fuzzy[0]
            return {'en_name': r[0], 'zh_name': r[1], 'slug': r[2], 'method': 'pp_fuzzy'}
        elif len(pp_fuzzy) > 1:
            best = min(pp_fuzzy, key=lambda x: len(x[0]))
            return {'en_name': best[0], 'zh_name': best[1], 'slug': best[2],
                    'method': f'pp_fuzzy({len(pp_fuzzy)}→1)'}

        return {'en_name': '?', 'zh_name': '?', 'slug': '?', 'method': 'no_match'}

    def _query_prices(self, matched_items: list[dict]) -> list[dict]:
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
                except Exception as e:
                    print(f"               [price] {item.get('en_name','?')} 查询异常: {e}")
                    result['price'] = None
            else:
                result['price'] = None
            results.append(result)
        return results

    def _draw_final_result(
        self, original: np.ndarray, ocr_lines: list,
        grouped_items: list, matched_items: list, scale: float
    ) -> np.ndarray:
        """在原图上绘制最终结果（分组框 + 纠错后物品名）。"""
        vis = original.copy()
        h, w = vis.shape[:2]

        group_colors = [
            (0, 255, 0), (255, 100, 0), (0, 180, 255),
            (200, 0, 255), (0, 255, 200), (80, 220, 0),
            (255, 150, 0), (180, 0, 200),
        ]

        for gi, (group, match) in enumerate(zip(grouped_items, matched_items)):
            color = group_colors[gi % len(group_colors)]

            # 分组外接框
            merged_box = group['box']
            mpts = np.array(merged_box, dtype=np.int32)
            cv2.polylines(vis, [mpts], True, color, 2, cv2.LINE_AA)

            # 标签：纠错后的精确名称 + 价格
            en = match.get('en_name', '?')
            zh = match.get('zh_name', '?')
            method = match.get('method', '?')
            price_info = match.get('price')

            if en != '?' and zh != '?':
                label = f"[{gi+1}] {en}"
                if price_info:
                    min_p = price_info.get('min_price', 0)
                    label += f"  {min_p}p"
                sub_label = f"      {zh} ({method})"
            else:
                label = f"[{gi+1}] {match['raw_text'][:30]}"
                sub_label = f"      未匹配 ({method})"

            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.55
            thickness = 1

            # 主标签
            (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)
            bx = int(merged_box[0][0])
            by = int(merged_box[0][1]) - th - 22
            if by < 5:
                by = int(merged_box[2][1]) + 8

            overlay = vis.copy()
            cv2.rectangle(overlay, (bx-2, by-2), (bx + tw + 4, by + th + baseline + 2),
                         (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.6, vis, 0.4, 0, vis)
            cv2.putText(vis, label, (bx, by + th), font, font_scale, color, thickness, cv2.LINE_AA)

            # 副标签（中文）
            (stw, sth), sbaseline = cv2.getTextSize(sub_label, font, font_scale - 0.08, thickness)
            sby = by + th + baseline + 4
            overlay2 = vis.copy()
            cv2.rectangle(overlay2, (bx, sby), (bx + stw + 4, sby + sth + sbaseline + 2),
                         (30, 30, 30), -1)
            cv2.addWeighted(overlay2, 0.6, vis, 0.4, 0, vis)
            cv2.putText(vis, sub_label, (bx, sby + sth), font, font_scale - 0.08,
                       (200, 200, 200), thickness, cv2.LINE_AA)

        # 信息面板
        matched_count = sum(1 for m in matched_items if m.get('en_name') != '?')
        priced_count = sum(1 for m in matched_items if m.get('price') is not None)
        info = f"Match: {matched_count}/{len(matched_items)} | Price: {priced_count}/{len(matched_items)} | Items: {len(grouped_items)}"
        cv2.putText(vis, info, (w-450, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)

        return vis

    def _draw_ocr_result(self, original: np.ndarray, ocr_lines: list, scale: float) -> np.ndarray:
        """在原图上绘制 OCR 结果（检测框 + 文字）。"""
        vis = original.copy()
        h, w = vis.shape[:2]

        # 绘制每个检测框
        colors = [
            (0, 255, 0),     # 绿
            (255, 0, 0),     # 蓝
            (0, 165, 255),   # 橙
            (255, 0, 255),   # 紫
            (0, 255, 255),   # 青
        ]

        for i, (text, box, score) in enumerate(ocr_lines):
            color = colors[i % len(colors)]

            # 绘制检测框
            pts = np.array(box, dtype=np.int32)
            cv2.polylines(vis, [pts], True, color, 2)

            # 绘制文字标签（在框上方）
            label = f"{text} ({score})"
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.6
            thickness = 1

            # 计算文字大小
            (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)

            # 文字背景位置（框左上角偏上）
            bx = int(box[0][0])
            by = int(box[0][1]) - th - 8
            if by < 0:
                by = int(box[2][1]) + 8  # 改到框下方

            # 绘制半透明背景
            overlay = vis.copy()
            cv2.rectangle(overlay, (bx, by), (bx + tw, by + th + baseline), (0, 0, 0), -1)
            cv2.addWeighted(overlay, 0.5, vis, 0.5, 0, vis)

            # 绘制文字
            cv2.putText(vis, label, (bx, by + th), font, font_scale, color, thickness, cv2.LINE_AA)

        # 在右上角添加信息面板
        info_text = f"OCR Results: {len(ocr_lines)} lines"
        cv2.putText(vis, info_text, (w-350, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        return vis


# ============================================================
#  主流程
# ============================================================

def debug_single_image(image_path: Path):
    """对单张图片执行完整调试。"""
    print(f"\n{'='*30}")
    print(f"  调试图片: {image_path.name}")
    print(f"{'='*30}\n")

    img = load_image(image_path)
    if img is None:
        print(f"[错误] 无法读取图片: {image_path}")
        return None

    debugger = PipelineDebugger()
    result = debugger.debug_pipeline(img)

    # 保存最终结果图到文件（CMD 环境下不弹窗）
    debugger._save_stage("final_result", result['final_image'])
    print(f"\n[完成] 结果已保存到 debug_output/")
    print(f"       可查看: 03_saturation_suppress.png (饱和度压制效果)")
    print(f"              03b_sat_mask.png (文字区域掩码)")
    print(f"              final_result.png (OCR 检测框标注)\n")

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="OCR 图像处理管线调试工具")
    parser.add_argument('target', nargs='?', default=None,
                        help="图片路径或文件夹路径（默认: test_ocr/）")
    args = parser.parse_args()

    target = Path(args.target) if args.target else TEST_DIR

    if target.is_file():
        # 单张图片
        debug_single_image(target)
    elif target.is_dir():
        # 文件夹：列出所有图片让用户选择
        images = [
            f for f in sorted(target.iterdir())
            if f.suffix.lower() in ('.png', '.jpg', '.jpeg', '.bmp')
        ]
        if not images:
            print(f"文件夹中没有找到图片: {target}")
            return

        print(f"\n找到 {len(images)} 张图片:\n")
        for i, img in enumerate(images, 1):
            print(f"  [{i}] {img.name}")

        while True:
            try:
                choice = input(f"\n选择编号 (1-{len(images)}) / 'a' 全部 / 'q' 退出: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break

            if choice == 'q':
                print("退出")
                break
            elif choice == 'a':
                for img in images:
                    debug_single_image(img)
            else:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(images):
                        debug_single_image(images[idx])
                    else:
                        print(f"无效编号，请输入 1-{len(images)}")
                except ValueError:
                    print("请输入数字编号")
    else:
        print(f"路径不存在: {target}")


if __name__ == "__main__":
    main()
