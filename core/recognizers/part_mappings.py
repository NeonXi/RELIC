"""
部件名称映射数据（中英互译）

从 item_name.py 和 matcher.py 中提取的共享常量，
消除两个模块之间的循环依赖。
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
