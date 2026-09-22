"""
[L2] core.pages — 页面层(导航项对应的内容页)

依赖: core.widgets / core.services / core.sections
职责: 每个导航项一个文件,组装该页面的所有 UI 元素 + 连接信号槽
父类: BasePage (base_page.py)

注意: 旧架构中的 management_panel.py / panel_builder.py / panel_styles.py 已被废弃,
本目录是 UI 重构后的新页面入口。

## AI 硬约束 — 修改本目录任何文件前必读
归属层:    [L2] (core/pages/) — 整层统一规范
允许依赖:  core.widgets/*, core.sections/*, core.services/*(读), core.state/*(读)
禁止依赖:  core.tokens/* 直接调用(只能通过 widget 间接触达)
           任何反向依赖 widgets(Widget 不能调 Page)
必读规范:  .trae/rules/开发规范.md §6.5

本层统一红线:
- ✗ 禁止在 Page 中 setStyleSheet(f"...") → 必须用 Token 或继承自 CyberWidget
- ✗ 禁止 Page 重写 paintEvent → 视觉交给 Widget
- ✗ 禁止 Page 直接读写 JSON / 调网络 → 走 Service.get()
- ✗ 禁止 Page 直接持有并修改另一个 Page → 走 EventBus
- ✗ 禁止硬编码颜色 "#XXXXXX" 或非 4 倍数尺寸 → 必须用 Token
- ✗ 禁止 Page 跨层反向调用(例如 import core.widgets.base 直接改 Mixin)

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.5。
"""
# WARFRAME-RELIC UI 页面模块
