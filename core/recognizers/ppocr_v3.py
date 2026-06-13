"""
PP-OCRv3 ONNX 识别器（严格移植自 RapidOCR 开源实现）

技术栈：ONNX Runtime + OpenCV + pyclipper
完全对齐 rapidocr-onnxruntime 的 DB 后处理和 CTC 解码算法。

用法:
    from core.recognizers.ppocr_v3 import PPOCRv3Recognizer
    ocr = PPOCRv3Recognizer()
    results = ocr.recognize(image)  # 返回 [(text, box, score), ...]
"""

import os
import time
import numpy as np
import cv2
import pyclipper
from shapely.geometry import Polygon


class PPOCRv3Recognizer:
    """PP-OCRv3 ONNX 识别器 —— 严格对齐 RapidOCR 源码。"""

    # ============================================================
    # 模型路径
    # ============================================================

    MODELS_DIR = os.path.join(
        os.path.dirname(__file__), '..', '..', 'WarframeMonitor_v1.0', 'models'
    )

    DET_MODEL_PATH = os.path.join(MODELS_DIR, 'ch_PP-OCRv3_det_infer.onnx')
    CLS_MODEL_PATH = os.path.join(MODELS_DIR, 'ch_ppocr_mobile_v2.0_cls_infer.onnx')
    REC_MODEL_PATH = os.path.join(MODELS_DIR, 'ch_PP-OCRv3_rec_infer.onnx')
    KEYS_PATH = os.path.join(MODELS_DIR, 'ppocr_keys_v1.txt')

    # ============================================================
    # 参数（与 RapidOCR 默认值一致）
    # ============================================================

    # DB 检测后处理
    DET_THRESH = 0.3
    BOX_THRESH = 0.5           # RapidOCR 默认 0.7，降低以保留更多候选
    MAX_CANDIDATES = 1000
    UNCLIP_RATIO = 1.6         # RapidOCR 默认值
    MIN_SIZE = 3               # 最小边长过滤

    # CRNN 识别
    REC_IMAGE_HEIGHT = 48
    REC_IMAGE_MAX_WIDTH = 320

    def __init__(self):
        """初始化 ONNX Runtime 会话和字符字典。"""
        import onnxruntime as ort

        print("[PPOCRv3] 正在加载模型...", flush=True)
        t_start = time.perf_counter()

        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = 1
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        # 1. DB-Net 检测模型
        if not os.path.exists(self.DET_MODEL_PATH):
            raise FileNotFoundError(f"检测模型未找到: {self.DET_MODEL_PATH}")
        self._det_session = ort.InferenceSession(
            self.DET_MODEL_PATH, sess_options,
            providers=['CPUExecutionProvider']
        )
        print("[PPOCRv3] ✓ DB-Net 检测模型", flush=True)

        # 2. AngleNet 方向分类模型
        if not os.path.exists(self.CLS_MODEL_PATH):
            raise FileNotFoundError(f"分类模型未找到: {self.CLS_MODEL_PATH}")
        self._cls_session = ort.InferenceSession(
            self.CLS_MODEL_PATH, sess_options,
            providers=['CPUExecutionProvider']
        )
        print("[PPOCRv3] ✓ AngleNet 方向分类模型", flush=True)

        # 3. CRNN 识别模型
        if not os.path.exists(self.REC_MODEL_PATH):
            raise FileNotFoundError(f"识别模型未找到: {self.REC_MODEL_PATH}")
        self._rec_session = ort.InferenceSession(
            self.REC_MODEL_PATH, sess_options,
            providers=['CPUExecutionProvider']
        )
        print("[PPOCRv3] ✓ CRNN 识别模型", flush=True)

        # 4. 字符字典（★ 与 RapidOCR 一致：插入 blank[0] + space[末尾]）
        self._char_dict = self._load_keys_file()

        elapsed = time.perf_counter() - t_start
        print(f"[PPOCRv3] === 初始化完成 ({elapsed:.2f}s) ===", flush=True)

    # ════════════════════════════════════
    #  字典加载（与 RapidOCR CTCLabelDecode 一致）
    # ════════════════════════════════════

    def _load_keys_file(self) -> list[str]:
        """读取字典文件，并按 RapidOCR 方式插入特殊字符。

        最终字典结构: ['blank', <原文件内容>, ' '] → 总数 = 原文件行数 + 2
        这与 CRNN 模型输出的 6625 类完全对应。
        """
        if not os.path.exists(self.KEYS_PATH):
            raise FileNotFoundError(f"字典未找到: {self.KEYS_PATH}")

        char_list = []
        with open(self.KEYS_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                ch = line.rstrip('\n\r')
                if ch:
                    char_list.append(ch)

        # ★ 与 RapidOCR CTCLabelDecode.get_character 一致：
        #   在末尾插入空格
        char_list.insert(len(char_list), ' ')
        #   在索引 0 插入 blank（CTC blank token）
        char_list.insert(0, 'blank')

        print(f"[PPOCRv3] 字典: 总数={len(char_list)} | "
              f"索引[0]={repr(char_list[0])} | "
              f"索引[1]={repr(char_list[1])} | "
              f"索引[-1]={repr(char_list[-1])}", flush=True)

        return char_list

    # ════════════════════════════════════
    #  图像预处理（与 RapidOCR DetPreProcess 一致）
    # ════════════════════════════════════

    @staticmethod
    def _det_preprocess(image: np.ndarray, limit_side_len: int = 960) -> np.ndarray:
        """DB 检测预处理：动态缩放到 limit_side_len，归一化，CHW。

        与 RapidOCR DetPreProcess 完全一致。
        """
        h, w = image.shape[:2]

        # 动态缩放（limit_type = max）
        ratio = 1.0
        if max(h, w) > limit_side_len:
            if h > w:
                ratio = float(limit_side_len) / h
            else:
                ratio = float(limit_side_len) / w

        resize_h = int(h * ratio)
        resize_w = int(w * ratio)
        # 取整到 32 的倍数
        resize_h = int(round(resize_h / 32)) * 32
        resize_w = int(round(resize_w / 32)) * 32

        resized = cv2.resize(image, (resize_w, resize_h))

        # 归一化: (img/255 - mean) / std  — 与 RapidOCR 一致
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        normalized = (resized.astype(np.float32) / 255.0 - mean) / std

        # HWC → CHW → add batch
        chw = normalized.transpose(2, 0, 1)
        return np.expand_dims(chw, axis=0).astype(np.float32)

    @staticmethod
    def _rec_preprocess(text_region: np.ndarray) -> np.ndarray:
        """CRNN 识别预处理：固定高度 48，宽度按比例。

        使用 mean=[0.5,0.5,0.5], std=[0.5,0.5,0.5]（与 RapidOCR 一致）。
        """
        h, w = text_region.shape[:2]
        ratio = 48.0 / h
        target_w = min(int(w * ratio), 320)
        target_w = max(target_w, 16)

        resized = cv2.resize(text_region, (target_w, 48))

        mean = np.array([0.5, 0.5, 0.5], dtype=np.float32)
        std = np.array([0.5, 0.5, 0.5], dtype=np.float32)
        normalized = (resized.astype(np.float32) / 255.0 - mean) / std

        chw = normalized.transpose(2, 0, 1)
        return np.expand_dims(chw, axis=0).astype(np.float32)

    # ════════════════════════════════════
    #  DB 后处理（与 RapidOCR DBPostProcess 完全一致）
    # ════════════════════════════════════

    def _db_postprocess(self, pred: np.ndarray, ori_shape: tuple) -> list[dict]:
        """DB 可微分二值化后处理。

        完全移植自 RapidOCR 的 DBPostProcess 类，
        使用 pyclipper 做多边形膨胀（关键差异点）。
        """
        src_h, src_w = ori_shape
        pred = pred[:, 0, :, :]          # (1, 1, H, W) → (1, H, W)
        segmentation = pred > self.DET_THRESH
        mask = segmentation[0].astype(np.uint8)

        height, width = mask.shape

        # 查找轮廓
        contours, _ = cv2.findContours(
            mask * 255, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE
        )

        num_contours = min(len(contours), self.MAX_CANDIDATES)

        boxes = []
        for index in range(num_contours):
            contour = contours[index]
            points, sside = self._get_mini_boxes(contour)
            if sside < self.MIN_SIZE:
                continue

            # ★ 快速评分模式（与 RapidOCR 一致）
            score = self._box_score_fast(pred[0], points.reshape(-1, 2))
            if self.BOX_THRESH > score:
                continue

            # ★ 用 pyclipper 膨胀（关键！与 RapidOCR 一致）
            box = self._unclip(points)
            if box is None or len(box) == 0:
                continue
            box, sside = self._get_mini_boxes(box)
            if sside < self.MIN_SIZE + 2:
                continue

            # 缩放回原图坐标
            box[:, 0] = np.clip(
                np.round(box[:, 0] / width * src_w), 0, src_w
            ).astype(np.int32)
            box[:, 1] = np.clip(
                np.round(box[:, 1] / height * src_h), 0, src_h
            ).astype(np.int32)

            boxes.append({
                'box': box.tolist(),
                'score': float(score),
            })

        # 按 y 坐标排序
        boxes.sort(key=lambda b: min(p[1] for p in b['box']))
        return boxes

    @staticmethod
    def _get_mini_boxes(contour: np.ndarray) -> tuple:
        """获取最小外接矩形，返回有序的 4 个顶点和最短边长。

        与 RapidOCR DBPostProcess.get_mini_boxes 完全一致。
        """
        bounding_box = cv2.minAreaRect(contour)
        points = sorted(list(cv2.boxPoints(bounding_box)), key=lambda x: x[0])

        index_1, index_2, index_3, index_4 = 0, 1, 2, 3
        if points[1][1] > points[0][1]:
            index_1, index_4 = 0, 1
        else:
            index_1, index_4 = 1, 0

        if points[3][1] > points[2][1]:
            index_2, index_3 = 2, 3
        else:
            index_2, index_3 = 3, 2

        box = np.array([
            points[index_1], points[index_2],
            points[index_3], points[index_4]
        ])
        return box, min(bounding_box[1])

    @staticmethod
    def _box_score_fast(bitmap: np.ndarray, box: np.ndarray) -> float:
        """快速框评分：计算框内概率均值。

        与 RapidOCR DBPostProcess.box_score_fast 完全一致。
        """
        h, w = bitmap.shape[:2]
        box = box.copy()
        xmin = np.clip(np.floor(box[:, 0].min()).astype(np.int32), 0, w - 1)
        xmax = np.clip(np.ceil(box[:, 0].max()).astype(np.int32), 0, w - 1)
        ymin = np.clip(np.floor(box[:, 1].min()).astype(np.int32), 0, h - 1)
        ymax = np.clip(np.ceil(box[:, 1].max()).astype(np.int32), 0, h - 1)

        mask = np.zeros((ymax - ymin + 1, xmax - xmin + 1), dtype=np.uint8)
        box[:, 0] = box[:, 0] - xmin
        box[:, 1] = box[:, 1] - ymin
        cv2.fillPoly(mask, box.reshape(1, -1, 2).astype(np.int32), 1)
        return cv2.mean(bitmap[ymin:ymax + 1, xmin:xmax + 1], mask)[0]

    def _unclip(self, box: np.ndarray) -> np.ndarray | None:
        """用 pyclipper 做多边形膨胀。

        与 RapidOCR DBPostProcess.unclip 完全一致。
        这是之前手动实现出错的关键所在！
        """
        try:
            poly = Polygon(box)
            if poly.length == 0:
                return None
            distance = poly.area * self.UNCLIP_RATIO / poly.length
            offset = pyclipper.PyclipperOffset()
            offset.AddPath(box, pyclipper.JT_ROUND, pyclipper.ET_CLOSEDPOLYGON)
            expanded = offset.Execute(distance)
            if not expanded:
                return None
            return np.array(expanded).reshape((-1, 1, 2))
        except Exception:
            return None

    # ════════════════════════════════════
    #  AngleNet 方向分类
    # ════════════════════════════════════

    def _classify_angle(self, text_region: np.ndarray) -> bool:
        """判断文字是否需要旋转 180°。"""
        input_tensor = self._rec_preprocess(text_region)
        output = self._cls_session.run(None, {'x': input_tensor})
        probs = output[0][0]
        return int(probs[1] > probs[0]) == 1

    # ════════════════════════════════════
    #  CRNN 识别 + CTC 解码（与 RapidOCR CTCLabelDecode 一致）
    # ════════════════════════════════════

    def _recognize_text(self, text_region: np.ndarray) -> tuple[str, float]:
        """CRNN 文字识别：返回 (文本, 平均置信度)。"""
        # Step 1: 方向分类 & 修正
        if self._classify_angle(text_region):
            text_region = cv2.rotate(text_region, cv2.ROTATE_180)

        # Step 2: 预处理
        input_tensor = self._rec_preprocess(text_region)

        # Step 3: ONNX 推理
        output = self._rec_session.run(None, {'x': input_tensor})
        preds = output[0]  # 原始输出

        # Step 4: 标准化形状 → (batch, T, C)
        if len(preds.shape) == 3:
            if preds.shape[0] == 1 and preds.shape[1] > 1:
                pass  # 已经是 (1, T, C)
            elif preds.shape[1] == 1:
                preds = preds[:, 0, :]  # (T, 1, C) → (T, C)
                preds = np.expand_dims(preds, axis=0)  # → (1, T, C)

        # Step 5: CTC 解码（与 RapidOCR CTCLabelDecode.decode 一致）
        text, score = self._ctc_decode(preds)
        return text, score

    def _ctc_decode(self, preds: np.ndarray) -> tuple[str, float]:
        """CTC 贪心解码。

        与 RapidOCR CTCLabelDecode.decode 完全一致：
        - argmax 取索引
        - 去重（连续相同索引只保留第一个）
        - 去除 blank（索引 0）
        """
        # preds shape: (1, T, C) 或 (T, C)
        if len(preds.shape) == 3:
            preds_idx = preds.argmax(axis=2)[0]      # (T,)
            preds_prob = preds.max(axis=2)[0]         # (T,)
        else:
            preds_idx = preds.argmax(axis=1)           # (T,)
            preds_prob = preds.max(axis=1)             # (T,)

        # ★ 去重：连续相同索引只保留第一个（与 RapidOCR 一致）
        selection = np.ones(len(preds_idx), dtype=bool)
        if len(preds_idx) > 1:
            selection[1:] = preds_idx[1:] != preds_idx[:-1]

        # ★ 去除 blank（索引 0）（与 RapidOCR get_ignored_tokens 一致）
        selection &= preds_idx != 0

        # 提取有效字符
        valid_indices = preds_idx[selection]
        valid_probs = preds_prob[selection]

        if len(valid_indices) == 0:
            return '', 0.0

        # 映射到字符
        char_list = []
        for idx in valid_indices:
            idx_int = int(idx)
            if 0 <= idx_int < len(self._char_dict):
                char_list.append(self._char_dict[idx_int])
            else:
                char_list.append('?')

        text = ''.join(char_list)
        avg_score = float(np.mean(valid_probs)) if len(valid_probs) > 0 else 0.0
        return text, avg_score

    # ════════════════════════════════════
    #  公开接口
    # ════════════════════════════════════

    def recognize(
        self,
        image: np.ndarray,
        filter_region: tuple[int, int, int, int] | None = None,
    ) -> list[tuple[str, list, float]]:
        """完整 OCR 流程：检测 → 分类 → 识别。"""
        t_total = time.perf_counter()

        # BGRA/BGR → RGB
        if len(image.shape) == 3 and image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2RGB)
        elif len(image.shape) == 3 and image.shape[2] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # Step 1: DB-Net 文字检测
        input_tensor = self._det_preprocess(image)
        outputs = self._det_session.run(None, {'x': input_tensor})
        pred = outputs[0]  # ONNX 返回 list，取第一个输出
        boxes = self._db_postprocess(pred, image.shape[:2])

        print(f"[PPOCRv3] 检测到 {len(boxes)} 个区域", flush=True)

        # Step 2: 逐区域 AngleNet + CRNN 识别
        results = []
        for i, box_info in enumerate(boxes):
            orig_box = box_info['box']
            box_pts = np.array(orig_box, dtype=np.int32)
            x, y, w, h = cv2.boundingRect(box_pts)

            padding = 4
            x = max(0, x - padding)
            y = max(0, y - padding)
            region = image[y:y+h+2*padding, x:x+w+2*padding]

            if region.size == 0 or region.shape[0] < 8 or region.shape[1] < 8:
                continue

            try:
                text, score = self._recognize_text(region)
                if text.strip():
                    results.append((text.strip(), orig_box, score))
                    print(f"  [{i}] \"{text.strip()}\" (score={score:.3f})", flush=True)
            except Exception as e:
                continue

        total_ms = (time.perf_counter() - t_total) * 1000

        # Step 3: ★ 垂直分组合并 —— 同一物品的多行文字拼在一起
        results = self._merge_vertical_groups(results)

        print(f"[PPOCRv3] 完成: {len(results)} 条 | {total_ms:.0f}ms", flush=True)
        return results

    @staticmethod
    def _merge_vertical_groups(
        results: list[tuple[str, list, float]],
        y_gap_threshold: float = 50.0,
    ) -> list[tuple[str, list, float]]:
        """将垂直距离近的文本框合并为同一物品。

        Warframe 物品名通常跨 1-2 行显示（如 "Ash Prime" + "神经光元 蓝图"），
        DB 检测器会把每行当成独立框。此函数按 Y 坐标分组合并。

        Args:
            results: [(text, [[x,y],...], score), ...]
            y_gap_threshold: 同组框中心 Y 距离阈值（像素）

        Returns:
            合并后的结果列表
        """
        if len(results) <= 1:
            return results

        # 计算每个框的中心点
        annotated = []
        for text, box, score in results:
            cx = sum(p[0] for p in box) / len(box)
            cy = sum(p[1] for p in box) / len(box)
            annotated.append((text, box, score, cx, cy))

        # 按 Y 坐标排序（从上到下）
        annotated.sort(key=lambda r: r[4])

        # 分组：Y 距离小于阈值的归为同组
        groups = []
        current_group = [annotated[0]]
        for i in range(1, len(annotated)):
            prev_cy = current_group[-1][4]
            curr_cy = annotated[i][4]
            if curr_cy - prev_cy < y_gap_threshold:
                current_group.append(annotated[i])
            else:
                groups.append(current_group)
                current_group = [annotated[i]]
        groups.append(current_group)

        # 合并每组：按 X 排序 → 拼接文字 → 合并框
        merged = []
        for group in groups:
            if len(group) == 1:
                text, box, score, _, _ = group[0]
                merged.append((text, box, score))
                continue

            # 组内按 X 排序（从左到右）
            group.sort(key=lambda r: r[3])

            # 拼接文字（空格分隔）
            combined_text = ' '.join(r[0] for r in group)

            # 合并边界框（取所有点的外接矩形）
            all_points = []
            combined_score = 0.0
            for r in group:
                all_points.extend(r[1])
                combined_score += r[2]
            combined_score /= len(group)

            xs = [p[0] for p in all_points]
            ys = [p[1] for p in all_points]
            merged_box = [
                [min(xs), min(ys)],
                [max(xs), min(ys)],
                [max(xs), max(ys)],
                [min(xs), max(ys)],
            ]
            merged.append((combined_text, merged_box, combined_score))

        return merged

    def get_timing(self) -> dict:
        """返回各阶段耗时。"""
        return {}
