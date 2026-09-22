"""
[L0/L1] Annotation — 截图标注的数据模型

强类型替代变长元组。用于在 overlay 上绘制 OCR 识别结果的标注。

依赖: Python 标准库 (dataclass)
职责: 定义标注数据结构(text/位置/颜色/过期时间),不做绘制
被谁用: core.overlay.py / core.services.screenshot_pipeline.py

用法:
    from core.annotation import Annotation
    from core.tokens.manager import TokenManager
    c = TokenManager.instance().get("accent.success", "#00FF00")

    # 单行标注
    a = Annotation(text="Lith P1 [出库]", x=100, y=200, expire_ms=8000, color=c)

    # 多行标注（每行独立颜色）
    a = Annotation(text="Meso A2\\n  ● Nekros Prime", x=100, y=200,
                   expire_ms=10000, color=c,
                   line_colors=[c, c])

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
- 禁止字段默认值硬编码颜色字面量 → color/line_colors 默认为 None,由调用方从 token 取

OPTIONS: 有疑义先读 .trae/rules/开发规范.md §6.7,别走捷径。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


# 颜色字段默认值:不写 hex 字面量,统一让调用方从 TokenManager 传入。
# get_line_color() 内部 None 兜底,语义等同于"未指定"而不是固定颜色。
DEFAULT_COLOR: Optional[str] = None


@dataclass
class Annotation:
    """单条覆盖层标注。

    字段说明:
        text:       标注文本（支持 \\n 多行）
        x, y:       标注左上角逻辑坐标
        expire_ms:  过期时间戳（毫秒,int(time.time()*1000) + duration_ms)
        color:      默认文字颜色（单行时使用,多行时作为 fallback）
                    默认 None,调用方应从 TokenManager 读取后传入
        line_colors: 多行文本的逐行颜色列表(可选,长度应与行数一致)
    """
    text: str
    x: int
    y: int
    expire_ms: int
    color: Optional[str] = None
    line_colors: Optional[list[str]] = None

    def is_expired(self, now_ms: int) -> bool:
        """判断标注是否已过期。"""
        return self.expire_ms <= now_ms

    @property
    def line_count(self) -> int:
        """返回文本行数。"""
        return self.text.count('\n') + 1

    @property
    def is_multiline(self) -> bool:
        """是否为多行文本。"""
        return '\n' in self.text

    def get_line_color(self, index: int) -> Optional[str]:
        """获取第 index 行的颜色(0-based),没有则回退到默认颜色。

        Returns:
            颜色字符串(token key 解析后的 hex / rgba),可能为 None
        """
        if self.line_colors and index < len(self.line_colors):
            return self.line_colors[index]
        return self.color

    @staticmethod
    def create(
        text: str,
        x: int,
        y: int,
        duration_ms: int = 5000,
        color: Optional[str] = None,
        line_colors: Optional[list[str]] = None,
    ) -> Annotation:
        """工厂方法:从相对时长创建标注(自动计算绝对过期时间)。

        Args:
            text: 标注文本
            x, y: 坐标
            duration_ms: 显示时长(毫秒,从当前时间起算)
            color: 颜色(默认 None,调用方应从 TokenManager 传入)
            line_colors: 多行逐行颜色
        """
        import time
        return Annotation(
            text=text,
            x=x,
            y=y,
            expire_ms=int(time.time() * 1000) + duration_ms,
            color=color,
            line_colors=line_colors,
        )
