"""
Matcher 引擎单元测试 — 物品匹配逻辑。

覆盖:
  - Warframe 部件判断
  - 部件后缀识别
"""

from __future__ import annotations

import pytest

from core.recognizers.matcher import (
    _is_warframe_part,
    _PART_SUFFIXES,
)


class TestIsWarframePart:

    def test_blueprint_is_part(self):
        assert _is_warframe_part("Paris Prime Blueprint") is True

    def test_blade_is_part(self):
        assert _is_warframe_part("Dual Zoren Prime Blade") is True

    def test_receiver_is_part(self):
        assert _is_warframe_part("Latron Prime Receiver") is True

    def test_handle_is_part(self):
        assert _is_warframe_part("Fulmin Handle") is True

    def test_chassis_is_part(self):
        assert _is_warframe_part("Nova Chassis") is True

    def test_neuroptics_is_part(self):
        assert _is_warframe_part("Mag Neuroptics") is True

    def test_systems_is_part(self):
        assert _is_warframe_part("Valkyr Systems") is True

    def test_complete_item_not_part(self):
        """完整物品名不含部件后缀，不应被判定为部件。"""
        assert _is_warframe_part("Paris Prime") is False

    def test_plain_name_not_part(self):
        assert _is_warframe_part("Forma") is False

    def test_carapace_is_guardian_part(self):
        assert _is_warframe_part("Djinn Carapace") is True

    def test_cerebrum_is_guardian_part(self):
        assert _is_warframe_part("Nautilus Cerebrum") is True


class TestPartSuffixesCompleteness:
    """确保已知部件后缀列表包含关键后缀。"""

    def test_contains_blueprint_relevant_suffixes(self):
        expected = {"Blade", "Barrel", "Receiver", "Handle",
                     "Grip", "Stock", "Head", "Guard"}
        assert expected.issubset(set(_PART_SUFFIXES))

    def test_contains_warframe_parts(self):
        expected = {"Chassis", "Systems", "Neuroptics",
                     "Carapace", "Cerebrum"}
        assert expected.issubset(set(_PART_SUFFIXES))
