"""
[L4] core.word_wrap_button — 支持自动换行的 QPushButton

PySide6 的 QPushButton 不支持 setWordWrap,本子类通过重写 paintEvent,
用 QPainter.drawText + Qt.TextWordWrap 手动绘制文字来实现自动换行。

用法: 直接替代 QPushButton,API 完全兼容。

依赖: PySide6.QtWidgets + PySide6.QtGui (QPainter)
被谁用: core.overlay (功能按钮)

## AI 硬约束 — 修改本文件前必读
归属层:    [L0/L1] (core/ 根目录,跨层桥接/全局管理器)
允许依赖:  视文件而定(本层可持有 widget 引用作桥接,但不实现绘制)
禁止依赖:  根目录 .py 不允许做业务实现 → 业务放 core/services/
必读规范:  .trae/rules/开发规范.md §6.7

本文件相关红线:
- 禁止根目录 .py 持有 widget 绘制逻辑 → 视觉交给 core/widgets/
- 禁止硬编码资源路径 → 必须 core.constants 取
- 禁止在根目录定义业务类 → 业务放对应层
- 禁止反向调用 UI(从 Service → Widget) → 单向数据流
- 禁止 try/except: pass 吞错 → 必须记录到日志或抛给上层

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.7,别走捷径。
"""

from PySide6.QtWidgets import QPushButton, QStyleOptionButton, QStyle
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtCore import Qt, QRect


class WordWrapButton(QPushButton):
    """支持自动换行的按钮。

    重写 paintEvent，在绘制背景和边框（由 QStyle 处理）之后，
    用 QPainter.drawText + TextWordWrap 手动绘制文字。
    这样长文案会自然折行，不会被截断。
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._word_wrap = True

    def paintEvent(self, event):
        """自定义绘制：背景/边框交给 QStyle，文字手动换行绘制。"""
        if not self._word_wrap or not self.text():
            # 无文字或未启用换行时，回退到默认绘制
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # ---- 绘制背景和边框（由 QStyle 处理，保持 QSS 兼容） ----
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        # 清除文字，让 QStyle 只画背景和边框，不画文字
        opt.text = ""
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, opt, painter, self)

        # ---- 手动绘制换行文字 ----
        margin = 10  # 左右边距
        text_rect = QRect(
            self.rect().x() + margin,
            self.rect().y() + 4,
            self.rect().width() - 2 * margin,
            self.rect().height() - 8,
        )

        painter.setFont(self.font())
        # 使用当前按钮状态的颜色（通过 palette）
        if self.isEnabled():
            color = self.palette().color(QPalette.ColorRole.ButtonText)
        else:
            color = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
        painter.setPen(color)

        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            self.text(),
        )

        painter.end()

    def sizeHint(self):
        """返回默认推荐尺寸，配合 layout 使用。"""
        hint = super().sizeHint()
        # 至少 40px 高，保证两行文字 + padding
        if hint.height() < 40:
            hint.setHeight(40)
        return hint
