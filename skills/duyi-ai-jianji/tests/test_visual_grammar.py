from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "assets" / "composition" / "semantic-stage" / "build.py"


def relation_state(layout: str, items: list[str]) -> dict[str, object]:
    is_connected = layout in {"narrative-path", "spoken-cause"}
    return {
        "id": "state-001",
        "action": "enter",
        "type": "relation",
        "fidelity_mode": "spoken-first",
        "relation_layout": layout,
        "layout_reason": "原话中的顺序和节点必须保持不变",
        "card_size": "medium",
        "content_structure": (
            "balanced-grid" if layout == "multi-item" else "horizontal-relation"
        ),
        "size_reason": "关系节点使用最大宽度中卡",
        "label": "WORKFLOW",
        "title": "从素材到发布",
        "reveal_at": 0.3,
        "items": [
            {
                "id": f"node-{index:03d}",
                "text": text,
                **(
                    {"incoming_connector": "→"}
                    if is_connected and index > 1
                    else {}
                ),
                "reveal_at": 0.3 + index * 0.2,
            }
            for index, text in enumerate(items, start=1)
        ],
    }


class AIJianjiVisualGrammarTests(unittest.TestCase):
    def build(self, state: dict[str, object]) -> tuple[str, dict[str, object]]:
        folder = tempfile.TemporaryDirectory(prefix="composition-visual-grammar-")
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        config = root / "config.json"
        output = root / "out"
        config.write_text(
            json.dumps(
                {
                    "chapter_en": "SPOKEN FLOW",
                    "chapter_zh": "口述流程",
                    "accent": "blue",
                    "layout": "fixed-left",
                    "duration": 5,
                    "states": [state],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        subprocess.run(
            [sys.executable, str(BUILDER), str(config), str(output)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return (
            (output / "index.html").read_text(encoding="utf-8"),
            json.loads((output / "overlay-spec.json").read_text(encoding="utf-8")),
        )

    def test_four_step_path_preserves_all_spoken_nodes_and_three_arrows(self) -> None:
        html, spec = self.build(
            relation_state(
                "narrative-path",
                ["录完素材", "Agent", "剪辑", "发布"],
            )
        )
        for text in ("录完素材", "Agent", "剪辑", "发布"):
            self.assertIn(text, html)
        self.assertEqual(html.count('class="relation-connector"'), 3)
        self.assertIn('id="state-01-edge-01"', html)
        self.assertIn('id="state-01-edge-02"', html)
        self.assertIn('id="state-01-edge-03"', html)
        self.assertIn("flex: 1 1 34px", html)
        self.assertIn("transform-origin: left center", html)
        self.assertRegex(
            html,
            r'fromTo\("#state-01-edge-01", \{ autoAlpha: 0, scaleX: 0 \}.*?, 0\.7\)',
        )
        self.assertRegex(
            html,
            r'fromTo\("#state-01-item-02", \{ autoAlpha: 0 \}.*?, 0\.7\)',
        )
        self.assertEqual(
            spec["card_size_selections"][0]["relation_layout"],
            "narrative-path",
        )
        self.assertEqual(
            spec["reference_contract"]["maximum_card_width"]["canvas_ratio"],
            0.33359375,
        )

    def test_global_connector_is_rejected(self) -> None:
        state = relation_state("narrative-path", ["素材", "Agent"])
        state["connector"] = "→"
        folder = tempfile.TemporaryDirectory(prefix="composition-global-connector-")
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        config = root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "chapter_en": "FLOW",
                    "chapter_zh": "流程",
                    "accent": "blue",
                    "layout": "fixed-left",
                    "duration": 5,
                    "states": [state],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(BUILDER), str(config), str(root / "out")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot use one global connector", result.stderr)

    def test_each_target_node_requires_its_own_connector(self) -> None:
        state = relation_state("narrative-path", ["素材", "Agent", "剪辑"])
        del state["items"][2]["incoming_connector"]
        folder = tempfile.TemporaryDirectory(prefix="composition-missing-edge-")
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        config = root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "chapter_en": "FLOW",
                    "chapter_zh": "流程",
                    "accent": "blue",
                    "layout": "fixed-left",
                    "duration": 5,
                    "states": [state],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(BUILDER), str(config), str(root / "out")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("incoming_connector must be", result.stderr)

    def test_five_items_use_equal_cells_with_centered_second_row(self) -> None:
        html, _spec = self.build(
            relation_state("multi-item", ["一", "二", "三", "四", "五"])
        )
        self.assertIn("relation-multi-item relation-count-5", html)
        self.assertIn(
            ".relation-multi-item.relation-count-5 .relation-node:nth-child(4)",
            html,
        )
        self.assertIn("grid-column: 3 / span 4", html)
        self.assertIn("grid-column: 7 / span 4", html)

    def test_thirteen_items_are_rejected_instead_of_overloading_composite(self) -> None:
        state = relation_state(
            "multi-item",
            [
                "一",
                "二",
                "三",
                "四",
                "五",
                "六",
                "七",
                "八",
                "九",
                "十",
                "十一",
                "十二",
                "十三",
            ],
        )
        folder = tempfile.TemporaryDirectory(prefix="composition-nine-items-")
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        config = root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "chapter_en": "TOO MANY",
                    "chapter_zh": "节点拆层",
                    "accent": "blue",
                    "layout": "fixed-left",
                    "duration": 5,
                    "states": [state],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(BUILDER), str(config), str(root / "out")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires 5-12 items", result.stderr)


if __name__ == "__main__":
    unittest.main()
