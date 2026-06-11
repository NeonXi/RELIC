"""
测试基础设施 — 共享 fixtures 和辅助工具。

提供:
  - qapp fixture: 全局 QApplication 实例（所有 Qt 测试需要）
  - tm fixture: 已加载 cyberpunk 预设的 TokenManager
  - sample_preset: 最小化预设数据（用于 resolver/manager 测试）
"""

from __future__ import annotations

import os
import sys

import pytest

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = str(__file__).rsplit(os.sep, 1)[0]
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ═══════════════════════════════════════════════════
#  Qt Application Fixture
# ═══════════════════════════════════════════════════

@pytest.fixture(scope="session")
def qapp():
    """全局 QApplication，每个测试会话只创建一次。"""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ═══════════════════════════════════════════════════
#  Token Manager Fixtures
# ═══════════════════════════════════════════════════

SAMPLE_PRESET = {
    "raw": {
        "yellow": "#FFE600",
        "cyan": "#00FFFF",
        "red": "#FF0000",
        "blue": "#0000FF",
        "black": "#000000",
        "white": "#FFFFFF",
        "dark_bg": "#0E0E24",
        "raised": "#141E38",
    },
    "alias": {
        "accent.primary": "@raw.yellow",
        "accent.secondary": "@raw.cyan",
        "bg.base": "@raw.dark_bg",
        "bg.raised": "@raw.raised",
    },
    "semantic": {
        "danger": "@raw.red",
        "success": "#44EE99",
        "warning": "lighten(@raw.yellow, 20%)",
    },
    "space": {
        "height": {"btn_md": 36, "btn_sm": 28},
        "spacing": {"xs": 4, "sm": 8, "md": 12, "lg": 16},
        "font": {"body_md": 13, "h3": 18},
        "corner": {"xs": 4, "sm": 8},
        "height.scrollbar": 8,
    },
}


@pytest.fixture()
def sample_resolver():
    """使用最小化预设数据的 TokenResolver。"""
    from core.tokens.resolver import TokenResolver
    return TokenResolver(SAMPLE_PRESET)


@pytest.fixture()
def tm(qapp):
    """已加载 SAMPLE_PRESET 的 TokenManager 单例（每次测试重置）。"""
    from core.tokens.manager import TokenManager
    TokenManager.reset()
    instance = TokenManager.instance()
    instance.load_from_dict(SAMPLE_PRESET.copy(), name="test")
    yield instance
    TokenManager.reset()


@pytest.fixture()
def real_tm(qapp):
    """加载真实 cyberpunk.yaml 预设的 TokenManager。"""
    from core.tokens.manager import TokenManager
    TokenManager.reset()
    instance = TokenManager.instance()
    try:
        instance.load_preset("cyberpunk")
    except (FileError, ImportError):
        pytest.skip("cyberpunk 预设文件不可用或缺少 PyYAML")
    yield instance
    TokenManager.reset()
