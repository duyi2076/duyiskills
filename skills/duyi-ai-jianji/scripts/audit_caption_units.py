#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from common import file_fingerprint, load_json, write_json
from contracts import EXIT_BLOCKED
from adaptive_rhythm import analyze_word_span
from speech_text import (
    approved_embedded_semantic_word_ids,
    display_width,
    has_embedded_hard_filler,
    is_hard_filler,
    join_word_text,
    unit_boundary_errors,
)


EPSILON = 0.0005
SCHEMA_VERSION = 1
ALLOWED_BOUNDARY_REASONS = {"sentence", "clause", "breath-group"}
PARTIAL_FIRST_WORD_ENTRY_STRATEGIES = {
    "silero-speech-onset",
    "continuous-speech-zero-cross-splice",
}


def retained_words(
    words: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    timeline_offset: float = 0.0,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    word_by_id = {str(word["word_id"]): word for word in words}
    output_cursor = 0.0
    for segment in segments:
        segment_start = float(segment["source_start"])
        segment_end = float(segment["source_end"])
        boundary = segment.get("boundary_analysis") or {}
        retained = []
        for word in words:
            start = float(word["start"]) + timeline_offset
            end = float(word["end"]) + timeline_offset
            if (
                start >= segment_start - EPSILON
                and end <= segment_end + EPSILON
            ):
                retained.append(word)
        first_id = str(boundary.get("first_meaningful_word_id") or "")
        if (
            boundary.get("entry_strategy")
            in PARTIAL_FIRST_WORD_ENTRY_STRATEGIES
            and first_id in word_by_id
            and all(str(word["word_id"]) != first_id for word in retained)
        ):
            retained.insert(0, word_by_id[first_id])
        previous_end = output_cursor
        for word in retained:
            start = float(word["start"]) + timeline_offset
            end = float(word["end"]) + timeline_offset
            if (
                str(word["word_id"]) == first_id
                and boundary.get("entry_strategy")
                in PARTIAL_FIRST_WORD_ENTRY_STRATEGIES
            ):
                start = max(
                    segment_start,
                    float(
                        boundary.get("speech_onset_seconds")
                        or word["start"]
                    ),
                )
                end = max(end, start + 0.020)
            planned_start = max(
                previous_end,
                output_cursor + start - segment_start,
            )
            planned_end = min(
                output_cursor + segment_end - segment_start,
                max(planned_start + 0.020, output_cursor + end - segment_start),
            )
            mapped = dict(word)
            mapped["_planned_output_start"] = planned_start
            mapped["_planned_output_end"] = planned_end
            output.append(mapped)
            previous_end = planned_end
        output_cursor += segment_end - segment_start
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit explicit semantic caption units against the retained transcript words."
    )
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--units", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--embedded-filler-review")
    parser.add_argument("--max-width", type=float, default=18.0)
    parser.add_argument("--max-duration", type=float, default=3.8)
    parser.add_argument("--adaptive-max-duration", type=float, default=5.5)
    args = parser.parse_args()

    transcript_path = Path(args.transcript).resolve()
    plan_path = Path(args.plan).resolve()
    units_path = Path(args.units).resolve()
    transcript = load_json(transcript_path)
    plan = load_json(plan_path)
    payload = load_json(units_path)
    source_words = transcript.get("words", [])
    segments = plan.get("segments", [])
    timeline_offset = float(
        (plan.get("boundary_refinement") or {}).get(
            "source_timeline_offset_seconds"
        )
        or 0.0
    )
    kept_words = retained_words(source_words, segments, timeline_offset)
    kept_ids = [str(word["word_id"]) for word in kept_words]
    kept_by_id = {str(word["word_id"]): word for word in kept_words}
    source_position = {
        str(word["word_id"]): index for index, word in enumerate(source_words)
    }
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    transcript_fingerprint = file_fingerprint(transcript_path)
    embedded_review_path = (
        Path(args.embedded_filler_review).resolve()
        if args.embedded_filler_review
        else None
    )
    embedded_review = load_json(embedded_review_path) if embedded_review_path else None
    try:
        approved_embedded_ids = approved_embedded_semantic_word_ids(
            embedded_review,
            transcript_sha256=transcript_fingerprint["sha256"],
        )
    except ValueError as exc:
        approved_embedded_ids = set()
        errors.append({"code": "embedded_filler_review_invalid", "message": str(exc)})

    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            {
                "code": "unsupported_caption_units_schema",
                "expected": SCHEMA_VERSION,
                "actual": payload.get("schema_version"),
            }
        )
    if payload.get("policy") != "semantic-complete":
        errors.append(
            {
                "code": "invalid_caption_units_policy",
                "expected": "semantic-complete",
                "actual": payload.get("policy"),
            }
        )

    retained_fillers = [
        {
            "word_id": word["word_id"],
            "text": word["text"],
            "start": word["start"],
            "end": word["end"],
        }
        for word in kept_words
        if is_hard_filler(str(word.get("text", "")))
    ]
    if retained_fillers:
        errors.append(
            {
                "code": "retained_hard_fillers",
                "count": len(retained_fillers),
                "words": retained_fillers,
            }
        )
    embedded_fillers = [
        {
            "word_id": word["word_id"],
            "text": word["text"],
            "start": word["start"],
            "end": word["end"],
        }
        for word in kept_words
        if has_embedded_hard_filler(str(word.get("text", "")))
        and str(word["word_id"]) not in approved_embedded_ids
    ]
    if embedded_fillers:
        errors.append(
            {
                "code": "ambiguous_embedded_hard_fillers",
                "count": len(embedded_fillers),
                "words": embedded_fillers,
            }
        )

    units = payload.get("units")
    if not isinstance(units, list) or not units:
        errors.append({"code": "caption_units_missing_or_empty"})
        units = []

    normalized_units: list[dict[str, Any]] = []
    covered_ids: list[str] = []
    seen_unit_ids: set[str] = set()
    for index, raw in enumerate(units, start=1):
        if not isinstance(raw, dict):
            errors.append({"code": "invalid_caption_unit", "index": index})
            continue
        unit_id = str(raw.get("id") or f"caption-unit-{index:03d}")
        if unit_id in seen_unit_ids:
            errors.append({"code": "duplicate_caption_unit_id", "unit_id": unit_id})
        seen_unit_ids.add(unit_id)
        start_id = str(raw.get("start_word_id") or "")
        end_id = str(raw.get("end_word_id") or "")
        reason = str(raw.get("boundary_reason") or "")
        if raw.get("approved") is not True:
            errors.append({"code": "caption_unit_not_approved", "unit_id": unit_id})
        if reason not in ALLOWED_BOUNDARY_REASONS:
            errors.append(
                {
                    "code": "invalid_boundary_reason",
                    "unit_id": unit_id,
                    "allowed": sorted(ALLOWED_BOUNDARY_REASONS),
                    "actual": reason,
                }
            )
        if start_id not in kept_by_id or end_id not in kept_by_id:
            errors.append(
                {
                    "code": "caption_unit_endpoint_not_retained",
                    "unit_id": unit_id,
                    "start_word_id": start_id,
                    "end_word_id": end_id,
                }
            )
            continue
        start_position = source_position[start_id]
        end_position = source_position[end_id]
        if end_position < start_position:
            errors.append({"code": "caption_unit_reversed", "unit_id": unit_id})
            continue
        unit_words = [
            word
            for word in kept_words
            if start_position
            <= source_position[str(word["word_id"])]
            <= end_position
        ]
        unit_ids = [str(word["word_id"]) for word in unit_words]
        text = join_word_text(unit_words)
        width = display_width(text)
        rhythm_analysis = analyze_word_span(
            unit_words,
            start_key="_planned_output_start",
            end_key="_planned_output_end",
        )
        planned_duration = float(rhythm_analysis["original_duration"])
        projected_duration = float(rhythm_analysis["projected_duration"])
        if width > args.max_width:
            errors.append(
                {
                    "code": "caption_unit_too_wide",
                    "unit_id": unit_id,
                    "width": round(width, 2),
                    "maximum": args.max_width,
                    "text": text,
                }
            )
        if projected_duration > args.adaptive_max_duration:
            errors.append(
                {
                    "code": "caption_unit_too_long",
                    "unit_id": unit_id,
                    "duration": round(projected_duration, 3),
                    "original_duration": round(planned_duration, 3),
                    "maximum": args.adaptive_max_duration,
                    "text": text,
                }
            )
        elif planned_duration > args.max_duration:
            warnings.append(
                {
                    "code": "caption_unit_uses_adaptive_duration",
                    "unit_id": unit_id,
                    "original_duration": round(planned_duration, 3),
                    "projected_duration": round(projected_duration, 3),
                    "preferred_maximum": args.max_duration,
                    "adaptive_maximum": args.adaptive_max_duration,
                    "action": rhythm_analysis["action"],
                    "text": text,
                }
            )
        for boundary_error in unit_boundary_errors(unit_words):
            errors.append(
                {
                    "code": boundary_error,
                    "unit_id": unit_id,
                    "text": text,
                }
            )
        normalized_units.append(
            {
                "id": unit_id,
                "sentence_id": str(raw.get("sentence_id") or ""),
                "full_sentence_text": str(raw.get("full_sentence_text") or ""),
                "start_word_id": start_id,
                "end_word_id": end_id,
                "boundary_reason": reason,
                "approved": True,
                "text": text,
                "display_width": round(width, 2),
                "planned_duration": round(planned_duration, 3),
                "projected_duration": round(projected_duration, 3),
                "rhythm_analysis": rhythm_analysis,
                "word_ids": unit_ids,
            }
        )
        covered_ids.extend(unit_ids)

    sentence_groups: dict[str, list[dict[str, Any]]] = {}
    for unit in normalized_units:
        sentence_id = unit["sentence_id"]
        full_sentence_text = unit["full_sentence_text"]
        if not sentence_id or not full_sentence_text:
            errors.append(
                {
                    "code": "locked_sentence_metadata_missing",
                    "unit_id": unit["id"],
                }
            )
            continue
        sentence_groups.setdefault(sentence_id, []).append(unit)
    for sentence_id, rows in sentence_groups.items():
        expected_values = {row["full_sentence_text"] for row in rows}
        if len(expected_values) != 1:
            errors.append(
                {
                    "code": "locked_sentence_text_inconsistent",
                    "sentence_id": sentence_id,
                }
            )

    if covered_ids != kept_ids:
        expected = set(kept_ids)
        actual = set(covered_ids)
        duplicates = sorted(
            word_id for word_id in actual if covered_ids.count(word_id) > 1
        )
        errors.append(
            {
                "code": "caption_unit_coverage_mismatch",
                "missing_word_ids": [
                    word_id for word_id in kept_ids if word_id not in actual
                ],
                "duplicate_word_ids": duplicates,
                "unexpected_word_ids": [
                    word_id for word_id in covered_ids if word_id not in expected
                ],
                "order_matches": covered_ids == kept_ids,
            }
        )

    report = {
        "schema_version": SCHEMA_VERSION,
        "ok": not errors,
        "policy": "semantic-complete",
        "inputs": {
            "transcript": transcript_fingerprint,
            "plan": file_fingerprint(plan_path),
            "units": file_fingerprint(units_path),
            "embedded_filler_review": (
                file_fingerprint(embedded_review_path) if embedded_review_path else None
            ),
        },
        "limits": {
            "max_display_width": args.max_width,
            "max_duration_seconds": args.max_duration,
            "adaptive_max_duration_seconds": args.adaptive_max_duration,
        },
        "retained_word_count": len(kept_words),
        "retained_word_ids": kept_ids,
        "hard_filler_count": len(retained_fillers),
        "ambiguous_embedded_filler_count": len(embedded_fillers),
        "approved_embedded_semantic_word_ids": sorted(approved_embedded_ids),
        "unit_count": len(normalized_units),
        "units": normalized_units,
        "errors": errors,
        "warnings": warnings,
    }
    write_json(args.output, report)
    state = "PASS" if report["ok"] else "BLOCKED"
    print(
        f"caption-unit audit: {state} "
        f"({len(errors)} errors, {len(normalized_units)} units, "
        f"{len(kept_words)} retained words)"
    )
    return 0 if report["ok"] else EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
