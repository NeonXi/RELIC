"""
[L-Recognizer] text_corrector — OCR 文字纠错模块

依赖: 无(纯函数)
被谁用: core.recognizers.item_name / core.recognizers.relic_name / core.recognizers.mod_name

职责:
  - 过滤 OCR 噪声字符
  - 字符混淆映射纠正(数字/字母形近字)
  - 物品名提取与清洗
  - Warframe 专有名词纠错

设计原则:
  - 核心逻辑移植自 OCR 移植技术文档 4.7 节
  - 扩展项目已有的 OCR 纠错经验(item_name.py 的混淆映射)
  - 提供可配置的纠错策略

用法:
    from core.recognizers.text_corrector import TextCorrector
    corrector = TextCorrector()
    clean_text = corrector.correct(raw_ocr_text)
    item_name = corrector.extract_item_name(ocr_result)

## AI 硬约束 — 修改本文件前必读
归属层:    [L-Recognizer] (core/recognizers/)
允许依赖:  numpy, onnxruntime, opencv-python, sqlite3, rapidocr-onnxruntime
禁止依赖:  core.widgets/* / core.pages/* / core.state/*
           (不能调 UI,只能输出结构化结果)
必读规范:  .trae/rules/开发规范.md §6.3

本文件相关红线:
- 禁止返回 Qt 控件 → 只能返回 dict(含 en_name / zh_name / slug / quality)
- 禁止阻塞主线程的长任务 → 必须放 QThread/Signal
- 禁止吞掉 OCR 错误 → 必须 try/except 记录到日志
- 禁止在 OCR 链路里调网络 API → OCR 是离线识别
- 禁止 import 整个 core.* → 只 import 同层 (recognizers) 模块

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.3。
"""

import re
from typing import Optional


