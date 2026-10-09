from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from adaptive_rhythm import (  # noqa: E402
    ADAPTIVE_CUE_DURATION,
    analyze_timeline,
    analyze_word_span,
    build_pieces,
    map_anchors,
    remap_timeline,
)


def word(index: int, text: str, start: float, end: float) -> dict:
    return {
        "word_id": f"word-{index:06d}",
        "text": text,
        "start": start,
        "end": end,
        "caption_unit_id": "cue-001",
    }


class AdaptiveRhythmTests(unittest.TestCase):
    def test_compresses_long_pause_before_speeding_normal_articulation(self) -> None:
        words = [
            word(1, "第", 0.0, 0.2),
            word(2, "二", 0.2, 0.4),
            word(3, "个", 0.4, 0.6),
            word(4, "如", 1.3, 1.5),
            word(5, "果", 1.5, 1.7),
            word(6, "输", 1.7, 1.9),
            word(7, "入", 1.9, 2.1),
            word(8, "错", 2.1, 2.3),
            word(9, "误", 2.3, 2.5),
        ]
        analysis = analyze_word_span(words)
        self.assertEqual(analysis["diagnosis"], "excessive-pause")
        self.assertEqual(analysis["speed_factor"], 1.0)
        self.assertEqual(len(analysis["pause_edits"]), 1)
        self.assertLess(analysis["projected_duration"], analysis["original_duration"])

    def test_caps_slow_local_speed_and_protects_mixed_language(self) -> None:
        slow = [
            word(index, text, (index - 1) * 0.6, (index - 1) * 0.6 + 0.45)
            for index, text in enumerate("这是一个比较缓慢完整表达", start=1)
        ]
        analysis = analyze_word_span(slow)
        self.assertEqual(analysis["action"], "speed-local-speech")
        self.assertGreater(analysis["speed_factor"], 1.0)
        self.assertLessEqual(analysis["speed_factor"], 1.15)

        mixed = [dict(item) for item in slow]
        mixed[3]["text"] = "Claude"
        protected = analyze_word_span(mixed)
        self.assertTrue(protected["protected"])
        self.assertEqual(protected["speed_factor"], 1.0)

    def test_piecewise_remap_preserves_word_order(self) -> None:
        words = [
            word(1, "这", 0.2, 0.5),
            word(2, "是", 0.5, 0.8),
            word(3, "一", 1.5, 1.8),
            word(4, "个", 1.8, 2.1),
            word(5, "测", 2.1, 2.4),
            word(6, "试", 2.4, 2.7),
            word(7, "句", 2.7, 3.0),
            word(8, "子", 3.0, 3.3),
        ]
        timeline = {
            "version": 2,
            "duration": 4.0,
            "inputs": {},
            "segments": [
                {
                    "id": "keep-001",
                    "output_start": 0.0,
                    "output_end": 4.0,
                    "duration": 4.0,
                }
            ],
            "words": words,
            "caption_units": [
                {
                    "id": "cue-001",
                    "sentence_id": "sentence-001",
                    "mapped_word_ids": [item["word_id"] for item in words],
                    "start": 0.2,
                    "end": 3.3,
                }
            ],
        }
        plan = analyze_timeline(timeline)
        pieces = build_pieces(4.0, plan["decisions"])
        mapped = remap_timeline(timeline, pieces)
        starts = [item["start"] for item in mapped["words"]]
        self.assertEqual(starts, sorted(starts))
        self.assertLess(mapped["duration"], timeline["duration"])
        self.assertLessEqual(
            plan["decisions"][0]["projected_duration"],
            ADAPTIVE_CUE_DURATION,
        )

    def test_animation_anchor_collects_nested_node_word_ids(self) -> None:
        mapped = map_anchors(
            {
                "segments": [
                    {
                        "id": "state-1",
                        "nodes": [
                            {"source_word_ids": ["word-000001"]},
                            {"source_word_ids": ["word-000002"]},
                        ],
                    }
                ]
            },
            {
                "word-000001": {"start": 1.0, "end": 1.2},
                "word-000002": {"start": 1.3, "end": 1.5},
            },
            2.0,
        )
        anchor = mapped["anchors"][0]
        self.assertEqual(
            anchor["source_word_ids"],
            ["word-000001", "word-000002"],
        )
        self.assertEqual(anchor["output_start"], 1.0)
        self.assertEqual(anchor["output_end"], 1.5)

    def test_cli_renders_real_audio_video_and_auditable_plan(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=320x180:r=25:d=4",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:sample_rate=48000:duration=4",
                    "-shortest",
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    str(source),
                ],
                check=True,
            )
            words = [
                word(1, "这", 0.2, 0.5),
                word(2, "是", 0.5, 0.8),
                word(3, "一", 1.6, 1.9),
                word(4, "个", 1.9, 2.2),
                word(5, "真", 2.2, 2.5),
                word(6, "实", 2.5, 2.8),
                word(7, "测", 2.8, 3.1),
                word(8, "试", 3.1, 3.4),
            ]
            timeline = {
                "version": 2,
                "duration": 4.0,
                "inputs": {},
                "segments": [
                    {
                        "id": "keep-001",
                        "output_start": 0.0,
                        "output_end": 4.0,
                        "duration": 4.0,
                    }
                ],
                "words": words,
                "caption_units": [
                    {
                        "id": "cue-001",
                        "sentence_id": "sentence-001",
                        "mapped_word_ids": [item["word_id"] for item in words],
                        "start": 0.2,
                        "end": 3.4,
                    }
                ],
            }
            timeline_path = root / "timeline.json"
            timeline_path.write_text(
                json.dumps(timeline, ensure_ascii=False),
                encoding="utf-8",
            )
            output_video = root / "rhythm.mp4"
            output_timeline = root / "rhythm-timeline.json"
            plan_output = root / "rhythm-plan.json"
            manifest_output = root / "rhythm-manifest.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "adaptive_rhythm.py"),
                    "--input",
                    str(source),
                    "--timeline",
                    str(timeline_path),
                    "--output-video",
                    str(output_video),
                    "--output-timeline",
                    str(output_timeline),
                    "--plan-output",
                    str(plan_output),
                    "--manifest-output",
                    str(manifest_output),
                    "--preset",
                    "ultrafast",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            manifest = json.loads(manifest_output.read_text(encoding="utf-8"))
            plan = json.loads(plan_output.read_text(encoding="utf-8"))
            self.assertTrue(manifest["ok"])
            self.assertGreaterEqual(plan["summary"]["pause_compressions"], 1)
            self.assertLess(
                manifest["output_media"]["duration"],
                4.0,
            )


if __name__ == "__main__":
    unittest.main()
