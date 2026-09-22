"""
[L-Recognizer] part_mappings — 部件名称映射数据(中英互译)

依赖: 无
被谁用: core.recognizers.item_name / core.recognizers.matcher

从 item_name.py 和 matcher.py 中提取的共享常量,
消除两个模块之间的循环依赖。

内容:
  - 中文部件词 → 英文后缀映射
  - 英文后缀 → 中文部件词映射

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

# ── 中文部件词 → 英文后缀映射 ──
PART_CN_TO_EN = {
    # 战甲部件 + Blueprint
    '机体':          'Chassis Blueprint',
    '系统':          'Systems Blueprint',
    '头部神经光元':   'Neuroptics Blueprint',
    '头部':          'Neuroptics',
    '神经光元':       'Neuroptics',
    # 武器部件（不含 Blueprint）
    '枪管':  'Barrel',
    '枪机':  'Receiver',
    '握柄':  'Handle',
    '握把':  'Grip',
    '枪托':  'Stock',
    '刀刃':  'Blade',
    '护手':  'Guard',
    '锤头':  'Head',
    '绳索':  'String',
    '下弓臂': 'Lower Limb',
    '上弓臂': 'Upper Limb',
    # 守护部件（不含 Blueprint）
    '外壳':  'Carapace',
    '头部':  'Cerebrum',
    # 通用蓝图
    '蓝图':  'Blueprint',
}

# ── 英文后缀 → 中文名（用于反向翻译显示） ──
PART_EN_TO_CN = {
    'Chassis Blueprint':     '机体蓝图',
    'Systems Blueprint':     '系统蓝图',
    'Neuroptics Blueprint':  '头部神经光元蓝图',
    'Blueprint':             '蓝图',
    'Barrel':      '枪管',
    'Receiver':    '枪机',
    'Handle':      '握柄',
    'Grip':        '握把',
    'Stock':       '枪托',
    'Blade':       '刀刃',
    'Guard':       '护手',
    'Head':        '锤头',
    'String':      '绳索',
    'Lower Limb':  '下弓臂',
    'Upper Limb':  '上弓臂',
    'Carapace':    '外壳',
    'Cerebrum':    '头部',
}

# ── 所有中文部件字符集合（用于 is_all_cjk 等判断） ──
_PART_CHARS = set('机体系统部神经光元蓝图枪握柄把刀刃锤绳弓臂管托手头外壳')

# ── 子分类映射（供正则匹配使用） ──
_WARFRAME_PART_CN = {
    '机体':          'Chassis',
    '系统':          'Systems',
    '头部神经光元':   'Neuroptics',
    '头部':          'Neuroptics',
    '神经光元':       'Neuroptics',
}

_WEAPON_PART_CN = {
    '枪管':  'Barrel',
    '枪机':  'Receiver',
    '握柄':  'Handle',
    '握把':  'Grip',
    '枪托':  'Stock',
    '刀刃':  'Blade',
    '护手':  'Guard',
    '锤头':  'Head',
    '绳索':  'String',
    '下弓臂': 'Lower Limb',
    '上弓臂': 'Upper Limb',
}

_SENTINEL_PART_CN = {
    '外壳':  'Carapace',
    '头部':  'Cerebrum',
    '系统':  'Systems',
}
