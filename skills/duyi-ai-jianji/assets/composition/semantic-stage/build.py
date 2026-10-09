#!/usr/bin/env python3
"""Build the locked AIJianji semantic-state overlay as a deterministic HyperFrames project."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT.parent
SKILL_ROOT = ROOT.parents[2]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from stage_layout import (  # noqa: E402
    LAYOUT_MODEL_ID,
    MAXIMUM_COMPOSITE_ITEMS,
    STAGE_HEIGHT_BUDGET_PX,
    estimated_chapter_height,
    estimated_state_height,
)


STYLE_PRESETS = ASSETS / "style-presets.json"
VISUAL_GRAMMAR_PATH = ASSETS / "visual-grammar.json"
STYLE_ID = "dark-reference-fixed"
HYPERFRAMES_VERSION = "0.7.69"
PIPELINE_VERSION = "3.16.0"
TIMELINE_CONTRACT_ID = "semantic-stage-timeline-v1"
CANVAS_WIDTH = 2560
CANVAS_HEIGHT = 1440
ACCENTS = {
    "blue": "#2D78F4",
    "red": "#FF315D",
    "green": "#20E5A0",
    "yellow": "#D8BE55",
}
VISUAL_TYPES = {
    "thesis",
    "quote",
    "chat",
    "comparison",
    "formula",
    "progressive-list",
    "path",
    "relation",
}
ACTIONS = {"enter", "update", "hold", "clear"}
PREVIOUS_TREATMENTS = {"hold", "dim", "cross-out"}
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
CONTAINER_ENTRY_SECONDS = 0.22
ITEM_ENTRY_SECONDS = 0.15
EXIT_SECONDS = 0.22
HEADER_LEAD_SECONDS = 0.30
REFERENCE_STAGE = {
    "x": 37,
    "y": 29,
    "header_height": 56,
}
FIXED_BOUNDS = {
    "min_x": 0.02890625,
    "min_y": 0.040278,
    "max_x": 0.3625,
    "max_y": 0.6,
}
PAINT_RGB_KEYS = {
    "panel_rgb",
    "fullscreen_rgb",
    "shadow_rgb",
    "stage_feather_rgb",
}
PAINT_OPACITY_KEYS = {
    "panel_opacity",
    "panel_strong_opacity",
    "panel_icon_opacity",
    "fullscreen_opacity",
    "shadow_opacity",
    "stage_feather_opacity",
}
PAINT_COLOR_KEYS = {
    "text_primary",
    "text_secondary",
    "text_subheading",
    "text_tertiary",
    "text_muted",
    "panel_text_primary",
    "panel_text_secondary",
    "panel_text_subheading",
    "panel_text_tertiary",
    "panel_text_muted",
    "text_on_accent",
    "border_panel",
    "border_chip",
    "border_comparison",
    "border_formula",
    "border_list",
    "dismiss",
}
PAINT_TOKEN_KEYS = PAINT_RGB_KEYS | PAINT_OPACITY_KEYS | PAINT_COLOR_KEYS
FORBIDDEN_CONFIG_PAINT_KEYS = {
    "css",
    "css_tokens",
    "layout_tokens",
    "paint_tokens",
    "skin",
    "skin_id",
    "style",
    "style_id",
    "timing_tokens",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--style", default=STYLE_ID)
    return parser.parse_args()


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("config must be a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_inputs_sha256(style: dict[str, Any]) -> str:
    return canonical_sha256(
        {
            "builder": file_sha256(Path(__file__).resolve()),
            "gsap": file_sha256(ROOT / "vendor" / "gsap.min.js"),
            "fonts": {
                name: file_sha256(ASSETS / "fonts" / name)
                for name in (
                    "NotoSansCJKsc-Bold.otf",
                    "NotoSansCJKsc-Regular.otf",
                    "NotoSansCJKsc-Medium.otf",
                    "SpaceMono-Bold.ttf",
                )
            },
            "style": style,
            "visual_grammar": read_json(VISUAL_GRAMMAR_PATH),
            "stage_layout": file_sha256(SKILL_ROOT / "scripts" / "stage_layout.py"),
            "hyperframes_version": HYPERFRAMES_VERSION,
            "pipeline_version": PIPELINE_VERSION,
        }
    )


def validate_paint_tokens(style_id: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"style {style_id!r} paint_tokens must be a JSON object")
    actual_keys = set(value)
    if actual_keys != PAINT_TOKEN_KEYS:
        missing = ", ".join(sorted(PAINT_TOKEN_KEYS - actual_keys)) or "none"
        unknown = ", ".join(sorted(actual_keys - PAINT_TOKEN_KEYS)) or "none"
        raise ValueError(
            f"style {style_id!r} paint_tokens must use the locked whitelist; "
            f"missing: {missing}; unknown: {unknown}"
        )
    for key in sorted(PAINT_RGB_KEYS):
        rgb = value[key]
        if (
            not isinstance(rgb, list)
            or len(rgb) != 3
            or any(
                isinstance(channel, bool)
                or not isinstance(channel, int)
                or not 0 <= channel <= 255
                for channel in rgb
            )
        ):
            raise ValueError(
                f"style {style_id!r} paint_tokens.{key} must be three 0-255 integers"
            )
    for key in sorted(PAINT_OPACITY_KEYS):
        opacity = value[key]
        if (
            isinstance(opacity, bool)
            or not isinstance(opacity, (int, float))
            or not 0 <= float(opacity) <= 1
        ):
            raise ValueError(
                f"style {style_id!r} paint_tokens.{key} must be between 0 and 1"
            )
    for key in sorted(PAINT_COLOR_KEYS):
        color = value[key]
        if (
            not isinstance(color, str)
            or len(color) != 7
            or color[0] != "#"
            or any(character not in "0123456789ABCDEF" for character in color[1:])
        ):
            raise ValueError(
                f"style {style_id!r} paint_tokens.{key} must be an uppercase #RRGGBB color"
            )
    return value


def load_skin(style_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = read_json(STYLE_PRESETS)
    presets = payload.get("presets")
    if not isinstance(presets, dict):
        raise ValueError("style-presets.json presets must be a JSON object")
    style = presets.get(style_id)
    if not isinstance(style, dict):
        available = ", ".join(sorted(presets))
        raise ValueError(f"unknown AIJianji style {style_id!r}; available: {available}")
    if str(style.get("skin_id", "")) != style_id:
        raise ValueError(f"style {style_id!r} must use the same locked skin_id")
    tokens = validate_paint_tokens(style_id, style.get("paint_tokens"))
    if str(style.get("font_family_id", "")) != "reference-font-pair":
        raise ValueError(f"style {style_id!r} changed the locked font family")
    if str(style.get("animation_font_file", "")) != "fonts/NotoSansCJKsc-Bold.otf":
        raise ValueError(f"style {style_id!r} changed the locked animation font")
    if str(style.get("subtitle_font_preset", "")) != "reference-caption":
        raise ValueError(f"style {style_id!r} changed the locked subtitle font preset")
    if style_id == "white-wall-fusion-fixed" and (
        tokens["panel_rgb"] != [10, 20, 27]
        or float(tokens["panel_opacity"]) != 0.82
        or tokens["text_primary"] != "#17212B"
        or tokens["panel_text_primary"] != "#F3F5F7"
        or float(tokens["stage_feather_opacity"]) != 0.0
        or float(tokens["fullscreen_opacity"]) != 0.0
    ):
        raise ValueError(
            "white-wall-fusion-fixed is fixed to a transparent stage, dark free "
            "text, and light text inside local dark panels"
        )
    return style, tokens


def rgb_css(value: Any) -> str:
    return ", ".join(str(int(channel)) for channel in value)


def rgba_css(rgb: Any, opacity: Any) -> str:
    alpha = fmt(float(opacity))
    if alpha.startswith("0."):
        alpha = alpha[1:]
    return f"rgba({rgb_css(rgb)}, {alpha})"


def number(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if result < 0:
        raise ValueError(f"{field} must be non-negative")
    return result


def fmt(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def ensure_fresh(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"output path is not a directory: {path}")
        if any(path.iterdir()):
            raise ValueError(f"output directory must be empty: {path}")
    else:
        path.mkdir(parents=True)


def text_width(value: str) -> float:
    return sum(0.5 if ord(character) < 128 else 1.0 for character in value)


def validate_text(value: str, field: str, maximum: float) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field} must be non-empty")
    if text_width(clean) > maximum:
        raise ValueError(f"{field} is too long for the fixed reference stage")
    return clean


def load_visual_grammar() -> dict[str, Any]:
    policy = read_json(VISUAL_GRAMMAR_PATH)
    if policy.get("schema_version") != 3:
        raise ValueError("visual grammar schema must be 3")
    sizes = policy.get("sizes")
    if not isinstance(sizes, dict) or set(sizes) != {"small", "medium"}:
        raise ValueError("visual grammar must define only small and medium cards")
    return policy


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


def validate_card_selection(
    state: dict[str, Any],
    state_type: str,
    index: int,
    policy: dict[str, Any],
) -> dict[str, Any]:
    size = str(state.get("card_size") or "").strip()
    structure = str(state.get("content_structure") or "").strip()
    reason = str(state.get("size_reason") or "").strip()
    default_layouts = {
        "thesis": "single-point",
        "quote": "quote",
        "chat": "chat",
        "comparison": "comparison",
        "formula": "formula",
        "progressive-list": "vertical-list",
        "path": "vertical-list",
    }
    relation_layout = str(
        state.get("relation_layout") or default_layouts.get(state_type, "")
    ).strip()
    fidelity_mode = str(state.get("fidelity_mode") or "spoken-first").strip()
    layout_reason = str(
        state.get("layout_reason")
        or "渲染器兼容默认；正式计划由视觉审计要求显式声明"
    ).strip()
    sizes = policy["sizes"]
    structures = set(policy.get("content_structures") or [])
    relation_layouts = policy.get("relation_layouts") or {}
    if size not in sizes:
        raise ValueError(
            f"state {index} card_size must be small or medium; "
            "medium is the default choice but must still be declared"
        )
    if structure not in structures:
        raise ValueError(f"state {index} content_structure is invalid")
    if text_width(reason) < 8:
        raise ValueError(f"state {index} size_reason must explain the choice")
    if fidelity_mode != "spoken-first":
        raise ValueError(f"state {index} fidelity_mode must be spoken-first")
    if relation_layout not in relation_layouts:
        raise ValueError(f"state {index} relation_layout is invalid or missing")
    if text_width(layout_reason) < 8:
        raise ValueError(f"state {index} layout_reason must explain the spoken relation")

    layout_policy = relation_layouts[relation_layout]
    weight = state_text_weight(state, state_type)
    maximum = float(
        layout_policy.get("maximum_text_weight", sizes[size]["maximum_text_weight"])
    )
    if weight > maximum:
        raise ValueError(
            f"state {index} text weight {weight:g} exceeds {size} card limit "
            f"{maximum:g}; split or compress the information instead of enlarging it"
        )
    compatible_layouts = set(
        (policy.get("type_layout_compatibility") or {}).get(state_type, [])
    )
    if relation_layout not in compatible_layouts:
        raise ValueError(
            f"state {index} type {state_type} cannot use relation_layout "
            f"{relation_layout}"
        )
    allowed_sizes = set(layout_policy.get("allowed_sizes") or [])
    if size not in allowed_sizes:
        raise ValueError(
            f"state {index} relation_layout {relation_layout} does not allow {size} card"
        )
    if state_type == "relation":
        item_count = len(state.get("items") or [])
        minimum = int(layout_policy.get("minimum_items", 0))
        maximum_items = int(layout_policy.get("maximum_items", 0))
        if not minimum <= item_count <= maximum_items:
            raise ValueError(
                f"state {index} relation_layout {relation_layout} requires "
                f"{minimum}-{maximum_items} items"
            )
    if state_type == "formula" and relation_layout != "formula":
        raise ValueError(f"state {index} formula must use relation_layout formula")
    return {
        "size": size,
        "content_structure": structure,
        "reason": reason,
        "relation_layout": relation_layout,
        "fidelity_mode": fidelity_mode,
        "layout_reason": layout_reason,
        "text_weight": weight,
        "reference_width": int(sizes[size]["reference_width"]),
        "template_width": int(sizes[size]["template_width"]),
        "canvas_ratio": float(sizes[size]["canvas_ratio"]),
    }


def highlighted_markup(value: str, accent_text: str) -> str:
    """Render one evidenced accent span without accepting arbitrary HTML."""
    if not accent_text or accent_text not in value:
        return html.escape(value)
    before, match, after = value.partition(accent_text)
    return (
        f"{html.escape(before)}"
        f'<span class="title-accent">{html.escape(match)}</span>'
        f"{html.escape(after)}"
    )


def state_markup(
    state: dict[str, Any],
    index: int,
    visual_grammar: dict[str, Any],
) -> tuple[str, list[tuple[str, float, str]], str, dict[str, Any]]:
    state_type = str(state.get("type") or "thesis")
    if state_type not in VISUAL_TYPES:
        raise ValueError(f"state {index} has unsupported type {state_type!r}")
    card_selection = validate_card_selection(
        state,
        state_type,
        index,
        visual_grammar,
    )
    title_limit = 30 if state_type == "formula" else 14
    title = validate_text(
        str(state.get("title") or ""),
        f"state {index} title",
        title_limit,
    )
    body = str(state.get("body") or "").strip()
    if body and text_width(body) > 32:
        raise ValueError(f"state {index} body is too long")
    label = str(state.get("label") or TYPE_LABELS[state_type]).strip()
    if label and text_width(label) > 18:
        raise ValueError(f"state {index} label is too long")
    previous_treatment = str(state.get("previous_treatment") or "hold")
    if previous_treatment not in PREVIOUS_TREATMENTS:
        raise ValueError(
            f"state {index} previous_treatment must be one of "
            f"{sorted(PREVIOUS_TREATMENTS)}"
        )
    items = state.get("items") or []
    maximum_items = MAXIMUM_COMPOSITE_ITEMS if state_type == "relation" else 4
    if not isinstance(items, list) or len(items) > maximum_items:
        raise ValueError(
            f"state {index} items must be an array of at most {maximum_items} entries"
        )
    item_markup: list[str] = []
    child_reveals: list[tuple[str, float, str]] = []
    item_reveals: list[float] = []
    for item_index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"state {index} item {item_index} must be an object")
        item_text = validate_text(
            str(item.get("text") or ""),
            f"state {index} item {item_index}",
            11,
        )
        item_id = f"state-{index:02d}-item-{item_index:02d}"
        reveal = number(item.get("reveal_at", state.get("reveal_at", 0)), f"{item_id}.reveal_at")
        item_reveals.append(reveal)
        child_reveals.append((item_id, reveal, "item"))
        item_markup.append(
            f'<li id="{item_id}"><span class="item-index">{item_index:02d}</span>'
            f'<span class="item-text">{html.escape(item_text)}</span></li>'
        )
    body_markup = f'<p class="state-body">{html.escape(body)}</p>' if body else ""
    list_markup = f'<ol class="state-items">{"".join(item_markup)}</ol>' if item_markup else ""
    label_markup = f'<div class="state-kicker">{html.escape(label.upper())}</div>' if label else ""
    state_id = f"state-{index:02d}"

    dismiss_markup = '<span class="state-dismiss" aria-hidden="true"></span>'
    if state_type == "relation":
        if body:
            raise ValueError(
                f"state {index} relation cannot render body; use nodes that preserve "
                "the spoken expression"
            )
        relation_layout = card_selection["relation_layout"]
        if "connector" in state:
            raise ValueError(
                f"state {index} relation cannot use one global connector; "
                "bind incoming_connector to each target item"
            )
        relation_items = [
            (
                f'<li id="state-{index:02d}-item-{item_index:02d}" '
                f'class="relation-node relation-node-{item_index:02d}">'
                f'<span>{html.escape(str(item["text"]).strip())}</span></li>'
            )
            for item_index, item in enumerate(items, start=1)
        ]
        if relation_layout in {"narrative-path", "spoken-cause"}:
            flow_parts: list[str] = []
            for item_index, node_markup in enumerate(relation_items):
                item = items[item_index]
                incoming_connector = str(item.get("incoming_connector") or "").strip()
                if item_index == 0:
                    if incoming_connector:
                        raise ValueError(
                            f"state {index} first relation item cannot have incoming_connector"
                        )
                else:
                    if incoming_connector not in {"→", "⇒"}:
                        raise ValueError(
                            f"state {index} relation item {item_index + 1} "
                            "incoming_connector must be → or ⇒"
                        )
                    edge_id = f"state-{index:02d}-edge-{item_index:02d}"
                    flow_parts.append(
                        f'<span id="{edge_id}" class="relation-connector" '
                        f'aria-hidden="true">{html.escape(incoming_connector)}</span>'
                    )
                    child_reveals.append(
                        (edge_id, item_reveals[item_index], "connector")
                    )
                flow_parts.append(node_markup)
            relation_markup = (
                f'<ol class="relation-flow relation-count-{len(items)}">'
                f'{"".join(flow_parts)}</ol>'
            )
        elif relation_layout == "hierarchy":
            parent = relation_items[0]
            children = "".join(relation_items[1:])
            relation_markup = (
                f'<ol class="relation-hierarchy relation-count-{len(items)}">'
                f'<div class="hierarchy-parent">{parent}</div>'
                f'<div class="hierarchy-rail" aria-hidden="true"></div>'
                f'<div class="hierarchy-children">{children}</div></ol>'
            )
        else:
            relation_markup = (
                f'<ol class="relation-grid relation-{html.escape(relation_layout)} '
                f'relation-count-{len(items)}">{"".join(relation_items)}</ol>'
            )
        content_markup = (
            f'<div class="relation-head">{label_markup}'
            f'<h2>{html.escape(title)}</h2></div>{relation_markup}'
        )
    elif state_type in {"progressive-list", "path"}:
        if body:
            raise ValueError(
                f"state {index} {state_type} cannot render body; the reference head "
                "contains only kicker and title"
            )
        if state_type == "path" and not state.get("label"):
            label_markup = (
                f'<div class="state-kicker">THE PATH · {max(1, len(items))} STEPS</div>'
            )
        content_markup = (
            f'<div class="list-head">{label_markup}<h2>{html.escape(title)}</h2>'
            f'{body_markup}</div>{list_markup}'
        )
    elif state_type == "quote":
        source_name = validate_text(
            str(state.get("source_name") or body),
            f"state {index} source_name",
            12,
        )
        source_note = str(state.get("source_note") or "").strip()
        if source_note and text_width(source_note) > 22:
            raise ValueError(f"state {index} source_note is too long")
        source_initial = str(state.get("source_initial") or source_name[:1]).strip()
        if text_width(source_initial) > 2:
            raise ValueError(f"state {index} source_initial is too long")
        accent_text = str(state.get("accent_text") or "").strip()
        content_markup = (
            '<div class="quote-mark" aria-hidden="true">“</div>'
            f'<h2>{highlighted_markup(title, accent_text)}</h2>'
            f'<div class="quote-source"><span class="source-avatar">{html.escape(source_initial)}</span>'
            f'<div class="source-copy">{label_markup}<p class="source-name">{html.escape(source_name)}</p>'
            f'<p class="source-note">{html.escape(source_note)}</p></div></div>'
        )
    elif state_type == "comparison":
        if body:
            raise ValueError(
                f"state {index} comparison cannot render body; the reference row "
                "contains only kicker and title"
            )
        icon = str(state.get("icon") or "●").strip()
        marker = str(state.get("marker") or "⚠").strip()
        if text_width(icon) > 2 or text_width(marker) > 2:
            raise ValueError(f"state {index} comparison icon/marker is too long")
        content_markup = (
            f'<div class="comparison-icon" aria-hidden="true">{html.escape(icon)}</div>'
            f'<div class="comparison-copy">{label_markup}<h2>{html.escape(title)}</h2>'
            f'</div><div class="comparison-marker" aria-hidden="true">{html.escape(marker)}</div>'
        )
    elif state_type == "formula":
        parts = state.get("parts")
        if parts is None:
            parts = [
                {"text": title, "tone": "primary"},
                {"text": body, "tone": "accent"},
            ]
        if not isinstance(parts, list) or not (2 <= len(parts) <= 7):
            raise ValueError(f"state {index} formula parts must contain 2-7 entries")
        part_markup: list[str] = []
        for part_index, part in enumerate(parts, start=1):
            if not isinstance(part, dict):
                raise ValueError(f"state {index} formula part {part_index} must be an object")
            part_text = validate_text(
                str(part.get("text") or ""),
                f"state {index} formula part {part_index}",
                14,
            )
            tone = str(part.get("tone") or "primary")
            if tone not in {"primary", "muted", "accent"}:
                raise ValueError(
                    f"state {index} formula part {part_index} tone must be "
                    "primary, muted, or accent"
                )
            part_id = f"state-{index:02d}-part-{part_index:02d}"
            reveal = number(
                part.get("reveal_at", state.get("reveal_at", 0)),
                f"{part_id}.reveal_at",
            )
            child_reveals.append((part_id, reveal, "item"))
            part_markup.append(
                f'<span id="{part_id}" class="formula-part tone-{tone}">'
                f"{html.escape(part_text)}</span>"
            )
        content_markup = f'<div class="formula-line">{"".join(part_markup)}</div>'
    elif state_type == "chat":
        content_markup = (
            f'<div class="chat-bubble chat-primary">{label_markup}'
            f'<h2>{html.escape(title)}</h2></div>'
            f'<div class="chat-bubble chat-secondary">{body_markup}</div>'
            f'{list_markup}'
        )
    else:
        accent_text = str(state.get("accent_text") or "").strip()
        content_markup = (
            f'{label_markup}<h2>{highlighted_markup(title, accent_text)}</h2>'
            f'{body_markup}{list_markup}'
        )
    return (
        f'<article id="{state_id}" class="state-layer state-{html.escape(state_type)}" '
        f'data-state-type="{html.escape(state_type)}" '
        f'data-card-size="{html.escape(card_selection["size"])}" '
        f'data-content-structure="{html.escape(card_selection["content_structure"])}" '
        f'data-relation-layout="{html.escape(card_selection["relation_layout"])}" '
        f'data-fidelity-mode="{html.escape(card_selection["fidelity_mode"])}" '
        f'data-previous-treatment="{html.escape(previous_treatment)}" '
        f'>{dismiss_markup}{content_markup}</article>',
        child_reveals,
        previous_treatment,
        card_selection,
    )


def main() -> int:
    args = parse_args()
    style, paint = load_skin(args.style)
    visual_grammar = load_visual_grammar()
    config = read_json(args.config.resolve())
    forbidden_keys = FORBIDDEN_CONFIG_PAINT_KEYS.intersection(config)
    if forbidden_keys:
        raise ValueError(
            "skin paint is selected only by --style; config cannot contain "
            + ", ".join(sorted(forbidden_keys))
        )
    ensure_fresh(args.out_dir.resolve())

    layout = str(config.get("layout") or "fixed-left")
    if layout not in {"fixed-left", "fullscreen"}:
        raise ValueError("layout must be fixed-left or fullscreen")
    accent_name = str(config.get("accent") or "blue")
    if accent_name not in ACCENTS:
        raise ValueError(f"accent must be one of {sorted(ACCENTS)}")
    accent = ACCENTS[accent_name]
    duration = number(config.get("duration"), "duration")
    if duration < 1.2:
        raise ValueError("duration must be at least 1.2 seconds")
    chapter_en = validate_text(str(config.get("chapter_en") or ""), "chapter_en", 24).upper()
    chapter_zh = validate_text(str(config.get("chapter_zh") or ""), "chapter_zh", 14)
    states = config.get("states")
    if not isinstance(states, list) or not states:
        raise ValueError("states must contain at least one state")
    if len(states) > 10:
        raise ValueError("a chapter may contain at most ten states including holds and clear")

    markup: list[str] = []
    timeline: list[str] = []
    assertions: list[dict[str, Any]] = [
        {"kind": "appearsBy", "selector": "#chapter-header", "bySec": 0.36},
        {"kind": "staysInFrame", "selector": "#chapter-header"},
    ]
    visible_states: list[str] = []
    card_size_selections: list[dict[str, Any]] = []
    visual_index = 0
    first_visual_at: float | None = None
    estimated_height = 0
    for state_index, state in enumerate(states, start=1):
        if not isinstance(state, dict):
            raise ValueError(f"state {state_index} must be an object")
        action = str(state.get("action") or "")
        if action not in ACTIONS:
            raise ValueError(f"state {state_index} action must be one of {sorted(ACTIONS)}")
        reveal = number(state.get("reveal_at", 0), f"state {state_index}.reveal_at")
        if reveal > duration:
            raise ValueError(f"state {state_index} reveal_at exceeds chapter duration")
        if action == "hold":
            if len(str(state.get("reason") or "").strip()) < 8:
                raise ValueError(f"hold state {state_index} needs an explicit reason")
            continue
        if action == "clear":
            if visible_states:
                timeline.append(
                    f'.to(".state-layer", {{ autoAlpha: 0, duration: {fmt(EXIT_SECONDS)}, '
                    f'ease: "power1.out" }}, {fmt(reveal)})'
                )
                visible_states.clear()
            continue

        if visual_index == 0 and action != "enter":
            raise ValueError("the first visual state in a chapter must use action='enter'")
        if visual_index > 0 and action == "enter":
            raise ValueError("later visual states must use action='update' to append layers")
        visual_index += 1
        estimated_height += estimated_state_height(
            state,
            is_first_visual=visual_index == 1,
        )
        state_id = f"state-{visual_index:02d}"
        state_html, child_reveals, previous_treatment, card_selection = state_markup(
            state,
            visual_index,
            visual_grammar,
        )
        card_size_selections.append(
            {
                "state_id": state_id,
                "state_type": str(state.get("type") or "thesis"),
                **card_selection,
            }
        )
        markup.append(state_html)
        scheduled_reveal = (
            max(reveal, HEADER_LEAD_SECONDS)
            if first_visual_at is None
            else reveal
        )
        if first_visual_at is None:
            first_visual_at = reveal
        if visible_states and previous_treatment in {"dim", "cross-out"}:
            previous_state = visible_states[-1]
            timeline.append(
                f'.to("#{previous_state}", {{ opacity: .42, duration: .18, '
                f'ease: "power1.out" }}, {fmt(scheduled_reveal)})'
            )
            if previous_treatment == "cross-out":
                timeline.append(
                    f'.fromTo("#{previous_state} .state-dismiss", '
                    f'{{ autoAlpha: 0, scale: .78 }}, '
                    f'{{ autoAlpha: 1, scale: 1, duration: .18, ease: "power2.out", '
                    f'immediateRender: false }}, {fmt(scheduled_reveal)})'
                )
        timeline.append(
            f'.fromTo("#{state_id}", {{ autoAlpha: 0 }}, '
            f'{{ autoAlpha: 1, duration: {fmt(CONTAINER_ENTRY_SECONDS)}, '
            f'ease: "power1.out", '
            f'immediateRender: false }}, {fmt(scheduled_reveal)})'
        )
        assertions.extend(
            [
                {
                    "kind": "appearsBy",
                    "selector": f"#{state_id}",
                    "bySec": round(
                        scheduled_reveal + CONTAINER_ENTRY_SECONDS + 0.04,
                        3,
                    ),
                },
                {"kind": "staysInFrame", "selector": f"#{state_id}"},
            ]
        )
        for child_id, child_reveal, child_kind in child_reveals:
            if child_reveal > duration:
                raise ValueError(f"{child_id} reveal_at exceeds chapter duration")
            if child_reveal + 0.001 < reveal:
                raise ValueError(f"{child_id} reveal_at precedes its parent state")
            scheduled_child_reveal = max(child_reveal, scheduled_reveal)
            if child_kind == "connector":
                timeline.append(
                    f'.fromTo("#{child_id}", {{ autoAlpha: 0, scaleX: 0 }}, '
                    f'{{ autoAlpha: 1, scaleX: 1, duration: .22, '
                    f'ease: "power2.out", immediateRender: false }}, '
                    f'{fmt(scheduled_child_reveal)})'
                )
            else:
                timeline.append(
                    f'.fromTo("#{child_id}", {{ autoAlpha: 0 }}, '
                    f'{{ autoAlpha: 1, duration: {fmt(ITEM_ENTRY_SECONDS)}, '
                    f'ease: "power1.out", '
                    f'immediateRender: false }}, {fmt(scheduled_child_reveal)})'
                )
            assertions.append(
                {
                    "kind": "appearsBy",
                    "selector": f"#{child_id}",
                    "bySec": round(
                        scheduled_child_reveal + ITEM_ENTRY_SECONDS + 0.04,
                        3,
                    ),
                }
            )
        visible_states.append(state_id)

    if visual_index == 0:
        raise ValueError("states must contain at least one enter or update action")
    layout_estimate = estimated_chapter_height(states)
    estimated_height = int(layout_estimate["estimated_height"])
    selected_layer_gap = int(layout_estimate["layer_gap"])
    if not layout_estimate["fits"] and layout_estimate["fits_after_gap_compaction"]:
        selected_layer_gap = int(layout_estimate["minimum_layer_gap"])
        estimated_height = int(layout_estimate["compact_estimated_height"])
    if layout == "fixed-left" and estimated_height > STAGE_HEIGHT_BUDGET_PX:
        raise ValueError(
            "fixed-left state layers exceed the 690px reference height budget after "
            "safe spacing compaction; automatically reflow same-group information into "
            "one composite card or split at a real semantic boundary"
        )
    exit_at = max(0.8, duration - EXIT_SECONDS)
    timeline.append(
        f'.to("#stage-shell", {{ autoAlpha: 0, duration: {fmt(EXIT_SECONDS)}, '
        f'ease: "power1.out" }}, {fmt(exit_at)})'
    )

    root_class = "layout-fullscreen" if layout == "fullscreen" else "layout-fixed-left"
    motion_payload = {"duration": round(duration, 3), "assertions": assertions}
    config_sha256 = canonical_sha256(config)
    timeline_contract = {
        "id": TIMELINE_CONTRACT_ID,
        "header_lead_seconds": HEADER_LEAD_SECONDS,
        "container_entry_seconds": CONTAINER_ENTRY_SECONDS,
        "item_entry_seconds": ITEM_ENTRY_SECONDS,
        "exit_seconds": EXIT_SECONDS,
        "dom_sha256": canonical_sha256(
            {
                "canvas": [CANVAS_WIDTH, CANVAS_HEIGHT],
                "root_class": root_class,
                "duration": round(duration, 6),
                "chapter_en": chapter_en,
                "chapter_zh": chapter_zh,
                "markup": markup,
            }
        ),
        "timeline_sha256": canonical_sha256(
            {
                "config_sha256": config_sha256,
                "header_sequence": [
                    ["#chapter-rail", 0.02, 0.18],
                    [".chapter-en", 0.06, 0.18],
                    [".chapter-zh", 0.12, 0.18],
                ],
                "state_steps": timeline,
            }
        ),
        "assertions_sha256": canonical_sha256(motion_payload),
    }
    panel_rgba = rgba_css(paint["panel_rgb"], paint["panel_opacity"])
    panel_strong_rgba = rgba_css(
        paint["panel_rgb"],
        paint["panel_strong_opacity"],
    )
    panel_icon_rgba = rgba_css(
        paint["panel_rgb"],
        paint["panel_icon_opacity"],
    )
    fullscreen_rgba = rgba_css(
        paint["fullscreen_rgb"],
        paint["fullscreen_opacity"],
    )
    shadow_rgba = rgba_css(paint["shadow_rgb"], paint["shadow_opacity"])
    feather_rgba = rgba_css(
        paint["stage_feather_rgb"],
        paint["stage_feather_opacity"],
    )
    feather_clear = rgba_css(paint["stage_feather_rgb"], 0)
    feather_background = (
        "none"
        if float(paint["stage_feather_opacity"]) == 0
        else (
            "radial-gradient("
            f"ellipse at 28% 32%, {feather_rgba} 0%, "
            f"{feather_rgba} 48%, {feather_clear} 78%)"
        )
    )
    free_text_shadow = (
        "1.5px 0 0 rgba(255,255,255,.92), "
        "-1.5px 0 0 rgba(255,255,255,.92), "
        "0 1.5px 0 rgba(255,255,255,.92), "
        "0 -1.5px 0 rgba(255,255,255,.92), "
        "1px 1px 2px rgba(255,255,255,.76)"
        if args.style == "white-wall-fusion-fixed"
        else "none"
    )
    html_text = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={CANVAS_WIDTH}, height={CANVAS_HEIGHT}" />
    <title>AIJianji Semantic Stage</title>
    <script src="./vendor/gsap.min.js"></script>
    <style>
      @font-face {{
        font-family: "AIJianji Chinese Bold";
        src: url("./vendor/NotoSansCJKsc-Bold.otf") format("opentype");
        font-weight: 700;
        font-display: block;
      }}
      @font-face {{
        font-family: "AIJianji Chinese";
        src: url("./vendor/NotoSansCJKsc-Regular.otf") format("opentype");
        font-weight: 400;
        font-display: block;
      }}
      @font-face {{
        font-family: "AIJianji Chinese Medium";
        src: url("./vendor/NotoSansCJKsc-Medium.otf") format("opentype");
        font-weight: 500;
        font-display: block;
      }}
      @font-face {{
        font-family: "AIJianji English";
        src: url("./vendor/SpaceMono-Bold.ttf") format("truetype");
        font-weight: 700;
        font-display: block;
      }}
      @font-face {{
        font-family: "AIJianji Emoji";
        src: local("Apple Color Emoji");
        font-display: block;
      }}
      * {{ box-sizing: border-box; }}
      html, body {{
        width: {CANVAS_WIDTH}px;
        height: {CANVAS_HEIGHT}px;
        margin: 0;
        overflow: hidden;
        background: transparent;
      }}
      body {{
        color: {paint["text_primary"]};
        font-family: "AIJianji Chinese", sans-serif;
        -webkit-font-smoothing: antialiased;
        text-rendering: geometricPrecision;
      }}
      #root, #clip {{ position: relative; width: 100%; height: 100%; overflow: hidden; }}
      #clip {{ position: absolute; inset: 0; }}
      .clip {{ visibility: hidden; }}
      #stage-shell {{
        position: absolute;
        left: 74px;
        top: 58px;
        width: 854px;
        transform-origin: top left;
      }}
      #stage-shell::before {{
        content: "";
        position: absolute;
        z-index: 0;
        inset: -76px -96px -100px -76px;
        pointer-events: none;
        background: {feather_background};
      }}
      #chapter-header {{
        position: relative;
        z-index: 1;
        width: fit-content;
        min-width: 520px;
        max-width: 854px;
        height: 112px;
        padding: 6px 0 0 28px;
        overflow: hidden;
      }}
      #chapter-rail {{
        position: absolute;
        opacity: 0;
        visibility: hidden;
        left: 0;
        top: 0;
        width: 6px;
        height: 112px;
        border-radius: 4px;
        background: {accent};
        transform-origin: top center;
      }}
      .chapter-en {{
        opacity: 0;
        visibility: hidden;
        color: {accent};
        font-family: "AIJianji English", monospace;
        font-size: 40px;
        line-height: 1.1;
        letter-spacing: .31em;
        white-space: nowrap;
      }}
      .chapter-zh {{
        opacity: 0;
        visibility: hidden;
        margin-top: 12px;
        color: {paint["text_subheading"]};
        font-size: 32px;
        line-height: 1;
        letter-spacing: .01em;
        text-shadow: {free_text_shadow};
      }}
      #state-stack {{
        position: relative;
        z-index: 1;
        display: flex;
        flex-direction: column;
        align-items: flex-start;
        gap: {selected_layer_gap}px;
        width: 854px;
        height: auto;
        max-height: 690px;
        margin-top: 4px;
        overflow: visible;
      }}
      .state-layer {{
        position: relative;
        flex: 0 0 auto;
        --card-width: 854px;
        width: var(--card-width);
        opacity: 0;
        visibility: hidden;
      }}
      .state-layer[data-card-size="small"] {{ --card-width: 746px; }}
      .state-layer[data-card-size="medium"] {{ --card-width: 854px; }}
      .state-kicker {{
        margin-bottom: 12px;
        color: {accent};
        font-family: "AIJianji English", monospace;
        font-size: 28px;
        line-height: 1;
        letter-spacing: .28em;
        white-space: nowrap;
      }}
      h2 {{
        margin: 0;
        color: {paint["text_primary"]};
        font-family: "AIJianji Chinese Bold", sans-serif;
        font-size: 54px;
        font-weight: 700;
        line-height: 1.2;
        letter-spacing: 0;
        text-shadow: {free_text_shadow};
      }}
      .title-accent {{ color: {accent}; }}
      .state-body {{
        margin: 12px 0 0;
        color: {paint["text_secondary"]};
        font-size: 30px;
        line-height: 1.35;
        text-shadow: {free_text_shadow};
      }}
      .state-dismiss {{
        position: absolute;
        z-index: 4;
        right: 26px;
        top: 20px;
        width: 54px;
        height: 54px;
        opacity: 0;
        visibility: hidden;
      }}
      .state-dismiss::before,
      .state-dismiss::after {{
        content: "";
        position: absolute;
        left: 25px;
        top: 0;
        width: 6px;
        height: 58px;
        border-radius: 3px;
        background: {paint["dismiss"]};
      }}
      .state-dismiss::before {{ transform: rotate(45deg); }}
      .state-dismiss::after {{ transform: rotate(-45deg); }}

      /* Opening / thesis slab: measured from the 00:05 reference frame. */
      .state-thesis {{
        width: var(--card-width);
        min-height: 0;
        padding: 44px 44px 32px;
        border: 2px solid color-mix(in srgb, {accent} 36%, {paint["border_panel"]});
        border-radius: 14px;
        background: {panel_rgba};
        box-shadow: 0 18px 52px {shadow_rgba};
      }}
      .state-thesis:has(.state-items) {{ min-height: 0; }}
      .state-thesis .state-kicker {{ margin-bottom: 24px; }}
      .state-thesis:has(.state-items) .state-kicker {{ margin-bottom: 36px; }}
      .state-thesis h2 {{ font-size: 56px; }}
      .state-thesis h2 {{
        color: {paint["panel_text_primary"]};
        text-shadow: none;
      }}
      .state-thesis:has(.state-items) h2 {{ font-size: 72px; }}
      .state-thesis:has(.state-items) .title-accent {{
        font-size: 104px;
        line-height: .75;
      }}
      .state-thesis .state-body {{
        margin-top: 10px;
        color: {paint["panel_text_primary"]};
        font-family: "AIJianji Chinese Bold", sans-serif;
        font-size: 40px;
        text-shadow: none;
      }}
      .state-thesis:has(.state-items) .state-body {{ font-size: 72px; }}
      .state-thesis .state-items {{
        display: flex;
        flex-wrap: wrap;
        gap: 16px;
        margin-top: 28px;
      }}
      .state-thesis .state-items li {{
        display: block;
        min-height: 0;
        padding: 12px 28px 14px;
        border: 2px solid color-mix(in srgb, {accent} 48%, {paint["border_chip"]});
        border-radius: 10px;
        background: color-mix(in srgb, {accent} 10%, {panel_strong_rgba});
      }}
      .state-thesis .item-index {{ display: none; }}
      .state-thesis .item-text {{
        color: {paint["panel_text_primary"]};
        font-size: 44px;
        text-shadow: none;
      }}

      /* Quote is deliberately unboxed in the reference. */
      .state-quote {{
        width: var(--card-width);
        padding: 12px 0 8px;
        background: transparent;
      }}
      .quote-mark {{
        height: 64px;
        color: {accent};
        font-family: "AIJianji Chinese Bold", sans-serif;
        font-size: 72px;
        font-weight: 700;
        line-height: .9;
      }}
      .state-quote h2 {{
        max-width: var(--card-width);
        margin-top: 40px;
        font-size: 72px;
        line-height: 1.45;
        white-space: pre-line;
      }}
      .quote-source {{
        position: relative;
        margin-top: 52px;
        min-height: 112px;
      }}
      .source-avatar {{
        display: grid;
        place-items: center;
        position: absolute;
        left: 0;
        top: 0;
        width: 112px;
        height: 112px;
        border-radius: 50%;
        color: {paint["text_on_accent"]};
        background: {accent};
        font-family: "AIJianji Chinese Bold", sans-serif;
        font-size: 46px;
      }}
      .source-copy {{ padding-left: 136px; }}
      .quote-source .state-kicker {{
        margin: 0 0 8px;
        color: {paint["text_secondary"]};
        font-size: 28px;
      }}
      .source-name {{
        margin: 0;
        color: {paint["text_primary"]};
        font-family: "AIJianji Chinese Bold", sans-serif;
        font-size: 48px;
      }}
      .source-note {{ margin: 4px 0 0; color: {paint["text_tertiary"]}; font-size: 28px; }}

      /* Bordered comparison rows used by THE FLOOD and similar sections. */
      .state-comparison {{
        display: grid;
        grid-template-columns: 112px 1fr 48px;
        align-items: center;
        width: var(--card-width);
        min-height: 162px;
        padding: 24px 28px 24px 32px;
        border: 2px solid color-mix(in srgb, {accent} 78%, {paint["border_comparison"]});
        border-radius: 16px;
        background: {panel_rgba};
        box-shadow: 0 18px 52px {shadow_rgba};
      }}
      .comparison-icon {{
        display: grid;
        place-items: center;
        width: 88px;
        height: 88px;
        border-radius: 16px;
        background: color-mix(in srgb, {accent} 12%, {panel_icon_rgba});
        font-family: "AIJianji Emoji";
        font-size: 44px;
      }}
      .state-comparison .state-kicker {{
        margin: 0 0 8px;
        font-size: 26px;
      }}
      .state-comparison h2 {{
        color: {paint["panel_text_primary"]};
        font-size: 44px;
        line-height: 1.05;
        text-shadow: none;
      }}
      .comparison-marker {{
        justify-self: end;
        color: {accent};
        font-size: 32px;
      }}

      /* Wide one-line formula card measured from the 01:20 reference frame. */
      .state-formula {{
        width: var(--card-width);
        min-height: 120px;
        padding: 24px 36px 26px;
        border: 2px solid color-mix(in srgb, {accent} 76%, {paint["border_formula"]});
        border-radius: 14px;
        background: {panel_rgba};
        box-shadow: 0 18px 52px {shadow_rgba};
      }}
      .state-formula:first-child {{ margin-top: 52px; }}
      .formula-line {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: nowrap;
        gap: 14px;
        min-height: 68px;
      }}
      .formula-part {{
        font-family: "AIJianji Chinese Bold", sans-serif;
        font-size: 48px;
        line-height: 1;
        white-space: nowrap;
        opacity: 0;
        visibility: hidden;
      }}
      .tone-primary {{ color: {paint["panel_text_primary"]}; }}
      .tone-muted {{ color: {paint["panel_text_muted"]}; }}
      .tone-accent {{ color: {accent}; }}

      /* Spoken-first relation grammar. The renderer arranges the evidenced
         nodes but never rewrites their wording, order, actor, or relation. */
      .state-relation {{
        width: var(--card-width);
        padding: 24px 28px 28px;
        border: 2px solid color-mix(in srgb, {accent} 58%, {paint["border_panel"]});
        border-radius: 14px;
        background: {panel_rgba};
        box-shadow: 0 18px 52px {shadow_rgba};
      }}
      .relation-head {{ margin-bottom: 22px; }}
      .relation-head .state-kicker {{ margin-bottom: 9px; font-size: 24px; }}
      .relation-head h2 {{
        color: {paint["panel_text_primary"]};
        font-size: 38px;
        line-height: 1.12;
        text-shadow: none;
      }}
      .relation-flow,
      .relation-grid,
      .relation-hierarchy {{
        margin: 0;
        padding: 0;
        list-style: none;
      }}
      .relation-flow {{
        display: flex;
        align-items: stretch;
        width: 100%;
      }}
      .relation-flow .relation-node {{
        flex: 0 1 auto;
        min-width: 0;
        padding: 16px 13px;
      }}
      .relation-connector {{
        display: flex;
        flex: 1 1 34px;
        min-width: 30px;
        align-items: center;
        justify-content: center;
        color: {accent};
        font-family: "AIJianji Chinese Bold", sans-serif;
        font-size: 36px;
        transform-origin: left center;
        opacity: 0;
        visibility: hidden;
      }}
      .relation-node {{
        display: grid;
        place-items: center;
        min-height: 76px;
        border: 2px solid color-mix(in srgb, {accent} 40%, {paint["border_chip"]});
        border-radius: 10px;
        background: color-mix(in srgb, {accent} 9%, {panel_strong_rgba});
        color: {paint["panel_text_primary"]};
        font-family: "AIJianji Chinese Bold", sans-serif;
        font-size: 31px;
        line-height: 1.12;
        text-align: center;
        white-space: nowrap;
        opacity: 0;
        visibility: hidden;
      }}
      .relation-grid {{
        display: grid;
        gap: 14px;
        width: 100%;
      }}
      .relation-parallel,
      .relation-comparison {{
        grid-template-columns: repeat(var(--relation-count), minmax(0, 1fr));
      }}
      .relation-count-2 {{ --relation-count: 2; }}
      .relation-count-3 {{ --relation-count: 3; }}
      .relation-count-4 {{ --relation-count: 4; }}
      .relation-multi-item {{
        grid-template-columns: repeat(12, minmax(0, 1fr));
      }}
      .relation-multi-item .relation-node {{ white-space: normal; }}
      .relation-multi-item.relation-count-5 .relation-node:nth-child(-n+3),
      .relation-multi-item.relation-count-6 .relation-node {{ grid-column: span 4; }}
      .relation-multi-item.relation-count-5 .relation-node:nth-child(4) {{
        grid-column: 3 / span 4;
      }}
      .relation-multi-item.relation-count-5 .relation-node:nth-child(5) {{
        grid-column: 7 / span 4;
      }}
      .relation-multi-item.relation-count-7 .relation-node:nth-child(-n+4),
      .relation-multi-item.relation-count-8 .relation-node {{ grid-column: span 3; }}
      .relation-multi-item.relation-count-7 .relation-node:nth-child(5) {{
        grid-column: 2 / span 3;
      }}
      .relation-multi-item.relation-count-7 .relation-node:nth-child(6) {{
        grid-column: 5 / span 3;
      }}
      .relation-multi-item.relation-count-7 .relation-node:nth-child(7) {{
        grid-column: 8 / span 3;
      }}
      .relation-multi-item.relation-count-9 .relation-node,
      .relation-multi-item.relation-count-10 .relation-node,
      .relation-multi-item.relation-count-11 .relation-node,
      .relation-multi-item.relation-count-12 .relation-node {{
        grid-column: span 3;
        white-space: normal;
      }}
      .relation-multi-item.relation-count-9 .relation-node:nth-child(9) {{
        grid-column: 5 / span 3;
      }}
      .relation-multi-item.relation-count-10 .relation-node:nth-child(9) {{
        grid-column: 4 / span 3;
      }}
      .relation-multi-item.relation-count-10 .relation-node:nth-child(10) {{
        grid-column: 7 / span 3;
      }}
      .relation-multi-item.relation-count-11 .relation-node:nth-child(9) {{
        grid-column: 2 / span 3;
      }}
      .relation-multi-item.relation-count-11 .relation-node:nth-child(10) {{
        grid-column: 5 / span 3;
      }}
      .relation-multi-item.relation-count-11 .relation-node:nth-child(11) {{
        grid-column: 8 / span 3;
      }}
      .relation-hierarchy .hierarchy-parent {{
        display: flex;
        justify-content: center;
      }}
      .relation-hierarchy .hierarchy-parent .relation-node {{
        width: min(46%, 330px);
      }}
      .hierarchy-rail {{
        width: 2px;
        height: 24px;
        margin: 0 auto;
        background: {accent};
      }}
      .hierarchy-children {{
        display: grid;
        grid-template-columns: repeat(var(--relation-count), minmax(0, 1fr));
        gap: 14px;
      }}
      .relation-hierarchy.relation-count-2 {{ --relation-count: 1; }}
      .relation-hierarchy.relation-count-3 {{ --relation-count: 2; }}
      .relation-hierarchy.relation-count-4 {{ --relation-count: 3; }}

      /* Path and progressive list: compact panel first, rows added below. */
      .state-progressive-list,
      .state-path {{
        width: var(--card-width);
        background: transparent;
      }}
      .list-head {{
        width: var(--card-width);
        min-height: 150px;
        padding: 26px 30px 26px;
        border-radius: 10px;
        background: {panel_rgba};
        box-shadow: 0 18px 52px {shadow_rgba};
      }}
      .state-progressive-list .list-head {{
        width: var(--card-width);
        border: 2px solid color-mix(in srgb, {accent} 64%, {paint["border_list"]});
      }}
      .list-head h2 {{
        color: {paint["panel_text_primary"]};
        font-size: 38px;
        text-shadow: none;
      }}
      .state-items {{
        display: grid;
        gap: 16px;
        margin: 20px 0 0;
        padding: 0;
        list-style: none;
      }}
      .state-items li {{
        display: grid;
        grid-template-columns: 104px 1fr;
        align-items: center;
        min-height: 104px;
        padding: 0;
        border: 0;
        background: transparent;
        opacity: 0;
        visibility: hidden;
      }}
      .item-index {{
        color: {accent};
        font-family: "AIJianji English", monospace;
        font-size: 50px;
        letter-spacing: 0;
      }}
      .item-text {{
        color: {paint["text_primary"]};
        font-family: "AIJianji Chinese Medium", sans-serif;
        font-size: 50px;
        line-height: 1.18;
        text-shadow: {free_text_shadow};
      }}

      /* Chat keeps each statement as an independent dark bubble. */
      .state-chat {{
        width: var(--card-width);
        background: transparent;
      }}
      .chat-bubble {{
        width: fit-content;
        max-width: calc(var(--card-width) - 34px);
        padding: 24px 32px;
        border-radius: 12px;
        background: {panel_rgba};
        box-shadow: 0 18px 52px {shadow_rgba};
      }}
      .chat-secondary {{ margin-top: 16px; margin-left: 68px; }}
      .chat-bubble h2 {{
        color: {paint["panel_text_primary"]};
        font-size: 42px;
        text-shadow: none;
      }}
      .chat-bubble .state-body {{
        margin: 0;
        color: {paint["panel_text_secondary"]};
        font-size: 34px;
        text-shadow: none;
      }}

      .layout-fullscreen #stage-shell {{
        left: 0;
        top: 0;
        display: grid;
        place-content: center;
        width: {CANVAS_WIDTH}px;
        height: {CANVAS_HEIGHT}px;
        padding: 210px 500px;
        background: {fullscreen_rgba};
      }}
      .layout-fullscreen #chapter-header {{
        width: 1500px;
        max-width: 1500px;
        height: 142px;
        padding-top: 22px;
        text-align: center;
        border-bottom: 5px solid {accent};
        background: transparent;
      }}
      .layout-fullscreen #chapter-rail {{ display: none; }}
      .layout-fullscreen .chapter-en {{ font-size: 54px; }}
      .layout-fullscreen .chapter-zh {{ font-size: 30px; }}
      .layout-fullscreen #state-stack {{ width: 1500px; height: 430px; margin-top: 32px; }}
      .layout-fullscreen .state-layer {{
        width: 1500px;
        min-height: 250px;
        padding: 50px 80px;
        text-align: center;
      }}
      .layout-fullscreen h2 {{ font-size: 78px; }}
      .layout-fullscreen .state-body {{ font-size: 38px; }}
    </style>
  </head>
  <body>
    <main id="root" class="{root_class}" data-composition-id="semantic-stage"
      data-start="0" data-width="{CANVAS_WIDTH}" data-height="{CANVAS_HEIGHT}"
      data-duration="{fmt(duration)}">
      <section id="clip" class="clip" data-start="0" data-duration="{fmt(duration)}" data-track-index="1">
        <div id="stage-shell">
          <header id="chapter-header">
            <span id="chapter-rail" aria-hidden="true"></span>
            <div class="chapter-en">{html.escape(chapter_en)}</div>
            <div class="chapter-zh">{html.escape(chapter_zh)}</div>
          </header>
          <div id="state-stack">{"".join(markup)}</div>
        </div>
      </section>
    </main>
    <script>
      window.__timelines = window.__timelines || {{}};
      const tl = gsap.timeline({{ paused: true }});
      tl.fromTo("#chapter-rail", {{ autoAlpha: 0, scaleY: 0 }},
        {{ autoAlpha: 1, scaleY: 1, duration: .18, ease: "power2.out",
          immediateRender: false }}, 0.02)
        .fromTo(".chapter-en", {{ autoAlpha: 0 }},
          {{ autoAlpha: 1, duration: .18, ease: "power1.out",
            immediateRender: false }}, 0.06)
        .fromTo(".chapter-zh", {{ autoAlpha: 0 }},
          {{ autoAlpha: 1, duration: .18, ease: "power1.out",
            immediateRender: false }}, 0.12)
        {"".join(timeline)};
      window.__timelines["semantic-stage"] = tl;
    </script>
  </body>
</html>
"""

    out_dir = args.out_dir.resolve()
    (out_dir / "index.html").write_text(html_text, encoding="utf-8")
    write_json(
        out_dir / "index.motion.json",
        motion_payload,
    )
    (out_dir / "vendor").mkdir()
    shutil.copy2(ROOT / "vendor" / "gsap.min.js", out_dir / "vendor" / "gsap.min.js")
    shutil.copy2(
        ASSETS / "fonts" / "NotoSansCJKsc-Bold.otf",
        out_dir / "vendor" / "NotoSansCJKsc-Bold.otf",
    )
    shutil.copy2(
        ASSETS / "fonts" / "NotoSansCJKsc-Regular.otf",
        out_dir / "vendor" / "NotoSansCJKsc-Regular.otf",
    )
    shutil.copy2(
        ASSETS / "fonts" / "NotoSansCJKsc-Medium.otf",
        out_dir / "vendor" / "NotoSansCJKsc-Medium.otf",
    )
    shutil.copy2(
        ASSETS / "fonts" / "SpaceMono-Bold.ttf",
        out_dir / "vendor" / "SpaceMono-Bold.ttf",
    )
    fixed_bounds = (
        {"min_x": 0.0, "min_y": 0.0, "max_x": 1.0, "max_y": 1.0}
        if layout == "fullscreen"
        else FIXED_BOUNDS
    )
    write_json(
        out_dir / "overlay-spec.json",
        {
            "schema_version": PIPELINE_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "template": "semantic-stage",
            "style": args.style,
            "skin_id": str(style["skin_id"]),
            "paint_tokens_sha256": canonical_sha256(paint),
            "build_inputs_sha256": build_inputs_sha256(style),
            "paint_token_keys": sorted(paint),
            "font_family_id": "reference-font-pair",
            "animation_font_file": "NotoSansCJKsc-Bold.otf",
            "animation_layout": "reference-fixed-left",
            "panel_mode": "content-panel",
            "outer_background": "transparent",
            "source_background_policy": (
                "transparent-stage"
                if args.style == "white-wall-fusion-fixed"
                else "transparent-overlay"
            ),
            "canvas": {"width": CANVAS_WIDTH, "height": CANVAS_HEIGHT},
            "coordinate_space": "normalized",
            "content_bounds": fixed_bounds,
            "layout": layout,
            "lane": "full" if layout == "fullscreen" else "left",
            "duration": round(duration, 6),
            "reference_contract": {
                "reference_canvas": [1280, 720],
                "stage": [
                    REFERENCE_STAGE["x"],
                    REFERENCE_STAGE["y"],
                    visual_grammar["sizes"]["medium"]["reference_width"],
                ],
                "card_sizes": {
                    key: {
                        "reference_width": int(value["reference_width"]),
                        "template_width": int(value["template_width"]),
                        "canvas_ratio": float(value["canvas_ratio"]),
                    }
                    for key, value in visual_grammar["sizes"].items()
                },
                "default_card_size": visual_grammar["default_size"],
                "maximum_card_width": visual_grammar["maximum_card_width"],
                "header_height": REFERENCE_STAGE["header_height"],
                "header_lead_seconds": HEADER_LEAD_SECONDS,
                "container_entry_seconds": CONTAINER_ENTRY_SECONDS,
                "item_entry_seconds": ITEM_ENTRY_SECONDS,
                "exit_seconds": EXIT_SECONDS,
                "panel_rgba": [
                    *paint["panel_rgb"],
                    float(paint["panel_opacity"]),
                ],
                "stage_feather_rgba": [
                    *paint["stage_feather_rgb"],
                    float(paint["stage_feather_opacity"]),
                ],
                "free_text_primary": paint["text_primary"],
                "panel_text_primary": paint["panel_text_primary"],
                "full_field_overlay_opacity": float(paint["fullscreen_opacity"]),
                "shadow_rgba": [
                    *paint["shadow_rgb"],
                    float(paint["shadow_opacity"]),
                ],
                "adaptive_repositioning": False,
            },
            "information_model": "persistent-layer-stack",
            "motion_model": "anchored-opacity",
            "semantic_timing_model": "exact-spoken-reveal",
            "component_skin": "type-specific-reference",
            "card_sizing_model": "spoken-first-content-height",
            "visual_grammar_model": "spoken-first-relations",
            "stage_layout_model": LAYOUT_MODEL_ID,
            "visual_grammar_sha256": canonical_sha256(visual_grammar),
            "card_size_selections": card_size_selections,
            "accent": accent_name,
            "state_count": visual_index,
            "estimated_layer_height": estimated_height,
            "layout_estimate": {
                **layout_estimate,
                "selected_layer_gap": selected_layer_gap,
                "selected_estimated_height": estimated_height,
            },
            "timeline_contract": timeline_contract,
            "runtime": {"engine": "hyperframes", "version": HYPERFRAMES_VERSION},
            "provenance": {
                "config_sha256": config_sha256,
                "source_word_ids": config.get("source_word_ids", []),
            },
        },
    )
    write_json(
        out_dir / "package.json",
        {
            "name": "composition-semantic-stage",
            "private": True,
            "version": "0.0.0",
            "devDependencies": {"hyperframes": HYPERFRAMES_VERSION},
            "scripts": {
                "check": f"npx hyperframes@{HYPERFRAMES_VERSION} check --at-transitions",
                "render": f"npx hyperframes@{HYPERFRAMES_VERSION} render --format mov --quality high --output overlay.mov",
            },
        },
    )
    print(f"built AIJianji semantic stage -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
