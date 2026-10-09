#!/usr/bin/env python3
"""Apply approved word-level ASR corrections while preserving word timing."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from common import load_json, write_json
from contracts import EXIT_BLOCKED, EXIT_SUCCESS, PIPELINE_VERSION


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def apply_corrections(
    transcript: dict[str, Any],
    review: dict[str, Any],
    *,
    transcript_sha256: str,
    source_media_sha256: str,
    asr_integrity_sha256: str,
) -> dict[str, Any]:
    if review.get("schema_version") != 1:
        raise ValueError("asr-corrections.json schema_version must be 1")
    if review.get("policy") != "word-level-asr-errors-only":
        raise ValueError(
            "asr-corrections.json policy must be 'word-level-asr-errors-only'"
        )
    if review.get("reviewed") is not True:
        raise PermissionError("ASR word review must set reviewed=true")
    if review.get("transcript_sha256") != transcript_sha256:
        raise ValueError("ASR correction review does not match the normalized transcript")
    if review.get("source_media_sha256") != source_media_sha256:
        raise ValueError("ASR correction review does not match the current source video")
    if review.get("asr_integrity_sha256") != asr_integrity_sha256:
        raise ValueError("ASR correction review does not match the current ASR integrity report")
    corrections = review.get("corrections")
    if not isinstance(corrections, list):
        raise ValueError("asr-corrections.json corrections must be an array")
    unresolved = review.get("unresolved", [])
    if not isinstance(unresolved, list):
        raise ValueError("asr-corrections.json unresolved must be an array")
    if unresolved:
        raise PermissionError(
            "ASR review has unresolved tokens: "
            + ", ".join(
                str(item.get("word_id") if isinstance(item, dict) else item)
                for item in unresolved
            )
        )
    preserved_uncertain = review.get("preserved_uncertain", [])
    if not isinstance(preserved_uncertain, list):
        raise ValueError(
            "asr-corrections.json preserved_uncertain must be an array"
        )

    words = transcript.get("words")
    if not isinstance(words, list) or not words:
        raise ValueError("normalized transcript must contain words")
    word_by_id = {
        str(word.get("word_id")): word
        for word in words
        if isinstance(word, dict) and word.get("word_id")
    }
    word_position = {
        str(word.get("word_id")): index
        for index, word in enumerate(words)
        if isinstance(word, dict) and word.get("word_id")
    }
    seen: set[str] = set()
    applied: list[dict[str, Any]] = []
    for index, raw in enumerate(corrections, start=1):
        correction = require_mapping(raw, f"correction {index}")
        raw_word_ids = correction.get("word_ids")
        if raw_word_ids is None:
            raw_word_ids = [correction.get("word_id")]
        if (
            not isinstance(raw_word_ids, list)
            or not raw_word_ids
            or len(raw_word_ids) > 8
        ):
            raise ValueError(f"correction {index} word_ids must contain 1-8 ids")
        word_ids = [str(item or "") for item in raw_word_ids]
        unknown = [word_id for word_id in word_ids if word_id not in word_by_id]
        if unknown:
            raise ValueError(f"correction {index} has unknown word_ids {unknown!r}")
        if len(set(word_ids)) != len(word_ids):
            raise ValueError(f"correction {index} repeats a word_id")
        positions = [word_position[word_id] for word_id in word_ids]
        if positions != list(range(positions[0], positions[0] + len(positions))):
            raise ValueError(f"correction {index} word_ids must be contiguous")
        correction_words = [word_by_id[word_id] for word_id in word_ids]
        utterance_ids = {str(word.get("utterance_id") or "") for word in correction_words}
        if len(utterance_ids) != 1:
            raise ValueError(f"correction {index} cannot cross utterances")
        overlap = sorted(set(word_ids) & seen)
        if overlap:
            raise ValueError(f"words corrected more than once: {overlap}")
        seen.update(word_ids)
        original = str(correction.get("original") or "")
        corrected = str(correction.get("corrected") or "").strip()
        actual_original = "".join(str(word.get("text") or "") for word in correction_words)
        if original != actual_original:
            raise ValueError(
                f"correction {index} original does not match {word_ids}"
            )
        if not corrected or "\n" in corrected or len(corrected) > 64:
            raise ValueError(f"correction {index} corrected text is not one short token")
        raw_parts = correction.get("corrected_parts")
        if len(word_ids) == 1 and raw_parts is None:
            corrected_parts = [corrected]
        else:
            if (
                not isinstance(raw_parts, list)
                or len(raw_parts) != len(word_ids)
                or any(not str(part) or "\n" in str(part) for part in raw_parts)
            ):
                raise ValueError(
                    f"correction {index} corrected_parts must match word_ids"
                )
            corrected_parts = [str(part) for part in raw_parts]
            if "".join(corrected_parts) != corrected:
                raise ValueError(
                    f"correction {index} corrected_parts do not form corrected text"
                )
        if correction.get("kind") != "asr_error":
            raise ValueError(f"correction {index} kind must be 'asr_error'")
        if correction.get("evidence") != "audio-and-context":
            raise ValueError(
                f"correction {index} evidence must be 'audio-and-context'"
            )
        if correction.get("confidence") != "high":
            raise PermissionError(
                f"correction {index} is not high-confidence; leave it unchanged and flag it"
            )
        if correction.get("approved") is not True:
            raise PermissionError(f"correction {index} must be approved")
        if corrected == original:
            raise ValueError(f"correction {index} does not change the ASR token")
        span_id = f"asr-correction-{index:04d}"
        for span_index, (word, corrected_part) in enumerate(
            zip(correction_words, corrected_parts, strict=True)
        ):
            word["asr_text"] = str(word.get("text") or "")
            word["text"] = corrected_part
            word["asr_correction_span_id"] = span_id
            word["asr_correction_span_index"] = span_index
            word["asr_correction_span_size"] = len(correction_words)
            word["asr_correction_span_text"] = corrected
        applied.append(
            {
                "word_ids": word_ids,
                "original": original,
                "corrected": corrected,
                "corrected_parts": corrected_parts,
                "start": correction_words[0].get("start"),
                "end": correction_words[-1].get("end"),
            }
        )

    preserved: list[dict[str, Any]] = []
    preserved_ids: set[str] = set()
    for index, raw in enumerate(preserved_uncertain, start=1):
        item = require_mapping(raw, f"preserved_uncertain {index}")
        word_id = str(item.get("word_id") or "")
        if word_id not in word_by_id:
            raise ValueError(
                f"preserved_uncertain {index} has unknown word_id {word_id!r}"
            )
        if word_id in seen or word_id in preserved_ids:
            raise ValueError(
                f"preserved_uncertain {index} repeats a reviewed word_id"
            )
        original = str(item.get("original") or "")
        actual_original = str(word_by_id[word_id].get("text") or "")
        if original != actual_original:
            raise ValueError(
                f"preserved_uncertain {index} original does not match {word_id}"
            )
        if item.get("decision") != "preserve_asr":
            raise ValueError(
                f"preserved_uncertain {index} decision must be 'preserve_asr'"
            )
        if item.get("confidence") != "not-high":
            raise ValueError(
                f"preserved_uncertain {index} confidence must be 'not-high'"
            )
        reason = str(item.get("reason") or "").strip()
        if not reason:
            raise ValueError(
                f"preserved_uncertain {index} must explain why evidence is insufficient"
            )
        preserved_ids.add(word_id)
        preserved.append(
            {
                "word_id": word_id,
                "original": original,
                "decision": "preserve_asr",
                "confidence": "not-high",
                "reason": reason,
            }
        )

    utterance_by_id = {
        str(item.get("utterance_id")): item
        for item in transcript.get("utterances", [])
        if isinstance(item, dict) and item.get("utterance_id")
    }
    for utterance_id, utterance in utterance_by_id.items():
        utterance["text"] = "".join(
            str(word.get("text") or "")
            for word in words
            if str(word.get("utterance_id")) == utterance_id
        )
    transcript["text"] = "".join(str(word.get("text") or "") for word in words)
    transcript["pipeline_version"] = PIPELINE_VERSION
    transcript["asr_correction"] = {
        "policy": "word-level-asr-errors-only",
        "reviewed": True,
        "applied_count": len(applied),
        "applied": applied,
        "unresolved_count": 0,
        "preserved_uncertain_count": len(preserved),
        "preserved_uncertain": preserved,
    }
    return transcript


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply approved word-level ASR corrections."
    )
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--integrity", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    transcript_path = Path(args.transcript).resolve()
    review_path = Path(args.review).resolve()
    source_path = Path(args.source).resolve()
    integrity_path = Path(args.integrity).resolve()
    try:
        integrity = load_json(integrity_path)
        if integrity.get("ok") is not True:
            raise PermissionError("ASR integrity report must pass before correction")
        integrity_inputs = integrity.get("inputs") or {}
        if (
            (integrity_inputs.get("source_media") or {}).get("sha256")
            != sha256_file(source_path)
            or (integrity_inputs.get("normalized_transcript") or {}).get("sha256")
            != sha256_file(transcript_path)
        ):
            raise ValueError("ASR integrity report does not match current inputs")
        corrected = apply_corrections(
            load_json(transcript_path),
            load_json(review_path),
            transcript_sha256=sha256_file(transcript_path),
            source_media_sha256=sha256_file(source_path),
            asr_integrity_sha256=sha256_file(integrity_path),
        )
        corrected["inputs"] = {
            "normalized_transcript_sha256": sha256_file(transcript_path),
            "asr_corrections_sha256": sha256_file(review_path),
            "source_media_sha256": sha256_file(source_path),
            "asr_integrity_sha256": sha256_file(integrity_path),
        }
        locked_master_sha256 = str(
            load_json(review_path).get("locked_text_master_sha256") or ""
        )
        if locked_master_sha256:
            corrected["inputs"]["locked_text_master_sha256"] = locked_master_sha256
            corrected["locked_text_master_sha256"] = locked_master_sha256
        write_json(args.output, corrected)
    except PermissionError as error:
        print(str(error), file=sys.stderr)
        return EXIT_BLOCKED
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_BLOCKED
    print(
        f"ASR corrections: {corrected['asr_correction']['applied_count']} -> "
        f"{args.output}"
    )
    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main())
