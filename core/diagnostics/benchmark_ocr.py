"""
OCR & 匹配准确率 Benchmark 工具

用法:
    1. 把截图放到 test_ocr/ 文件夹
    2. 文件名 = 正确答案 (如 "Ash Prime Neuroptics Blueprint.png")
    3. 运行: python core/diagnostics/benchmark_ocr.py

输出:
    - 控制台: 详细报告
    - benchmark_report.txt: 保存报告到文件

示例文件命名:
    Ash Prime Neuroptics Blueprint.png
    Latron Prime Receiver.png
    Forma Blueprint.png
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2
import numpy as np


# ============================================================
#  配置
# ============================================================

TEST_DIR = PROJECT_ROOT / "test_ocr"
REPORT_FILE = PROJECT_ROOT / "benchmark_report.txt"

# 支持的图片格式
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp'}


# ============================================================
#  核心测试逻辑
# ============================================================

def load_test_images() -> list[tuple[str, Path]]:
    """
    加载测试图片，返回 [(ground_truth, image_path), ...]

    ground_truth = 文件名（去掉扩展名）
    """
    if not TEST_DIR.exists():
        print(f"错误: 测试文件夹不存在: {TEST_DIR}")
        print(f"请创建该文件夹并放入截图（文件名 = 正确答案）")
        return []

    images = []
    for f in sorted(TEST_DIR.iterdir()):
        if f.suffix.lower() in IMAGE_EXTENSIONS:
            # 文件名作为正确答案（如 "Ash Prime Neuroptics Blueprint.png" → "Ash Prime Neuroptics Blueprint"）
            ground_truth = f.stem
            images.append((ground_truth, f))

    return images


def run_ocr_and_match(image_path: Path) -> dict:
    """
    对单张图片运行完整 OCR + 匹配流程。

    Returns:
        {
            'ocr_texts': [str],           # OCR 原始识别文本列表
            'matched_items': [dict],      # 匹配后的物品列表
            'timing_ms': float,           # 耗时（毫秒）
            'error': str | None,          # 错误信息
        }
    """
    result = {
        'ocr_texts': [],
        'matched_items': [],
        'timing_ms': 0,
        'error': None,
    }

    t_start = time.perf_counter()

    try:
        # 1. 读取图片（兼容中文路径）
        # cv2.imread 不支持中文路径，改用 np.fromfile + imdecode
        img_data = np.fromfile(str(image_path), dtype=np.uint8)
        img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
        if img is None:
            result['error'] = f"无法读取图片: {image_path}"
            return result

        # 2. OCR 识别
        from core.recognizers.item_name import ItemNameRecognizer
        recognizer = ItemNameRecognizer()
        ocr_results = recognizer.recognize_all_with_boxes(img)

        # ocr_results 格式: [(english_name, box, [variants]), ...]
        result['ocr_texts'] = [r[0] for r in ocr_results] if ocr_results else []

        # 3. 物品匹配
        if ocr_results:
            from core.recognizers.matcher import match_items
            matched = match_items(ocr_results)
            result['matched_items'] = matched

    except Exception as e:
        result['error'] = f"{type(e).__name__}: {e}"
        import traceback
        traceback.print_exc()

    result['timing_ms'] = (time.perf_counter() - t_start) * 1000
    return result


def compare_result(ground_truth: str, ocr_texts: list, matched_items: list) -> dict:
    """
    对比识别结果与正确答案。

    Returns:
        {
            'ocr_correct': bool,          # OCR 输出是否包含正确答案
            'match_correct': bool,        # 匹配是否成功找到正确物品
            'ocr_best_match': str,        # 最接近的 OCR 结果
            'match_best': str | None,     # 最佳匹配结果
            'error_type': str | None,     # 错误类型分类
        }
    """
    gt_lower = ground_truth.lower()

    # 检查 OCR 是否识别出了正确答案（或非常接近）
    ocr_correct = False
    ocr_best = None
    best_ocr_sim = 0

    for text in ocr_texts:
        text_lower = text.lower()
        similarity = calculate_similarity(gt_lower, text_lower)
        if similarity > best_ocr_sim:
            best_ocr_sim = similarity
            ocr_best = text
        if gt_lower == text_lower or text_lower in gt_lower or gt_lower in text_lower:
            ocr_correct = True

    # 检查匹配是否正确
    match_correct = False
    match_best = None
    best_match_sim = 0

    for item in matched_items:
        en_name = item.get('en_name', '')
        en_lower = en_name.lower()
        similarity = calculate_similarity(gt_lower, en_lower)
        if similarity > best_match_sim:
            best_match_sim = similarity
            match_best = en_name
        if gt_lower == en_lower:
            match_correct = True

    # 分类错误类型
    error_type = classify_error(ground_truth, ocr_texts, matched_items, ocr_correct, match_correct)

    return {
        'ocr_correct': ocr_correct,
        'match_correct': match_correct,
        'ocr_best_match': ocr_best,
        'match_best': match_best,
        'error_type': error_type,
        'best_ocr_similarity': best_ocr_sim,
        'best_match_similarity': best_match_sim,
    }


def calculate_similarity(s1: str, s2: str) -> float:
    """
    计算两个字符串的相似度 (0-1)。

    使用简单的单词覆盖 + 编辑距离混合策略。
    """
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    # 完全包含
    if s1 in s2 or s2 in s1:
        return 0.9

    # 单词级别比较
    words1 = set(s1.split())
    words2 = set(s2.split())
    if words1 and words2:
        intersection = words1 & words2
        union = words1 | words2
        word_score = len(intersection) / len(union)

        # 编辑距离惩罚
        edit_dist = levenshtein(s1, s2)
        max_len = max(len(s1), len(s2))
        edit_score = 1 - (edit_dist / max_len)

        return (word_score * 0.6 + edit_score * 0.4)

    return 0.0


def levenshtein(s1: str, s2: str) -> int:
    """计算编辑距离。"""
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (0 if c1 == c2 else 1)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def classify_error(
    ground_truth: str,
    ocr_texts: list,
    matched_items: list,
    ocr_correct: bool,
    match_correct: bool
) -> str | None:
    """
    分类错误类型。

    Returns:
        错误类型字符串或 None（如果完全正确）
    """
    if match_correct:
        return None  # 完全正确

    gt_lower = ground_truth.lower()

    if not ocr_texts:
        return "ocr_empty"  # OCR 完全没有输出

    # 检查字符混淆
    common_confusions = [('i', 'l'), ('l', '1'), ('0', 'o'), ('s', '5')]
    has_confusion = False
    for ocr_text in ocr_texts:
        ocr_lower = ocr_text.lower()
        for a, b in common_confusions:
            if a in ocr_lower and b in gt_lower:
                has_confusion = True
                break
            if b in ocr_lower and a in gt_lower:
                has_confusion = True
                break

    # 检查漏字
    missing_words = []
    gt_words = set(gt_lower.split())
    for ocr_text in ocr_texts:
        ocr_words = set(ocr_text.lower().split())
        missing = gt_words - ocr_words
        if missing:
            missing_words.extend(missing)

    if has_confusion and missing_words:
        return "confusion+missing"
    elif has_confusion:
        return "char_confusion"
    elif missing_words:
        return "missing_words"

    # 检查多字/粘连
    for ocr_text in ocr_texts:
        if len(ocr_text.replace(' ', '')) > len(ground_truth.replace(' ', '')) * 1.3:
            return "extra_chars"

    # 默认：其他类型错误
    return "other_error"


# ============================================================
#  报告生成
# ============================================================

def generate_report(results: list[dict]) -> str:
    """生成格式化的测试报告。"""
    total = len(results)
    if total == 0:
        return "没有测试样本"

    # 统计
    ocr_correct_count = sum(1 for r in results if r['comparison']['ocr_correct'])
    match_correct_count = sum(1 for r in results if r['comparison']['match_correct'])

    # 错误类型统计
    error_types = {}
    for r in results:
        et = r['comparison']['error_type']
        if et:
            error_types[et] = error_types.get(et, 0) + 1

    # 耗时统计
    timings = [r['result']['timing_ms'] for r in results]
    avg_time = sum(timings) / len(timings) if timings else 0
    max_time = max(timings) if timings else 0
    min_time = min(timings) if timings else 0

    lines = []
    lines.append("=" * 60)
    lines.append("  OCR & 匹配准确率 Benchmark 报告")
    lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"测试样本数: {total} 张")
    lines.append("")

    # 总体指标
    lines.append("-" * 60)
    lines.append("【总体准确率】")
    lines.append("-" * 60)
    ocr_rate = ocr_correct_count / total * 100
    match_rate = match_correct_count / total * 100
    lines.append(f"OCR 准确率: {ocr_correct_count}/{total} ({ocr_rate:.1f}%)")
    lines.append(f"匹配成功率: {match_correct_count}/{total} ({match_rate:.1f}%)")
    lines.append("")

    # 性能
    lines.append("-" * 60)
    lines.append("【性能指标】")
    lines.append("-" * 60)
    lines.append(f"平均耗时: {avg_time:.0f}ms")
    lines.append(f"最快: {min_time:.0f}ms | 最慢: {max_time:.0f}ms")
    lines.append("")

    # 错误分布
    if error_types:
        lines.append("-" * 60)
        lines.append("【错误类型分布】")
        lines.append("-" * 60)
        sorted_errors = sorted(error_types.items(), key=lambda x: x[1], reverse=True)
        for et, count in sorted_errors:
            bar = "█" * count + "░" * (total - count)
            label = ERROR_TYPE_LABELS.get(et, et)
            lines.append(f"  {label:20s} {count:2d} 次  {bar}  ({count/total*100:.1f}%)")
        lines.append("")

    # 详细结果
    lines.append("-" * 60)
    lines.append("【详细结果】")
    lines.append("-" * 60)

    for i, r in enumerate(results, 1):
        gt = r['ground_truth']
        comp = r['comparison']

        status = "✓" if comp['match_correct'] else "✗"
        lines.append(f"\n[{i:2d}] {status} {gt}")

        # OCR 输出
        ocr_str = ", ".join(r['result']['ocr_texts']) if r['result']['ocr_texts'] else "(空)"
        lines.append(f"    OCR: {ocr_str}")

        # 匹配结果
        if comp['match_best']:
            lines.append(f"    匹配: {comp['match_best']}")

        # 错误信息
        if comp['error_type']:
            label = ERROR_TYPE_LABELS.get(comp['error_type'], comp['error_type'])
            lines.append(f"    错误: {label}")

        # 异常
        if r['result']['error']:
            lines.append(f"    异常: {r['result']['error']}")

        # 耗时
        lines.append(f"    耗时: {r['result']['timing_ms']:.0f}ms")

    lines.append("")
    lines.append("=" * 60)
    lines.append("结论与建议")
    lines.append("=" * 60)

    if ocr_rate >= 80:
        lines.append("✓ OCR 阶段表现良好")
    elif ocr_rate >= 60:
        lines.append("△ OCR 阶段有改进空间")
    else:
        lines.append("✗ OCR 阶段是主要瓶颈，需要重点优化")

    if match_rate >= 80:
        lines.append("✓ 匹配阶段表现良好")
    elif match_rate >= 60:
        lines.append("△ 匹配有改进空间")
    else:
        lines.append("✗ 匹配阶段是主要瓶颈，需要重点优化")

    # 主要问题建议
    if error_types:
        top_error = max(error_types.items(), key=lambda x: x[1])[0]
        suggestions = ERROR_SUGGESTIONS.get(top_error, "")
        if suggestions:
            lines.append(f"\n最常见问题: {ERROR_TYPE_LABELS.get(top_error, top_error)}")
            lines.append(f"建议: {suggestions}")

    return "\n".join(lines)


# 错误类型中文标签
ERROR_TYPE_LABELS = {
    "char_confusion": "字符混淆(I/l/1等)",
    "missing_words": "漏字(Prime/Blueprint等)",
    "confusion+missing": "混淆+漏字",
    "extra_chars": "多字/粘连",
    "ocr_empty": "OCR无输出",
    "other_error": "其他错误",
}

# 优化建议
ERROR_SUGGESTIONS = {
    "char_confusion": "优化图像预处理或增加后处理纠错规则",
    "missing_words": "检查OCR检测灵敏度或调整图像放大倍数",
    "confusion+missing": "综合上述两项建议",
    "extra_chars": "调整行合并逻辑或添加粘连拆分",
    "ocr_empty": "检查图片质量、颜色过滤设置或文字大小",
    "other_error": "查看具体案例分析原因",
}


# ============================================================
#  主流程
# ============================================================

def main():
    print("\n" + "=" * 60)
    print("  OCR & 匹配准确率 Benchmark 工具")
    print("=" * 60 + "\n")

    # 1. 加载测试图片
    print(f"[1/4] 扫描测试文件夹: {TEST_DIR}")
    images = load_test_images()

    if not images:
        print("\n未找到测试图片!")
        print(f"请将截图放入 {TEST_DIR} 文件夹")
        print("文件名使用正确的物品名称，例如:")
        print("  - Ash Prime Neuroptics Blueprint.png")
        print("  - Latron Prime Receiver.png")
        print("  - Forma Blueprint.png")
        return

    print(f"      找到 {len(images)} 张测试图片\n")

    # 2. 运行测试
    results = []
    for i, (ground_truth, image_path) in enumerate(images, 1):
        print(f"[{i}/{len(images)}] 处理: {ground_truth}")
        print(f"         图片: {image_path.name}")

        run_result = run_ocr_and_match(image_path)
        comparison = compare_result(
            ground_truth,
            run_result['ocr_texts'],
            run_result['matched_items'],
        )

        results.append({
            'ground_truth': ground_truth,
            'image_path': image_path.name,
            'result': run_result,
            'comparison': comparison,
        })

        # 显示简要结果
        status = "✓" if comparison['match_correct'] else "✗"
        ocr_output = run_result['ocr_texts'][0] if run_result['ocr_texts'] else "(无)"
        match_output = comparison['match_best'] or "(未匹配)"
        print(f"         结果: {status} OCR=[{ocr_output}] 匹配=[{match_output}] ({run_result['timing_ms']:.0f}ms)\n")

    # 3. 生成报告
    report = generate_report(results)

    # 4. 输出报告
    print("\n" + report)

    # 保存到文件
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n报告已保存至: {REPORT_FILE}")


if __name__ == "__main__":
    main()
