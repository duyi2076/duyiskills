#!/usr/bin/env python3
"""Audit every AIJianji visual reveal against exact spoken evidence and word timing."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from common import file_fingerprint, load_json, write_json
from contracts import EXIT_BLOCKED, PIPELINE_VERSION


ROLES = {
    "setup",
    "explain",
    "compare",
    "conclude",
    "recap",
    "instruction",
    "example",
}
ENTRY_SECONDS = {"state": 0.22, "item": 0.15, "formula-part": 0.15}
MINIMUM_READABLE_HOLD_SECONDS = {"state": 1.0, "item": 0.75, "formula-part": 0.6}


def normalized_text(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def text_for_state(state: dict[str, Any]) -> str:
    parts = state.get("parts")
    if isinstance(parts, list):
        return "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
    return " ".join(
        value
        for value in (
            str(state.get("title") or "").strip(),
            str(state.get("body") or "").strip(),
        )
        if value
    )


def collect_units(plan: dict[str, Any]) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
    units: dict[tuple[str, str], dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    segments = plan.get("segments")
    if not isinstance(segments, list):
        return units, [{"code": "animation_segments_missing"}]
    for segment_index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        segment_id = str(segment.get("id") or "")
        states = (segment.get("config") or {}).get("states")
        if not segment_id or not isinstance(states, list):
            continue
        for state_index, state in enumerate(states, start=1):
            if not isinstance(state, dict) or state.get("action") not in {"enter", "update"}:
                continue
            state_id = str(state.get("id") or "")
            if not state_id:
                errors.append(
                    {
                        "code": "semantic_state_id_missing",
                        "segment_id": segment_id,
                        "state_index": state_index,
                    }
                )
                continue
            key = (segment_id, state_id)
            if key in units:
                errors.append({"code": "semantic_visual_id_duplicate", "segment_id": segment_id, "visual_id": state_id})
            units[key] = {
                "segment_id": segment_id,
                "visual_id": state_id,
                "unit": "state",
                "card_text": text_for_state(state),
                "trigger_word_ids": [str(value) for value in state.get("trigger_word_ids", [])],
                "segment_source_word_ids": [str(value) for value in segment.get("source_word_ids", [])],
            }
            for item_index, item in enumerate(state.get("items") or [], start=1):
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "")
                if not item_id:
                    errors.append(
                        {
                            "code": "semantic_item_id_missing",
                            "segment_id": segment_id,
                            "state_id": state_id,
                            "item_index": item_index,
                        }
                    )
                    continue
                item_key = (segment_id, item_id)
                if item_key in units:
                    errors.append({"code": "semantic_visual_id_duplicate", "segment_id": segment_id, "visual_id": item_id})
                units[item_key] = {
                    "segment_id": segment_id,
                    "visual_id": item_id,
                    "unit": "item",
                    "card_text": str(item.get("text") or ""),
                    "trigger_word_ids": [str(value) for value in item.get("trigger_word_ids", [])],
                    "segment_source_word_ids": [str(value) for value in segment.get("source_word_ids", [])],
                }
            for part_index, part in enumerate(state.get("parts") or [], start=1):
                if not isinstance(part, dict):
                    continue
                part_id = str(part.get("id") or "")
                if not part_id:
                    errors.append(
                        {
                            "code": "semantic_formula_part_id_missing",
                            "segment_id": segment_id,
                            "state_id": state_id,
                            "part_index": part_index,
                        }
                    )
                    continue
                part_key = (segment_id, part_id)
                if part_key in units:
                    errors.append({"code": "semantic_visual_id_duplicate", "segment_id": segment_id, "visual_id": part_id})
                units[part_key] = {
                    "segment_id": segment_id,
                    "visual_id": part_id,
                    "unit": "formula-part",
                    "card_text": str(part.get("text") or ""),
                    "trigger_word_ids": [str(value) for value in part.get("trigger_word_ids", [])],
                    "segment_source_word_ids": [str(value) for value in segment.get("source_word_ids", [])],
                }
    return units, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", required=True)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--animation-plan", required=True)
    parser.add_argument("--reveal-timeline", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    brief_path = Path(args.brief).resolve()
    timeline_path = Path(args.timeline).resolve()
    plan_path = Path(args.animation_plan).resolve()
    reveal_path = Path(args.reveal_timeline).resolve()
    brief = load_json(brief_path)
    timeline = load_json(timeline_path)
    plan = load_json(plan_path)
    reveal = load_json(reveal_path)
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if reveal.get("schema_version") != 1:
        errors.append({"code": "semantic_reveal_schema_must_be_1"})
    if reveal.get("policy") != "exact-spoken-reveal":
        errors.append({"code": "semantic_reveal_policy_not_locked"})

    words = timeline.get("words")
    if not isinstance(words, list) or not words:
        errors.append({"code": "mapped_words_missing"})
        words = []
    word_by_id = {
        str(word.get("word_id")): word
        for word in words
        if isinstance(word, dict) and word.get("word_id")
    }
    word_index = {str(word.get("word_id")): index for index, word in enumerate(words) if isinstance(word, dict)}
    units, unit_errors = collect_units(plan)
    errors.extend(unit_errors)
    events = reveal.get("events")
    if not isinstance(events, list):
        errors.append({"code": "semantic_reveal_events_missing"})
        events = []

    seen: set[tuple[str, str]] = set()
    mapped_events: list[dict[str, Any]] = []
    for event_index, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            errors.append({"code": "semantic_reveal_event_not_object", "event_index": event_index})
            continue
        segment_id = str(event.get("segment_id") or "")
        visual_id = str(event.get("visual_id") or "")
        key = (segment_id, visual_id)
        unit = units.get(key)
        if unit is None:
            errors.append(
                {
                    "code": "semantic_reveal_unknown_visual",
                    "event_index": event_index,
                    "segment_id": segment_id,
                    "visual_id": visual_id,
                }
            )
            continue
        if key in seen:
            errors.append({"code": "semantic_reveal_duplicate_visual", "segment_id": segment_id, "visual_id": visual_id})
            continue
        seen.add(key)
        if event.get("unit") != unit["unit"]:
            errors.append(
                {
                    "code": "semantic_reveal_unit_mismatch",
                    "segment_id": segment_id,
                    "visual_id": visual_id,
                    "expected": unit["unit"],
                    "actual": event.get("unit"),
                }
            )
        role = str(event.get("role") or "")
        if role not in ROLES:
            errors.append({"code": "semantic_reveal_role_invalid", "segment_id": segment_id, "visual_id": visual_id})

        fields = {
            name: str(event.get(name) or "")
            for name in (
                "evidence_start_word_id",
                "evidence_end_word_id",
                "earliest_allowed_word_id",
                "trigger_word_id",
                "fully_visible_by_word_id",
                "hold_until_word_id",
            )
        }
        missing_fields = [name for name, value in fields.items() if value not in word_by_id]
        if missing_fields:
            errors.append(
                {
                    "code": "semantic_reveal_word_unmapped",
                    "segment_id": segment_id,
                    "visual_id": visual_id,
                    "fields": missing_fields,
                }
            )
            continue
        indexes = {name: word_index[value] for name, value in fields.items()}
        if indexes["evidence_start_word_id"] > indexes["evidence_end_word_id"]:
            errors.append({"code": "semantic_evidence_range_reversed", "segment_id": segment_id, "visual_id": visual_id})
            continue
        evidence_words = words[
            indexes["evidence_start_word_id"] : indexes["evidence_end_word_id"] + 1
        ]
        evidence_text = "".join(str(word.get("text") or "") for word in evidence_words if isinstance(word, dict))
        spoken_excerpt = str(event.get("spoken_excerpt") or "")
        if not normalized_text(spoken_excerpt) or normalized_text(spoken_excerpt) != normalized_text(evidence_text):
            errors.append(
                {
                    "code": "semantic_spoken_excerpt_not_exact",
                    "segment_id": segment_id,
                    "visual_id": visual_id,
                    "expected": evidence_text,
                    "actual": spoken_excerpt,
                }
            )
        trigger_ids = unit["trigger_word_ids"]
        mapped_trigger_ids = [word_id for word_id in trigger_ids if word_id in word_by_id]
        expected_trigger = min(
            mapped_trigger_ids,
            key=lambda word_id: float(word_by_id[word_id]["start"]),
        ) if mapped_trigger_ids else None
        if fields["trigger_word_id"] != expected_trigger:
            errors.append(
                {
                    "code": "semantic_trigger_differs_from_render",
                    "segment_id": segment_id,
                    "visual_id": visual_id,
                    "expected": expected_trigger,
                    "actual": fields["trigger_word_id"],
                }
            )
        ordered = [
            indexes["earliest_allowed_word_id"],
            indexes["trigger_word_id"],
            indexes["fully_visible_by_word_id"],
            indexes["hold_until_word_id"],
        ]
        if ordered != sorted(ordered):
            errors.append(
                {
                    "code": "semantic_reveal_order_invalid",
                    "segment_id": segment_id,
                    "visual_id": visual_id,
                }
            )
        if not (
            indexes["evidence_start_word_id"]
            <= indexes["trigger_word_id"]
            <= indexes["evidence_end_word_id"]
        ):
            errors.append(
                {
                    "code": "semantic_trigger_outside_spoken_evidence",
                    "segment_id": segment_id,
                    "visual_id": visual_id,
                }
            )
        trigger_time = float(word_by_id[fields["trigger_word_id"]]["start"])
        visible_by_time = float(word_by_id[fields["fully_visible_by_word_id"]]["end"])
        entry_seconds = ENTRY_SECONDS[unit["unit"]]
        if visible_by_time + 0.02 < trigger_time + entry_seconds:
            errors.append(
                {
                    "code": "semantic_fully_visible_too_early",
                    "segment_id": segment_id,
                    "visual_id": visual_id,
                    "required": round(trigger_time + entry_seconds, 3),
                    "actual": round(visible_by_time, 3),
                }
            )
        hold_until_time = float(word_by_id[fields["hold_until_word_id"]]["end"])
        readable_hold = hold_until_time - (trigger_time + entry_seconds)
        minimum_readable_hold = MINIMUM_READABLE_HOLD_SECONDS[unit["unit"]]
        if readable_hold + 0.02 < minimum_readable_hold:
            errors.append(
                {
                    "code": "semantic_reveal_readability_too_short",
                    "segment_id": segment_id,
                    "visual_id": visual_id,
                    "actual": round(readable_hold, 3),
                    "minimum": minimum_readable_hold,
                }
            )
        segment_ids = [word_id for word_id in unit["segment_source_word_ids"] if word_id in word_by_id]
        if segment_ids:
            segment_start = min(float(word_by_id[word_id]["start"]) for word_id in segment_ids)
            segment_end = max(float(word_by_id[word_id]["end"]) for word_id in segment_ids)
            hold_until = hold_until_time
            if hold_until + 0.5 < segment_end:
                errors.append(
                    {
                        "code": "semantic_hold_ends_before_persistent_chapter",
                        "segment_id": segment_id,
                        "visual_id": visual_id,
                        "hold_until": round(hold_until, 3),
                        "chapter_end": round(segment_end, 3),
                    }
                )
        else:
            segment_start = 0.0
            segment_end = float(timeline.get("duration") or 0.0)

        timing_reason = str(event.get("timing_reason") or "").strip()
        if len(timing_reason) < 8:
            errors.append({"code": "semantic_timing_reason_missing", "segment_id": segment_id, "visual_id": visual_id})
        spoiler = event.get("spoiler_check")
        if not isinstance(spoiler, dict) or spoiler.get("passed") is not True or len(
            str(spoiler.get("reason") or "").strip()
        ) < 8:
            errors.append({"code": "semantic_spoiler_check_not_approved", "segment_id": segment_id, "visual_id": visual_id})

        mapped_events.append(
            {
                "event_id": str(event.get("id") or f"event-{event_index:03d}"),
                "segment_id": segment_id,
                "visual_id": visual_id,
                "unit": unit["unit"],
                "role": role,
                "card_text": unit["card_text"],
                "spoken_excerpt": spoken_excerpt,
                "trigger_word_id": fields["trigger_word_id"],
                "trigger_time": round(trigger_time, 3),
                "fully_visible_time": round(trigger_time + entry_seconds, 3),
                "hold_until_time": round(hold_until_time, 3),
                "chapter_start": round(segment_start, 3),
                "chapter_end": round(segment_end, 3),
                "evidence_word_ids": [
                    fields["evidence_start_word_id"],
                    fields["evidence_end_word_id"],
                ],
                "timing_reason": timing_reason,
                "spoiler_check": spoiler,
            }
        )

    missing_units = sorted(set(units) - seen)
    for segment_id, visual_id in missing_units:
        errors.append(
            {
                "code": "semantic_reveal_visual_uncovered",
                "segment_id": segment_id,
                "visual_id": visual_id,
                "unit": units[(segment_id, visual_id)]["unit"],
            }
        )

    mapped_events.sort(key=lambda item: (item["trigger_time"], item["segment_id"], item["visual_id"]))
    report = {
        "schema_version": 1,
        "pipeline_version": PIPELINE_VERSION,
        "ok": not errors,
        "policy": "exact-spoken-reveal",
        "inputs": {
            "brief": file_fingerprint(brief_path),
            "timeline": file_fingerprint(timeline_path),
            "animation_plan": file_fingerprint(plan_path),
            "reveal_timeline": file_fingerprint(reveal_path),
        },
        "visual_unit_count": len(units),
        "event_count": len(mapped_events),
        "coverage_complete": not missing_units and len(seen) == len(units),
        "mapped_events": mapped_events,
        "errors": errors,
        "warnings": warnings,
        "agent_review_required": [
            "card_meaning_matches_spoken_excerpt",
            "trigger_feels_natural_in_continuous_playback",
            "no_future_conclusion_is_revealed_early",
            "persistent_card_remains_relevant_until_chapter_end",
        ],
    }
    write_json(args.output, report)
    print(
        f"semantic reveal: {'PASS' if report['ok'] else 'BLOCKED'} "
        f"({len(mapped_events)}/{len(units)} units, {len(errors)} errors)"
    )
    return 0 if report["ok"] else EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
