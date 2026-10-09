from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from stage_layout import (  # noqa: E402
    STAGE_HEIGHT_BUDGET_PX,
    estimated_chapter_height,
    estimated_state_height,
    relation_row_distribution,
)


def relation_state(item_count: int, *, layout: str = "multi-item") -> dict:
    return {
        "id": "state-001",
        "action": "enter",
        "type": "relation",
        "fidelity_mode": "spoken-first",
        "relation_layout": layout,
        "layout_reason": "原话列出同一组连续编号信息",
        "card_size": "medium",
        "content_structure": "balanced-grid" if layout == "multi-item" else "parallel-row",
        "size_reason": "同组节点使用中卡按内容均衡排列",
        "reveal_at": 0.3,
        "label": "STANDARD",
        "title": "十项标准",
        "items": [
            {
                "id": f"item-{index:03d}",
                "text": f"第{index}项",
                "reveal_at": 0.3 + index * 0.1,
            }
            for index in range(1, item_count + 1)
        ],
    }


class AIJianjiStageLayoutTests(unittest.TestCase):
    def test_short_thesis_uses_content_height_not_large_fixed_slab(self) -> None:
        height = estimated_state_height(
            {
                "type": "thesis",
                "card_size": "small",
                "title": "一个提示词",
            }
        )
        self.assertLess(height, 260)
        self.assertGreater(height, 120)

    def test_ten_same_group_items_fit_one_composite_card(self) -> None:
        estimate = estimated_chapter_height([relation_state(10)])
        self.assertTrue(estimate["fits"])
        self.assertLessEqual(estimate["estimated_height"], STAGE_HEIGHT_BUDGET_PX)
        self.assertEqual(relation_row_distribution("multi-item", 10), [4, 4, 2])

    def test_three_separate_relation_shells_require_reflow(self) -> None:
        states = []
        for index in range(3):
            state = relation_state(4, layout="parallel")
            state["id"] = f"state-{index + 1:03d}"
            state["action"] = "enter" if index == 0 else "update"
            states.append(state)
        estimate = estimated_chapter_height(states)
        self.assertFalse(estimate["fits"])
        self.assertFalse(estimate["fits_after_gap_compaction"])

    def test_builder_emits_content_height_contract_and_ten_item_grid(self) -> None:
        builder = ROOT / "assets" / "composition" / "semantic-stage" / "build.py"
        with tempfile.TemporaryDirectory(prefix="composition-content-height-") as folder:
            root = Path(folder)
            config = {
                "chapter_en": "SKILL STANDARD",
                "chapter_zh": "十项标准",
                "accent": "blue",
                "layout": "fixed-left",
                "duration": 6,
                "states": [relation_state(10)],
            }
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(config, ensure_ascii=False),
                encoding="utf-8",
            )
            output = root / "out"
            subprocess.run(
                [sys.executable, str(builder), str(config_path), str(output)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            html = (output / "index.html").read_text(encoding="utf-8")
            spec = json.loads(
                (output / "overlay-spec.json").read_text(encoding="utf-8")
            )
            self.assertIn("relation-count-10", html)
            self.assertIn("max-height: 690px", html)
            self.assertIn(".state-thesis:has(.state-items) { min-height: 0; }", html)
            self.assertNotIn("data-layout-allow-occlusion", html)
            self.assertEqual(
                spec["stage_layout_model"],
                "measured-content-height-reflow-v1",
            )
            self.assertLessEqual(spec["estimated_layer_height"], 690)


if __name__ == "__main__":
    unittest.main()
