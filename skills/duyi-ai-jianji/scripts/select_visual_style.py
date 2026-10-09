#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from common import load_json, write_json


SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROUTING = SKILL_ROOT / "assets" / "composition" / "style-routing.json"
DEFAULT_STYLES = SKILL_ROOT / "assets" / "composition" / "style-presets.json"
DEFAULT_SUBTITLE_FONTS = SKILL_ROOT / "assets" / "composition" / "subtitle-font-presets.json"
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select one deterministic visual style for animation and speech captions."
    )
    parser.add_argument("--input", required=True, type=Path, help="style-selection-input.json")
    parser.add_argument("--output", required=True, type=Path, help="style-decision.json")
    parser.add_argument("--routing", type=Path, default=DEFAULT_ROUTING)
    parser.add_argument("--styles", type=Path, default=DEFAULT_STYLES)
    parser.add_argument("--subtitle-fonts", type=Path, default=DEFAULT_SUBTITLE_FONTS)
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing decision when its fingerprint differs",
    )
    return parser.parse_args()


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_mapping(payload: Any, label: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def normalize_reasons(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("ai_assessment.reasons must be an array of strings")
    return [item.strip() for item in value if item.strip()]


def validate_paint_tokens(style_id: str, value: Any) -> dict[str, Any]:
    tokens = require_mapping(value, f"style {style_id!r} paint_tokens")
    actual_keys = set(tokens)
    if actual_keys != PAINT_TOKEN_KEYS:
        missing = ", ".join(sorted(PAINT_TOKEN_KEYS - actual_keys)) or "none"
        unknown = ", ".join(sorted(actual_keys - PAINT_TOKEN_KEYS)) or "none"
        raise ValueError(
            f"style {style_id!r} paint_tokens must use the locked whitelist; "
            f"missing: {missing}; unknown: {unknown}"
        )
    for key in sorted(PAINT_RGB_KEYS):
        rgb = tokens[key]
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
        opacity = tokens[key]
        if (
            isinstance(opacity, bool)
            or not isinstance(opacity, (int, float))
            or not 0 <= float(opacity) <= 1
        ):
            raise ValueError(
                f"style {style_id!r} paint_tokens.{key} must be between 0 and 1"
            )
    for key in sorted(PAINT_COLOR_KEYS):
        color = tokens[key]
        if (
            not isinstance(color, str)
            or len(color) != 7
            or color[0] != "#"
            or any(character not in "0123456789ABCDEF" for character in color[1:])
        ):
            raise ValueError(
                f"style {style_id!r} paint_tokens.{key} must be an uppercase #RRGGBB color"
            )
    return tokens


def validate_style_pair(
    style_id: str,
    style_presets: dict[str, Any],
    subtitle_presets: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    style = style_presets.get(style_id)
    if not isinstance(style, dict):
        available = ", ".join(sorted(style_presets))
        raise ValueError(f"unknown style {style_id!r}; available: {available}")

    skin_id = str(style.get("skin_id", ""))
    if skin_id != style_id:
        raise ValueError(
            f"style {style_id!r} must use the same locked skin_id; got {skin_id!r}"
        )
    paint_tokens = validate_paint_tokens(style_id, style.get("paint_tokens"))
    if str(style.get("panel", "")) != (
        f"#{paint_tokens['panel_rgb'][0]:02X}"
        f"{paint_tokens['panel_rgb'][1]:02X}"
        f"{paint_tokens['panel_rgb'][2]:02X}"
    ):
        raise ValueError(f"style {style_id!r} panel differs from paint_tokens.panel_rgb")
    if float(style.get("panel_opacity", -1)) != float(paint_tokens["panel_opacity"]):
        raise ValueError(
            f"style {style_id!r} panel_opacity differs from paint_tokens.panel_opacity"
        )
    if style_id == "white-wall-fusion-fixed" and (
        paint_tokens["panel_rgb"] != [10, 20, 27]
        or float(paint_tokens["panel_opacity"]) != 0.82
        or paint_tokens["text_primary"] != "#17212B"
        or paint_tokens["panel_text_primary"] != "#F3F5F7"
        or float(paint_tokens["stage_feather_opacity"]) != 0.0
        or float(paint_tokens["fullscreen_opacity"]) != 0.0
    ):
        raise ValueError(
            "white-wall-fusion-fixed is fixed to a transparent stage, dark free "
            "text, and light text inside local dark panels"
        )
    for key in ("text_primary", "text_secondary"):
        if str(style.get(key, "")) != str(paint_tokens[key]):
            raise ValueError(f"style {style_id!r} {key} differs from paint_tokens.{key}")

    subtitle_id = str(style.get("subtitle_font_preset", ""))
    subtitle = subtitle_presets.get(subtitle_id)
    if not isinstance(subtitle, dict):
        raise ValueError(
            f"style {style_id!r} points to unknown subtitle preset {subtitle_id!r}"
        )

    animation_family = str(style.get("font_family_id", ""))
    subtitle_family = str(subtitle.get("font_family_id", ""))
    if not animation_family or animation_family != subtitle_family:
        raise ValueError(
            f"style {style_id!r} font family mismatch: "
            f"animation={animation_family!r}, subtitle={subtitle_family!r}"
        )
    return style, subtitle


def select_style(
    selection_input: dict[str, Any],
    routing: dict[str, Any],
    style_presets: dict[str, Any],
    subtitle_presets: dict[str, Any],
    animation_contract: dict[str, Any],
) -> dict[str, Any]:
    default_style = str(routing.get("default_style", "dark-reference-fixed"))
    threshold = float(routing.get("confidence_threshold", 0.75))
    if not 0 <= threshold <= 1:
        raise ValueError("confidence_threshold must be between 0 and 1")

    user_style_value = selection_input.get("user_style")
    user_style = str(user_style_value).strip() if user_style_value is not None else ""
    profile: str | None = None
    confidence: float | None = None

    if user_style:
        style_id = user_style
        source = "user_override"
        user_reason = selection_input.get("user_reason")
        reasons = (
            [str(user_reason).strip()]
            if isinstance(user_reason, str) and user_reason.strip()
            else ["用户明确指定该皮肤，覆盖 AI 自动判断。"]
        )
    else:
        assessment_value = selection_input.get("ai_assessment")
        if assessment_value is None:
            style_id = default_style
            source = "default_fallback"
            reasons = ["AIJianji 视觉皮肤锁定为参考样片，不参与随机或内容路由。"]
        else:
            assessment = require_mapping(assessment_value, "ai_assessment")
            profile = str(assessment.get("profile", "")).strip()
            profiles = require_mapping(routing.get("auto_profiles"), "auto_profiles")
            route = profiles.get(profile)
            if not isinstance(route, dict):
                available = ", ".join(sorted(profiles))
                raise ValueError(
                    f"unknown ai_assessment.profile {profile!r}; available: {available}"
                )

            confidence_value = assessment.get("confidence")
            if isinstance(confidence_value, bool) or not isinstance(
                confidence_value, (int, float)
            ):
                raise ValueError("ai_assessment.confidence must be a number between 0 and 1")
            confidence = float(confidence_value)
            if not 0 <= confidence <= 1:
                raise ValueError("ai_assessment.confidence must be between 0 and 1")

            reasons = normalize_reasons(assessment.get("reasons"))
            if not reasons:
                reasons = ["AI 已完成内容画像，但未提供补充证据说明。"]

            if bool(route.get("always_fallback")):
                style_id = default_style
                source = "default_fallback"
                reasons.append("AIJianji 固定使用参考样片皮肤。")
            elif confidence < threshold:
                style_id = default_style
                source = "default_fallback"
                reasons.append(
                    f"AI 置信度 {confidence:.2f} 低于阈值 {threshold:.2f}，仍固定使用参考样片皮肤。"
                )
            else:
                style_id = str(route.get("style_id", ""))
                source = "ai_routing"

    style, subtitle = validate_style_pair(
        style_id,
        style_presets,
        subtitle_presets,
    )
    if not bool(style.get("auto_eligible")) and source != "user_override":
        raise ValueError(
            f"style {style_id!r} is manual-only and requires an explicit user override"
        )
    if not bool(style.get("auto_eligible")):
        user_reason = selection_input.get("user_reason")
        if (
            selection_input.get("user_confirmed") is not True
            or not isinstance(user_reason, str)
            or not user_reason.strip()
        ):
            raise ValueError(
                f"style {style_id!r} requires user_confirmed=true and a non-empty user_reason"
            )

    animation_layout = str(animation_contract.get("layout", ""))
    animation_panel_mode = str(animation_contract.get("panel_mode", ""))
    if animation_layout != "reference-fixed-left":
        raise ValueError(
            "styles.animation_contract.layout must be 'reference-fixed-left' for AIJianji"
        )
    if animation_panel_mode != "content-panel":
        raise ValueError(
            "styles.animation_contract.panel_mode must be 'content-panel' for AIJianji"
        )
    information_model = str(animation_contract.get("information_model", ""))
    motion_model = str(animation_contract.get("motion_model", ""))
    component_skin = str(animation_contract.get("component_skin", ""))
    if information_model != "persistent-layer-stack":
        raise ValueError("AIJianji information model must be 'persistent-layer-stack'")
    if motion_model != "anchored-opacity":
        raise ValueError("AIJianji motion model must be 'anchored-opacity'")
    if component_skin != "type-specific-reference":
        raise ValueError("AIJianji component skin must be 'type-specific-reference'")
    if str(routing.get("fixed_animation_layout", "")) != animation_layout:
        raise ValueError("routing fixed_animation_layout differs from the style contract")
    if str(routing.get("fixed_animation_panel_mode", "")) != animation_panel_mode:
        raise ValueError("routing fixed_animation_panel_mode differs from the style contract")

    return {
        "decision_version": 2,
        "routing_policy": str(routing.get("policy", "")),
        "source": source,
        "style_id": style_id,
        "skin_id": str(style["skin_id"]),
        "style_label": str(style.get("label", style_id)),
        "paint_tokens_sha256": canonical_sha256(style["paint_tokens"]),
        "font_family_id": str(style["font_family_id"]),
        "animation_font_file": str(style["animation_font_file"]),
        "subtitle_font_preset": str(style["subtitle_font_preset"]),
        "subtitle_font_file": str(subtitle["font_file"]),
        "animation_layout": animation_layout,
        "animation_panel_mode": animation_panel_mode,
        "information_model": information_model,
        "motion_model": motion_model,
        "component_skin": component_skin,
        "animation_panel_exceptions": animation_contract.get("panel_exceptions", {}),
        "profile": profile,
        "confidence": confidence,
        "confidence_threshold": threshold,
        "reasons": reasons,
        "user_confirmed": selection_input.get("user_confirmed") is True,
        "applied_to": ["animation", "speech-to-text-captions"],
        "locked_for_video": True,
    }


def main() -> int:
    args = parse_args()
    try:
        selection_input = require_mapping(load_json(args.input), "input")
        routing = require_mapping(load_json(args.routing), "routing")
        styles_payload = require_mapping(load_json(args.styles), "styles")
        subtitle_payload = require_mapping(load_json(args.subtitle_fonts), "subtitle fonts")
        style_presets = require_mapping(styles_payload.get("presets"), "styles.presets")
        animation_contract = require_mapping(
            styles_payload.get("animation_contract"),
            "styles.animation_contract",
        )
        subtitle_presets = require_mapping(
            subtitle_payload.get("presets"), "subtitle fonts.presets"
        )

        fingerprint = canonical_sha256(
            {
                "selection_input": selection_input,
                "routing": routing,
                "styles": styles_payload,
                "subtitle_fonts": subtitle_payload,
            }
        )

        if args.output.exists() and not args.force:
            existing = require_mapping(load_json(args.output), "existing output")
            if existing.get("input_fingerprint") == fingerprint:
                print(
                    f"reused: {existing.get('style_id')} "
                    f"({existing.get('source')}) -> {args.output}"
                )
                return 0
            raise ValueError(
                f"{args.output} already contains a decision for different inputs; "
                "preserve it or rerun with --force after an intentional user-approved change"
            )

        decision = select_style(
            selection_input,
            routing,
            style_presets,
            subtitle_presets,
            animation_contract,
        )
        decision["input_fingerprint"] = fingerprint
        write_json(args.output, decision)
        print(f"selected: {decision['style_id']} ({decision['source']}) -> {args.output}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
