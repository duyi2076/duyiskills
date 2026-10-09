#!/usr/bin/env python3
"""Gate the AIJianji chapter/state plan against the locked reference contract."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from common import file_fingerprint, load_json, write_json
from contracts import EXIT_BLOCKED, PIPELINE_VERSION
from stage_layout import (
    LAYOUT_MODEL_ID,
    MAXIMUM_COMPOSITE_ITEMS,
    STAGE_HEIGHT_BUDGET_PX,
    automatic_reflow_strategy,
    estimated_chapter_height,
    estimated_state_height,
)


ACCENTS = {"blue", "red", "green", "yellow"}
ACTIONS = {"enter", "update", "hold", "clear"}
TYPES = {
    "thesis",
    "quote",
    "chat",
    "comparison",
    "formula",
    "progressive-list",
    "path",
    "relation",
}
TYPE_LABELS = {
    "thesis": "KEY IDEA",
    "quote": "THE QUOTE",
    "chat": "CONVERSATION",
    "comparison": "COMPARISON",
    "formula": "THE FORMULA",
    "progressive-list": "KEY POINTS",
    "path": "THE PATH",
    "relation": "THE RELATION",
}
PREVIOUS_TREATMENTS = {"hold", "dim", "cross-out"}
FORBIDDEN_SKIN_KEYS = {"style", "skin", "skin_id", "theme", "preset"}
VISUAL_GRAMMAR_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "composition"
    / "visual-grammar.json"
)


def forbidden_skin_paths(value: Any, prefix: str = "") -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key) in FORBIDDEN_SKIN_KEYS:
                paths.append(path)
            paths.extend(forbidden_skin_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(forbidden_skin_paths(child, f"{prefix}[{index}]"))
    return paths


def text_width(value: str) -> float:
    return sum(0.5 if ord(character) < 128 else 1.0 for character in value)


def state_text_weight(state: dict[str, Any], state_type: str) -> float:
    label = str(state.get("label") or TYPE_LABELS.get(state_type, ""))
    title = str(state.get("title") or "")
    body = str(state.get("body") or "")
    if state_type == "formula":
        parts = state.get("parts") if isinstance(state.get("parts"), list) else []
        return sum(
            text_width(str(part.get("text") or ""))
            for part in parts
            if isinstance(part, dict)
        )
    if state_type in {"progressive-list", "path"}:
        return text_width(label) + text_width(title)
    if state_type == "relation":
        items = state.get("items") if isinstance(state.get("items"), list) else []
        return text_width(label) + text_width(title) + sum(
            text_width(str(item.get("text") or ""))
            for item in items
            if isinstance(item, dict)
        )
    if state_type == "quote":
        return (
            text_width(title)
            + text_width(str(state.get("source_name") or body))
            + text_width(str(state.get("source_note") or ""))
        )
    if state_type == "thesis":
        items = state.get("items") if isinstance(state.get("items"), list) else []
        return (
            text_width(label)
            + text_width(title)
            + text_width(body)
            + sum(
                text_width(str(item.get("text") or ""))
                for item in items
                if isinstance(item, dict)
            )
        )
    return text_width(label) + text_width(title) + text_width(body)


def audit_card_selection(
    *,
    state: dict[str, Any],
    state_type: str,
    segment_id: str,
    state_index: int,
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    errors: list[dict[str, Any]] = []
    sizes = policy.get("sizes") if isinstance(policy.get("sizes"), dict) else {}
    structures = set(policy.get("content_structures") or [])
    relation_layouts = policy.get("relation_layouts") or {}
    size = str(state.get("card_size") or "").strip()
    structure = str(state.get("content_structure") or "").strip()
    reason = str(state.get("size_reason") or "").strip()
    relation_layout = str(state.get("relation_layout") or "").strip()
    fidelity_mode = str(state.get("fidelity_mode") or "").strip()
    layout_reason = str(state.get("layout_reason") or "").strip()
    common = {"id": segment_id, "index": state_index}
    if size not in sizes:
        errors.append(
            {
                "code": "card_size_invalid_or_missing",
                **common,
                "actual": size,
                "allowed": ["small", "medium"],
            }
        )
        return errors, None
    if structure not in structures:
        errors.append(
            {
                "code": "content_structure_invalid_or_missing",
                **common,
                "actual": structure,
            }
        )
    if text_width(reason) < 8:
        errors.append({"code": "card_size_reason_missing", **common})
    if fidelity_mode != "spoken-first":
        errors.append(
            {
                "code": "spoken_first_fidelity_missing",
                **common,
                "actual": fidelity_mode,
            }
        )
    if relation_layout not in relation_layouts:
        errors.append(
            {
                "code": "relation_layout_invalid_or_missing",
                **common,
                "actual": relation_layout,
            }
        )
    if text_width(layout_reason) < 8:
        errors.append({"code": "layout_reason_missing", **common})

    weight = state_text_weight(state, state_type)
    layout_policy = (
        relation_layouts[relation_layout]
        if relation_layout in relation_layouts
        else {}
    )
    maximum = float(
        layout_policy.get(
            "maximum_text_weight",
            sizes[size].get("maximum_text_weight") or 0,
        )
    )
    if weight > maximum:
        errors.append(
            {
                "code": "card_text_exceeds_selected_size",
                **common,
                "card_size": size,
                "actual": weight,
                "maximum": maximum,
                "hint": "split or compress the information instead of choosing a larger card",
            }
        )
    if relation_layout in relation_layouts:
        compatible_layouts = set(
            (policy.get("type_layout_compatibility") or {}).get(state_type, [])
        )
        if relation_layout not in compatible_layouts:
            errors.append(
                {
                    "code": "relation_layout_not_allowed_for_type",
                    **common,
                    "type": state_type,
                    "relation_layout": relation_layout,
                }
            )
        if size not in set(layout_policy.get("allowed_sizes") or []):
            errors.append(
                {
                    "code": "card_size_not_allowed_for_relation_layout",
                    **common,
                    "relation_layout": relation_layout,
                    "card_size": size,
                }
            )
        if state_type == "relation":
            item_count = len(state.get("items") or [])
            minimum = int(layout_policy.get("minimum_items", 0))
            maximum_items = int(layout_policy.get("maximum_items", 0))
            if not minimum <= item_count <= maximum_items:
                errors.append(
                    {
                        "code": "relation_item_count_invalid",
                        **common,
                        "relation_layout": relation_layout,
                        "actual": item_count,
                        "expected": [minimum, maximum_items],
                    }
                )
            if "connector" in state:
                errors.append(
                    {
                        "code": "relation_global_connector_forbidden",
                        **common,
                        "relation_layout": relation_layout,
                    }
                )
            relation_items = state.get("items") or []
            if relation_layout in {"narrative-path", "spoken-cause"}:
                for item_index, item in enumerate(relation_items):
                    if not isinstance(item, dict):
                        continue
                    incoming = str(item.get("incoming_connector") or "").strip()
                    if item_index == 0 and incoming:
                        errors.append(
                            {
                                "code": "relation_first_item_connector_forbidden",
                                **common,
                                "relation_layout": relation_layout,
                                "item_index": item_index + 1,
                            }
                        )
                    elif item_index > 0 and incoming not in {"→", "⇒"}:
                        errors.append(
                            {
                                "code": "relation_incoming_connector_missing_or_invalid",
                                **common,
                                "relation_layout": relation_layout,
                                "item_index": item_index + 1,
                            }
                        )
            else:
                for item_index, item in enumerate(relation_items):
                    if (
                        isinstance(item, dict)
                        and str(item.get("incoming_connector") or "").strip()
                    ):
                        errors.append(
                            {
                                "code": "relation_connector_not_allowed_for_layout",
                                **common,
                                "relation_layout": relation_layout,
                                "item_index": item_index + 1,
                            }
                        )
    if state_type == "formula" and relation_layout != "formula":
        errors.append({"code": "formula_relation_layout_invalid", **common})

    selection = {
        "segment_id": segment_id,
        "state_index": state_index,
        "state_type": state_type,
        "card_size": size,
        "content_structure": structure,
        "size_reason": reason,
        "relation_layout": relation_layout,
        "fidelity_mode": fidelity_mode,
        "layout_reason": layout_reason,
        "text_weight": weight,
    }
    return errors, selection


def mapped_times(word_ids: list[str], source_to_output: dict[str, Any]) -> list[dict[str, float]]:
    return [
        source_to_output[word_id]
        for word_id in word_ids
        if word_id in source_to_output
    ]


def local_trigger(
    payload: dict[str, Any],
    source_to_output: dict[str, Any],
    chapter_start: float,
) -> float | None:
    word_ids = [str(item) for item in payload.get("trigger_word_ids", [])]
    available = mapped_times(word_ids, source_to_output)
    if not available:
        return None
    return min(float(item["start"]) for item in available) - chapter_start


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", required=True)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--direction", required=True)
    parser.add_argument("--animation-plan", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    brief_path = Path(args.brief).resolve()
    timeline_path = Path(args.timeline).resolve()
    direction_path = Path(args.direction).resolve()
    plan_path = Path(args.animation_plan).resolve()
    brief = load_json(brief_path)
    timeline = load_json(timeline_path)
    direction = load_json(direction_path)
    plan = load_json(plan_path)
    visual_grammar = load_json(VISUAL_GRAMMAR_PATH)
    if visual_grammar.get("schema_version") != 3:
        raise ValueError("visual grammar schema must be 3")
    duration = float(timeline.get("duration") or brief.get("duration") or 0)
    source_to_output = timeline.get("source_to_output") or {}
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if direction.get("schema_version") != 3:
        errors.append({"code": "direction_schema_must_be_3"})
    if direction.get("system") != "reference-1to1":
        errors.append({"code": "direction_system_not_locked"})
    if len(str(direction.get("viewer_experience") or "").strip()) < 12:
        errors.append({"code": "viewer_experience_missing"})
    if len(str(direction.get("rhythm") or "").strip()) < 8:
        errors.append({"code": "rhythm_missing"})
    if plan.get("schema_version") != 3:
        errors.append({"code": "animation_plan_schema_must_be_3"})

    segments = plan.get("segments")
    if not isinstance(segments, list):
        errors.append({"code": "segments_must_be_array"})
        segments = []
    minimum_chapters = 1 if duration < 45 else 2
    maximum_chapters = max(3, min(7, int(duration // 20) + 2))
    if not minimum_chapters <= len(segments) <= maximum_chapters:
        errors.append(
            {
                "code": "chapter_count_out_of_range",
                "actual": len(segments),
                "expected": [minimum_chapters, maximum_chapters],
            }
        )

    ids: set[str] = set()
    intervals: list[tuple[float, float, str]] = []
    state_count = 0
    fullscreen_count = 0
    chapter_height_estimates: dict[str, int] = {}
    chapter_layout_estimates: dict[str, dict[str, Any]] = {}
    layout_reflow_requests: list[dict[str, Any]] = []
    card_size_selections: list[dict[str, Any]] = []
    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            errors.append({"code": "segment_not_object", "index": index})
            continue
        segment_id = str(segment.get("id") or "")
        if not segment_id or segment_id in ids:
            errors.append({"code": "segment_id_invalid_or_duplicate", "index": index, "id": segment_id})
            continue
        ids.add(segment_id)
        if segment.get("template") != "semantic-stage":
            errors.append({"code": "template_not_semantic_stage", "id": segment_id})
        if len(str(segment.get("purpose") or "").strip()) < 8:
            errors.append({"code": "segment_purpose_missing", "id": segment_id})
        if segment.get("render_approved") is not True:
            errors.append({"code": "segment_not_render_approved", "id": segment_id})
        word_ids = [str(item) for item in segment.get("source_word_ids", [])]
        available = mapped_times(word_ids, source_to_output)
        if len(available) < 2:
            errors.append({"code": "segment_unmapped", "id": segment_id})
            continue
        start = min(float(item["start"]) for item in available)
        end = max(float(item["end"]) for item in available)
        if end - start < 3:
            errors.append({"code": "chapter_too_short", "id": segment_id, "duration": round(end - start, 3)})
        intervals.append((start, end, segment_id))

        config = segment.get("config")
        if not isinstance(config, dict):
            errors.append({"code": "config_missing", "id": segment_id})
            continue
        skin_paths = forbidden_skin_paths(config)
        if skin_paths:
            errors.append(
                {
                    "code": "per_segment_skin_override_forbidden",
                    "id": segment_id,
                    "paths": skin_paths,
                }
            )
        layout = str(config.get("layout") or "")
        if layout not in {"fixed-left", "fullscreen"}:
            errors.append({"code": "layout_invalid", "id": segment_id, "layout": layout})
        if layout == "fullscreen":
            fullscreen_count += 1
        if config.get("accent") not in ACCENTS:
            errors.append({"code": "accent_invalid", "id": segment_id})
        if not str(config.get("chapter_en") or "").strip():
            errors.append({"code": "chapter_en_missing", "id": segment_id})
        if not str(config.get("chapter_zh") or "").strip():
            errors.append({"code": "chapter_zh_missing", "id": segment_id})
        states = config.get("states")
        if not isinstance(states, list) or not states:
            errors.append({"code": "states_missing", "id": segment_id})
            continue
        previous_reveal = -1.0
        visual_states = 0
        first_visual_action: str | None = None
        estimated_height = 0
        visual_unit_ids: set[str] = set()
        for state_index, state in enumerate(states, start=1):
            state_count += 1
            if not isinstance(state, dict):
                errors.append({"code": "state_not_object", "id": segment_id, "index": state_index})
                continue
            action = str(state.get("action") or "")
            if action not in ACTIONS:
                errors.append({"code": "state_action_invalid", "id": segment_id, "index": state_index})
                continue
            trigger = local_trigger(state, source_to_output, start)
            if trigger is None:
                errors.append({"code": "state_trigger_unmapped", "id": segment_id, "index": state_index})
                continue
            if trigger + 0.03 < previous_reveal:
                errors.append({"code": "state_trigger_not_ascending", "id": segment_id, "index": state_index})
            previous_reveal = max(previous_reveal, trigger)
            if action == "hold":
                if len(str(state.get("reason") or "").strip()) < 8:
                    errors.append({"code": "hold_reason_missing", "id": segment_id, "index": state_index})
                continue
            if action == "clear":
                continue
            state_id = str(state.get("id") or "")
            if not state_id:
                errors.append({"code": "state_id_missing", "id": segment_id, "index": state_index})
            elif state_id in visual_unit_ids:
                errors.append(
                    {
                        "code": "visual_unit_id_duplicate",
                        "id": segment_id,
                        "visual_id": state_id,
                    }
                )
            else:
                visual_unit_ids.add(state_id)
            visual_states += 1
            estimated_height += estimated_state_height(
                state,
                is_first_visual=visual_states == 1,
            )
            if first_visual_action is None:
                first_visual_action = action
                if action != "enter":
                    errors.append(
                        {
                            "code": "chapter_must_enter_before_updates",
                            "id": segment_id,
                            "index": state_index,
                        }
                    )
            elif action == "enter":
                errors.append(
                    {
                        "code": "later_visual_state_must_update_not_reenter",
                        "id": segment_id,
                        "index": state_index,
                    }
                )
            previous_treatment = str(state.get("previous_treatment") or "hold")
            if previous_treatment not in PREVIOUS_TREATMENTS:
                errors.append(
                    {
                        "code": "previous_treatment_invalid",
                        "id": segment_id,
                        "index": state_index,
                        "actual": previous_treatment,
                    }
                )
            if any(key in state for key in ("replace", "replace_state", "remove_previous")):
                errors.append(
                    {
                        "code": "state_replacement_forbidden",
                        "id": segment_id,
                        "index": state_index,
                    }
                )
            state_type = str(state.get("type") or "")
            if state_type not in TYPES:
                errors.append({"code": "state_type_invalid", "id": segment_id, "index": state_index})
            else:
                size_errors, size_selection = audit_card_selection(
                    state=state,
                    state_type=state_type,
                    segment_id=segment_id,
                    state_index=state_index,
                    policy=visual_grammar,
                )
                errors.extend(size_errors)
                if size_selection is not None:
                    card_size_selections.append(size_selection)
            if state_type in {"path", "progressive-list", "comparison"} and str(
                state.get("body") or ""
            ).strip():
                errors.append(
                    {
                        "code": "reference_component_body_forbidden",
                        "id": segment_id,
                        "index": state_index,
                        "type": state_type,
                    }
                )
            if state_type == "comparison" and not str(state.get("icon") or "").strip():
                errors.append(
                    {
                        "code": "comparison_icon_missing",
                        "id": segment_id,
                        "index": state_index,
                    }
                )
            if state_type == "formula":
                parts = state.get("parts")
                if not isinstance(parts, list) or not (2 <= len(parts) <= 7):
                    errors.append(
                        {
                            "code": "formula_parts_missing",
                            "id": segment_id,
                            "index": state_index,
                        }
                    )
            if not str(state.get("title") or "").strip():
                errors.append({"code": "state_title_missing", "id": segment_id, "index": state_index})
            items = state.get("items") or []
            maximum_items = (
                MAXIMUM_COMPOSITE_ITEMS if state_type == "relation" else 4
            )
            if not isinstance(items, list) or len(items) > maximum_items:
                errors.append({"code": "state_items_invalid", "id": segment_id, "index": state_index})
                continue
            item_trigger = trigger
            for item_index, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    errors.append(
                        {"code": "item_not_object", "id": segment_id, "state": state_index, "item": item_index}
                    )
                    continue
                if not str(item.get("text") or "").strip():
                    errors.append(
                        {"code": "item_text_missing", "id": segment_id, "state": state_index, "item": item_index}
                    )
                item_id = str(item.get("id") or "")
                if not item_id:
                    errors.append(
                        {
                            "code": "item_id_missing",
                            "id": segment_id,
                            "state": state_index,
                            "item": item_index,
                        }
                    )
                elif item_id in visual_unit_ids:
                    errors.append(
                        {
                            "code": "visual_unit_id_duplicate",
                            "id": segment_id,
                            "visual_id": item_id,
                        }
                    )
                else:
                    visual_unit_ids.add(item_id)
                resolved = local_trigger(item, source_to_output, start)
                if resolved is None:
                    errors.append(
                        {"code": "item_trigger_unmapped", "id": segment_id, "state": state_index, "item": item_index}
                    )
                elif resolved + 0.03 < item_trigger:
                    errors.append(
                        {"code": "item_trigger_not_ascending", "id": segment_id, "state": state_index, "item": item_index}
                    )
                else:
                    item_trigger = resolved
            if state_type == "formula":
                parts = state.get("parts") if isinstance(state.get("parts"), list) else []
                part_trigger = trigger
                for part_index, part in enumerate(parts, start=1):
                    if not isinstance(part, dict):
                        continue
                    part_id = str(part.get("id") or "")
                    if not part_id:
                        errors.append(
                            {
                                "code": "formula_part_id_missing",
                                "id": segment_id,
                                "state": state_index,
                                "part": part_index,
                            }
                        )
                    elif part_id in visual_unit_ids:
                        errors.append(
                            {
                                "code": "visual_unit_id_duplicate",
                                "id": segment_id,
                                "visual_id": part_id,
                            }
                        )
                    else:
                        visual_unit_ids.add(part_id)
                    resolved = local_trigger(part, source_to_output, start)
                    if resolved is None:
                        errors.append(
                            {
                                "code": "formula_part_trigger_unmapped",
                                "id": segment_id,
                                "state": state_index,
                                "part": part_index,
                            }
                        )
                    elif resolved + 0.03 < part_trigger:
                        errors.append(
                            {
                                "code": "formula_part_trigger_not_ascending",
                                "id": segment_id,
                                "state": state_index,
                                "part": part_index,
                            }
                        )
                    else:
                        part_trigger = resolved
        if visual_states == 0:
            errors.append({"code": "chapter_has_no_visual_state", "id": segment_id})
        elif visual_states > 4:
            errors.append(
                {
                    "code": "chapter_has_too_many_visual_layers",
                    "id": segment_id,
                    "actual": visual_states,
                    "maximum": 4,
                }
            )
        layout_estimate = estimated_chapter_height(states)
        selected_height = int(layout_estimate["estimated_height"])
        if (
            not layout_estimate["fits"]
            and layout_estimate["fits_after_gap_compaction"]
        ):
            selected_height = int(layout_estimate["compact_estimated_height"])
        chapter_height_estimates[segment_id] = selected_height
        chapter_layout_estimates[segment_id] = {
            **layout_estimate,
            "selected_estimated_height": selected_height,
        }
        if layout == "fixed-left" and selected_height > STAGE_HEIGHT_BUDGET_PX:
            request = {
                "segment_id": segment_id,
                "reason": "estimated_stage_overflow",
                "actual": selected_height,
                "maximum": STAGE_HEIGHT_BUDGET_PX,
                "automatic": True,
                "human_review_required": False,
                "strategy_order": automatic_reflow_strategy(),
            }
            layout_reflow_requests.append(request)
            errors.append(
                {
                    "code": "chapter_layout_reflow_required",
                    "id": segment_id,
                    "actual": selected_height,
                    "maximum": STAGE_HEIGHT_BUDGET_PX,
                    "hint": (
                        "AI must automatically reflow same-group information into one "
                        "content-height composite card, then rerun the audit"
                    ),
                }
            )
        first_visual = next(
            (
                local_trigger(state, source_to_output, start)
                for state in states
                if isinstance(state, dict) and state.get("action") in {"enter", "update"}
            ),
            None,
        )
        if first_visual is None or first_visual > 3:
            errors.append({"code": "first_state_too_late", "id": segment_id, "actual": first_visual})

    if fullscreen_count > max(1, int(duration // 150) + 1):
        errors.append({"code": "too_many_fullscreen_transitions", "actual": fullscreen_count})

    intervals.sort()
    if intervals and intervals[0][0] > 8:
        errors.append({"code": "first_chapter_too_late", "actual": round(intervals[0][0], 3)})
    covered = 0.0
    previous_end = 0.0
    for start, end, segment_id in intervals:
        if start < previous_end - 0.05:
            errors.append({"code": "chapter_overlap", "id": segment_id})
        if previous_end and start - previous_end > 12:
            warnings.append(
                {"code": "long_stage_gap", "start": round(previous_end, 3), "end": round(start, 3)}
            )
        covered += max(0, end - max(start, previous_end))
        previous_end = max(previous_end, end)
    coverage_ratio = covered / duration if duration > 0 else 0
    if intervals and coverage_ratio < 0.65:
        errors.append({"code": "stage_coverage_too_low", "actual": round(coverage_ratio, 3), "minimum": 0.65})

    direction_chapters = direction.get("chapters")
    if not isinstance(direction_chapters, list):
        errors.append({"code": "direction_chapters_must_be_array"})
        direction_chapters = []
    direction_ids = {
        str(item.get("segment_id") or item.get("id") or "")
        for item in direction_chapters
        if isinstance(item, dict)
    }
    if direction_ids != ids:
        errors.append(
            {
                "code": "direction_plan_chapter_mismatch",
                "missing_in_direction": sorted(ids - direction_ids),
                "extra_in_direction": sorted(direction_ids - ids),
            }
        )

    report = {
        "schema_version": 3,
        "pipeline_version": PIPELINE_VERSION,
        "ok": not errors,
        "inputs": {
            "brief": file_fingerprint(brief_path),
            "timeline": file_fingerprint(timeline_path),
            "direction": file_fingerprint(direction_path),
            "animation_plan": file_fingerprint(plan_path),
        },
        "duration": round(duration, 3),
        "beat_count": state_count,
        "major_count": len(segments),
        "density_profile": "reference-state-machine",
        "information_model": "persistent-layer-stack",
        "motion_model": "anchored-opacity",
        "chapter_count": len(segments),
        "state_count": state_count,
        "fullscreen_count": fullscreen_count,
        "coverage_ratio": round(coverage_ratio, 3),
        "chapter_height_estimates": chapter_height_estimates,
        "card_sizing_model": "spoken-first-content-height",
        "visual_grammar_model": "spoken-first-relations",
        "stage_layout_model": LAYOUT_MODEL_ID,
        "card_size_selections": card_size_selections,
        "chapter_layout_estimates": chapter_layout_estimates,
        "layout_reflow_requests": layout_reflow_requests,
        "intervals": [
            {"start": round(start, 3), "end": round(end, 3), "beat_id": segment_id}
            for start, end, segment_id in intervals
        ],
        "errors": errors,
        "warnings": warnings,
    }
    write_json(args.output, report)
    print(
        f"visual direction: {'PASS' if report['ok'] else 'BLOCKED'} "
        f"({len(segments)} chapters, {state_count} states, {len(errors)} errors)"
    )
    return 0 if report["ok"] else EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
