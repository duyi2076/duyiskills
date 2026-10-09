#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from common import file_fingerprint, load_json, sha256_file, write_json
from contracts import PIPELINE_VERSION, validate_cut_plan


def resolve_nested_triggers(
    anchor: dict[str, Any],
    *,
    source_to_output: dict[str, dict[str, float]],
    output_start: float,
    output_end: float,
) -> dict[str, Any]:
    """Resolve AIJianji state/item/formula-part words into chapter-local deterministic times."""
    resolved = dict(anchor)
    config = anchor.get("config")
    if not isinstance(config, dict):
        return resolved
    mapped_config = dict(config)
    states = config.get("states")
    if not isinstance(states, list):
        return resolved
    mapped_states: list[dict[str, Any]] = []
    for state in states:
        if not isinstance(state, dict):
            mapped_states.append(state)
            continue
        mapped_state = dict(state)
        trigger_ids = [str(item) for item in state.get("trigger_word_ids", [])]
        trigger_words = [
            source_to_output[word_id]
            for word_id in trigger_ids
            if word_id in source_to_output
        ]
        if trigger_words:
            absolute = min(float(item["start"]) for item in trigger_words)
            mapped_state["reveal_at"] = round(
                max(0.0, min(output_end, absolute) - output_start),
                3,
            )
        items = state.get("items")
        if isinstance(items, list):
            mapped_items: list[Any] = []
            for item in items:
                if not isinstance(item, dict):
                    mapped_items.append(item)
                    continue
                mapped_item = dict(item)
                item_ids = [str(value) for value in item.get("trigger_word_ids", [])]
                item_words = [
                    source_to_output[word_id]
                    for word_id in item_ids
                    if word_id in source_to_output
                ]
                if item_words:
                    absolute = min(float(value["start"]) for value in item_words)
                    mapped_item["reveal_at"] = round(
                        max(0.0, min(output_end, absolute) - output_start),
                        3,
                    )
                mapped_items.append(mapped_item)
            mapped_state["items"] = mapped_items
        parts = state.get("parts")
        if isinstance(parts, list):
            mapped_parts: list[Any] = []
            for part in parts:
                if not isinstance(part, dict):
                    mapped_parts.append(part)
                    continue
                mapped_part = dict(part)
                part_ids = [str(value) for value in part.get("trigger_word_ids", [])]
                part_words = [
                    source_to_output[word_id]
                    for word_id in part_ids
                    if word_id in source_to_output
                ]
                if part_words:
                    absolute = min(float(value["start"]) for value in part_words)
                    mapped_part["reveal_at"] = round(
                        max(0.0, min(output_end, absolute) - output_start),
                        3,
                    )
                mapped_parts.append(mapped_part)
            mapped_state["parts"] = mapped_parts
        mapped_states.append(mapped_state)
    mapped_config["states"] = mapped_states
    mapped_config["duration"] = round(output_end - output_start, 3)
    mapped_config["source_word_ids"] = anchor.get("source_word_ids", [])
    resolved["config"] = mapped_config
    return resolved


