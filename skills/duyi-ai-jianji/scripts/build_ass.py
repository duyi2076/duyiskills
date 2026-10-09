#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any

from common import atomic_write_text, file_fingerprint, load_json, write_json
from contracts import EXIT_BLOCKED
from speech_text import has_embedded_hard_filler, is_hard_filler


ASCII_WORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+.#_-]*$")
LATIN_WORD = re.compile(r"^[A-Za-z][A-Za-z0-9+.#_-]*$")
PUNCTUATION = set("，。！？；：、,.!?;:")
DISPLAY_PUNCTUATION = set("，。！？；：、,.!?;:…“”‘’")


def display_width(text: str) -> float:
    return sum(0.55 if ord(character) < 128 else 1.0 for character in text)


def join_tokens(tokens: list[str]) -> str:
    result = ""
    previous = ""
    for token in tokens:
        if not token:
            continue
        if result:
            both_ascii_words = ASCII_WORD.match(previous) and ASCII_WORD.match(token)
            latin_boundary = (LATIN_WORD.match(previous) and not ASCII_WORD.match(token)) or (
                LATIN_WORD.match(token) and not ASCII_WORD.match(previous)
            )
            if both_ascii_words or latin_boundary:
                result += " "
        result += token
        previous = token
    return result


def caption_display_tokens(words: list[dict[str, Any]]) -> list[str]:
    """Collapse one lexical ASR correction span into one visible caption token.

    Every original word id and timing stays in the timeline, while a correction
    such as a+镜+头 -> Agent is rendered as Agent instead of A gen t.
    """
    tokens: list[str] = []
    spans: dict[str, dict[str, Any]] = {}
    for word in words:
        display = str(word.get("display") or "")
        span_id = str(word.get("asr_correction_span_id") or "")
        if not span_id:
            tokens.append(display)
            continue
        try:
            span_index = int(word.get("asr_correction_span_index"))
            span_size = int(word.get("asr_correction_span_size"))
        except (TypeError, ValueError) as error:
            raise ValueError(f"invalid ASR correction span metadata for {span_id}") from error
        span_text = str(word.get("asr_correction_span_text") or "")
        if span_size < 1 or not 0 <= span_index < span_size or not span_text:
            raise ValueError(f"invalid ASR correction span metadata for {span_id}")
        state = spans.setdefault(
            span_id,
            {"size": span_size, "text": span_text, "indices": []},
        )
        if state["size"] != span_size or state["text"] != span_text:
            raise ValueError(f"inconsistent ASR correction span metadata for {span_id}")
        state["indices"].append(span_index)
        tokens.append(span_text if span_index == 0 else "")
    for span_id, state in spans.items():
        if state["indices"] != list(range(state["size"])):
            raise ValueError(
                f"ASR correction span {span_id} is split across caption units"
            )
    return tokens


def ass_time(seconds: float) -> str:
    centiseconds = max(0, int(round(seconds * 100)))
    hours, centiseconds = divmod(centiseconds, 360000)
    minutes, centiseconds = divmod(centiseconds, 6000)
    whole_seconds, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}"


def encode_ass_attachment(data: bytes) -> str:
    """Encode bytes using the SSA/ASS attachment variant of UUEncoding."""
    encoded: list[str] = []
    for offset in range(0, len(data), 3):
        chunk = data[offset : offset + 3]
        value = int.from_bytes(chunk.ljust(3, b"\0"), "big")
        for shift in (18, 12, 6, 0)[: len(chunk) + 1]:
            encoded.append(chr(((value >> shift) & 0x3F) + 33))
    payload = "".join(encoded)
    return "\n".join(payload[offset : offset + 80] for offset in range(0, len(payload), 80))


def uuencode_font_section(font_path: Path) -> str:
    """Encode a font file into a valid ASS [Fonts] attachment section."""
    data = font_path.read_bytes()
    parts = ["[Fonts]\n", f"fontname: {font_path.name}\n"]
    parts.append(encode_ass_attachment(data))
    parts.append("\n\n")
    return "".join(parts)


def apply_phrase_replacements(text: str, phrases: list[dict[str, str]]) -> str:
    for phrase in phrases:
        source = phrase.get("from", "")
        target = phrase.get("to", "")
        if source:
            text = text.replace(source, target)
    return text


