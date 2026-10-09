from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_asr_integrity import audit  # noqa: E402


class AIJianjiASRIntegrityTests(unittest.TestCase):
    def fixtures(self, root: Path) -> tuple[Path, Path, Path, Path]:
        source = root / "source.mp4"
        source.write_bytes(b"video")
        asr = root / "asr.json"
        asr.write_text(
            json.dumps(
                {
                    "provider": "agent_plan",
                    "resource_id": "volc.seedasr.sauc.duration",
                    "asr_contract": {
                        "provider_family": "doubao-asr",
                        "provider": "agent_plan",
                        "resource_id": "volc.seedasr.sauc.duration",
                        "word_timing_required": True,
                        "local_asr_forbidden": True,
                    },
                    "source_media": {
                        "path": str(source),
                        "size_bytes": source.stat().st_size,
                        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    },
                    "utterances": [
                        {
                            "text": "你好",
                            "words": [
                                {"text": "你", "start_time": 100, "end_time": 300},
                                {"text": "好", "start_time": 300, "end_time": 500},
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        transcript = root / "transcript.json"
        transcript.write_text(
            json.dumps(
                {
                    "utterances": [
                        {
                            "utterance_id": "utt-0001",
                            "text": "你好",
                            "word_ids": ["word-000001", "word-000002"],
                        }
                    ],
                    "words": [
                        {
                            "word_id": "word-000001",
                            "utterance_id": "utt-0001",
                            "text": "你",
                            "start": 0.1,
                            "end": 0.3,
                        },
                        {
                            "word_id": "word-000002",
                            "utterance_id": "utt-0001",
                            "text": "好",
                            "start": 0.3,
                            "end": 0.5,
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        preflight = root / "preflight.json"
        preflight.write_text(
            json.dumps({"media": {"duration": 1.0}}, ensure_ascii=False),
            encoding="utf-8",
        )
        return source, asr, transcript, preflight

    def test_accepts_source_bound_complete_word_timing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixtures(Path(folder))
            report = audit(
                source_path=paths[0],
                asr_path=paths[1],
                transcript_path=paths[2],
                preflight_path=paths[3],
            )
            self.assertTrue(report["ok"])
            self.assertEqual(report["counts"]["normalized_words"], 2)
            self.assertEqual(
                report["inputs"]["source_media"]["path"], str(paths[0].resolve())
            )

    def test_rejects_zero_duration_or_dropped_word(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixtures(Path(folder))
            transcript = json.loads(paths[2].read_text(encoding="utf-8"))
            transcript["words"][1]["end"] = 0.3
            transcript["utterances"][0]["word_ids"] = ["word-000001"]
            paths[2].write_text(json.dumps(transcript), encoding="utf-8")
            report = audit(
                source_path=paths[0],
                asr_path=paths[1],
                transcript_path=paths[2],
                preflight_path=paths[3],
            )
            self.assertFalse(report["ok"])
            codes = {item["code"] for item in report["errors"]}
            self.assertIn("normalized_word_invalid_range", codes)
            self.assertIn("utterance_word_coverage_mismatch", codes)

    def test_rejects_local_whisper_even_when_word_timing_is_complete(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            paths = self.fixtures(Path(folder))
            asr = json.loads(paths[1].read_text(encoding="utf-8"))
            asr["provider"] = "mlx-whisper"
            asr["asr_contract"]["provider_family"] = "local-asr"
            paths[1].write_text(json.dumps(asr), encoding="utf-8")
            report = audit(
                source_path=paths[0],
                asr_path=paths[1],
                transcript_path=paths[2],
                preflight_path=paths[3],
            )
            self.assertFalse(report["ok"])
            codes = {item["code"] for item in report["errors"]}
            self.assertIn("asr_provider_not_doubao", codes)
            self.assertIn("doubao_asr_contract_missing", codes)


if __name__ == "__main__":
    unittest.main()
