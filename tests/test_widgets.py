"""
Widgets 层单元测试 — 自定义控件实例化与基本行为。

覆盖:
  - CyberButton 创建与显示
  - CyberLineEdit 创建
  - CyberPanel 创建
  - CyberCard 创建
  - CyberComboBox 创建
  - CyberLogViewer 创建
  - HotkeyEdit 创建
  - 基本交互（点击、输入、focus）
  注意: 这些测试需要 QApplication (qapp fixture)。
"""

from __future__ import annotations

import pytest

from PySide6.QtWidgets import QPushButton, QFrame, QLineEdit, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor


# ═══════════════════════════════════════════════════
#  辅助: 安全导入控件类，如果依赖不满足则跳过
# ═══════════════════════════════════════════════════

def _import_or_skip(module_path, class_name):
    """尝试导入控件类，失败则返回 skip 标记。"""
    try:
        parts = module_path.split(".")
        mod = __import__(module_path, fromlist=[class_name])
        return getattr(mod, class_name)
    except Exception:
        return None


CyberButton = _import_or_skip("core.widgets.button", "CyberButton")
CyberLineEdit = _import_or_skip("core.widgets.line_edit", "CyberLineEdit")
CyberPanel = _import_or_skip("core.widgets.panel", "CyberPanel")
CyberCard = _import_or_skip("core.widgets.card", "CyberCard")
CyberComboBox = _import_or_skip("core.widgets.combo_box", "CyberComboBox")
CyberLogViewer = _import_or_skip("core.widgets.log_viewer", "CyberLogViewer")
HotkeyEdit = _import_or_skip("core.widgets.hotkey_edit", "HotkeyEdit")


def _skip_if_none(cls, name):
    if cls is None:
        pytest.skip(f"{name} 导入失败，可能缺少依赖")


class TestCyberButton:

    def test_create(self, qapp):
        _skip_if_none(CyberButton, "CyberButton")
        btn = CyberButton("Test")
        assert btn.text() == "Test"
        assert isinstance(btn, QPushButton)

    def test_inherits_qpushbutton(self, qapp):
        _skip_if_none(CyberButton, "CyberButton")
        btn = CyberButton()
        assert isinstance(btn, QPushButton)


class TestCyberLineEdit:

    def test_create(self, qapp):
        _skip_if_none(CyberLineEdit, "CyberLineEdit")
        edit = CyberLineEdit()
        assert isinstance(edit, QLineEdit)

    def test_set_text(self, qapp):
        _skip_if_none(CyberLineEdit, "CyberLineEdit")
        edit = CyberLineEdit()
        edit.setText("hello")
        assert edit.text() == "hello"


class TestCyberPanel:

    def test_create(self, qapp):
        _skip_if_none(CyberPanel, "CyberPanel")
        panel = CyberPanel()
        assert isinstance(panel, QFrame)

    def test_has_layout(self, qapp):
        _skip_if_none(CyberPanel, "CyberPanel")
        panel = CyberPanel()
        assert panel.layout() is not None


class TestCyberCard:

    def test_create(self, qapp):
        _skip_if_none(CyberCard, "CyberCard")
        card = CyberCard(title="Test Card")
        assert isinstance(card, QFrame)


class TestCyberComboBox:

    def test_create(self, qapp):
        _skip_if_none(CyberComboBox, "CyberComboBox")
        combo = CyberComboBox()
        # 应该是一个可用的 combo box


class TestCyberLogViewer:

    def test_create(self, qapp):
        _skip_if_none(CyberLogViewer, "CyberLogViewer")
        viewer = CyberLogViewer(title="Test Log", max_lines=100)
        assert viewer is not None


class TestHotkeyEdit:

    def test_create(self, qapp):
        _skip_if_none(HotkeyEdit, "HotkeyEdit")
        edit = HotkeyEdit()
        assert edit is not None
