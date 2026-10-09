#!/usr/bin/env python3
"""Bind normalized word timing to the current ASR file and source video."""
from __future__ import annotations

import argparse
import math
import sys
import unicodedata
from pathlib import Path
from typing import Any

from common import file_fingerprint, load_json, write_json
from contracts import EXIT_BLOCKED, EXIT_SUCCESS, PIPELINE_VERSION


OVERLAP_TOLERANCE_SECONDS = 0.02
MEDIA_TOLERANCE_SECONDS = 0.25
EXPECTED_ASR_PROVIDER = "agent_plan"
EXPECTED_ASR_RESOURCE_ID = "volc.seedasr.sauc.duration"


def find_utterances(payload: Any) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    if isinstance(payload, dict):
        candidates.extend(
            [
                payload.get("utterances"),
                payload.get("result", {}).get("utterances")
                if isinstance(payload.get("result"), dict)
                else None,
                payload.get("raw", {}).get("result", {}).get("utterances")
                if isinstance(payload.get("raw"), dict)
                and isinstance(payload.get("raw", {}).get("result"), dict)
                else None,
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    raise ValueError("cannot find utterances in ASR JSON")


def comparable_text(value: Any) -> str:
    return "".join(
        character.lower()
        for character in str(value or "")
        if not unicodedata.category(character).startswith(("P", "Z"))
    )


def finite_number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def audit(
    *,
    source_path: Path,
    asr_path: Path,
    transcript_path: Path,
    preflight_path: Path,
) -> dict[str, Any]:
    asr = load_json(asr_path)
    transcript = load_json(transcript_path)
    preflight = load_json(preflight_path)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    source_fingerprint = file_fingerprint(source_path)

    if asr.get("provider") != EXPECTED_ASR_PROVIDER:
        errors.append(
            {
                "code": "asr_provider_not_doubao",
                "expected": EXPECTED_ASR_PROVIDER,
                "actual": asr.get("provider"),
            }
        )
    if asr.get("resource_id") != EXPECTED_ASR_RESOURCE_ID:
        errors.append(
            {
                "code": "asr_resource_not_doubao_word_level",
                "expected": EXPECTED_ASR_RESOURCE_ID,
                "actual": asr.get("resource_id"),
            }
        )
    asr_contract = asr.get("asr_contract")
    if (
        not isinstance(asr_contract, dict)
        or asr_contract.get("provider_family") != "doubao-asr"
        or asr_contract.get("local_asr_forbidden") is not True
    ):
        errors.append({"code": "doubao_asr_contract_missing"})
    bound_source = asr.get("source_media")
    if (
        not isinstance(bound_source, dict)
        or bound_source.get("sha256") != source_fingerprint["sha256"]
        or bound_source.get("size_bytes") != source_fingerprint["size_bytes"]
    ):
        errors.append({"code": "doubao_asr_source_binding_mismatch"})

    media_duration = float((preflight.get("media") or {}).get("duration") or 0)
    if media_duration <= 0:
        errors.append({"code": "invalid_media_duration"})

    raw_utterances = find_utterances(asr)
    raw_meaningful_words = 0
    raw_separator_tokens = 0
    for utterance_index, utterance in enumerate(raw_utterances, start=1):
        if not isinstance(utterance, dict):
            errors.append(
                {"code": "invalid_raw_utterance", "utterance": utterance_index}
            )
            continue
        for word_index, raw_word in enumerate(utterance.get("words") or [], start=1):
            if not isinstance(raw_word, dict):
                errors.append(
                    {
                        "code": "invalid_raw_word",
                        "utterance": utterance_index,
                        "word": word_index,
                    }
                )
                continue
            text = str(raw_word.get("text") or "")
            if not text.strip():
                raw_separator_tokens += 1
                continue
            raw_meaningful_words += 1
            try:
                start_ms = finite_number(raw_word.get("start_time"))
                end_ms = finite_number(raw_word.get("end_time"))
            except (TypeError, ValueError):
                errors.append(
                    {
                        "code": "raw_word_invalid_timing",
                        "utterance": utterance_index,
                        "word": word_index,
                        "text": text,
                    }
                )
                continue
            if start_ms < 0 or end_ms <= start_ms:
                errors.append(
                    {
                        "code": "raw_word_invalid_range",
                        "utterance": utterance_index,
                        "word": word_index,
                        "text": text,
                        "start_ms": start_ms,
                        "end_ms": end_ms,
                    }
                )

    words = transcript.get("words")
    if not isinstance(words, list) or not words:
        errors.append({"code": "normalized_words_missing"})
        words = []
    if len(words) != raw_meaningful_words:
        errors.append(
            {
                "code": "normalized_word_count_mismatch",
                "raw_meaningful_words": raw_meaningful_words,
                "normalized_words": len(words),
            }
        )

    seen_ids: set[str] = set()
    previous_start = -1.0
    previous_end = -1.0
    for index, word in enumerate(words, start=1):
        if not isinstance(word, dict):
            errors.append({"code": "normalized_word_invalid", "word": index})
            continue
        word_id = str(word.get("word_id") or "")
        if not word_id or word_id in seen_ids:
            errors.append(
                {"code": "normalized_word_id_invalid", "word": index, "word_id": word_id}
            )
        seen_ids.add(word_id)
        try:
            start = finite_number(word.get("start"))
            end = finite_number(word.get("end"))
        except (TypeError, ValueError):
            errors.append(
                {"code": "normalized_word_invalid_timing", "word_id": word_id}
            )
            continue
        if start < 0 or end <= start:
            errors.append(
                {
                    "code": "normalized_word_invalid_range",
                    "word_id": word_id,
                    "start": start,
                    "end": end,
                }
            )
        if start < previous_start:
            errors.append(
                {
                    "code": "normalized_word_not_monotonic",
                    "word_id": word_id,
                    "start": start,
                    "previous_start": previous_start,
                }
            )
        if previous_end >= 0 and start < previous_end - OVERLAP_TOLERANCE_SECONDS:
            errors.append(
                {
                    "code": "normalized_word_illegal_overlap",
                    "word_id": word_id,
                    "overlap_seconds": round(previous_end - start, 3),
                }
            )
        if media_duration > 0 and end > media_duration + MEDIA_TOLERANCE_SECONDS:
            errors.append(
                {
                    "code": "normalized_word_outside_media",
                    "word_id": word_id,
                    "end": end,
                    "media_duration": media_duration,
                }
            )
        previous_start = start
        previous_end = max(previous_end, end)

    word_by_id = {
        str(word.get("word_id")): word
        for word in words
        if isinstance(word, dict) and word.get("word_id")
    }
    utterances = transcript.get("utterances")
    referenced_word_ids: list[str] = []
    if not isinstance(utterances, list):
        errors.append({"code": "normalized_utterances_missing"})
        utterances = []
    for utterance in utterances:
        if not isinstance(utterance, dict):
            errors.append({"code": "normalized_utterance_invalid"})
            continue
        word_ids = utterance.get("word_ids")
        if not isinstance(word_ids, list):
            errors.append(
                {
                    "code": "normalized_utterance_word_ids_missing",
                    "utterance_id": utterance.get("utterance_id"),
                }
            )
            continue
        referenced_word_ids.extend(str(item) for item in word_ids)
        missing = [str(item) for item in word_ids if str(item) not in word_by_id]
        if missing:
            errors.append(
                {
                    "code": "normalized_utterance_unknown_words",
                    "utterance_id": utterance.get("utterance_id"),
                    "word_ids": missing,
                }
            )
            continue
        joined = "".join(str(word_by_id[str(item)].get("text") or "") for item in word_ids)
        if comparable_text(joined) != comparable_text(utterance.get("text")):
            errors.append(
                {
                    "code": "utterance_text_word_mismatch",
                    "utterance_id": utterance.get("utterance_id"),
                }
            )
    expected_ids = [str(word.get("word_id")) for word in words if isinstance(word, dict)]
    if referenced_word_ids != expected_ids:
        errors.append({"code": "utterance_word_coverage_mismatch"})

    first_start = float(words[0]["start"]) if words else None
    last_end = float(words[-1]["end"]) if words else None
    if words and media_duration > 0:
        leading_gap = max(0.0, first_start or 0.0)
        trailing_gap = max(0.0, media_duration - (last_end or 0.0))
        if leading_gap > 10.0:
            warnings.append(
                {"code": "large_leading_untranscribed_span", "seconds": round(leading_gap, 3)}
            )
        if trailing_gap > 10.0:
            warnings.append(
                {"code": "large_trailing_untranscribed_span", "seconds": round(trailing_gap, 3)}
            )

    return {
        "schema_version": 1,
        "pipeline_version": PIPELINE_VERSION,
        "ok": not errors,
        "policy": "doubao-source-bound-word-timing-integrity",
        "inputs": {
            "source_media": source_fingerprint,
            "asr": file_fingerprint(asr_path),
            "normalized_transcript": file_fingerprint(transcript_path),
            "preflight": file_fingerprint(preflight_path),
        },
        "counts": {
            "raw_utterances": len(raw_utterances),
            "raw_meaningful_words": raw_meaningful_words,
            "raw_separator_tokens": raw_separator_tokens,
            "normalized_words": len(words),
        },
        "timing": {
            "media_duration": media_duration,
            "first_word_start": first_start,
            "last_word_end": last_end,
        },
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--asr", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--preflight", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = audit(
            source_path=Path(args.source).resolve(),
            asr_path=Path(args.asr).resolve(),
            transcript_path=Path(args.transcript).resolve(),
            preflight_path=Path(args.preflight).resolve(),
        )
    except (OSError, TypeError, ValueError) as error:
        report = {
            "schema_version": 1,
            "pipeline_version": PIPELINE_VERSION,
            "ok": False,
            "policy": "doubao-source-bound-word-timing-integrity",
            "errors": [{"code": "integrity_audit_failed", "message": str(error)}],
            "warnings": [],
        }
    write_json(args.output, report)
    print(f"ASR integrity: {'PASS' if report['ok'] else 'BLOCKED'} -> {args.output}")
    return EXIT_SUCCESS if report["ok"] else EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
