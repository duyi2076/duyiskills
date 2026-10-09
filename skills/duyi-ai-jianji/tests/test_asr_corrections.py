from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from apply_asr_corrections import apply_corrections  # noqa: E402


def canonical_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode()


class AIJianjiASRCorrectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.transcript = {
            "words": [
                {
                    "word_id": "word-000001",
                    "utterance_id": "utt-0001",
                    "text": "cloud",
                    "start": 1.0,
                    "end": 1.4,
                },
                {
                    "word_id": "word-000002",
                    "utterance_id": "utt-0001",
                    "text": "很好用",
                    "start": 1.4,
                    "end": 2.0,
                },
            ],
            "utterances": [
                {
                    "utterance_id": "utt-0001",
                    "text": "cloud很好用",
                    "word_ids": ["word-000001", "word-000002"],
                }
            ],
            "text": "cloud很好用",
        }
        self.digest = hashlib.sha256(canonical_bytes(self.transcript)).hexdigest()
        self.source_digest = "source-sha256"
        self.integrity_digest = "integrity-sha256"

    def review(self) -> dict:
        return {
            "schema_version": 1,
            "policy": "word-level-asr-errors-only",
            "reviewed": True,
            "transcript_sha256": self.digest,
            "source_media_sha256": self.source_digest,
            "asr_integrity_sha256": self.integrity_digest,
            "unresolved": [],
            "preserved_uncertain": [],
            "corrections": [
                {
                    "word_id": "word-000001",
                    "original": "cloud",
                    "corrected": "Claude",
                    "kind": "asr_error",
                    "evidence": "audio-and-context",
                    "confidence": "high",
                    "approved": True,
                }
            ],
        }

    def test_applies_one_word_without_changing_timing_or_id(self) -> None:
        result = apply_corrections(
            copy.deepcopy(self.transcript),
            self.review(),
            transcript_sha256=self.digest,
            source_media_sha256=self.source_digest,
            asr_integrity_sha256=self.integrity_digest,
        )
        word = result["words"][0]
        self.assertEqual(word["word_id"], "word-000001")
        self.assertEqual((word["start"], word["end"]), (1.0, 1.4))
        self.assertEqual(word["asr_text"], "cloud")
        self.assertEqual(word["text"], "Claude")
        self.assertEqual(result["utterances"][0]["text"], "Claude很好用")
        self.assertEqual(result["asr_correction"]["applied_count"], 1)

    def test_empty_review_is_valid_and_preserves_words(self) -> None:
        review = self.review()
        review["corrections"] = []
        result = apply_corrections(
            copy.deepcopy(self.transcript),
            review,
            transcript_sha256=self.digest,
            source_media_sha256=self.source_digest,
            asr_integrity_sha256=self.integrity_digest,
        )
        self.assertEqual(result["words"][0]["text"], "cloud")
        self.assertEqual(result["asr_correction"]["applied_count"], 0)

    def test_repairs_one_lexical_term_split_across_contiguous_tokens(self) -> None:
        transcript = copy.deepcopy(self.transcript)
        transcript["words"] = [
            {
                "word_id": "word-000001",
                "utterance_id": "utt-0001",
                "text": "a",
                "start": 1.0,
                "end": 1.1,
            },
            {
                "word_id": "word-000002",
                "utterance_id": "utt-0001",
                "text": "镜",
                "start": 1.1,
                "end": 1.2,
            },
            {
                "word_id": "word-000003",
                "utterance_id": "utt-0001",
                "text": "头",
                "start": 1.2,
                "end": 1.4,
            },
        ]
        transcript["utterances"][0]["word_ids"] = [
            "word-000001",
            "word-000002",
            "word-000003",
        ]
        transcript["utterances"][0]["text"] = "a镜头"
        transcript["text"] = "a镜头"
        digest = hashlib.sha256(canonical_bytes(transcript)).hexdigest()
        review = {
            "schema_version": 1,
            "policy": "word-level-asr-errors-only",
            "reviewed": True,
            "transcript_sha256": digest,
            "source_media_sha256": self.source_digest,
            "asr_integrity_sha256": self.integrity_digest,
            "unresolved": [],
            "corrections": [
                {
                    "word_ids": [
                        "word-000001",
                        "word-000002",
                        "word-000003",
                    ],
                    "original": "a镜头",
                    "corrected": "Agent",
                    "corrected_parts": ["A", "gen", "t"],
                    "kind": "asr_error",
                    "evidence": "audio-and-context",
                    "confidence": "high",
                    "approved": True,
                }
            ],
        }
        result = apply_corrections(
            transcript,
            review,
            transcript_sha256=digest,
            source_media_sha256=self.source_digest,
            asr_integrity_sha256=self.integrity_digest,
        )
        self.assertEqual(
            [word["text"] for word in result["words"]],
            ["A", "gen", "t"],
        )
        self.assertEqual(
            [word["asr_correction_span_index"] for word in result["words"]],
            [0, 1, 2],
        )
        self.assertEqual(
            {word["asr_correction_span_text"] for word in result["words"]},
            {"Agent"},
        )
        self.assertEqual(result["utterances"][0]["text"], "Agent")

    def test_rejects_speaker_rewrite_or_uncertain_guess(self) -> None:
        review = self.review()
        review["corrections"][0]["kind"] = "speaker_rewrite"
        with self.assertRaisesRegex(ValueError, "kind must be 'asr_error'"):
            apply_corrections(
                copy.deepcopy(self.transcript),
                review,
                transcript_sha256=self.digest,
                source_media_sha256=self.source_digest,
                asr_integrity_sha256=self.integrity_digest,
            )
        review = self.review()
        review["corrections"][0]["confidence"] = "medium"
        with self.assertRaisesRegex(PermissionError, "not high-confidence"):
            apply_corrections(
                copy.deepcopy(self.transcript),
                review,
                transcript_sha256=self.digest,
                source_media_sha256=self.source_digest,
                asr_integrity_sha256=self.integrity_digest,
            )

    def test_rejects_original_mismatch(self) -> None:
        review = self.review()
        review["corrections"][0]["original"] = "Claude"
        with self.assertRaisesRegex(ValueError, "original does not match"):
            apply_corrections(
                copy.deepcopy(self.transcript),
                review,
                transcript_sha256=self.digest,
                source_media_sha256=self.source_digest,
                asr_integrity_sha256=self.integrity_digest,
            )

    def test_unresolved_audio_is_blocked_instead_of_guessed(self) -> None:
        review = self.review()
        review["corrections"] = []
        review["unresolved"] = [
            {"word_id": "word-000001", "reason": "audio is ambiguous"}
        ]
        with self.assertRaisesRegex(PermissionError, "unresolved tokens"):
            apply_corrections(
                copy.deepcopy(self.transcript),
                review,
                transcript_sha256=self.digest,
                source_media_sha256=self.source_digest,
                asr_integrity_sha256=self.integrity_digest,
            )

    def test_low_confidence_word_is_preserved_and_logged(self) -> None:
        review = self.review()
        review["corrections"] = []
        review["preserved_uncertain"] = [
            {
                "word_id": "word-000001",
                "original": "cloud",
                "decision": "preserve_asr",
                "confidence": "not-high",
                "reason": "上下文不足以确认这是专有名词还是普通词",
            }
        ]
        result = apply_corrections(
            copy.deepcopy(self.transcript),
            review,
            transcript_sha256=self.digest,
            source_media_sha256=self.source_digest,
            asr_integrity_sha256=self.integrity_digest,
        )
        self.assertEqual(result["words"][0]["text"], "cloud")
        self.assertEqual(result["asr_correction"]["unresolved_count"], 0)
        self.assertEqual(
            result["asr_correction"]["preserved_uncertain_count"],
            1,
        )

    def test_preserved_uncertain_requires_explicit_safe_decision(self) -> None:
        review = self.review()
        review["corrections"] = []
        review["preserved_uncertain"] = [
            {
                "word_id": "word-000001",
                "original": "cloud",
                "decision": "guess",
                "confidence": "not-high",
                "reason": "证据不足",
            }
        ]
        with self.assertRaisesRegex(ValueError, "decision must be 'preserve_asr'"):
            apply_corrections(
                copy.deepcopy(self.transcript),
                review,
                transcript_sha256=self.digest,
                source_media_sha256=self.source_digest,
                asr_integrity_sha256=self.integrity_digest,
            )


if __name__ == "__main__":
    unittest.main()
