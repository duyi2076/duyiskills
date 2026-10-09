#!/usr/bin/env python3
"""Validate an AI editorial plan and build the one human-review packet."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import ImageFont

from adaptive_rhythm import analyze_word_span
from apply_asr_corrections import apply_corrections
from build_ass import caption_display_tokens, strip_display_punctuation
from common import load_json, write_json
from speech_text import (
    display_width,
    is_hard_filler,
    join_word_text,
    unit_boundary_errors,
)


SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSETS = SKILL_ROOT / "assets" / "composition"
SUBTITLE_STYLE = ASSETS / "subtitle-style.json"
SUBTITLE_PRESETS = ASSETS / "subtitle-font-presets.json"
SCHEMA_VERSION = 1
ALLOWED_DELETE_KINDS = {
    "filler",
    "repeated_retake",
    "incomplete_start",
    "explicit_user_removal",
}
ALLOWED_BOUNDARIES = {"sentence", "clause", "breath-group"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def contiguous_ids(
    row: dict[str, Any],
    *,
    positions: dict[str, int],
    ordered_ids: list[str],
    label: str,
) -> list[str]:
    start_id = str(row.get("start_word_id") or "")
    end_id = str(row.get("end_word_id") or "")
    if start_id not in positions or end_id not in positions:
        raise ValueError(f"{label} has unknown endpoints {start_id!r}..{end_id!r}")
    start, end = positions[start_id], positions[end_id]
    if end < start:
        raise ValueError(f"{label} is reversed")
    return ordered_ids[start : end + 1]


def corrected_text(words: list[dict[str, Any]]) -> str:
    display_words = [
        {**word, "display": str(word.get("text") or "")}
        for word in words
    ]
    return join_word_text(
        [
            {"text": token}
            for token in caption_display_tokens(display_words)
            if token
        ]
    )


def measured_text(
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    maximum_pixels: int,
    maximum_fullwidth: float,
) -> dict[str, Any]:
    bounds = font.getbbox(text or " ")
    pixel_width = max(0, int(bounds[2] - bounds[0]))
    fullwidth = display_width(text)
    return {
        "pixel_width": pixel_width,
        "maximum_pixels": maximum_pixels,
        "fullwidth_units": round(fullwidth, 2),
        "maximum_fullwidth_units": maximum_fullwidth,
        "passed": pixel_width <= maximum_pixels and fullwidth <= maximum_fullwidth,
    }


def map_retained_word_times(
    words: list[dict[str, Any]],
    deleted_ids: set[str],
) -> list[dict[str, Any]]:
    """Map retained words onto the deletion-compacted output timeline."""
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        if str(word["word_id"]) in deleted_ids:
            if current:
                groups.append(current)
                current = []
        else:
            current.append(word)
    if current:
        groups.append(current)

    mapped_words: list[dict[str, Any]] = []
    output_cursor = 0.0
    for group in groups:
        source_start = float(group[0]["start"])
        source_end = float(group[-1]["end"])
        previous_end = output_cursor
        for word in group:
            planned_start = max(
                previous_end,
                output_cursor + float(word["start"]) - source_start,
            )
            planned_end = max(
                planned_start + 0.020,
                output_cursor + float(word["end"]) - source_start,
            )
            mapped_words.append(
                {
                    **word,
                    "_planned_output_start": planned_start,
                    "_planned_output_end": planned_end,
                }
            )
            previous_end = planned_end
        output_cursor += source_end - source_start
    return mapped_words


def build_packet(
    transcript: dict[str, Any],
    plan: dict[str, Any],
    *,
    transcript_path: Path,
    plan_path: Path,
    source_path: Path,
    integrity_path: Path,
    width: int,
    height: int,
) -> tuple[dict[str, Any], str]:
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("editorial-review-plan.json schema_version must be 1")
    if plan.get("policy") != "one-human-review-before-lock":
        raise ValueError(
            "editorial-review-plan.json policy must be one-human-review-before-lock"
        )
    if plan.get("ai_review_complete") is not True:
        raise PermissionError("AI must finish all editorial decisions before human review")

    words = transcript.get("words")
    if not isinstance(words, list) or not words:
        raise ValueError("normalized transcript has no words")
    ordered_ids = [str(word["word_id"]) for word in words]
    if len(set(ordered_ids)) != len(ordered_ids):
        raise ValueError("normalized transcript has duplicate word IDs")
    by_id = {str(word["word_id"]): word for word in words}
    positions = {word_id: index for index, word_id in enumerate(ordered_ids)}

    integrity = load_json(integrity_path)
    if integrity.get("ok") is not True:
        raise PermissionError("ASR integrity must pass before editorial review")
    inputs = require_mapping(plan.get("inputs"), "editorial plan inputs")
    expected = {
        "normalized_transcript_sha256": sha256(transcript_path),
        "source_media_sha256": sha256(source_path),
        "asr_integrity_sha256": sha256(integrity_path),
    }
    for key, value in expected.items():
        if inputs.get(key) != value:
            raise ValueError(f"editorial plan {key} does not match current run")

    speaker_issues = plan.get("speaker_issues", [])
    if not isinstance(speaker_issues, list):
        raise ValueError("speaker_issues must be an array")
    for index, raw in enumerate(speaker_issues, start=1):
        issue = require_mapping(raw, f"speaker issue {index}")
        word_ids = contiguous_ids(
            issue,
            positions=positions,
            ordered_ids=ordered_ids,
            label=f"speaker issue {index}",
        )
        if issue.get("decision") != "preserve_original":
            raise ValueError(
                f"speaker issue {index} must preserve the speaker's actual wording"
            )
        if not str(issue.get("reason") or "").strip():
            raise ValueError(f"speaker issue {index} needs a reason")
        issue["word_ids"] = word_ids
        issue["original_text"] = join_word_text([by_id[word_id] for word_id in word_ids])

    correction_review = {
        "schema_version": 1,
        "policy": "word-level-asr-errors-only",
        "reviewed": True,
        "transcript_sha256": expected["normalized_transcript_sha256"],
        "source_media_sha256": expected["source_media_sha256"],
        "asr_integrity_sha256": expected["asr_integrity_sha256"],
        "term_hints": plan.get("term_hints", []),
        "corrections": plan.get("corrections", []),
        "preserved_uncertain": plan.get("preserved_uncertain", []),
        "unresolved": plan.get("unresolved", []),
    }
    corrected = apply_corrections(
        copy.deepcopy(transcript),
        correction_review,
        transcript_sha256=expected["normalized_transcript_sha256"],
        source_media_sha256=expected["source_media_sha256"],
        asr_integrity_sha256=expected["asr_integrity_sha256"],
    )
    corrected_words = corrected["words"]
    corrected_by_id = {
        str(word["word_id"]): word for word in corrected_words
    }

    deleted_ids: set[str] = set()
    delete_rows: list[dict[str, Any]] = []
    deletions = plan.get("deletions", [])
    if not isinstance(deletions, list):
        raise ValueError("deletions must be an array")
    for index, raw in enumerate(deletions, start=1):
        deletion = require_mapping(raw, f"deletion {index}")
        word_ids = contiguous_ids(
            deletion,
            positions=positions,
            ordered_ids=ordered_ids,
            label=f"deletion {index}",
        )
        overlap = deleted_ids.intersection(word_ids)
        if overlap:
            raise ValueError(f"deletion {index} overlaps {sorted(overlap)}")
        kind = str(deletion.get("kind") or "")
        if kind not in ALLOWED_DELETE_KINDS:
            raise ValueError(f"deletion {index} has unsupported kind {kind!r}")
        if not str(deletion.get("reason") or "").strip():
            raise ValueError(f"deletion {index} needs a reason")
        deleted_ids.update(word_ids)
        delete_rows.append(
            {
                **deletion,
                "id": str(deletion.get("id") or f"deletion-{index:03d}"),
                "word_ids": word_ids,
                "original_text": join_word_text([by_id[word_id] for word_id in word_ids]),
            }
        )

    retained_words = map_retained_word_times(corrected_words, deleted_ids)
    retained_ids = [str(word["word_id"]) for word in retained_words]
    retained_by_id = {str(word["word_id"]): word for word in retained_words}
    hard_fillers = [
        {"word_id": word["word_id"], "text": word["text"]}
        for word in retained_words
        if is_hard_filler(str(word.get("text") or ""))
    ]
    if hard_fillers:
        raise ValueError(f"retained hard fillers are forbidden: {hard_fillers}")

    subtitle_style = load_json(SUBTITLE_STYLE)
    presets = load_json(SUBTITLE_PRESETS).get("presets", {})
    preset_id = str(plan.get("subtitle_font_preset") or subtitle_style["font_preset"])
    preset = require_mapping(presets.get(preset_id), f"subtitle preset {preset_id!r}")
    if preset_id != "reference-caption":
        raise ValueError("AIJianji editorial lock only permits reference-caption")
    font_path = ASSETS / str(preset["font_file"])
    font_size = int(round(float(preset["font_size_at_1080"]) * height / 1080.0))
    font = ImageFont.truetype(str(font_path), font_size)
    maximum_pixels = int(
        width
        * (
            1.0
            - float(preset.get("margin_left_ratio", 0.1))
            - float(preset.get("margin_right_ratio", 0.1))
        )
    )
    maximum_fullwidth = float(preset["max_fullwidth_chars"])
    preferred_duration = float(
        preset.get("preferred_max_duration", preset["max_duration"])
    )
    adaptive_maximum_duration = float(
        preset.get("adaptive_max_duration", 5.5)
    )

    sentences = plan.get("sentences")
    if not isinstance(sentences, list) or not sentences:
        raise ValueError("sentences must be a non-empty array")
    sentence_rows: list[dict[str, Any]] = []
    covered_ids: list[str] = []
    seen_sentence_ids: set[str] = set()
    seen_cue_ids: set[str] = set()
    cue_break_after: set[str] = set()
    sentence_break_after: set[str] = set()
    caption_units: list[dict[str, Any]] = []
    for sentence_index, raw in enumerate(sentences, start=1):
        sentence = require_mapping(raw, f"sentence {sentence_index}")
        sentence_id = str(sentence.get("id") or f"sentence-{sentence_index:03d}")
        if sentence_id in seen_sentence_ids:
            raise ValueError(f"duplicate sentence id {sentence_id}")
        seen_sentence_ids.add(sentence_id)
        sentence_word_ids = contiguous_ids(
            sentence,
            positions=positions,
            ordered_ids=ordered_ids,
            label=sentence_id,
        )
        sentence_word_ids = [
            word_id for word_id in sentence_word_ids if word_id not in deleted_ids
        ]
        if not sentence_word_ids:
            raise ValueError(f"{sentence_id} has no retained words")
        cues = sentence.get("cues")
        if not isinstance(cues, list) or not cues:
            raise ValueError(f"{sentence_id} has no subtitle cues")
        sentence_covered: list[str] = []
        cue_rows: list[dict[str, Any]] = []
        for cue_index, raw_cue in enumerate(cues, start=1):
            cue = require_mapping(raw_cue, f"{sentence_id} cue {cue_index}")
            cue_id = str(cue.get("id") or f"{sentence_id}-cue-{cue_index:02d}")
            if cue_id in seen_cue_ids:
                raise ValueError(f"duplicate cue id {cue_id}")
            seen_cue_ids.add(cue_id)
            cue_word_ids = contiguous_ids(
                cue,
                positions=positions,
                ordered_ids=ordered_ids,
                label=cue_id,
            )
            cue_word_ids = [
                word_id for word_id in cue_word_ids if word_id not in deleted_ids
            ]
            if not cue_word_ids:
                raise ValueError(f"{cue_id} has no retained words")
            if any(word_id not in sentence_word_ids for word_id in cue_word_ids):
                raise ValueError(f"{cue_id} escapes {sentence_id}")
            reason = str(cue.get("boundary_reason") or "")
            if reason not in ALLOWED_BOUNDARIES:
                raise ValueError(f"{cue_id} has invalid boundary reason {reason!r}")
            cue_words = [retained_by_id[word_id] for word_id in cue_word_ids]
            visible = strip_display_punctuation(corrected_text(cue_words))
            measurement = measured_text(
                visible,
                font=font,
                maximum_pixels=maximum_pixels,
                maximum_fullwidth=maximum_fullwidth,
            )
            if not measurement["passed"]:
                raise ValueError(
                    f"{cue_id} exceeds the real subtitle width contract: "
                    f"{visible!r} {measurement}"
                )
            rhythm_analysis = analyze_word_span(
                cue_words,
                start_key="_planned_output_start",
                end_key="_planned_output_end",
            )
            planned_duration = float(rhythm_analysis["original_duration"])
            projected_duration = float(rhythm_analysis["projected_duration"])
            if projected_duration > adaptive_maximum_duration:
                raise ValueError(
                    f"{cue_id} exceeds the adaptive subtitle duration contract: "
                    f"{projected_duration:.3f}s > "
                    f"{adaptive_maximum_duration:.3f}s "
                    f"for {visible!r}"
                )
            boundary_errors = unit_boundary_errors(cue_words)
            if boundary_errors:
                raise ValueError(
                    f"{cue_id} violates subtitle boundary contract "
                    f"{boundary_errors}: {visible!r}"
                )
            supplied_text = str(cue.get("text") or "").strip()
            if supplied_text and strip_display_punctuation(supplied_text) != visible:
                raise ValueError(f"{cue_id} text rewrites the locked spoken words")
            cue_row = {
                "id": cue_id,
                "sentence_id": sentence_id,
                "start_word_id": cue_word_ids[0],
                "end_word_id": cue_word_ids[-1],
                "boundary_reason": reason,
                "text": visible,
                "word_ids": cue_word_ids,
                "measurement": measurement,
                "planned_duration": round(planned_duration, 3),
                "rhythm_analysis": rhythm_analysis,
            }
            cue_rows.append(cue_row)
            caption_units.append(
                {
                    "id": cue_id,
                    "sentence_id": sentence_id,
                    "full_sentence_text": "",
                    "start_word_id": cue_word_ids[0],
                    "end_word_id": cue_word_ids[-1],
                    "boundary_reason": reason,
                    "approved": True,
                }
            )
            sentence_covered.extend(cue_word_ids)
            cue_break_after.add(cue_word_ids[-1])
        if sentence_covered != sentence_word_ids:
            raise ValueError(f"{sentence_id} cues do not cover its words exactly once")
        full_text = "".join(row["text"] for row in cue_rows)
        supplied_full_text = str(sentence.get("full_sentence_text") or "").strip()
        if supplied_full_text and strip_display_punctuation(supplied_full_text) != full_text:
            raise ValueError(f"{sentence_id} full text rewrites the spoken words")
        for unit in caption_units[-len(cue_rows) :]:
            unit["full_sentence_text"] = full_text
        sentence_rows.append(
            {
                "id": sentence_id,
                "start_word_id": sentence_word_ids[0],
                "end_word_id": sentence_word_ids[-1],
                "full_sentence_text": full_text,
                "word_ids": sentence_word_ids,
                "cues": cue_rows,
            }
        )
        sentence_break_after.add(sentence_word_ids[-1])
        covered_ids.extend(sentence_word_ids)
    if covered_ids != retained_ids:
        raise ValueError("sentences/cues must cover every retained word exactly once and in order")

    correction_by_start: dict[str, dict[str, Any]] = {}
    correction_member_ids: set[str] = set()
    for correction in correction_review["corrections"]:
        ids = correction.get("word_ids") or [correction.get("word_id")]
        ids = [str(item) for item in ids]
        correction_by_start[ids[0]] = {**correction, "word_ids": ids}
        correction_member_ids.update(ids)

    rendered: list[str] = []
    index = 0
    while index < len(words):
        source_word = words[index]
        word_id = str(source_word["word_id"])
        correction = correction_by_start.get(word_id)
        if correction:
            original = "".join(str(by_id[item]["text"]) for item in correction["word_ids"])
            replacement = str(correction["corrected"])
            rendered.append(
                f"**{replacement}**（原转写：{original}；原因：ASR 误听，音频与上下文明确）"
            )
            index += len(correction["word_ids"])
            word_id = correction["word_ids"][-1]
        elif word_id in correction_member_ids:
            index += 1
            continue
        else:
            text = str(source_word["text"])
            rendered.append(f"<u>{text}</u>" if word_id in deleted_ids else text)
            index += 1
        if word_id in sentence_break_after:
            rendered.append("\n\n")
        elif word_id in cue_break_after:
            rendered.append("  \n")

    packet_core = {
        "schema_version": SCHEMA_VERSION,
        "status": "awaiting_single_human_review",
        "policy": "one-human-review-before-lock",
        "inputs": {
            "normalized_transcript": {
                "path": str(transcript_path),
                "sha256": expected["normalized_transcript_sha256"],
            },
            "editorial_review_plan": {
                "path": str(plan_path),
                "sha256": sha256(plan_path),
            },
            "source_media": {
                "path": str(source_path),
                "sha256": expected["source_media_sha256"],
            },
            "asr_integrity": {
                "path": str(integrity_path),
                "sha256": expected["asr_integrity_sha256"],
            },
        },
        "subtitle_contract": {
            "preset_id": preset_id,
            "font_file": str(font_path),
            "font_file_sha256": sha256(font_path),
            "font_size": font_size,
            "render_width": width,
            "render_height": height,
            "maximum_pixels": maximum_pixels,
            "maximum_fullwidth_units": maximum_fullwidth,
            "preferred_duration_seconds": preferred_duration,
            "adaptive_maximum_duration_seconds": adaptive_maximum_duration,
        },
        "summary": {
            "total_words": len(words),
            "retained_words": len(retained_ids),
            "deleted_words": len(deleted_ids),
            "asr_corrections": len(correction_review["corrections"]),
            "preserved_uncertain": len(correction_review["preserved_uncertain"]),
            "speaker_issues_preserved": len(speaker_issues),
            "sentences": len(sentence_rows),
            "subtitle_cues": len(caption_units),
        },
        "asr_review": correction_review,
        "speaker_issues": speaker_issues,
        "deletions": delete_rows,
        "sentences": sentence_rows,
        "caption_units": caption_units,
        "semantic_map": plan.get(
            "semantic_map",
            {
                "schema_version": 1,
                "policy": "spoken-semantic-map",
                "propositions": [],
            },
        ),
        "retained_word_ids": retained_ids,
        "deleted_word_ids": [word_id for word_id in ordered_ids if word_id in deleted_ids],
    }
    packet_core["decision_sha256"] = canonical_sha256(
        {
            "asr_review": packet_core["asr_review"],
            "speaker_issues": packet_core["speaker_issues"],
            "deletions": packet_core["deletions"],
            "sentences": packet_core["sentences"],
            "caption_units": packet_core["caption_units"],
            "semantic_map": packet_core["semantic_map"],
        }
    )

    markdown = [
        "# AIJianji 唯一一次文字确认稿",
        "",
        "普通文字＝保留；<u>下划线＝建议删除</u>；粗体修正词后附原转写与原因。",
        "下面的换行就是最终字幕断句；确认后文字、删除、句子和字幕换行一起锁定。",
        "",
        "## 完整标注逐字稿",
        "",
        "".join(rendered).strip(),
        "",
        "## 最终字幕断句",
        "",
    ]
    for sentence in sentence_rows:
        markdown.extend([f"### {sentence['id']}", ""])
        for cue in sentence["cues"]:
            width_note = (
                f"{cue['measurement']['pixel_width']}/"
                f"{cue['measurement']['maximum_pixels']} px"
            )
            rhythm = cue["rhythm_analysis"]
            duration_note = (
                f"原 {cue['planned_duration']:.3f}s"
                f" → 预计 {float(rhythm['projected_duration']):.3f}s"
                f" · {rhythm['duration_class']}"
            )
            markdown.append(
                f"{cue['text']}  `{cue['id']} · {width_note} · {duration_note}`"
            )
        markdown.append("")
    if speaker_issues:
        markdown.extend(["## 说话者原话保留项", ""])
        for issue in speaker_issues:
            markdown.append(
                f"- {issue['original_text']}：{issue['reason']}（保留原话，不伪装成 ASR 错误）"
            )
        markdown.append("")
    markdown.extend(
        [
            "## 本轮只需确认",
            "",
            "请一次性确认：删除内容、ASR 词级修正、说话者原话保留、完整句和字幕断句。",
            "如需调整，直接指出修改；AI 写回同一份决定后立即锁定，不再发第二轮审批。",
            "",
        ]
    )
    return packet_core, "\n".join(markdown)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--integrity", required=True)
    parser.add_argument("--markdown-output", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    args = parser.parse_args()
    transcript_path = Path(args.transcript).resolve()
    plan_path = Path(args.plan).resolve()
    source_path = Path(args.source).resolve()
    integrity_path = Path(args.integrity).resolve()
    packet, markdown = build_packet(
        load_json(transcript_path),
        load_json(plan_path),
        transcript_path=transcript_path,
        plan_path=plan_path,
        source_path=source_path,
        integrity_path=integrity_path,
        width=args.width,
        height=args.height,
    )
    write_json(args.json_output, packet)
    markdown_path = Path(args.markdown_output)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(markdown, encoding="utf-8")
    print(json.dumps(packet["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
