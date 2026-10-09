from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from contracts import (
    FIXED_LEFT_CONTENT_BOUNDS,
    PIPELINE_VERSION,
    composition_contract,
    delivery_dimensions,
)
from duyi_edit import semantic_stage_build_inputs_sha256
from remap_timeline import resolve_nested_triggers


class AIJianjiContractTests(unittest.TestCase):
    def test_delivery_dimensions_enforce_1080p_floor(self) -> None:
        self.assertEqual(delivery_dimensions(1440, 810), (1920, 1080))
        self.assertEqual(delivery_dimensions(1920, 1080), (1920, 1080))
        self.assertEqual(delivery_dimensions(3840, 2160), (3840, 2160))
        self.assertEqual(delivery_dimensions(1080, 1920), (1080, 1920))

    def test_composition_never_moves_away_from_left_stage(self) -> None:
        left = composition_contract("left")
        right = composition_contract("right")
        self.assertEqual(left["overlay_lane"], "left")
        self.assertEqual(right["overlay_lane"], "left")
        self.assertEqual(right["animation_layout"], "reference-fixed-left")
        self.assertEqual(right["panel_mode"], "content-panel")
        self.assertEqual(right["adaptive_repositioning"], "false")

    def test_nested_word_triggers_become_chapter_local_times(self) -> None:
        anchor = {
            "source_word_ids": ["word-1", "word-4"],
            "config": {
                "states": [
                    {
                        "action": "enter",
                        "trigger_word_ids": ["word-2"],
                        "items": [
                            {"text": "第二项", "trigger_word_ids": ["word-3"]}
                        ],
                        "parts": [
                            {"id": "part-1", "text": "关系", "trigger_word_ids": ["word-3"]},
                            {"id": "part-2", "text": "结果", "trigger_word_ids": ["word-4"]},
                        ],
                    }
                ]
            },
        }
        mapped = resolve_nested_triggers(
            anchor,
            source_to_output={
                "word-1": {"start": 10.0, "end": 10.2},
                "word-2": {"start": 11.25, "end": 11.5},
                "word-3": {"start": 13.0, "end": 13.2},
                "word-4": {"start": 15.0, "end": 15.2},
            },
            output_start=10.0,
            output_end=15.2,
        )
        state = mapped["config"]["states"][0]
        self.assertEqual(state["reveal_at"], 1.25)
        self.assertEqual(state["items"][0]["reveal_at"], 3.0)
        self.assertEqual(state["parts"][0]["reveal_at"], 3.0)
        self.assertEqual(state["parts"][1]["reveal_at"], 5.0)
        self.assertEqual(mapped["config"]["duration"], 5.2)

    def test_builder_emits_exact_reference_spec(self) -> None:
        builder = ROOT / "assets" / "composition" / "semantic-stage" / "build.py"
        config = ROOT / "assets" / "composition" / "semantic-stage" / "config.example.json"
        with tempfile.TemporaryDirectory(prefix="composition-test-") as folder:
            output = Path(folder) / "project"
            subprocess.run(
                [sys.executable, str(builder), str(config), str(output)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            spec = json.loads((output / "overlay-spec.json").read_text(encoding="utf-8"))
            style_presets = json.loads(
                (ROOT / "assets" / "composition" / "style-presets.json").read_text(
                    encoding="utf-8"
                )
            )
            selected_style = style_presets["presets"]["dark-reference-fixed"]
            self.assertEqual(spec["pipeline_version"], PIPELINE_VERSION)
            self.assertEqual(
                spec["build_inputs_sha256"],
                semantic_stage_build_inputs_sha256(selected_style),
            )
            self.assertEqual(spec["canvas"], {"width": 2560, "height": 1440})
            self.assertEqual(spec["layout"], "fixed-left")
            self.assertEqual(
                spec["content_bounds"],
                FIXED_LEFT_CONTENT_BOUNDS,
            )
            self.assertEqual(
                spec["content_bounds"]["max_x"],
                (37 + 427) / 1280,
            )
            self.assertEqual(spec["panel_mode"], "content-panel")
            self.assertEqual(spec["reference_contract"]["stage"], [37, 29, 427])
            self.assertEqual(
                spec["reference_contract"]["maximum_card_width"]["reference_width"],
                427,
            )
            self.assertEqual(spec["reference_contract"]["default_card_size"], "medium")
            self.assertEqual(
                {
                    key: value["reference_width"]
                    for key, value in spec["reference_contract"]["card_sizes"].items()
                },
                {"small": 373, "medium": 427},
            )
            self.assertEqual(
                spec["card_sizing_model"],
                "spoken-first-content-height",
            )
            self.assertEqual(
                spec["visual_grammar_model"],
                "spoken-first-relations",
            )
            self.assertEqual(
                spec["stage_layout_model"],
                "measured-content-height-reflow-v1",
            )
            self.assertFalse(spec["reference_contract"]["adaptive_repositioning"])
            self.assertEqual(spec["information_model"], "persistent-layer-stack")
            self.assertEqual(spec["motion_model"], "anchored-opacity")
            self.assertEqual(spec["semantic_timing_model"], "exact-spoken-reveal")
            self.assertEqual(spec["component_skin"], "type-specific-reference")
            self.assertEqual(
                spec["reference_contract"]["panel_rgba"],
                [10, 20, 27, 0.82],
            )
            html = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn('id="chapter-rail"', html)
            self.assertRegex(
                html,
                r"#chapter-rail \{[^}]*opacity: 0;[^}]*visibility: hidden;",
            )
            self.assertRegex(
                html,
                r"\.chapter-en \{[^}]*opacity: 0;[^}]*visibility: hidden;",
            )
            self.assertRegex(
                html,
                r"\.chapter-zh \{[^}]*opacity: 0;[^}]*visibility: hidden;",
            )
            self.assertIn("state-layer state-thesis", html)
            self.assertIn(".state-formula", html)
            self.assertIn("duration: 0.15", html)
            self.assertNotIn("y: 16", html)
            self.assertNotIn("x: -12", html)
            self.assertNotIn('.to("#state-01"', html)
            self.assertIn("NotoSansCJKsc-Bold.otf", html)
            self.assertNotIn("NotoSansCJKsc-Black.otf", html)
            self.assertIn("rgba(10, 20, 27, .82)", html)
            self.assertNotIn("rgba(5, 14, 22, .93)", html)

    def test_font_manifest_locks_regular_secondary_face(self) -> None:
        manifest = json.loads(
            (ROOT / "assets" / "composition" / "font-assets.json").read_text(encoding="utf-8")
        )
        regular = next(item for item in manifest["fonts"] if item["id"] == "noto-cjk-regular")
        bold = next(item for item in manifest["fonts"] if item["id"] == "noto-cjk-bold")
        medium = next(item for item in manifest["fonts"] if item["id"] == "noto-cjk-medium")
        self.assertEqual(
            regular["sha256"],
            "2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b",
        )
        self.assertIn("animation_zh_secondary", regular["role"])
        self.assertEqual(
            bold["sha256"],
            "b5f0d1a190a7f9b43c310a8850630af12553df32c4c050543f9059732d9b4c0a",
        )
        self.assertIn("animation_zh_primary", bold["role"])
        self.assertEqual(
            medium["sha256"],
            "ca094f6b0001fb048ca39ddd797a0cdb0179e1e55c6561e111c49c3e6a61d7b7",
        )
        self.assertIn("animation_zh_list", medium["role"])

    def test_builder_blocks_clipped_layer_stacks(self) -> None:
        builder = ROOT / "assets" / "composition" / "semantic-stage" / "build.py"
        with tempfile.TemporaryDirectory(prefix="composition-overflow-") as folder:
            folder_path = Path(folder)
            config_path = folder_path / "config.json"
            states = []
            for index in range(4):
                states.append(
                    {
                        "id": f"state-{index + 1:03d}",
                        "action": "enter" if index == 0 else "update",
                        "type": "thesis",
                        "card_size": "medium",
                        "content_structure": "core-idea",
                        "size_reason": "完整观点使用默认中卡版式",
                        "reveal_at": 0.3 + index,
                        "title": f"完整信息{index + 1}",
                        "body": "这是一层完整卡片",
                    }
                )
            config_path.write_text(
                json.dumps(
                    {
                        "chapter_en": "OVERFLOW TEST",
                        "chapter_zh": "层高门禁",
                        "accent": "blue",
                        "layout": "fixed-left",
                        "duration": 8,
                        "states": states,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(builder), str(config_path), str(folder_path / "out")],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("690px reference height budget", result.stderr)

    def test_reference_components_reject_generic_body_rows(self) -> None:
        builder = ROOT / "assets" / "composition" / "semantic-stage" / "build.py"
        with tempfile.TemporaryDirectory(prefix="composition-component-") as folder:
            folder_path = Path(folder)
            config_path = folder_path / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "chapter_en": "THE PATH",
                        "chapter_zh": "字段门禁",
                        "accent": "green",
                        "layout": "fixed-left",
                        "duration": 5,
                        "states": [
                            {
                                "action": "enter",
                                "type": "path",
                                "card_size": "small",
                                "content_structure": "vertical-list",
                                "size_reason": "路径短标题使用小卡逐项增加",
                                "reveal_at": 0.3,
                                "title": "正确卡头",
                                "body": "参考片不存在的第三行",
                                "items": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(builder), str(config_path), str(folder_path / "out")],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("cannot render body", result.stderr)

    def test_formula_emits_tone_separated_parts(self) -> None:
        builder = ROOT / "assets" / "composition" / "semantic-stage" / "build.py"
        with tempfile.TemporaryDirectory(prefix="composition-formula-") as folder:
            folder_path = Path(folder)
            config_path = folder_path / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "chapter_en": "UNLOCKED",
                        "chapter_zh": "关系分色",
                        "accent": "green",
                        "layout": "fixed-left",
                        "duration": 5,
                        "states": [
                            {
                                "action": "enter",
                                "type": "formula",
                                "fidelity_mode": "spoken-first",
                                "relation_layout": "formula",
                                "layout_reason": "原话按主项等号结果建立公式",
                                "card_size": "medium",
                                "content_structure": "horizontal-relation",
                                "size_reason": "公式使用最大中卡横向建立",
                                "reveal_at": 0.3,
                                "title": "关系",
                                "parts": [
                                    {"id": "part-001", "text": "前置知识", "tone": "primary", "reveal_at": 0.3},
                                    {"id": "part-002", "text": "=", "tone": "muted", "reveal_at": 1.0},
                                    {"id": "part-003", "text": "自主探索", "tone": "accent", "reveal_at": 1.5},
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            output = folder_path / "out"
            subprocess.run(
                [sys.executable, str(builder), str(config_path), str(output)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            html = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn("tone-primary", html)
            self.assertIn("tone-muted", html)
            self.assertIn("tone-accent", html)
            self.assertIn('id="state-01-part-01"', html)
            self.assertIn('id="state-01-part-02"', html)
            self.assertIn('.fromTo("#state-01-part-02"', html)
            self.assertIn("visibility: hidden", html)

    def test_builder_renders_both_declared_card_sizes(self) -> None:
        builder = ROOT / "assets" / "composition" / "semantic-stage" / "build.py"
        cases = {
            "small": {
                "type": "thesis",
                "content_structure": "short-single",
                "size_reason": "单一短结论使用小卡展示",
                "title": "短结论",
            },
            "medium": {
                "type": "thesis",
                "content_structure": "core-idea",
                "size_reason": "完整核心观点使用默认中卡",
                "title": "核心观点",
                "body": "补充一行完整解释",
            },
        }
        expected_widths = {"small": 373, "medium": 427}
        with tempfile.TemporaryDirectory(prefix="composition-card-sizes-") as folder:
            root = Path(folder)
            for size, state_fields in cases.items():
                config_path = root / f"{size}.json"
                state = {
                    "id": "state-001",
                    "action": "enter",
                    "card_size": size,
                    "reveal_at": 0.3,
                    **state_fields,
                }
                config_path.write_text(
                    json.dumps(
                        {
                            "chapter_en": "CARD SIZE",
                            "chapter_zh": "两档尺寸",
                            "accent": "blue",
                            "layout": "fixed-left",
                            "duration": 4,
                            "states": [state],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                output = root / f"out-{size}"
                subprocess.run(
                    [sys.executable, str(builder), str(config_path), str(output)],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                html = (output / "index.html").read_text(encoding="utf-8")
                spec = json.loads((output / "overlay-spec.json").read_text(encoding="utf-8"))
                self.assertIn(f'data-card-size="{size}"', html)
                self.assertEqual(
                    spec["card_size_selections"][0]["reference_width"],
                    expected_widths[size],
                )

    def test_large_card_is_rejected_everywhere(self) -> None:
        builder = ROOT / "assets" / "composition" / "semantic-stage" / "build.py"
        with tempfile.TemporaryDirectory(prefix="composition-large-guard-") as folder:
            root = Path(folder)
            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "chapter_en": "VERTICAL LIST",
                        "chapter_zh": "禁止大卡",
                        "accent": "green",
                        "layout": "fixed-left",
                        "duration": 4,
                        "states": [
                            {
                                "id": "state-001",
                                "action": "enter",
                                "type": "path",
                                "fidelity_mode": "spoken-first",
                                "relation_layout": "vertical-list",
                                "layout_reason": "原话按步骤竖向展开",
                                "card_size": "large",
                                "content_structure": "vertical-list",
                                "size_reason": "错误示例故意使用大卡触发门禁",
                                "reveal_at": 0.3,
                                "title": "三个步骤",
                                "items": [],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(builder), str(config_path), str(root / "out")],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("card_size must be small or medium", result.stderr)

    def test_semantic_reveal_audit_requires_exact_covered_spoken_events(self) -> None:
        auditor = ROOT / "scripts" / "audit_semantic_reveal.py"
        with tempfile.TemporaryDirectory(prefix="composition-semantic-") as folder:
            root = Path(folder)
            words = [
                {
                    "word_id": f"word-{index}",
                    "text": text,
                    "start": round((index - 1) * 0.5, 3),
                    "end": round(index * 0.5, 3),
                }
                for index, text in enumerate("开始介绍流程", start=1)
            ]
            brief = root / "brief.json"
            timeline = root / "timeline.json"
            plan = root / "plan.json"
            reveal = root / "reveal.json"
            report = root / "report.json"
            brief.write_text("{}\n", encoding="utf-8")
            timeline.write_text(
                json.dumps({"duration": 3.0, "words": words}, ensure_ascii=False),
                encoding="utf-8",
            )
            plan.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "segments": [
                            {
                                "id": "chapter-001",
                                "source_word_ids": ["word-1", "word-6"],
                                "config": {
                                    "states": [
                                        {
                                            "id": "state-001",
                                            "action": "enter",
                                            "type": "path",
                                            "card_size": "small",
                                            "content_structure": "vertical-list",
                                            "size_reason": "路径短标题使用小卡逐项增加",
                                            "title": "介绍流程",
                                            "trigger_word_ids": ["word-1"],
                                            "items": [
                                                {
                                                    "id": "item-001",
                                                    "text": "流程",
                                                    "trigger_word_ids": ["word-5"],
                                                }
                                            ],
                                        }
                                    ]
                                },
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            reveal.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "policy": "exact-spoken-reveal",
                        "events": [
                            {
                                "id": "reveal-state",
                                "segment_id": "chapter-001",
                                "visual_id": "state-001",
                                "unit": "state",
                                "role": "setup",
                                "spoken_excerpt": "开始介绍",
                                "evidence_start_word_id": "word-1",
                                "evidence_end_word_id": "word-4",
                                "earliest_allowed_word_id": "word-1",
                                "trigger_word_id": "word-1",
                                "fully_visible_by_word_id": "word-2",
                                "hold_until_word_id": "word-6",
                                "timing_reason": "主题开始时建立流程卡片",
                                "spoiler_check": {
                                    "passed": True,
                                    "reason": "只展示已经开始介绍的流程主题",
                                },
                            },
                            {
                                "id": "reveal-item",
                                "segment_id": "chapter-001",
                                "visual_id": "item-001",
                                "unit": "item",
                                "role": "explain",
                                "spoken_excerpt": "流程",
                                "evidence_start_word_id": "word-5",
                                "evidence_end_word_id": "word-6",
                                "earliest_allowed_word_id": "word-5",
                                "trigger_word_id": "word-5",
                                "fully_visible_by_word_id": "word-6",
                                "hold_until_word_id": "word-6",
                                "timing_reason": "说到流程二字时增加这一项",
                                "spoiler_check": {
                                    "passed": True,
                                    "reason": "出现前没有提前展示流程这一项",
                                },
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(auditor),
                    "--brief",
                    str(brief),
                    "--timeline",
                    str(timeline),
                    "--animation-plan",
                    str(plan),
                    "--reveal-timeline",
                    str(reveal),
                    "--output",
                    str(report),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["coverage_complete"])
            self.assertEqual(payload["event_count"], 2)

            broken = json.loads(reveal.read_text(encoding="utf-8"))
            broken["events"][1]["spoiler_check"]["passed"] = False
            reveal.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(auditor),
                    "--brief",
                    str(brief),
                    "--timeline",
                    str(timeline),
                    "--animation-plan",
                    str(plan),
                    "--reveal-timeline",
                    str(reveal),
                    "--output",
                    str(report),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(result.returncode, 4)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertIn(
                "semantic_spoiler_check_not_approved",
                {item["code"] for item in payload["errors"]},
            )

    def test_semantic_reveal_sheet_renders_three_frame_evidence(self) -> None:
        maker = ROOT / "scripts" / "make_semantic_reveal_sheet.py"
        with tempfile.TemporaryDirectory(prefix="composition-reveal-sheet-") as folder:
            root = Path(folder)
            video = root / "sample.mp4"
            audit = root / "audit.json"
            output = root / "sheet.jpg"
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=#345678:s=640x360:r=25:d=1",
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(video),
                ],
                check=True,
            )
            audit.write_text(
                json.dumps(
                    {
                        "ok": True,
                        "mapped_events": [
                            {
                                "visual_id": "item-001",
                                "role": "explain",
                                "card_text": "剪辑流程",
                                "spoken_excerpt": "这里开始解释剪辑流程",
                                "trigger_time": 0.4,
                                "fully_visible_time": 0.55,
                                "chapter_start": 0.0,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    sys.executable,
                    str(maker),
                    "--video",
                    str(video),
                    "--audit",
                    str(audit),
                    "--output",
                    str(output),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 10_000)

    def test_empty_style_input_locks_reference_skin(self) -> None:
        selector = ROOT / "scripts" / "select_visual_style.py"
        with tempfile.TemporaryDirectory(prefix="composition-style-") as folder:
            input_path = Path(folder) / "input.json"
            output_path = Path(folder) / "output.json"
            input_path.write_text("{}\n", encoding="utf-8")
            subprocess.run(
                [
                    sys.executable,
                    str(selector),
                    "--input",
                    str(input_path),
                    "--output",
                    str(output_path),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            decision = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(decision["style_id"], "dark-reference-fixed")
            self.assertEqual(decision["animation_layout"], "reference-fixed-left")
            self.assertEqual(decision["animation_panel_mode"], "content-panel")


if __name__ == "__main__":
    unittest.main()
