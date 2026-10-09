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
from contracts import AUDIT_REPORT_SCHEMA_VERSION, EXIT_BLOCKED, PIPELINE_VERSION
from speech_text import (
    approved_embedded_semantic_word_ids,
    has_embedded_hard_filler,
    is_hard_filler,
)


EPSILON = 0.0005
MIN_START_MARGIN = 0.020
MAX_START_MARGIN = 0.090
MIN_END_MARGIN = 0.020
MAX_END_MARGIN = 0.350
EXPECTED_BOUNDARY_METHOD = "asr-plus-silero-vad-plus-energy"
CONTINUOUS_SPLICE_STRATEGY = "continuous-speech-zero-cross-splice"
CONTINUOUS_SPLICE_PREROLL = 0.004
CONTINUOUS_SPLICE_POSTROLL = 0.002
CONTINUOUS_SPLICE_MAX_FADE_MS = 6.0


def boundary_inside_word(
    boundary: float,
    words: list[dict[str, Any]],
    timeline_offset: float = 0.0,
) -> dict[str, Any] | None:
    for word in words:
        start = float(word["start"]) + timeline_offset
        end = float(word["end"]) + timeline_offset
        if start + EPSILON < boundary < end - EPSILON:
            return word
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a source-timeline cut plan.")
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument(
        "--boundary-report",
        required=True,
        help="Passing refine_boundaries.py report bound to this refined plan",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Source media whose SHA-256 will bind this audit to apply_cut_plan.py",
    )
    parser.add_argument(
        "--review-decisions",
        help="Optional JSON containing approved_ids or decisions keyed by review id",
    )
    parser.add_argument("--embedded-filler-review")
    parser.add_argument(
        "--approve-review",
        action="append",
        default=[],
        metavar="ID",
        help="Explicitly approve one review_required id; repeat as needed",
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    transcript_path = Path(args.transcript).resolve()
    plan_path = Path(args.plan).resolve()
    boundary_report_path = Path(args.boundary_report).resolve()
    source_path = Path(args.input).resolve()
    transcript = load_json(transcript_path)
    plan = load_json(plan_path)
    boundary_report = load_json(boundary_report_path)
    words = transcript.get("words", [])
    word_by_id = {word["word_id"]: word for word in words}
    boundary_refinement = plan.get("boundary_refinement") or {}
    timeline_offset = float(
        boundary_refinement.get("source_timeline_offset_seconds") or 0.0
    )
    source_window = plan.get("source_window", {})
    window_start = timeline_offset + float(source_window.get("start", 0))
    window_end = timeline_offset + float(
        source_window.get("end", transcript.get("duration") or 0)
    )
    segments = plan.get("segments", [])
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    plan_fingerprint = file_fingerprint(plan_path)
    transcript_fingerprint = file_fingerprint(transcript_path)
    source_fingerprint = file_fingerprint(source_path)
    boundary_inputs = boundary_report.get("inputs") if isinstance(boundary_report, dict) else None
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
    if not isinstance(boundary_inputs, dict):
        errors.append({"code": "boundary_report_missing_inputs"})
    else:
        expected_pairs = (
            ("refined_plan", plan_fingerprint["sha256"]),
            ("transcript", transcript_fingerprint["sha256"]),
            ("source_media", source_fingerprint["sha256"]),
        )
        for name, expected_sha256 in expected_pairs:
            actual = boundary_inputs.get(name)
            if not isinstance(actual, dict) or actual.get("sha256") != expected_sha256:
                errors.append(
                    {
                        "code": "boundary_report_input_mismatch",
                        "input": name,
                    }
                )
    if boundary_report.get("pipeline_version") != PIPELINE_VERSION:
        errors.append({"code": "boundary_report_pipeline_version_invalid"})
    if boundary_report.get("method") != EXPECTED_BOUNDARY_METHOD:
        errors.append(
            {
                "code": "boundary_method_invalid",
                "expected": EXPECTED_BOUNDARY_METHOD,
                "actual": boundary_report.get("method"),
            }
        )
    if boundary_refinement.get("method") != EXPECTED_BOUNDARY_METHOD:
        errors.append({"code": "plan_boundary_method_invalid"})
    if "source_timeline_offset_seconds" not in boundary_refinement:
        errors.append({"code": "source_timeline_offset_missing"})
    if boundary_report.get("ok") is not True or boundary_report.get("errors"):
        errors.append({"code": "boundary_refinement_not_approved"})

    if not segments:
        errors.append({"code": "no_segments"})
    sentence_review = plan.get("sentence_boundary_review")
    if not isinstance(sentence_review, dict):
        warnings.append(
            {
                "code": "legacy_sentence_boundary_review_missing",
                "message": "semantic completeness is enforced by caption-units.audit.json",
            }
        )
    else:
        for field in (
            "approved",
            "opening_direct",
            "all_entries_complete",
            "all_tails_complete",
        ):
            if sentence_review.get(field) is not True:
                warnings.append(
                    {
                        "code": "legacy_sentence_boundary_review_not_approved",
                        "field": field,
                    }
                )

    previous_end = window_start
    expected_duration = 0.0
    retained_fillers: list[dict[str, Any]] = []
    embedded_fillers: list[dict[str, Any]] = []
    seen_segment_ids: set[str] = set()
    for index, segment in enumerate(segments):
        segment_id = str(segment.get("id") or "")
        if not segment_id:
            errors.append({"code": "segment_id_missing", "index": index + 1})
            segment_id = f"missing-segment-{index + 1}"
        elif segment_id in seen_segment_ids:
            errors.append({"code": "duplicate_segment_id", "segment": segment_id})
        seen_segment_ids.add(segment_id)
        start = float(segment.get("source_start", -1))
        end = float(segment.get("source_end", -1))
        if start < window_start - EPSILON or end > window_end + EPSILON:
            errors.append({"code": "outside_source_window", "segment": segment_id, "start": start, "end": end})
        if end - start < 0.25:
            errors.append({"code": "segment_too_short", "segment": segment_id, "duration": end - start})
        if start < previous_end - EPSILON:
            errors.append({"code": "overlap_or_unsorted", "segment": segment_id, "previous_end": previous_end})
        for boundary_name, boundary in (("start", start), ("end", end)):
            hit = boundary_inside_word(boundary, words, timeline_offset)
            if hit:
                analysis = segment.get("boundary_analysis") or {}
                speech_onset = float(
                    analysis.get("speech_onset_seconds") or -1.0
                )
                vad_protected_start = (
                    boundary_name == "start"
                    and analysis.get("entry_strategy")
                    == "silero-speech-onset"
                    and boundary <= speech_onset - MIN_START_MARGIN + EPSILON
                )
                if vad_protected_start:
                    continue
                continuous_splice_boundary = (
                    boundary_name == "start"
                    and analysis.get("entry_strategy")
                    == CONTINUOUS_SPLICE_STRATEGY
                    and (
                        str(hit.get("word_id"))
                        == str(analysis.get("first_meaningful_word_id"))
                        or str(hit.get("word_id"))
                        == str(
                            analysis.get(
                                "discarded_predecessor_filler_word_id"
                            )
                        )
                    )
                )
                if continuous_splice_boundary:
                    continue
                errors.append(
                    {
                        "code": "cut_inside_word",
                        "segment": segment_id,
                        "boundary": boundary_name,
                        "time": boundary,
                        "word_id": hit["word_id"],
                        "word": hit["text"],
                        "word_range": [hit["start"], hit["end"]],
                    }
                )
        ids = segment.get("source_word_ids", [])
        missing = [word_id for word_id in ids if word_id not in word_by_id]
        if missing:
            errors.append({"code": "unknown_word_ids", "segment": segment_id, "word_ids": missing})
        outside = [
            word_id
            for word_id in ids
            if word_id in word_by_id
            and (
                float(word_by_id[word_id]["start"]) + timeline_offset
                < start - EPSILON
                or float(word_by_id[word_id]["end"]) + timeline_offset
                > end + EPSILON
            )
        ]
        boundary = segment.get("boundary_analysis")
        if (
            outside
            and isinstance(boundary, dict)
            and boundary.get("entry_strategy")
            in {"silero-speech-onset", CONTINUOUS_SPLICE_STRATEGY}
            and ids
            and outside == [ids[0]]
        ):
            outside = []
        if outside:
            errors.append({"code": "listed_words_outside_segment", "segment": segment_id, "word_ids": outside})
        if not ids:
            warnings.append({"code": "segment_has_no_word_ids", "segment": segment_id})
        elif all(word_id in word_by_id for word_id in (ids[0], ids[-1])):
            first_word = word_by_id[ids[0]]
            last_word = word_by_id[ids[-1]]
            boundary = segment.get("boundary_analysis") or {}
            acoustic_start = float(
                boundary.get("speech_onset_seconds")
                or float(first_word["start"]) + timeline_offset
            )
            margins = {
                "start": (
                    acoustic_start - start,
                    -CONTINUOUS_SPLICE_POSTROLL
                    if boundary.get("entry_strategy")
                    == CONTINUOUS_SPLICE_STRATEGY
                    else MIN_START_MARGIN,
                    CONTINUOUS_SPLICE_PREROLL
                    if boundary.get("entry_strategy")
                    == CONTINUOUS_SPLICE_STRATEGY
                    else MAX_START_MARGIN,
                ),
                "end": (
                    end - (float(last_word["end"]) + timeline_offset),
                    MIN_END_MARGIN,
                    MAX_END_MARGIN,
                ),
            }
            for boundary_name, (margin, minimum, maximum) in margins.items():
                if margin < minimum - EPSILON or margin > maximum + EPSILON:
                    errors.append(
                        {
                            "code": "boundary_margin_out_of_range",
                            "segment": segment_id,
                            "boundary": boundary_name,
                            "margin_seconds": round(margin, 4),
                            "allowed_seconds": [minimum, maximum],
                            "word_id": ids[0] if boundary_name == "start" else ids[-1],
                        }
                    )
        boundary = segment.get("boundary_analysis")
        if not isinstance(boundary, dict):
            errors.append({"code": "missing_boundary_analysis", "segment": segment_id})
        else:
            if boundary.get("entry_clean") is not True:
                errors.append({"code": "unclean_segment_entry", "segment": segment_id})
            if boundary.get("tail_clear") is not True:
                errors.append({"code": "unprotected_segment_tail", "segment": segment_id})
            if boundary.get("entry_context") not in {
                "opening",
                "after-filler",
                "normal",
            }:
                errors.append(
                    {"code": "entry_context_missing", "segment": segment_id}
                )
            if boundary.get("entry_strategy") not in {
                "silero-speech-onset",
                "energy-trough-near-asr",
                CONTINUOUS_SPLICE_STRATEGY,
            }:
                errors.append(
                    {"code": "entry_strategy_invalid", "segment": segment_id}
                )
            headroom_ms = float(boundary.get("headroom_seconds", 0.0)) * 1000.0
            tailroom_ms = float(boundary.get("tailroom_seconds", 0.0)) * 1000.0
            fade_in_ms = float(boundary.get("fade_in_ms", 0.0))
            fade_out_ms = float(boundary.get("fade_out_ms", 0.0))
            allowed_fade_in_ms = (
                CONTINUOUS_SPLICE_MAX_FADE_MS
                if boundary.get("entry_strategy")
                == CONTINUOUS_SPLICE_STRATEGY
                else min(12.0, headroom_ms + EPSILON)
            )
            if fade_in_ms < 0 or fade_in_ms > allowed_fade_in_ms:
                errors.append({"code": "unsafe_fade_in", "segment": segment_id})
            if fade_out_ms < 0 or fade_out_ms > min(12.0, tailroom_ms + EPSILON):
                errors.append({"code": "unsafe_fade_out", "segment": segment_id})
            maximum_headroom_ms = {
                "opening": 60.0,
                "after-filler": 60.0,
                "normal": 90.0,
            }.get(str(boundary.get("entry_context")), 0.0)
            minimum_headroom_ms = (
                0.0
                if boundary.get("entry_strategy")
                == CONTINUOUS_SPLICE_STRATEGY
                else MIN_START_MARGIN * 1000.0
            )
            if (
                headroom_ms < minimum_headroom_ms - EPSILON
                or headroom_ms > maximum_headroom_ms + EPSILON
            ):
                errors.append(
                    {
                        "code": "dynamic_headroom_out_of_range",
                        "segment": segment_id,
                        "entry_context": boundary.get("entry_context"),
                        "headroom_ms": round(headroom_ms, 3),
                        "maximum_ms": maximum_headroom_ms,
                    }
                )
        semantic_boundary = segment.get("sentence_boundary_review")
        if isinstance(semantic_boundary, dict) and (
            semantic_boundary.get("entry_complete") is not True
            or semantic_boundary.get("exit_complete") is not True
        ):
            warnings.append(
                {
                    "code": "physical_splice_crosses_semantic_unit",
                    "segment": segment_id,
                    "message": "allowed only when caption-units audit joins the complete semantic unit",
                }
            )
        expected_duration += max(0.0, end - start)
        previous_end = end
        for word in words:
            word_start = float(word["start"]) + timeline_offset
            word_end = float(word["end"]) + timeline_offset
            if (
                word_start >= start - EPSILON
                and word_end <= end + EPSILON
                and is_hard_filler(word.get("text", ""))
            ):
                retained_fillers.append(
                    {
                        "segment": segment_id,
                        "word_id": word["word_id"],
                        "text": word["text"],
                        "start": word["start"],
                        "end": word["end"],
                    }
                )
            elif (
                word_start >= start - EPSILON
                and word_end <= end + EPSILON
                and has_embedded_hard_filler(word.get("text", ""))
                and str(word["word_id"]) not in approved_embedded_ids
            ):
                embedded_fillers.append(
                    {
                        "segment": segment_id,
                        "word_id": word["word_id"],
                        "text": word["text"],
                        "start": word["start"],
                        "end": word["end"],
                    }
                )

    if retained_fillers:
        errors.append(
            {
                "code": "retained_hard_fillers",
                "count": len(retained_fillers),
                "words": retained_fillers,
            }
        )
    if embedded_fillers:
        errors.append(
            {
                "code": "ambiguous_embedded_hard_fillers",
                "count": len(embedded_fillers),
                "words": embedded_fillers,
                "message": "obtain finer word timing before cutting; do not hide the filler in captions",
            }
        )

    approved_ids: set[str] = set()
    if args.approve_review:
        errors.append(
            {
                "code": "unbound_cli_review_approval_forbidden",
                "message": "write a hash-bound review-decisions.json instead",
            }
        )
    if args.review_decisions:
        decisions_path = Path(args.review_decisions).resolve()
        decisions_payload = load_json(decisions_path)
        if not isinstance(decisions_payload, dict):
            parser.error("--review-decisions must contain a JSON object")
        if decisions_payload.get("schema_version") != 1:
            errors.append({"code": "review_decisions_schema_invalid"})
        decision_inputs = decisions_payload.get("inputs")
        expected_decision_inputs = {
            "corrected_transcript_sha256": transcript_fingerprint["sha256"],
            "cut_plan_sha256": plan_fingerprint["sha256"],
            "boundary_report_sha256": file_fingerprint(boundary_report_path)["sha256"],
            "source_media_sha256": source_fingerprint["sha256"],
        }
        if not isinstance(decision_inputs, dict) or any(
            decision_inputs.get(name) != expected
            for name, expected in expected_decision_inputs.items()
        ):
            errors.append(
                {
                    "code": "review_decisions_input_mismatch",
                    "expected": expected_decision_inputs,
                }
            )
        approved_ids.update(str(item) for item in decisions_payload.get("approved_ids", []))
        decisions = decisions_payload.get("decisions", {})
        if isinstance(decisions, dict):
            approved_ids.update(
                str(review_id)
                for review_id, decision in decisions.items()
                if decision is True
                or (isinstance(decision, dict) and decision.get("approved") is True)
            )

    required_reviews = []
    for index, item in enumerate(plan.get("review_required", []), start=1):
        if not isinstance(item, dict):
            errors.append({"code": "invalid_review_item", "index": index})
            continue
        review_id = str(item.get("id") or f"review-{index:03d}")
        required_reviews.append(review_id)
    unknown_approvals = sorted(approved_ids - set(required_reviews))
    if unknown_approvals:
        errors.append({"code": "unknown_review_approvals", "review_ids": unknown_approvals})
    unresolved_ids = sorted(set(required_reviews) - approved_ids)
    blocked = bool(unresolved_ids)

    report = {
        "schema_version": AUDIT_REPORT_SCHEMA_VERSION,
        "ok": not errors and not blocked,
        "blocked": blocked,
        "inputs": {
            "transcript": transcript_fingerprint,
            "plan": plan_fingerprint,
            "source_media": source_fingerprint,
            "boundary_report": file_fingerprint(boundary_report_path),
            "embedded_filler_review": (
                file_fingerprint(embedded_review_path) if embedded_review_path else None
            ),
            "transcript_sha256": transcript_fingerprint["sha256"],
            "plan_sha256": plan_fingerprint["sha256"],
            "source_media_sha256": source_fingerprint["sha256"],
        },
        "boundary_margin_seconds": {
            "start": {"minimum": MIN_START_MARGIN, "maximum": MAX_START_MARGIN},
            "end": {"minimum": MIN_END_MARGIN, "maximum": MAX_END_MARGIN},
        },
        "segment_count": len(segments),
        "expected_duration": round(expected_duration, 3),
        "speech_cleanup": {
            "policy": "remove-all-nonsemantic-hard-fillers",
            "hard_filler_count": len(retained_fillers),
            "retained_words": retained_fillers,
            "ambiguous_embedded_count": len(embedded_fillers),
            "ambiguous_embedded_words": embedded_fillers,
            "approved_semantic_word_ids": sorted(approved_embedded_ids),
        },
        "review_required_count": len(required_reviews),
        "review": {
            "required_ids": required_reviews,
            "approved_ids": sorted(approved_ids & set(required_reviews)),
            "unresolved_ids": unresolved_ids,
        },
        "errors": errors,
        "warnings": warnings,
    }
    write_json(args.output, report)
    state = "PASS" if report["ok"] else "BLOCKED" if blocked and not errors else "FAIL"
    print(
        f"cut-plan audit: {state} "
        f"({len(errors)} errors, {len(warnings)} warnings, {len(unresolved_ids)} unresolved reviews)"
    )
    if report["ok"]:
        return 0
    return EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
