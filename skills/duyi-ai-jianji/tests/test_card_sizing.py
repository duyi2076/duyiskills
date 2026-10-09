from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_visual_direction import audit_card_selection  # noqa: E402
from common import load_json  # noqa: E402


POLICY = load_json(ROOT / "assets" / "composition" / "visual-grammar.json")


class AIJianjiCardSizingTests(unittest.TestCase):
    def test_medium_is_valid_for_a_core_idea(self) -> None:
        errors, selection = audit_card_selection(
            state={
                "type": "thesis",
                "fidelity_mode": "spoken-first",
                "relation_layout": "single-point",
                "layout_reason": "原话只建立一个核心观点",
                "card_size": "medium",
                "content_structure": "core-idea",
                "size_reason": "完整核心观点使用默认中卡",
                "title": "核心观点",
                "body": "一行完整解释",
            },
            state_type="thesis",
            segment_id="chapter-001",
            state_index=1,
            policy=POLICY,
        )
        self.assertEqual(errors, [])
        self.assertEqual(selection["card_size"], "medium")

    def test_large_card_no_longer_exists(self) -> None:
        errors, _selection = audit_card_selection(
            state={
                "type": "path",
                "fidelity_mode": "spoken-first",
                "relation_layout": "vertical-list",
                "layout_reason": "原话按三个步骤逐项展开",
                "card_size": "large",
                "content_structure": "vertical-list",
                "size_reason": "错误示例故意选择大卡触发门禁",
                "title": "三个步骤",
            },
            state_type="path",
            segment_id="chapter-001",
            state_index=1,
            policy=POLICY,
        )
        codes = {item["code"] for item in errors}
        self.assertIn("card_size_invalid_or_missing", codes)

    def test_text_overflow_does_not_authorize_a_large_card(self) -> None:
        errors, _selection = audit_card_selection(
            state={
                "type": "thesis",
                "fidelity_mode": "spoken-first",
                "relation_layout": "single-point",
                "layout_reason": "原话只建立一个核心观点",
                "card_size": "medium",
                "content_structure": "core-idea",
                "size_reason": "完整核心观点使用默认中卡",
                "title": "这是一个需要拆层而不是扩大卡片的核心观点",
                "body": "这段解释故意写得非常非常长用来验证文字过多时流水线会直接阻断并要求拆成多个完整语义层而不是扩大卡片继续塞入更多文字",
            },
            state_type="thesis",
            segment_id="chapter-001",
            state_index=1,
            policy=POLICY,
        )
        self.assertIn(
            "card_text_exceeds_selected_size",
            {item["code"] for item in errors},
        )

    def test_four_step_spoken_path_uses_medium_card(self) -> None:
        errors, selection = audit_card_selection(
            state={
                "type": "relation",
                "fidelity_mode": "spoken-first",
                "relation_layout": "narrative-path",
                "layout_reason": "原话使用然后和交给表达四步推进",
                "card_size": "medium",
                "content_structure": "horizontal-relation",
                "size_reason": "四节点三箭头在最大中卡内铺满",
                "title": "素材工作流",
                "items": [
                    {"text": "录完素材"},
                    {"text": "Agent", "incoming_connector": "→"},
                    {"text": "剪辑", "incoming_connector": "→"},
                    {"text": "发布", "incoming_connector": "→"},
                ],
            },
            state_type="relation",
            segment_id="chapter-001",
            state_index=1,
            policy=POLICY,
        )
        self.assertEqual(errors, [])
        self.assertEqual(selection["relation_layout"], "narrative-path")
        self.assertEqual(selection["card_size"], "medium")

    def test_five_items_require_balanced_multi_item_layout(self) -> None:
        errors, _selection = audit_card_selection(
            state={
                "type": "relation",
                "fidelity_mode": "spoken-first",
                "relation_layout": "parallel",
                "layout_reason": "原话列出五个同级信息点",
                "card_size": "medium",
                "content_structure": "balanced-grid",
                "size_reason": "五项使用中卡均衡换行",
                "title": "五个要点",
                "items": [{"text": str(index)} for index in range(5)],
            },
            state_type="relation",
            segment_id="chapter-001",
            state_index=1,
            policy=POLICY,
        )
        self.assertIn("relation_item_count_invalid", {item["code"] for item in errors})

    def test_ten_short_same_group_items_allow_one_composite_card(self) -> None:
        errors, selection = audit_card_selection(
            state={
                "type": "relation",
                "fidelity_mode": "spoken-first",
                "relation_layout": "multi-item",
                "layout_reason": "原话按第一至第十列出同一组连续标准",
                "card_size": "medium",
                "content_structure": "balanced-grid",
                "size_reason": "十个同组短节点使用一个中卡复合外壳",
                "title": "十项标准",
                "items": [{"text": f"第{index}项"} for index in range(1, 11)],
            },
            state_type="relation",
            segment_id="chapter-001",
            state_index=1,
            policy=POLICY,
        )
        self.assertEqual(errors, [])
        self.assertEqual(selection["relation_layout"], "multi-item")


if __name__ == "__main__":
    unittest.main()