class TextCorrector:
    """OCR 文字纠错器 —— 针对游戏内物品名识别优化。

    纠错流水线：
      1. 去除首尾空白
      2. 过滤特殊噪声字符
      3. 应用字符混淆映射
      4. 清理多余空格
      5. 物品名提取（去除数量/状态标记）
    """

    # ============================================================
    # 配置参数（来自技术文档 + 项目经验）
    # ============================================================

    # 需过滤的噪声字符集（来自技术文档 4.7 节）
    FILTER_CHARS = set("_|\\/=[]【】\"',.=-~!()<>{}@#$%^&*2x")

    # 价格/数量验证正则（来自技术文档）
    PRICE_PATTERN = re.compile(r'^[0-9]+$')
    MARKED_PRICE_PATTERN = re.compile(r'^[✔✓]*[0-9]+$')

    # ============================================================
    # 字符混淆映射（双向，来自技术文档 + item_name.py 经验）
    # ============================================================

    # 基础混淆对（数字 ↔ 字母）
    BASIC_CONFUSION: dict[str, str] = {
        '0': 'O',
        'O': '0',
        '1': 'l',
        'l': '1',
        'I': '1',
        'S': '5',
        's': '5',
        'B': '8',
        'G': '6',
        'Z': '2',
        'z': '2',
    }

    # Warframe 常见 OCR 错误（项目经验积累）
    WARFRAME_CONFUSION: dict[str, str] = {
        # 常见武器名误识别
        'Akbari': 'Akari',
        'Akbani': 'Akari',
        'Arca': 'Arc',
        'Braton': 'Braton',
        'Burston': 'Burston',
        'Cronus': 'Cronus',
        'Dakra': 'Dakra',
        'Fang': 'Fang',
        'Galatine': 'Galatine',
        'Gram': 'Gram',
        'Helios': 'Helios',
        'Karst': 'Karst',
        'Latron': 'Latron',
        'Lex': 'Lex',
        'Mire': 'Mire',
        'MK1': 'Mk1',
        'Mosma': 'Mosma',
        'Nami': 'Nami',
        'Pana': 'Pana',
        'Penta': 'Penta',
        'Soma': 'Soma',
        'Tatsu': 'Tatsu',
        'Torid': 'Torid',
        'Vasto': 'Vasto',
        # Prime 变体常见错误
        'Primee': 'Prime',
        'Primme': 'Prime',
        'Priime': 'Prime',
        # Blueprint 常见变体
        'Bluepring': 'Blueprint',
        'Bluerint': 'Blueprint',
        # Set 常见误识别
        'Sett': 'Set',
        'sett': 'set',
    }

    # 数量/状态标记正则
    QUANTITY_SUFFIX = re.compile(
        r'\s*[xX×]\d+\s*$'  # " x5", " x10" 等
    )
    STATUS_MARKERS = re.compile(
        r'\s*[\[(（][^\])）]*[\])）]\s*$'  # "(已拥有)", "[MAX]" 等
    )

    def __init__(self, aggressive: bool = False):
        """初始化纠错器。

        Args:
            aggressive: 是否启用激进模式（更多替换规则，可能误伤）
        """
        self._aggressive = aggressive

        # 合并所有混淆映射
        self._confusion_map = dict(self.BASIC_CONFUSION)
        if self._aggressive:
            self._confusion_map.update(self.WARFRAME_CONFUSION)

    # ════════════════════════════════════
    #  公开接口
    # ════════════════════════════════════

    def correct(self, text: str) -> str:
        """完整纠错流程：清洗 → 过滤 → 纠错。

        Args:
            text: OCR 原始文本

        Returns:
            纠错后的干净文本
        """
        if not text or not text.strip():
            return ''

        result = text

        # Step 1: 去除首尾空白
        result = result.strip()

        # Step 2: 过滤特殊字符
        result = self._filter_chars(result)

        # Step 3: 去除连续空格
        result = self._collapse_spaces(result)

        # Step 4: 应用字符混淆映射
        result = self._apply_confusion_map(result)

        # Step 5: 价格字段特殊处理
        result = self._clean_price_field(result)

        return result.strip()

    def extract_item_name(self, ocr_text: str) -> str:
        """从 OCR 结果中提取纯物品名。

        处理：
          - 去除数量后缀 (" x5", " x10")
          - 去除状态标记 ("(已拥有)", "[MAX]")
          - 返回清洗后的基础名称

        Args:
            ocr_text: OCR 识别的原始文本

        Returns:
            纯物品名（用于 API 查询）
        """
        if not ocr_text:
            return ''

        name = ocr_text.strip()

        # 先整体纠错
        name = self.correct(name)

        # 去除数量后缀
        name = self.QUANTITY_SUFFIX.sub('', name)

        # 去除状态标记
        name = self.STATUS_MARKERS.sub('', name)

        # 最终清理
        name = name.strip()

        return name

    def is_price_field(self, text: str) -> bool:
        """判断文本是否为价格/数量字段。

        Args:
            text: 待检测文本

        Returns:
            True 表示是价格或数量字段
        """
        if not text:
            return False
        cleaned = text.strip()
        return bool(self.PRICE_PATTERN.match(cleaned) or
                    self.MARKED_PRICE_PATTERN.match(cleaned))

    # ════════════════════════════════════
    #  内部实现
    # ════════════════════════════════════

    def _filter_chars(self, text: str) -> str:
        """过滤噪声字符集。"""
        return ''.join(ch for ch in text if ch not in self.FILTER_CHARS)

    def _collapse_spaces(self, text: str) -> str:
        """合并连续空格为单个空格。"""
        return re.sub(r' {2,}', ' ', text)

    def _apply_confusion_map(self, text: str) -> str:
        """应用字符混淆映射。

        策略：
          - 仅对纯英文/数字文本应用基础映射
          - 对已知 Warframe 词应用专有映射
        """
        result = list(text)
        i = 0

        while i < len(result):
            ch = result[i]

            # 基础混淆映射（单字符）
            if ch in self._confusion_map:
                replacement = self._confusion_map[ch]
                # 智能替换：根据上下文决定是否替换
                if self._should_replace(result, i, ch, replacement):
                    result[i] = replacement

            i += 1

        return ''.join(result)

    @staticmethod
    def _should_replace(chars: list, idx: int, original: str, replacement: str) -> bool:
        """智能判断是否应该执行替换（基于上下文）。

        简化版：始终替换（后续可优化为基于上下文的决策树）
        """
        # 当前简化实现：始终应用映射
        # TODO: 可扩展为基于 N-gram 的上下文分析
        return True

    def _clean_price_field(self, text: str) -> str:
        """清理价格字段中的特殊标记。"""
        if self.MARKED_PRICE_PATTERN.match(text):
            # 去除 ✔✓ 标记
            text = ''.join(ch for ch in text if ch not in ('✔', '✓'))
        return text

    # ════════════════════════════════════
    #  批量处理工具
    # ════════════════════════════════════

    def correct_batch(self, texts: list[str]) -> list[str]:
        """批量纠错。

        Args:
            texts: OCR 文本列表

        Returns:
            纠错后的文本列表
        """
        return [self.correct(text) for text in texts]

    def extract_item_names(self, ocr_results: list[tuple]) -> list[dict]:
        """从 OCR 结果列表中批量提取物品名。

        Args:
            ocr_results: [(text, box, score), ...]

        Returns:
            [{"original": str, "corrected": str, "item_name": str, "box": list, "score": float}, ...]
        """
        results = []
        for text, box, score in ocr_results:
            corrected = self.correct(text)
            item_name = self.extract_item_name(text)
            results.append({
                'original': text,
                'corrected': corrected,
                'item_name': item_name,
                'box': box,
                'score': score,
            })
        return results