def main() -> int:
    parser = argparse.ArgumentParser(description="Map source word/animation anchors onto the cut output timeline.")
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--caption-units", required=True)
    parser.add_argument("--caption-unit-audit", required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--audit-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--cut-manifest", help="Optional apply_cut_plan manifest; uses actual encoded segment durations")
    parser.add_argument("--anchors")
    parser.add_argument("--anchors-output")
    args = parser.parse_args()

    transcript_path = Path(args.transcript).resolve()
    plan_path = Path(args.plan).resolve()
    caption_units_path = Path(args.caption_units).resolve()
    caption_unit_audit_path = Path(args.caption_unit_audit).resolve()
    source_path = Path(args.input).resolve()
    audit_report_path = Path(args.audit_report).resolve()
    transcript = load_json(transcript_path)
    plan = validate_cut_plan(load_json(plan_path))
    caption_units = load_json(caption_units_path)
    caption_unit_audit = load_json(caption_unit_audit_path)
    if caption_unit_audit.get("ok") is not True or caption_unit_audit.get("errors"):
        raise PermissionError("caption-unit audit is not approved")
    audit_inputs = caption_unit_audit.get("inputs") or {}
    expected_inputs = {
        "transcript": file_fingerprint(transcript_path)["sha256"],
        "plan": file_fingerprint(plan_path)["sha256"],
        "units": file_fingerprint(caption_units_path)["sha256"],
    }
    for name, expected_sha256 in expected_inputs.items():
        actual = audit_inputs.get(name)
        if not isinstance(actual, dict) or actual.get("sha256") != expected_sha256:
            raise ValueError(f"caption-unit audit does not match current {name}")
    unit_by_word_id: dict[str, dict[str, Any]] = {}
    for unit in caption_unit_audit.get("units", []):
        for word_id in unit.get("word_ids", []):
            if word_id in unit_by_word_id:
                raise ValueError(f"caption word assigned twice: {word_id}")
            unit_by_word_id[str(word_id)] = unit
    source_words = transcript.get("words", [])
    word_by_id = {
        str(word["word_id"]): word
        for word in source_words
    }
    timeline_offset = float(
        (plan.get("boundary_refinement") or {}).get(
            "source_timeline_offset_seconds"
        )
        or 0.0
    )
    actual_duration_by_id: dict[str, float] = {}
    if args.cut_manifest:
        manifest = load_json(args.cut_manifest)
        if manifest.get("schema_version") != 2:
            raise ValueError("cut manifest schema is not supported")
        expected_manifest_hashes = {
            "plan_sha256": sha256_file(plan_path),
            "source_sha256": sha256_file(source_path),
            "audit_report_sha256": sha256_file(audit_report_path),
        }
        for field, expected in expected_manifest_hashes.items():
            if manifest.get(field) != expected:
                raise ValueError(f"cut manifest does not match current {field}")
        plan_segments = plan.get("segments", [])
        manifest_segments = manifest.get("segments", [])
        if len(plan_segments) != len(manifest_segments):
            raise ValueError("cut manifest segment count differs from the plan")
        for planned, rendered in zip(plan_segments, manifest_segments):
            if (
                str(planned.get("id")) != str(rendered.get("id"))
                or abs(float(planned["source_start"]) - float(rendered["source_start"])) > 0.0005
                or abs(float(planned["source_end"]) - float(rendered["source_end"])) > 0.0005
            ):
                raise ValueError("cut manifest segment identity or bounds differ from the plan")
        cut_output = Path(str(manifest.get("output") or ""))
        if (
            not cut_output.is_file()
            or manifest.get("output_sha256") != sha256_file(cut_output)
        ):
            raise ValueError("cut manifest output media is missing or changed")
        actual_duration_by_id = {
            str(item["id"]): float(item["actual_duration"])
            for item in manifest.get("segments", [])
            if item.get("actual_duration") is not None
        }
    mapped_words: list[dict[str, Any]] = []
    mapped_segments: list[dict[str, Any]] = []
    source_to_output: dict[str, dict[str, float]] = {}
    output_cursor = 0.0

    for segment in plan.get("segments", []):
        source_start = float(segment["source_start"])
        source_end = float(segment["source_end"])
        planned_duration = source_end - source_start
        duration = actual_duration_by_id.get(str(segment.get("id")), planned_duration)
        output_start = output_cursor
        output_end = output_start + duration
        segment_words = [
            word
            for word in source_words
            if float(word["start"]) + timeline_offset
            >= source_start - 0.0005
            and float(word["end"]) + timeline_offset
            <= source_end + 0.0005
        ]
        boundary = segment.get("boundary_analysis") or {}
        listed_ids = [str(value) for value in segment.get("source_word_ids", [])]
        if (
            boundary.get("entry_strategy")
            in {
                "silero-speech-onset",
                "continuous-speech-zero-cross-splice",
            }
            and listed_ids
            and listed_ids[0] in word_by_id
            and all(
                str(word["word_id"]) != listed_ids[0]
                for word in segment_words
            )
        ):
            segment_words.insert(0, word_by_id[listed_ids[0]])
        previous_word_end = output_start
        for word in segment_words:
            mapped = dict(word)
            unit = unit_by_word_id.get(str(word["word_id"]))
            if not unit:
                raise ValueError(f"mapped word has no approved caption unit: {word['word_id']}")
            media_word_start = float(word["start"]) + timeline_offset
            media_word_end = float(word["end"]) + timeline_offset
            if (
                str(word["word_id"])
                == str(boundary.get("first_meaningful_word_id") or "")
                and boundary.get("entry_strategy")
                in {
                    "silero-speech-onset",
                    "continuous-speech-zero-cross-splice",
                }
            ):
                media_word_start = max(
                    source_start,
                    float(
                        boundary.get("speech_onset_seconds")
                        or word["start"]
                    ),
                )
                media_word_end = max(media_word_end, media_word_start + 0.020)
            mapped_start = max(
                previous_word_end,
                output_start + media_word_start - source_start,
            )
            mapped_end = min(
                output_end,
                max(
                    mapped_start + 0.020,
                    output_start + media_word_end - source_start,
                ),
            )
            mapped["asr_start"] = word["start"]
            mapped["asr_end"] = word["end"]
            mapped["source_start"] = round(media_word_start, 6)
            mapped["source_end"] = round(media_word_end, 6)
            mapped["start"] = round(mapped_start, 3)
            mapped["end"] = round(mapped_end, 3)
            mapped["segment_id"] = segment.get("id")
            mapped["caption_unit_id"] = unit["id"]
            mapped["caption_unit_start"] = word["word_id"] == unit["start_word_id"]
            mapped["caption_unit_end"] = word["word_id"] == unit["end_word_id"]
            mapped_words.append(mapped)
            source_to_output[word["word_id"]] = {"start": mapped["start"], "end": mapped["end"]}
            previous_word_end = mapped_end
        mapped_segments.append(
            {
                "id": segment.get("id"),
                "source_start": source_start,
                "source_end": source_end,
                "output_start": round(output_start, 3),
                "output_end": round(output_end, 3),
                "duration": round(duration, 3),
                "planned_duration": round(planned_duration, 3),
                "actual_duration_used": round(duration, 6),
                "word_ids": [word["word_id"] for word in segment_words],
            }
        )
        output_cursor = output_end

    mapped_caption_units: list[dict[str, Any]] = []
    for unit in caption_unit_audit.get("units", []):
        mapped = [
            word for word in mapped_words if word.get("caption_unit_id") == unit["id"]
        ]
        if not mapped:
            raise ValueError(f"approved caption unit was not mapped: {unit['id']}")
        mapped_caption_units.append(
            {
                **unit,
                "start": mapped[0]["start"],
                "end": mapped[-1]["end"],
                "mapped_word_ids": [word["word_id"] for word in mapped],
            }
        )

    result = {
        "version": 2,
        "pipeline_version": PIPELINE_VERSION,
        "inputs": {
            "transcript": file_fingerprint(transcript_path),
            "plan": file_fingerprint(plan_path),
            "caption_units": file_fingerprint(caption_units_path),
            "caption_unit_audit": file_fingerprint(caption_unit_audit_path),
            "source_media": file_fingerprint(source_path),
            "audit_report": file_fingerprint(audit_report_path),
            "cut_manifest": file_fingerprint(args.cut_manifest) if args.cut_manifest else None,
        },
        "duration": round(output_cursor, 3),
        "source": transcript.get("source"),
        "segments": mapped_segments,
        "words": mapped_words,
        "caption_units": mapped_caption_units,
        "source_to_output": source_to_output,
    }
    write_json(args.output, result)

    if args.anchors:
        anchors_payload = load_json(args.anchors)
        anchors = (
            anchors_payload
            if isinstance(anchors_payload, list)
            else anchors_payload.get("anchors", [])
            if isinstance(anchors_payload, dict)
            else None
        )
        if not isinstance(anchors, list):
            raise ValueError("--anchors must contain an array or an object with an anchors array")
        mapped_anchors = []
        for anchor in anchors:
            word_ids = anchor.get("source_word_ids", [])
            available = [source_to_output[word_id] for word_id in word_ids if word_id in source_to_output]
            mapped = dict(anchor)
            if available:
                mapped["status"] = "mapped"
                output_start = min(float(item["start"]) for item in available)
                output_end = max(float(item["end"]) for item in available)
                output_start += float(anchor.get("start_offset_seconds", 0.0))
                if anchor.get("duration_seconds") is not None:
                    output_end = output_start + float(anchor["duration_seconds"])
                output_start = max(0.0, output_start)
                output_end = min(output_cursor, output_end)
                mapped["output_start"] = round(output_start, 3)
                mapped["output_end"] = round(output_end, 3)
                mapped = resolve_nested_triggers(
                    mapped,
                    source_to_output=source_to_output,
                    output_start=output_start,
                    output_end=output_end,
                )
                missing = [word_id for word_id in word_ids if word_id not in source_to_output]
                if missing:
                    mapped["missing_source_word_ids"] = missing
            else:
                mapped["status"] = "dropped"
                mapped["output_start"] = None
                mapped["output_end"] = None
            mapped_anchors.append(mapped)
        anchors_output = args.anchors_output or f"{args.output}.anchors.json"
        write_json(anchors_output, {"version": 1, "anchors": mapped_anchors})
        print(f"mapped {len(mapped_anchors)} anchors -> {anchors_output}")

    print(f"mapped {len(mapped_words)} words / {len(mapped_segments)} segments -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