def strip_display_punctuation(text: str) -> str:
    output: list[str] = []
    for index, character in enumerate(text):
        if character == "." and index > 0 and index + 1 < len(text) and text[index - 1].isdigit() and text[index + 1].isdigit():
            output.append(character)
        elif character not in DISPLAY_PUNCTUATION:
            output.append(character)
    return "".join(output).strip()


def ends_with_sentence_punctuation(text: str) -> bool:
    """A word ends a sentence only when its final character is punctuation;
    a period inside a number (e.g. "5.6") is not a sentence boundary."""
    stripped = text.strip()
    if not stripped:
        return False
    tail = stripped[-1]
    if tail == "." and len(stripped) >= 2 and stripped[-2].isdigit():
        return False
    return tail in PUNCTUATION


def rounded_rectangle_path(x: float, y: float, width: float, height: float, radius: float) -> str:
    """Return an ASS vector path for a modest rounded rectangle."""
    radius = max(0.0, min(radius, width / 2.0, height / 2.0))
    right = x + width
    bottom = y + height
    control = radius * 0.5522847498

    def number(value: float) -> str:
        return str(int(round(value)))

    return " ".join(
        [
            "m", number(x + radius), number(y),
            "l", number(right - radius), number(y),
            "b", number(right - radius + control), number(y), number(right), number(y + radius - control), number(right), number(y + radius),
            "l", number(right), number(bottom - radius),
            "b", number(right), number(bottom - radius + control), number(right - radius + control), number(bottom), number(right - radius), number(bottom),
            "l", number(x + radius), number(bottom),
            "b", number(x + radius - control), number(bottom), number(x), number(bottom - radius + control), number(x), number(bottom - radius),
            "l", number(x), number(y + radius),
            "b", number(x), number(y + radius - control), number(x + radius - control), number(y), number(x + radius), number(y),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build single-line ASS captions from mapped words.")
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--caption-unit-audit", required=True)
    parser.add_argument("--style", required=True)
    parser.add_argument("--font-preset", help="Override the style's bundled subtitle font preset")
    parser.add_argument(
        "--embed-fonts",
        action="store_true",
        help="Embed the resolved preset font file into the ASS [Fonts] section (uuencoded); "
        "use when the render host cannot resolve the font via fontsdir",
    )
    parser.add_argument("--corrections")
    parser.add_argument("--output", required=True)
    parser.add_argument("--captions-json", required=True)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args()

    timeline_path = Path(args.timeline).resolve()
    timeline = load_json(timeline_path)
    caption_unit_audit_path = Path(args.caption_unit_audit).resolve()
    caption_unit_audit = load_json(caption_unit_audit_path)
    if caption_unit_audit.get("ok") is not True or caption_unit_audit.get("errors"):
        print("captions blocked: caption-unit audit is not approved", file=sys.stderr)
        return EXIT_BLOCKED
    approved_embedded_ids = set(
        str(item)
        for item in caption_unit_audit.get(
            "approved_embedded_semantic_word_ids", []
        )
    )
    timeline_audit_input = (timeline.get("inputs") or {}).get("caption_unit_audit")
    if (
        not isinstance(timeline_audit_input, dict)
        or timeline_audit_input.get("sha256")
        != file_fingerprint(caption_unit_audit_path)["sha256"]
    ):
        print(
            "captions blocked: timeline is not bound to the current caption-unit audit",
            file=sys.stderr,
        )
        return EXIT_BLOCKED
    style = load_json(args.style)
    preset_file = Path(__file__).resolve().parents[1] / "assets" / "composition" / "subtitle-font-presets.json"
    requested_preset = args.font_preset or style.get("font_preset")
    if requested_preset:
        preset_payload = load_json(preset_file)
        preset = preset_payload.get("presets", {}).get(requested_preset)
        if not preset:
            available = ", ".join(sorted(preset_payload.get("presets", {})))
            parser.error(f"unknown font preset {requested_preset!r}; available: {available}")
        style.update({key: value for key, value in preset.items() if key not in {"label", "use_for"}})
        style["font_preset"] = requested_preset
        style["font_preset_label"] = preset.get("label", requested_preset)
        font_file = preset_file.parent / str(preset.get("font_file", ""))
        if not font_file.is_file():
            parser.error(f"font file missing for preset {requested_preset!r}: {font_file}")
    if args.embed_fonts:
        if not requested_preset:
            parser.error("--embed-fonts requires a resolved font preset (style.font_preset or --font-preset)")
        style["embedded_font_file"] = font_file.name
        style["embedded_font_sha256"] = hashlib.sha256(font_file.read_bytes()).hexdigest()
    corrections = load_json(args.corrections) if args.corrections else {}
    by_word_id = corrections.get("by_word_id", {})
    phrases = corrections.get("phrases", [])
    break_after_word_ids = set(corrections.get("break_after_word_ids", []))
    if by_word_id or phrases:
        print(
            "captions blocked: text corrections must be applied in "
            "asr-corrections.json before semantic review",
            file=sys.stderr,
        )
        return EXIT_BLOCKED
    maximum = float(style.get("max_fullwidth_chars", 22))
    max_duration = float(
        style.get("adaptive_max_duration", style.get("max_duration", 5.5))
    )
    min_duration = float(style.get("min_duration", 0.6))

    normalized_words = []
    for word in timeline.get("words", []):
        if is_hard_filler(word.get("text", "")):
            print(
                "captions blocked: retained hard filler "
                f"{word.get('word_id')}={word.get('text')!r}",
                file=sys.stderr,
            )
            return EXIT_BLOCKED
        if (
            has_embedded_hard_filler(word.get("text", ""))
            and str(word.get("word_id")) not in approved_embedded_ids
        ):
            print(
                "captions blocked: ambiguous embedded hard filler "
                f"{word.get('word_id')}={word.get('text')!r}",
                file=sys.stderr,
            )
            return EXIT_BLOCKED
        normalized = dict(word)
        normalized["display"] = str(by_word_id.get(word["word_id"], word["text"]))
        normalized_words.append(normalized)

    mapped_units = timeline.get("caption_units")
    if not isinstance(mapped_units, list) or not mapped_units:
        print("captions blocked: mapped timeline has no caption units", file=sys.stderr)
        return EXIT_BLOCKED
    if break_after_word_ids:
        print(
            "captions blocked: break_after_word_ids is obsolete; edit caption-units.json instead",
            file=sys.stderr,
        )
        return EXIT_BLOCKED

    cues: list[dict[str, Any]] = []
    seen_word_ids: list[str] = []
    for unit in mapped_units:
        unit_id = str(unit.get("id") or "")
        current = [
            word for word in normalized_words if word.get("caption_unit_id") == unit_id
        ]
        expected_ids = [str(item) for item in unit.get("mapped_word_ids", [])]
        actual_ids = [str(item["word_id"]) for item in current]
        if not current or actual_ids != expected_ids:
            print(
                f"captions blocked: mapped caption unit {unit_id!r} is incomplete",
                file=sys.stderr,
            )
            return EXIT_BLOCKED
        try:
            display_tokens = caption_display_tokens(current)
        except ValueError as error:
            print(f"captions blocked: {error}", file=sys.stderr)
            return EXIT_BLOCKED
        text = apply_phrase_replacements(join_tokens(display_tokens), phrases)
        if style.get("strip_display_punctuation", False):
            text = strip_display_punctuation(text)
        if not text:
            print(
                f"captions blocked: caption unit {unit_id!r} became empty",
                file=sys.stderr,
            )
            return EXIT_BLOCKED
        if display_width(text) > maximum:
            print(
                f"captions blocked: caption unit {unit_id!r} exceeds width {maximum}",
                file=sys.stderr,
            )
            return EXIT_BLOCKED
        start = float(current[0]["start"])
        spoken_end = float(current[-1]["end"])
        if spoken_end - start > max_duration:
            print(
                f"captions blocked: caption unit {unit_id!r} exceeds duration {max_duration}s",
                file=sys.stderr,
            )
            return EXIT_BLOCKED
        end = max(spoken_end, start + min_duration)
        if end > timeline.get("duration", end):
            end = float(timeline["duration"])
        cues.append(
            {
                "id": f"caption-{len(cues) + 1:04d}",
                "caption_unit_id": unit_id,
                "sentence_id": unit.get("sentence_id"),
                "full_sentence_text": unit.get("full_sentence_text"),
                "start": round(start, 3),
                "end": round(end, 3),
                "text": text,
                "word_ids": actual_ids,
                "semantic_complete": True,
                "boundary_reason": unit.get("boundary_reason"),
            }
        )
        seen_word_ids.extend(actual_ids)
    timeline_word_ids = [str(word["word_id"]) for word in normalized_words]
    if seen_word_ids != timeline_word_ids:
        print(
            "captions blocked: caption units do not cover mapped words exactly once",
            file=sys.stderr,
        )
        return EXIT_BLOCKED

    # Prevent a minimum-duration extension from overlapping the next cue.
    for index in range(len(cues) - 1):
        if cues[index]["end"] > cues[index + 1]["start"]:
            cues[index]["end"] = round(max(cues[index]["start"] + 0.2, cues[index + 1]["start"] - 0.01), 3)

    scale = args.height / 1080.0
    font_size = int(round(float(style.get("font_size_at_1080", 54)) * scale))
    margin_bottom = int(round(float(style.get("margin_bottom_at_1080", 62)) * scale))
    margin_left = int(round(args.width * float(style.get("margin_left_ratio", 0.11))))
    margin_right = int(round(args.width * float(style.get("margin_right_ratio", 0.11))))
    bold = -1 if style.get("bold", True) else 0
    border_style = int(style.get("border_style", 1))
    rounded_background = bool(style.get("background_enabled", False) and style.get("background_mode") == "rounded")
    background_radius = float(style.get("background_radius_at_1080", 11)) * scale
    background_padding_x = float(style.get("background_padding_x_at_1080", 14)) * scale
    background_padding_y = float(style.get("background_padding_y_at_1080", 6)) * scale
    text_width_factor = float(style.get("text_width_factor", 0.76))
    box_height = font_size * float(style.get("background_height_factor", 1.18)) + background_padding_y * 2
    box_bottom = args.height - margin_bottom + float(style.get("background_bottom_offset_at_1080", 7)) * scale
    spacing = style.get("spacing", 0)
    ass_font_name = style.get("ass_font_name", style.get("font_name", "PingFang SC"))
    style["ass_font_name"] = ass_font_name
    fonts_section = uuencode_font_section(font_file) if args.embed_fonts else ""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {args.width}
PlayResY: {args.height}
ScaledBorderAndShadow: yes
WrapStyle: 2

{fonts_section}[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Duyi,{ass_font_name},{font_size},{style.get('primary_color', '&H00FFFFFF')},&H000000FF,{style.get('outline_color', '&H00000000')},{style.get('back_color', '&H80000000')},{bold},0,0,0,100,100,{spacing},0,{border_style},{style.get('outline', 3)},{style.get('shadow', 2)},{style.get('alignment', 2)},{margin_left},{margin_right},{margin_bottom},1
Style: RoundedBackground,Arial,10,{style.get('background_color', '&HB3000000')},&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for cue in cues:
        safe_text = cue["text"].replace("{", "\\{").replace("}", "\\}").replace("\n", " ")
        if rounded_background:
            estimated_text_width = display_width(cue["text"]) * font_size * text_width_factor
            box_width = min(args.width - margin_left - margin_right, estimated_text_width + background_padding_x * 2)
            box_x = (args.width - box_width) / 2.0
            box_y = box_bottom - box_height
            path = rounded_rectangle_path(box_x, box_y, box_width, box_height, background_radius)
            cue["background"] = {
                "mode": "rounded",
                "x": round(box_x, 2),
                "y": round(box_y, 2),
                "width": round(box_width, 2),
                "height": round(box_height, 2),
                "radius": round(background_radius, 2),
            }
            lines.append(
                f"Dialogue: 0,{ass_time(cue['start'])},{ass_time(cue['end'])},RoundedBackground,,0,0,0,,"
                f"{{\\an7\\pos(0,0)\\p1}}{path}{{\\p0}}\n"
            )
        lines.append(f"Dialogue: 1,{ass_time(cue['start'])},{ass_time(cue['end'])},Duyi,,0,0,0,,{safe_text}\n")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(output, "".join(lines))
    write_json(
        args.captions_json,
        {
            "version": 2,
            "duration": timeline.get("duration"),
            "resolution": {"width": args.width, "height": args.height},
            "style": str(Path(args.style).resolve()),
            "font_presets": str(preset_file),
            "resolved_style": style,
            "corrections": corrections,
            "caption_unit_audit": file_fingerprint(caption_unit_audit_path),
            "timeline": file_fingerprint(timeline_path),
            "speech_cleanup": {
                "policy": "remove-all-nonsemantic-hard-fillers",
                "retained_hard_filler_count": 0,
            },
            "segmentation": {
                "policy": "semantic-complete",
                "caption_unit_count": len(mapped_units),
                "one_unit_per_cue": True,
            },
            "cues": cues,
        },
    )
    print(f"captions: {len(cues)} cues -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
