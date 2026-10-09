#!/usr/bin/env python3
"""Shared deterministic height estimates for the AIJianji fixed-left information stage."""

from __future__ import annotations

import math
from typing import Any


LAYOUT_MODEL_ID = "measured-content-height-reflow-v1"
STAGE_HEIGHT_BUDGET_PX = 690
LAYER_GAP_PX = 24
MINIMUM_LAYER_GAP_PX = 16
MAXIMUM_COMPOSITE_ITEMS = 12


def text_width(value: str) -> float:
    return sum(0.5 if ord(character) < 128 else 1.0 for character in value)


def wrapped_line_count(value: str, *, units_per_line: float) -> int:
    clean = str(value or "").strip()
    if not clean:
        return 0
    return max(1, math.ceil(text_width(clean) / units_per_line))


def relation_row_distribution(relation_layout: str, item_count: int) -> list[int]:
    if item_count <= 0:
        return []
    if relation_layout != "multi-item":
        return [item_count]
    distributions = {
        5: [3, 2],
        6: [3, 3],
        7: [4, 3],
        8: [4, 4],
        9: [4, 4, 1],
        10: [4, 4, 2],
        11: [4, 4, 3],
        12: [4, 4, 4],
    }
    return distributions.get(item_count, [item_count])


def estimated_state_height(
    state: dict[str, Any],
    *,
    is_first_visual: bool = False,
) -> int:
    """Estimate natural CSS height without pretending to replace browser measurement."""
    state_type = str(state.get("type") or "")
    card_size = str(state.get("card_size") or "medium")
    items = state.get("items") if isinstance(state.get("items"), list) else []
    title = str(state.get("title") or "")
    body = str(state.get("body") or "")

    if state_type == "thesis":
        title_lines = wrapped_line_count(
            title,
            units_per_line=10 if card_size == "small" else 12,
        )
        body_lines = wrapped_line_count(
            body,
            units_per_line=16 if card_size == "small" else 19,
        )
        height = 66 + 28 + 14 + max(1, title_lines) * 67
        if body_lines:
            height += 10 + body_lines * 54
        if items:
            total_item_units = sum(
                text_width(str(item.get("text") or ""))
                for item in items
                if isinstance(item, dict)
            )
            item_rows = max(1, math.ceil(total_item_units / 20))
            height += 28 + item_rows * 68 + max(0, item_rows - 1) * 16
        return int(height)

    if state_type == "quote":
        title_lines = wrapped_line_count(
            title,
            units_per_line=9 if card_size == "small" else 11,
        )
        source_note = str(state.get("source_note") or "")
        note_lines = wrapped_line_count(source_note, units_per_line=18)
        return int(84 + 40 + max(1, title_lines) * 104 + 52 + 112 + note_lines * 34)

    if state_type == "comparison":
        return 162

    if state_type == "formula":
        return 172 if is_first_visual else 120

    if state_type == "relation":
        relation_layout = str(state.get("relation_layout") or "")
        title_lines = wrapped_line_count(title, units_per_line=17)
        head_height = 24 + 9 + max(1, title_lines) * 43 + 22
        if relation_layout == "hierarchy":
            content_height = 76 + 24 + 76
        else:
            row_count = len(relation_row_distribution(relation_layout, len(items)))
            content_height = max(1, row_count) * 76 + max(0, row_count - 1) * 14
        return int(52 + head_height + content_height)

    if state_type in {"progressive-list", "path"}:
        return 150 + (20 if items else 0) + len(items) * 104 + max(0, len(items) - 1) * 16

    if state_type == "chat":
        body_lines = wrapped_line_count(body, units_per_line=18)
        return 96 + 16 + max(76, body_lines * 46 + 48) + len(items) * 74

    return 220


def estimated_chapter_height(states: list[dict[str, Any]]) -> dict[str, Any]:
    visual_states = [
        state
        for state in states
        if isinstance(state, dict) and state.get("action") in {"enter", "update"}
    ]
    heights = [
        estimated_state_height(state, is_first_visual=index == 0)
        for index, state in enumerate(visual_states)
    ]
    total = sum(heights) + max(0, len(heights) - 1) * LAYER_GAP_PX
    compact_total = sum(heights) + max(0, len(heights) - 1) * MINIMUM_LAYER_GAP_PX
    return {
        "model": LAYOUT_MODEL_ID,
        "state_heights": heights,
        "layer_gap": LAYER_GAP_PX,
        "minimum_layer_gap": MINIMUM_LAYER_GAP_PX,
        "estimated_height": total,
        "compact_estimated_height": compact_total,
        "maximum_height": STAGE_HEIGHT_BUDGET_PX,
        "fits": total <= STAGE_HEIGHT_BUDGET_PX,
        "fits_after_gap_compaction": compact_total <= STAGE_HEIGHT_BUDGET_PX,
    }


def automatic_reflow_strategy() -> list[dict[str, str]]:
    return [
        {
            "id": "content-height",
            "instruction": "按真实内容高度收紧短卡，禁止保留与内容无关的固定大面积空白",
        },
        {
            "id": "spacing-compaction",
            "instruction": "在不低于美观下限的前提下，把层间距从24px收紧到最低16px",
        },
        {
            "id": "same-group-composite",
            "instruction": "把同一语义组的连续并列信息合并为一个复合卡片外壳，保留逐项触发",
        },
        {
            "id": "completed-summary-strip",
            "instruction": "把已经讲完但仍相关的内容收拢为摘要条，不删除、不改写原始节点",
        },
        {
            "id": "chapter-split",
            "instruction": "仍无法容纳时按真实语义边界拆成新章节，不得裁切或突破33.4%宽度",
        },
    ]
