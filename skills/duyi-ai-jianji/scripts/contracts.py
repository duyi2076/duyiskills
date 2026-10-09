#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
from __future__ import annotations

from typing import Any


PIPELINE_VERSION = "3.16.0"
FIXED_LEFT_CONTENT_BOUNDS = {
    "max_x": 0.3625,
    "max_y": 0.6,
    "min_x": 0.02890625,
    "min_y": 0.040278,
}
RUN_STATE_SCHEMA_VERSION = 3
AUDIT_REPORT_SCHEMA_VERSION = 3

EXIT_SUCCESS = 0
EXIT_USAGE = 2
EXIT_ENVIRONMENT = 3
EXIT_BLOCKED = 4
EXIT_STAGE_FAILED = 5
EXIT_QA_FAILED = 6
EXIT_LOCKED = 7
EXIT_SCHEMA = 8

STAGE_STATUSES = {
    "pending",
    "running",
    "succeeded",
    "failed",
    "blocked",
    "skipped",
}

STAGE_ORDER = [
    "doctor",
    "preflight",
    "normalize",
    "asr_integrity",
    "editorial_review",
    "human_lock",
    "asr_correction",
    "semantic_review",
    "boundary_refine",
    "audit_gate",
    "caption_structure",
    "cut",
    "remap",
    "rhythm",
    "style_lock",
    "captions",
    "visual_direction",
    "semantic_timing",
    "animations",
    "compose",
    "validate",
    "agent_review",
]


def delivery_dimensions(width: int, height: int) -> tuple[int, int]:
    """Keep native detail when possible, but never deliver 16:9 landscape below 1080p."""
    if width <= 0 or height <= 0:
        raise ValueError("source dimensions must be positive")
    if width <= height:
        return width, height
    if abs(width / height - 16 / 9) > 0.01:
        return width, height
    if height >= 1080:
        return width, height
    return 1920, 1080


def composition_contract(speaker_lane: str = "left") -> dict[str, str]:
    if speaker_lane not in {"left", "right"}:
        raise ValueError("speaker_lane must be 'left' or 'right'")
    return {
        "speaker_lane": speaker_lane,
        "overlay_lane": "left",
        "animation_layout": "reference-fixed-left",
        "panel_mode": "content-panel",
        "outer_background": "transparent",
        "adaptive_repositioning": "false",
    }


def require_mapping(payload: Any, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def validate_run_state(payload: Any) -> dict[str, Any]:
    state = require_mapping(payload, "run state")
    if state.get("schema_version") != RUN_STATE_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported run state schema {state.get('schema_version')!r}; "
            f"expected {RUN_STATE_SCHEMA_VERSION}"
        )
    stages = require_mapping(state.get("stages"), "run state stages")
    missing = [name for name in STAGE_ORDER if name not in stages]
    if missing:
        raise ValueError(f"run state is missing stages: {', '.join(missing)}")
    for name, stage in stages.items():
        stage_map = require_mapping(stage, f"stage {name}")
        if stage_map.get("status") not in STAGE_STATUSES:
            raise ValueError(f"stage {name} has invalid status {stage_map.get('status')!r}")
    return state


def validate_cut_plan(payload: Any) -> dict[str, Any]:
    plan = require_mapping(payload, "cut plan")
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("cut plan must contain a non-empty segments array")
    for index, value in enumerate(segments, start=1):
        segment = require_mapping(value, f"cut plan segment {index}")
        try:
            start = float(segment["source_start"])
            end = float(segment["source_end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"cut plan segment {index} has invalid source bounds") from exc
        if end <= start:
            raise ValueError(f"cut plan segment {index} must end after it starts")
    return plan


def validate_audit_gate(
    report: Any,
    *,
    plan_sha256: str,
    input_sha256: str,
) -> dict[str, Any]:
    audit = require_mapping(report, "audit report")
    if audit.get("schema_version") != AUDIT_REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported audit report schema {audit.get('schema_version')!r}; "
            "rerun audit_cut_plan.py"
        )
    inputs = require_mapping(audit.get("inputs"), "audit report inputs")
    if inputs.get("plan_sha256") != plan_sha256:
        raise ValueError("audit report does not match the current cut plan")
    if inputs.get("source_media_sha256") != input_sha256:
        raise ValueError("audit report does not match the current source media")
    review = require_mapping(audit.get("review"), "audit report review")
    unresolved = review.get("unresolved_ids")
    if not isinstance(unresolved, list):
        raise ValueError("audit report review.unresolved_ids must be an array")
    if audit.get("errors"):
        raise ValueError("audit report contains errors")
    if unresolved:
        raise PermissionError(
            "cut plan has unresolved review items: " + ", ".join(str(item) for item in unresolved)
        )
    if audit.get("blocked") or not audit.get("ok"):
        raise PermissionError("audit report is not approved for cutting")
    return audit
