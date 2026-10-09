from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from common import file_fingerprint  # noqa: E402
from build_ass import caption_display_tokens, join_tokens  # noqa: E402
from speech_text import has_embedded_hard_filler, is_hard_filler  # noqa: E402


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


class AIJianjiSpeechRuleTests(unittest.TestCase):
    def test_multiword_asr_correction_renders_as_one_caption_token(self) -> None:
        words = [
            {
                "display": part,
                "asr_correction_span_id": "asr-correction-0001",
                "asr_correction_span_index": index,
                "asr_correction_span_size": 3,
                "asr_correction_span_text": "Agent",
            }
            for index, part in enumerate(("A", "gen", "t"))
        ]
        self.assertEqual(join_tokens(caption_display_tokens(words)), "Agent")

    def test_multiword_asr_correction_cannot_split_across_caption_units(self) -> None:
        words = [
            {
                "display": "A",
                "asr_correction_span_id": "asr-correction-0001",
                "asr_correction_span_index": 0,
                "asr_correction_span_size": 3,
                "asr_correction_span_text": "Agent",
            }
        ]
        with self.assertRaisesRegex(ValueError, "split across caption units"):
            caption_display_tokens(words)

    def test_hard_fillers_are_narrow_and_repetitions_match(self) -> None:
        for value in ("嗯", "呃", "啊啊", "，嗯。", "额呃"):
            self.assertTrue(is_hard_filler(value), value)
        for value in ("然后", "所以", "就是", "那个", "嗯对"):
            self.assertFalse(is_hard_filler(value), value)
        for value in ("嗯对", "嗯，对", "呃我觉得", "啊这个"):
            self.assertTrue(has_embedded_hard_filler(value), value)

    def test_caption_audit_blocks_internal_retained_filler(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "transcript.json"
            plan = root / "plan.json"
            units = root / "units.json"
            report = root / "report.json"
            write_json(
                transcript,
                {
                    "words": [
                        {"word_id": "w1", "text": "你", "start": 0.1, "end": 0.2},
                        {"word_id": "w2", "text": "呃", "start": 0.3, "end": 0.4},
                        {"word_id": "w3", "text": "好", "start": 0.5, "end": 0.6},
                    ]
                },
            )
            write_json(plan, {"segments": [{"source_start": 0.0, "source_end": 0.7}]})
            write_json(
                units,
                {
                    "schema_version": 1,
                    "policy": "semantic-complete",
                    "units": [
                        {
                            "id": "u1",
                            "sentence_id": "sentence-001",
                            "full_sentence_text": "说完",
                            "start_word_id": "w1",
                            "end_word_id": "w3",
                            "boundary_reason": "sentence",
                            "approved": True,
                        }
                    ],
                },
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "audit_caption_units.py"),
                    "--transcript",
                    str(transcript),
                    "--plan",
                    str(plan),
                    "--units",
                    str(units),
                    "--output",
                    str(report),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 4)
            codes = {item["code"] for item in json.loads(report.read_text())["errors"]}
            self.assertIn("retained_hard_fillers", codes)

    def test_one_semantic_unit_can_span_two_physical_segments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "transcript.json"
            plan = root / "plan.json"
            units = root / "units.json"
            report = root / "report.json"
            write_json(
                transcript,
                {
                    "words": [
                        {"word_id": "w1", "text": "说", "start": 0.1, "end": 0.2},
                        {"word_id": "w2", "text": "呃", "start": 0.3, "end": 0.4},
                        {"word_id": "w3", "text": "完", "start": 0.5, "end": 0.6},
                    ]
                },
            )
            write_json(
                plan,
                {
                    "segments": [
                        {"source_start": 0.0, "source_end": 0.25},
                        {"source_start": 0.45, "source_end": 0.7},
                    ]
                },
            )
            write_json(
                units,
                {
                    "schema_version": 1,
                    "policy": "semantic-complete",
                    "units": [
                        {
                            "id": "u1",
                            "sentence_id": "sentence-001",
                            "full_sentence_text": "说完",
                            "start_word_id": "w1",
                            "end_word_id": "w3",
                            "boundary_reason": "sentence",
                            "approved": True,
                        }
                    ],
                },
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "audit_caption_units.py"),
                    "--transcript",
                    str(transcript),
                    "--plan",
                    str(plan),
                    "--units",
                    str(units),
                    "--output",
                    str(report),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(report.read_text())
            self.assertEqual(payload["hard_filler_count"], 0)
            self.assertEqual(payload["units"][0]["word_ids"], ["w1", "w3"])

    def test_subtitle_builder_never_merges_adjacent_semantic_units(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audit = root / "audit.json"
            timeline = root / "timeline.json"
            style = root / "style.json"
            ass = root / "captions.ass"
            captions = root / "captions.json"
            write_json(
                audit,
                {
                    "ok": True,
                    "errors": [],
                    "policy": "semantic-complete",
                    "unit_count": 2,
                    "units": [
                        {"id": "u1", "word_ids": ["w1"], "boundary_reason": "sentence"},
                        {"id": "u2", "word_ids": ["w2"], "boundary_reason": "sentence"},
                    ],
                },
            )
            audit_fingerprint = file_fingerprint(audit)
            write_json(
                timeline,
                {
                    "duration": 1.2,
                    "inputs": {"caption_unit_audit": audit_fingerprint},
                    "words": [
                        {
                            "word_id": "w1",
                            "text": "完",
                            "start": 0.1,
                            "end": 0.4,
                            "caption_unit_id": "u1",
                        },
                        {
                            "word_id": "w2",
                            "text": "下一句",
                            "start": 0.5,
                            "end": 0.9,
                            "caption_unit_id": "u2",
                        },
                    ],
                    "caption_units": [
                        {
                            "id": "u1",
                            "mapped_word_ids": ["w1"],
                            "boundary_reason": "sentence",
                        },
                        {
                            "id": "u2",
                            "mapped_word_ids": ["w2"],
                            "boundary_reason": "sentence",
                        },
                    ],
                },
            )
            write_json(
                style,
                {
                    "font_size_at_1080": 54,
                    "max_fullwidth_chars": 22,
                    "max_duration": 3.8,
                    "min_duration": 0.2,
                    "strip_display_punctuation": True,
                },
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "build_ass.py"),
                    "--timeline",
                    str(timeline),
                    "--caption-unit-audit",
                    str(audit),
                    "--style",
                    str(style),
                    "--output",
                    str(ass),
                    "--captions-json",
                    str(captions),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(captions.read_text())
            self.assertEqual(
                [cue["caption_unit_id"] for cue in payload["cues"]],
                ["u1", "u2"],
            )
            self.assertEqual([cue["text"] for cue in payload["cues"]], ["完", "下一句"])


if __name__ == "__main__":
    unittest.main()
