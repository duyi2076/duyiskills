from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_editorial_review import build_packet  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AIJianjiEditorialLockTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path, Path, Path, dict]:
        source = root / "source.mov"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x180:r=25:d=2",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-shortest",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                str(source),
            ],
            check=True,
        )
        transcript_path = root / "normalized-transcript.json"
        transcript = {
            "words": [
                {"word_id": "word-000001", "utterance_id": "u1", "text": "嗯", "start": 0.0, "end": 0.2},
                {"word_id": "word-000002", "utterance_id": "u1", "text": "我", "start": 0.25, "end": 0.4},
                {"word_id": "word-000003", "utterance_id": "u1", "text": "说", "start": 0.4, "end": 0.55},
                {"word_id": "word-000004", "utterance_id": "u1", "text": "cloud", "start": 0.55, "end": 0.9},
                {"word_id": "word-000005", "utterance_id": "u1", "text": "可以", "start": 0.9, "end": 1.2},
            ],
            "utterances": [{"utterance_id": "u1", "text": "嗯我说cloud可以"}],
        }
        transcript_path.write_text(
            json.dumps(transcript, ensure_ascii=False), encoding="utf-8"
        )
        integrity = root / "asr-integrity.json"
        integrity.write_text(json.dumps({"ok": True}), encoding="utf-8")
        plan_path = root / "editorial-review-plan.json"
        plan = {
            "schema_version": 1,
            "policy": "one-human-review-before-lock",
            "ai_review_complete": True,
            "inputs": {
                "normalized_transcript_sha256": sha256(transcript_path),
                "source_media_sha256": sha256(source),
                "asr_integrity_sha256": sha256(integrity),
            },
            "subtitle_font_preset": "reference-caption",
            "term_hints": ["Claude"],
            "corrections": [
                {
                    "word_id": "word-000004",
                    "original": "cloud",
                    "corrected": "Claude",
                    "kind": "asr_error",
                    "evidence": "audio-and-context",
                    "confidence": "high",
                    "approved": True,
                }
            ],
            "preserved_uncertain": [],
            "unresolved": [],
            "speaker_issues": [
                {
                    "start_word_id": "word-000003",
                    "end_word_id": "word-000003",
                    "decision": "preserve_original",
                    "reason": "这是说话者实际说出的词，不冒充 ASR 错误",
                }
            ],
            "deletions": [
                {
                    "id": "deletion-001",
                    "start_word_id": "word-000001",
                    "end_word_id": "word-000001",
                    "kind": "filler",
                    "reason": "开篇非语义填充音",
                }
            ],
            "sentences": [
                {
                    "id": "sentence-001",
                    "start_word_id": "word-000002",
                    "end_word_id": "word-000005",
                    "cues": [
                        {
                            "id": "cue-001",
                            "start_word_id": "word-000002",
                            "end_word_id": "word-000004",
                            "boundary_reason": "clause",
                        },
                        {
                            "id": "cue-002",
                            "start_word_id": "word-000005",
                            "end_word_id": "word-000005",
                            "boundary_reason": "sentence",
                        },
                    ],
                }
            ],
            "semantic_map": {
                "schema_version": 1,
                "policy": "spoken-semantic-map",
                "propositions": [],
            },
        }
        plan_path.write_text(
            json.dumps(plan, ensure_ascii=False), encoding="utf-8"
        )
        return source, transcript_path, integrity, plan_path, transcript

    def test_builds_one_complete_human_packet_and_locks_derivatives(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, transcript_path, integrity, plan_path, transcript = self.fixture(root)
            packet, markdown = build_packet(
                copy.deepcopy(transcript),
                json.loads(plan_path.read_text(encoding="utf-8")),
                transcript_path=transcript_path,
                plan_path=plan_path,
                source_path=source,
                integrity_path=integrity,
                width=1920,
                height=1080,
            )
            self.assertEqual(packet["status"], "awaiting_single_human_review")
            self.assertEqual(packet["summary"]["deleted_words"], 1)
            self.assertEqual(packet["summary"]["asr_corrections"], 1)
            self.assertEqual(packet["summary"]["subtitle_cues"], 2)
            self.assertEqual(packet["sentences"][0]["cues"][0]["text"], "我说 Claude")
            self.assertEqual(packet["sentences"][0]["cues"][1]["text"], "可以")
            self.assertIn("<u>嗯</u>", markdown)
            self.assertIn("原转写：cloud", markdown)
            self.assertIn("cue-001", markdown)

            packet_path = root / "editorial-review.json"
            packet_path.write_text(
                json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            outputs = {
                "output": root / "locked-editorial-master.json",
                "corrected-transcript-output": root / "corrected-transcript.json",
                "asr-corrections-output": root / "asr-corrections.json",
                "cut-plan-output": root / "cut-plan.json",
                "caption-units-output": root / "caption-units.json",
                "semantic-map-output": root / "semantic-map.json",
            }
            command = [
                sys.executable,
                str(ROOT / "scripts" / "lock_editorial_review.py"),
                "--packet",
                str(packet_path),
                "--confirmation-note",
                "用户一次确认通过",
                "--user-confirmed",
            ]
            for flag, path in outputs.items():
                command.extend([f"--{flag}", str(path)])
            subprocess.run(command, check=True, capture_output=True, text=True)
            master_sha = sha256(outputs["output"])
            for key in (
                "corrected-transcript-output",
                "asr-corrections-output",
                "cut-plan-output",
                "caption-units-output",
                "semantic-map-output",
            ):
                payload = json.loads(outputs[key].read_text(encoding="utf-8"))
                self.assertEqual(payload["locked_text_master_sha256"], master_sha)

    def test_rejects_second_round_or_unfinished_ai_review(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, transcript_path, integrity, plan_path, transcript = self.fixture(root)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["ai_review_complete"] = False
            with self.assertRaises(PermissionError):
                build_packet(
                    transcript,
                    plan,
                    transcript_path=transcript_path,
                    plan_path=plan_path,
                    source_path=source,
                    integrity_path=integrity,
                    width=1920,
                    height=1080,
                )

    def test_rejects_overlong_cue_before_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, transcript_path, integrity, plan_path, transcript = self.fixture(root)
            transcript["words"][-1]["end"] = 7.0
            transcript_path.write_text(
                json.dumps(transcript, ensure_ascii=False), encoding="utf-8"
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["inputs"]["normalized_transcript_sha256"] = sha256(transcript_path)
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ValueError,
                "exceeds the adaptive subtitle duration contract",
            ):
                build_packet(
                    transcript,
                    plan,
                    transcript_path=transcript_path,
                    plan_path=plan_path,
                    source_path=source,
                    integrity_path=integrity,
                    width=1920,
                    height=1080,
                )

    def test_rejects_forbidden_cue_boundary_before_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source, transcript_path, integrity, plan_path, transcript = self.fixture(root)
            transcript["words"][1]["text"] = "把"
            transcript_path.write_text(
                json.dumps(transcript, ensure_ascii=False), encoding="utf-8"
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["inputs"]["normalized_transcript_sha256"] = sha256(transcript_path)
            plan["sentences"][0]["cues"][0]["end_word_id"] = "word-000002"
            plan["sentences"][0]["cues"][1]["start_word_id"] = "word-000003"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ValueError,
                "violates subtitle boundary contract",
            ):
                build_packet(
                    transcript,
                    plan,
                    transcript_path=transcript_path,
                    plan_path=plan_path,
                    source_path=source,
                    integrity_path=integrity,
                    width=1920,
                    height=1080,
                )


if __name__ == "__main__":
    unittest.main()
