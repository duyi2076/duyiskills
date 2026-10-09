#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
"""Prepare a bounded, text-only directing brief from the final cut timeline."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from common import file_fingerprint, load_json, write_json
from contracts import PIPELINE_VERSION


def mapped_range(word_ids: list[str], source_to_output: dict[str, Any]) -> dict[str, Any]:
    available = [source_to_output[word_id] for word_id in word_ids if word_id in source_to_output]
    missing = [word_id for word_id in word_ids if word_id not in source_to_output]
    if not available:
        return {"status": "dropped", "output_start": None, "output_end": None, "missing_word_ids": missing}
    return {
        "status": "mapped",
        "output_start": round(min(float(item["start"]) for item in available), 3),
        "output_end": round(max(float(item["end"]) for item in available), 3),
        "missing_word_ids": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a text-only visual-director brief.")
    parser.add_argument("--semantic-map", required=True)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    semantic_path = Path(args.semantic_map).resolve()
    timeline_path = Path(args.timeline).resolve()
    semantic = load_json(semantic_path)
    timeline = load_json(timeline_path)
    propositions = semantic.get("propositions")
    if not isinstance(propositions, list):
        raise ValueError("semantic map must contain propositions")
    source_to_output = timeline.get("source_to_output")
    if not isinstance(source_to_output, dict):
        raise ValueError("mapped timeline must contain source_to_output")

    mapped_propositions: list[dict[str, Any]] = []
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for proposition in propositions:
        if not isinstance(proposition, dict):
            continue
        word_ids = [str(item) for item in proposition.get("source_word_ids", [])]
        item = {
            "id": str(proposition.get("id") or ""),
            "text": str(proposition.get("text") or ""),
            "role": proposition.get("role"),
            "source_word_ids": word_ids,
            "visual_candidate": proposition.get("visual_candidate") is True,
            "visual_template": proposition.get("visual_template"),
            "visual_mode": proposition.get("visual_mode"),
            "visual_segment_id": proposition.get("visual_segment_id"),
            **mapped_range(word_ids, source_to_output),
        }
        mapped_propositions.append(item)
        if item["visual_candidate"] and item["visual_segment_id"]:
            candidates[str(item["visual_segment_id"])].append(item)

    candidate_groups = []
    for candidate_id, items in sorted(candidates.items()):
        starts = [float(item["output_start"]) for item in items if item["output_start"] is not None]
        ends = [float(item["output_end"]) for item in items if item["output_end"] is not None]
        candidate_groups.append(
            {
                "candidate_id": candidate_id,
                "status": "mapped" if starts else "dropped",
                "suggested_template": next(
                    (item["visual_template"] for item in items if item.get("visual_template")),
                    None,
                ),
                "suggested_mode": next(
                    (item["visual_mode"] for item in items if item.get("visual_mode")),
                    None,
                ),
                "proposition_ids": [item["id"] for item in items],
                "source_word_ids": list(
                    dict.fromkeys(
                        word_id for item in items for word_id in item["source_word_ids"]
                    )
                ),
                "output_start": round(min(starts), 3) if starts else None,
                "output_end": round(max(ends), 3) if ends else None,
                "texts": [item["text"] for item in items],
            }
        )

    duration = float(timeline.get("duration") or 0.0)
    transcript_words = [
        {
            "word_id": str(word.get("word_id") or ""),
            "text": str(word.get("text") or ""),
            "start": word.get("start"),
            "end": word.get("end"),
        }
        for word in timeline.get("words", [])
        if isinstance(word, dict) and word.get("word_id")
    ]
    brief = {
        "schema_version": 1,
        "pipeline_version": PIPELINE_VERSION,
        "inputs": {
            "semantic_map": file_fingerprint(semantic_path),
            "timeline": file_fingerprint(timeline_path),
        },
        "duration": round(duration, 3),
        "director_role": "semantic-state-video-director",
        "decision_scope": {
            "text_director": [
                "chapter",
                "state",
                "trigger_word_ids",
                "semantic_reveal_timeline",
                "hold",
                "purpose",
            ],
            "fixed_frame_gate": [
                "reference_canvas_1280x720",
                "fixed_left_stage",
                "no_speaker_avoidance",
                "caption_track_separate"
            ],
        },
        "reference_contract": {
            "system": "reference-1to1",
            "stage": {
                "x": 37,
                "y": 29,
                "small_width": 373,
                "medium_width": 427,
                "maximum_width": 427,
                "maximum_canvas_ratio": 0.33359375,
                "default_size": "medium",
                "canvas": [1280, 720],
            },
            "chapter_count_typical": [3, 6],
            "state_count_typical": [8, 16],
            "header_lead_seconds": 0.3,
            "container_entry_seconds": 0.22,
            "item_entry_seconds": 0.15,
            "exit_seconds": 0.22,
            "information_model": "persistent-layer-stack",
            "motion_model": "anchored-opacity",
            "component_skin": "type-specific-reference",
            "card_sizing_model": "spoken-first-content-height",
            "visual_grammar_model": "spoken-first-relations",
            "stage_layout_model": "measured-content-height-reflow-v1",
            "card_size_rules": {
                "small": "373px; short single point or compact path head",
                "medium": "427px; default and maximum for all relations",
                "maximum": "33.4% of the 1280px reference canvas",
                "required_fields": [
                    "fidelity_mode",
                    "relation_layout",
                    "layout_reason",
                    "card_size",
                    "content_structure",
                    "size_reason",
                ],
                "height_policy": "content-driven; no fixed empty slab",
                "overflow_policy": "AI automatically reflows and retries; never crop or exceed 33.4%",
                "spoken_first_policy": "preserve spoken nodes, actors, order, and relation before formal neatness",
                "multi_item_rows": {
                    "5": [3, 2],
                    "6": [3, 3],
                    "7": [4, 3],
                    "8": [4, 4],
                    "9": [4, 4, 1],
                    "10": [4, 4, 2],
                    "11": [4, 4, 3],
                    "12": [4, 4, 4]
                },
            },
            "panel": {"rgb": [10, 20, 27], "opacity": 0.82},
            "animation_chinese_face": "Noto Sans CJK SC Bold",
            "component_field_rules": {
                "path/progressive-list": "kicker + title + items; body forbidden",
                "comparison": "icon + kicker + title + marker; body forbidden",
                "formula": "2-7 parts with primary/muted/accent tones",
                "relation": "2-12 spoken-first nodes; 9-12 only for one short same-group multi-item composite",
                "quote": "title + optional accent_text + source_name/source_note/source_initial",
                "thesis": "title + optional accent_text/body/items",
            },
            "persistent_after_entry": True,
            "adaptive_repositioning": False,
            "allowed_template": "semantic-stage",
        },
        "semantic_reveal_contract": {
            "policy": "exact-spoken-reveal",
            "required_for": ["state", "item", "formula-part"],
            "required_fields": [
                "spoken_excerpt",
                "evidence_start_word_id",
                "evidence_end_word_id",
                "earliest_allowed_word_id",
                "trigger_word_id",
                "fully_visible_by_word_id",
                "hold_until_word_id",
                "timing_reason",
                "spoiler_check",
            ],
            "rules": [
                "spoken_excerpt must exactly equal the contiguous mapped words between its evidence bounds",
                "trigger_word_id must equal the first rendered trigger_word_id",
                "the trigger must fall inside the spoken evidence window",
                "no visual may appear before earliest_allowed_word_id",
                "persistent visuals must remain semantically relevant through the chapter end",
                "formula parts reveal independently in spoken order",
            ],
            "agent_review_checks": [
                "card meaning matches the exact spoken excerpt",
                "trigger feels natural in continuous playback",
                "future conclusions are not shown early",
                "held information remains relevant",
            ],
        },
        "candidate_groups": candidate_groups,
        "propositions": mapped_propositions,
        "transcript_words": transcript_words,
    }
    write_json(args.output, brief)
    print(
        f"visual brief: {len(mapped_propositions)} propositions / "
        f"{len(candidate_groups)} candidate groups -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
