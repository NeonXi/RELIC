"""
WARFRAME-RELIC UI 字符串预设 — 普通模式（标准中文）

所有 UI 展示的文本集中定义在此，通过 data/ui_strings.S() 访问。
"""

STRINGS = {
    # ── 功能按钮标签（截图后弹出）──
    "button": {
        "mode_check":      "查状态",
        "mode_query":      "查部件",
        "mode_translate":  "翻译",
    },

    # ── 覆盖层提示文字 ──
    "overlay": {
        "please_select_first":     "请先框选遗物区域",
        "screenshot_failed":       "截图失败，请重试",
        "fullscreen_failed":       "全屏捕获失败",
        "screenshot_done":         "截图完成",
        "please_screenshot_first": "请先按快捷键截图",
        "ocr_recognizing":         "正在识别文字...",
        "db_not_ready":            "数据库未就绪，请稍后再试",
        "no_features_enabled":     "未启用任何功能",
        "selection_cancelled":     "已取消选择",
        "relic_vaulted":           "入库",
        "relic_available":         "出库",
        "query_legend":            "\n━━━ 图例说明 ━━━\n"
                                   "金 = 必掉\n"
                                   "银 = 常见\n"
                                   "铜 = 稀有",
        "no_text_detected":        "未能识别文字",
        "translate_failed":        "翻译失败",
        "selection_status_idle":   "",
        "selection_status_released": "",
        "mode_selected":           "已选择功能: {mode}",
        "relic_no_parts_info":     "【{name}】无数据",
        "region_saved":            "区域已保存: ({l},{t})-({r},{b}) {w}x{h}",
    },

    # ── 快捷键标签 ──
    "hotkey": {
        "label_select":       "区域选择",
        "label_fullscreen":   "全屏捕获",
        "label_eye_mask":     "护眼遮罩",
    },

    # ── 导航标签 ──
    "nav": {
        "eye_mask": "护眼遮罩",
    },

    # ── 功能开关标签 ──
    "feature_toggle": {
        "label_check_status": "遗物状态检查",
        "label_query_parts":  "遗物内含查询",
        "label_translate":    "自动翻译",
    },
}
