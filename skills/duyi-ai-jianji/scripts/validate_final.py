#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from common import canonical_json_sha256, load_json, media_summary, write_json


ALLOWED_OVERLAY_TEMPLATES = {
    "semantic-stage",
}
SKILL_ROOT = Path(__file__).resolve().parents[1]
STYLE_PRESETS = SKILL_ROOT / "assets" / "composition" / "style-presets.json"
SUBTITLE_FONT_PRESETS = SKILL_ROOT / "assets" / "composition" / "subtitle-font-presets.json"
STYLE_DECISION_SOURCES = {"user_override", "ai_routing", "default_fallback"}
PROCESS_TIMEOUT_SECONDS = 120
FONT_RENDER_FAILURE_PATTERNS = (
    "error opening memory font",
    "fontselect: failed",
    "could not find codec parameters for stream",
    "error opening filters",
)
PIPELINE_VERSION = "3.16.0"
HYPERFRAMES_VERSION = "0.7.69"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_stage_build_inputs_sha256(style: dict[str, Any]) -> str:
    builder_root = SKILL_ROOT / "assets" / "composition" / "semantic-stage"
    assets = SKILL_ROOT / "assets" / "composition"
    return canonical_json_sha256(
        {
            "builder": file_sha256(builder_root / "build.py"),
            "gsap": file_sha256(builder_root / "vendor" / "gsap.min.js"),
            "fonts": {
                name: file_sha256(assets / "fonts" / name)
                for name in (
                    "NotoSansCJKsc-Bold.otf",
                    "NotoSansCJKsc-Regular.otf",
                    "NotoSansCJKsc-Medium.otf",
                    "SpaceMono-Bold.ttf",
                )
            },
            "style": style,
            "visual_grammar": load_json(assets / "visual-grammar.json"),
            "stage_layout": file_sha256(SKILL_ROOT / "scripts" / "stage_layout.py"),
            "hyperframes_version": HYPERFRAMES_VERSION,
            "pipeline_version": PIPELINE_VERSION,
        }
    )


def full_decode(path: Path) -> dict[str, Any]:
    """Decode every audio/video packet so truncated or corrupt media cannot pass."""
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-xerror",
                "-i",
                str(path),
                "-map",
                "0:v:0?",
                "-map",
                "0:a:0?",
                "-f",
                "null",
                "-",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "ffmpeg_not_found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "decode_timeout"}
    return {
        "ok": completed.returncode == 0,
        "returncode": completed.returncode,
        "stderr": completed.stderr[-4000:],
    }


def inspect_ass_dialogues(path: Path) -> list[dict[str, Any]]:
    dialogues: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(",", 9)
        if len(fields) != 10 or fields[3].strip() != "Duyi":
            continue
        dialogues.append(
            {
                "start": fields[1].strip(),
                "end": fields[2].strip(),
                "text": fields[9].replace("\\{", "{").replace("\\}", "}"),
            }
        )
    return dialogues


def _ass_seconds(value: str) -> float:
    hours, minutes, rest = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


def compare_ass_dialogues(captions: list[dict[str, Any]], dialogues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if len(captions) != len(dialogues):
        errors.append(
            {
                "code": "caption_ass_dialogue_count_mismatch",
                "captions_json": len(captions),
                "ass_dialogues": len(dialogues),
            }
        )
        return errors
    for cue, dialogue in zip(captions, dialogues):
        if (
            abs(float(cue["start"]) - _ass_seconds(dialogue["start"])) > 0.021
            or abs(float(cue["end"]) - _ass_seconds(dialogue["end"])) > 0.021
            or str(cue.get("text", "")).replace("\n", " ") != dialogue["text"]
        ):
            errors.append(
                {
                    "code": "caption_ass_dialogue_mismatch",
                    "caption": cue.get("id"),
                    "json_range": [cue.get("start"), cue.get("end")],
                    "ass_range": [dialogue["start"], dialogue["end"]],
                }
            )
    return errors


def validate_audit_gate(
    audit_report: dict[str, Any],
    plan_path: Path,
    source_path: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    audit_errors = audit_report.get("errors") or []
    review = audit_report.get("review") if isinstance(audit_report.get("review"), dict) else {}
    if "unresolved_ids" in review:
        unresolved_ids = [str(item) for item in review.get("unresolved_ids") or []]
    else:
        legacy_count = int(
            audit_report.get("review_required_count", len(audit_report.get("review_required") or []))
        )
        unresolved_ids = [f"legacy-review-{index + 1:03d}" for index in range(legacy_count)]
    inputs = audit_report.get("inputs") if isinstance(audit_report.get("inputs"), dict) else {}
    plan_input = inputs.get("plan") if isinstance(inputs.get("plan"), dict) else {}
    source_input = inputs.get("source_media") if isinstance(inputs.get("source_media"), dict) else {}
    audited_plan_sha256 = (
        plan_input.get("sha256")
        or inputs.get("plan_sha256")
        or audit_report.get("plan_sha256")
    )
    audited_source_sha256 = source_input.get("sha256") or inputs.get("source_media_sha256")
    validation = {
        "provided": True,
        "schema_version": audit_report.get("schema_version"),
        "ok": bool(audit_report.get("ok")) and not audit_errors and not unresolved_ids,
        "review_required_count": int(audit_report.get("review_required_count", len(unresolved_ids))),
        "unresolved_ids": unresolved_ids,
        "plan_sha256": audited_plan_sha256,
        "source_media_sha256": audited_source_sha256,
    }
    if not audit_report.get("ok") or audit_errors:
        errors.append({"code": "cut_audit_not_approved"})
    if unresolved_ids:
        errors.append(
            {
                "code": "cut_audit_review_required",
                "count": len(unresolved_ids),
                "review_ids": unresolved_ids,
            }
        )
    actual_plan_sha256 = file_sha256(plan_path)
    if audited_plan_sha256 and audited_plan_sha256 != actual_plan_sha256:
        errors.append(
            {
                "code": "cut_audit_plan_hash_mismatch",
                "expected": audited_plan_sha256,
                "actual": actual_plan_sha256,
            }
        )
    if source_path is not None and audited_source_sha256:
        actual_source_sha256 = file_sha256(source_path)
        if audited_source_sha256 != actual_source_sha256:
            errors.append(
                {
                    "code": "cut_audit_source_hash_mismatch",
                    "expected": audited_source_sha256,
                    "actual": actual_source_sha256,
                }
            )
    return validation, errors


def decode_ass_attachment(payload: str) -> bytes:
    encoded = "".join(payload.splitlines())
    if len(encoded) % 4 == 1:
        raise ValueError("invalid encoded attachment length")
    decoded = bytearray()
    for offset in range(0, len(encoded), 4):
        chunk = encoded[offset : offset + 4]
        if any(not 33 <= ord(character) <= 96 for character in chunk):
            raise ValueError("attachment contains a character outside the ASS encoding range")
        value = 0
        for index, character in enumerate(chunk):
            value |= ((ord(character) - 33) & 0x3F) << (18 - index * 6)
        decoded.append((value >> 16) & 0xFF)
        if len(chunk) >= 3:
            decoded.append((value >> 8) & 0xFF)
        if len(chunk) >= 4:
            decoded.append(value & 0xFF)
    return bytes(decoded)


def inspect_ass_fonts(path: Path) -> dict[str, Any]:
    style_font_name = None
    style_bold = None
    attachments: dict[str, list[str]] = {}
    current_attachment = None
    in_fonts = False
    section_headers = {
        "[Script Info]",
        "[V4 Styles]",
        "[V4+ Styles]",
        "[Events]",
        "[Graphics]",
        "[Aegisub Project Garbage]",
        "[Aegisub Extradata]",
    }
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "[Fonts]":
            in_fonts = True
            current_attachment = None
            continue
        if line in section_headers:
            in_fonts = False
            current_attachment = None
        if line.startswith("Style: Duyi,"):
            fields = line.split(",")
            if len(fields) >= 8:
                style_font_name = fields[1].strip()
                try:
                    style_bold = int(fields[7])
                except ValueError:
                    style_bold = None
        if not in_fonts:
            continue
        if line.startswith("fontname:"):
            current_attachment = line.split(":", 1)[1].strip()
            attachments[current_attachment] = []
        elif current_attachment and line:
            attachments[current_attachment].append(line)

    decoded_attachments: dict[str, dict[str, Any]] = {}
    for name, lines in attachments.items():
        try:
            data = decode_ass_attachment("\n".join(lines))
            decoded_attachments[name] = {
                "ok": True,
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        except ValueError as error:
            decoded_attachments[name] = {"ok": False, "error": str(error)}
    return {
        "style_font_name": style_font_name,
        "style_bold": style_bold,
        "attachments": decoded_attachments,
    }


def measure_loudness(path: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-filter_complex",
                "ebur128=peak=true:dualmono=true",
                "-f",
                "null",
                "-",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "integrated_lufs": None,
            "true_peak_dbfs": None,
            "error": "ffmpeg_not_found",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "integrated_lufs": None,
            "true_peak_dbfs": None,
            "error": "measurement_timeout",
        }
    summary = completed.stderr.rsplit("Summary:", 1)[-1]
    integrated = re.search(r"I:\s*(-?\d+(?:\.\d+)?)\s+LUFS", summary)
    true_peak = re.search(r"Peak:\s*(-?\d+(?:\.\d+)?)\s+dBFS", summary)
    return {
        "ok": completed.returncode == 0 and integrated is not None and true_peak is not None,
        "integrated_lufs": float(integrated.group(1)) if integrated else None,
        "true_peak_dbfs": float(true_peak.group(1)) if true_peak else None,
        "returncode": completed.returncode,
    }


def measure_audio_activity(path: Path, duration: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-vn",
                "-af",
                "silencedetect=n=-50dB:d=0.15",
                "-f",
                "null",
                "-",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "ffmpeg_not_found"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "measurement_timeout"}
    silence_durations = [float(value) for value in re.findall(r"silence_duration:\s*(\d+(?:\.\d+)?)", completed.stderr)]
    silence_seconds = min(duration, sum(silence_durations))
    active_seconds = max(0.0, duration - silence_seconds)
    active_ratio = active_seconds / duration if duration > 0 else 0.0
    return {
        "ok": completed.returncode == 0,
        "threshold_db": -50,
        "minimum_silence_duration": 0.15,
        "silence_seconds": round(silence_seconds, 3),
        "active_seconds": round(active_seconds, 3),
        "active_ratio": round(active_ratio, 4),
    }


def _clamp_roi(roi: tuple[float, float, float, float], width: int, height: int) -> tuple[int, int, int, int] | None:
    x, y, roi_width, roi_height = roi
    left = max(0, min(width - 1, int(round(x))))
    top = max(0, min(height - 1, int(round(y))))
    right = max(left + 1, min(width, int(round(x + roi_width))))
    bottom = max(top + 1, min(height, int(round(y + roi_height))))
    if right - left < 2 or bottom - top < 2:
        return None
    return left, top, right - left, bottom - top


def overlay_roi(
    overlay: dict[str, Any],
    overlay_video: dict[str, Any],
    final_video: dict[str, Any],
) -> tuple[int, int, int, int] | None:
    bounds = overlay.get("content_bounds")
    if not isinstance(bounds, dict):
        return None
    try:
        min_x = float(bounds["min_x"])
        min_y = float(bounds["min_y"])
        max_x = float(bounds["max_x"])
        max_y = float(bounds["max_y"])
    except (KeyError, TypeError, ValueError):
        return None
    coordinate_space = str(bounds.get("coordinate_space") or overlay.get("coordinate_space") or "").lower()
    final_width = int(final_video.get("width") or 0)
    final_height = int(final_video.get("height") or 0)
    if coordinate_space in {"normalized", "ratio"} or (
        not coordinate_space and max(abs(min_x), abs(min_y), abs(max_x), abs(max_y)) <= 1.0
    ):
        roi = (
            min_x * final_width,
            min_y * final_height,
            (max_x - min_x) * final_width,
            (max_y - min_y) * final_height,
        )
    else:
        canvas = overlay.get("canvas") if isinstance(overlay.get("canvas"), dict) else {}
        canvas_width = float(canvas.get("width") or overlay_video.get("width") or final_width)
        canvas_height = float(canvas.get("height") or overlay_video.get("height") or final_height)
        if canvas_width <= 0 or canvas_height <= 0:
            return None
        roi = (
            min_x * final_width / canvas_width,
            min_y * final_height / canvas_height,
            (max_x - min_x) * final_width / canvas_width,
            (max_y - min_y) * final_height / canvas_height,
        )
    return _clamp_roi(roi, final_width, final_height)


def caption_roi(
    cue: dict[str, Any],
    caption_resolution: dict[str, Any],
    final_video: dict[str, Any],
) -> tuple[int, int, int, int] | None:
    background = cue.get("background")
    if not isinstance(background, dict):
        return None
    try:
        x = float(background["x"])
        y = float(background["y"])
        width = float(background["width"])
        height = float(background["height"])
        source_width = float(caption_resolution["width"])
        source_height = float(caption_resolution["height"])
    except (KeyError, TypeError, ValueError):
        return None
    final_width = int(final_video.get("width") or 0)
    final_height = int(final_video.get("height") or 0)
    if source_width <= 0 or source_height <= 0:
        return None
    return _clamp_roi(
        (
            x * final_width / source_width,
            y * final_height / source_height,
            width * final_width / source_width,
            height * final_height / source_height,
        ),
        final_width,
        final_height,
    )


def extract_gray_roi(
    path: Path,
    timestamp: float,
    roi: tuple[int, int, int, int],
    *,
    scale_to: tuple[int, int] | None = None,
) -> bytes:
    x, y, width, height = roi
    filters: list[str] = []
    if scale_to is not None:
        filters.append(f"scale={scale_to[0]}:{scale_to[1]}:flags=lanczos")
    filters.extend([f"crop={width}:{height}:{x}:{y}", "format=gray"])
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{max(0.0, timestamp):.6f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            ",".join(filters),
            "-f",
            "rawvideo",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=PROCESS_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0 or len(completed.stdout) != width * height:
        detail = completed.stderr.decode("utf-8", errors="replace")[-1000:]
        raise RuntimeError(detail or "frame extraction returned an unexpected byte count")
    return completed.stdout


def pixel_difference(
    baseline: Path,
    final: Path,
    timestamp: float,
    roi: tuple[int, int, int, int],
    *,
    baseline_scale_to: tuple[int, int] | None = None,
) -> dict[str, Any]:
    try:
        before = extract_gray_roi(
            baseline,
            timestamp,
            roi,
            scale_to=baseline_scale_to,
        )
        after = extract_gray_roi(final, timestamp, roi)
    except (FileNotFoundError, subprocess.TimeoutExpired, RuntimeError) as error:
        return {"ok": False, "visible": False, "error": str(error), "time": round(timestamp, 3), "roi": roi}
    differences = [abs(left - right) for left, right in zip(before, after)]
    mean_difference = sum(differences) / len(differences) if differences else 0.0
    changed_ratio = sum(value >= 20 for value in differences) / len(differences) if differences else 0.0
    maximum = max(differences, default=0)
    visible = mean_difference >= 2.0 or (changed_ratio >= 0.004 and maximum >= 35)
    return {
        "ok": True,
        "visible": visible,
        "time": round(timestamp, 3),
        "roi": list(roi),
        "mean_abs_difference": round(mean_difference, 4),
        "changed_ratio_20": round(changed_ratio, 6),
        "max_difference": maximum,
    }


def alpha_activity(path: Path, timestamp: float) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                f"{max(0.0, timestamp):.6f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                "alphaextract,format=gray",
                "-f",
                "rawvideo",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=PROCESS_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return {"ok": False, "visible": False, "error": str(error)}
    pixels = completed.stdout
    if completed.returncode != 0 or not pixels:
        return {
            "ok": False,
            "visible": False,
            "error": completed.stderr.decode("utf-8", errors="replace")[-1000:],
        }
    visible_ratio = sum(value > 4 for value in pixels) / len(pixels)
    return {"ok": True, "visible": visible_ratio > 0.0001, "visible_alpha_ratio": round(visible_ratio, 6)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Mechanical QA for a rendered talking-head edit.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--final", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--normalized-transcript", required=True)
    parser.add_argument("--asr-corrections", required=True)
    parser.add_argument("--asr-integrity", required=True)
    parser.add_argument("--locked-text-master", required=True)
    parser.add_argument("--caption-units", required=True)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--embedded-filler-review")
    parser.add_argument(
        "--cut-manifest",
        help="Optional apply_cut_plan manifest; uses the encoded cut duration instead of theoretical source-range sums",
    )
    parser.add_argument(
        "--rhythm-manifest",
        help="Optional adaptive-rhythm manifest; when provided, the rhythm output becomes the caption/overlay-free baseline",
    )
    parser.add_argument("--captions", required=True)
    parser.add_argument("--caption-unit-audit", required=True)
    parser.add_argument("--captions-ass", required=True)
    parser.add_argument("--overlays", required=True)
    parser.add_argument("--style-decision", required=True)
    parser.add_argument(
        "--base-video",
        help="Caption/overlay-free cut used as the pixel-evidence baseline; required when visual elements are declared",
    )
    parser.add_argument("--audit-report", help="Optional cut-plan audit report; review_required blocks final QA")
    parser.add_argument("--visual-direction-audit", help="Optional passing visual-direction audit")
    parser.add_argument("--visual-direction", help="visual-direction.json bound to the visual audit")
    parser.add_argument("--animation-plan", help="animation-plan.json bound to the visual audit")
    parser.add_argument("--semantic-reveal-audit", help="Passing exact spoken reveal audit")
    parser.add_argument("--semantic-reveal-timeline", help="Agent-authored reveal timeline bound to its audit")
    parser.add_argument("--render-log", help="Optional render stderr/stdout log checked for libass font fallback")
    parser.add_argument("--delivery-width", type=int, required=True)
    parser.add_argument("--delivery-height", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--duration-tolerance", type=float, default=0.25)
    args = parser.parse_args()

    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    final_path = Path(args.final)
    if not final_path.is_file() or final_path.stat().st_size == 0:
        write_json(args.output, {"ok": False, "errors": [{"code": "missing_or_empty_final"}]})
        return 1

    try:
        source = media_summary(args.source)
        final = media_summary(args.final)
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as error:
        write_json(
            args.output,
            {
                "ok": False,
                "errors": [{"code": "media_probe_failed", "error": str(error)}],
                "warnings": [],
            },
        )
        return 1
    plan_path = Path(args.plan)
    transcript_path = Path(args.transcript)
    normalized_transcript_path = Path(args.normalized_transcript)
    asr_corrections_path = Path(args.asr_corrections)
    asr_integrity_path = Path(args.asr_integrity)
    corrected_transcript = load_json(transcript_path)
    locked_text_master_path = Path(args.locked_text_master)
    locked_text_master = load_json(locked_text_master_path)
    locked_text_master_sha256 = file_sha256(locked_text_master_path)
    if (
        locked_text_master.get("status") != "locked"
        or (locked_text_master.get("confirmation") or {}).get("user_confirmed")
        is not True
        or (locked_text_master.get("confirmation") or {}).get("review_count") != 1
    ):
        errors.append({"code": "locked_text_master_invalid"})
    correction_inputs = corrected_transcript.get("inputs") or {}
    if (
        correction_inputs.get("normalized_transcript_sha256")
        != file_sha256(normalized_transcript_path)
        or correction_inputs.get("asr_corrections_sha256")
        != file_sha256(asr_corrections_path)
        or correction_inputs.get("source_media_sha256")
        != file_sha256(Path(args.source))
        or correction_inputs.get("asr_integrity_sha256")
        != file_sha256(asr_integrity_path)
    ):
        errors.append({"code": "asr_correction_input_hash_mismatch"})
    integrity = load_json(asr_integrity_path)
    integrity_inputs = integrity.get("inputs") or {}
    if (
        integrity.get("ok") is not True
        or (integrity_inputs.get("source_media") or {}).get("sha256")
        != file_sha256(Path(args.source))
        or (integrity_inputs.get("normalized_transcript") or {}).get("sha256")
        != file_sha256(normalized_transcript_path)
    ):
        errors.append({"code": "asr_integrity_contract_invalid"})
    correction_contract = corrected_transcript.get("asr_correction") or {}
    if (
        correction_contract.get("policy") != "word-level-asr-errors-only"
        or correction_contract.get("reviewed") is not True
        or correction_contract.get("unresolved_count") != 0
    ):
        errors.append({"code": "asr_correction_contract_invalid"})
    if (
        corrected_transcript.get("locked_text_master_sha256")
        != locked_text_master_sha256
        or load_json(asr_corrections_path).get("locked_text_master_sha256")
        != locked_text_master_sha256
        or load_json(plan_path).get("locked_text_master_sha256")
        != locked_text_master_sha256
        or load_json(Path(args.caption_units)).get("locked_text_master_sha256")
        != locked_text_master_sha256
    ):
        errors.append({"code": "locked_text_master_binding_mismatch"})
    caption_units_path = Path(args.caption_units)
    timeline_path = Path(args.timeline)
    plan = load_json(plan_path)
    timeline_payload = load_json(timeline_path)
    captions_payload = load_json(args.captions)
    caption_unit_audit_path = Path(args.caption_unit_audit)
    caption_unit_audit = load_json(caption_unit_audit_path)
    captions_ass_path = Path(args.captions_ass)
    overlays_payload = load_json(args.overlays)
    style_decision = load_json(args.style_decision)
    styles_payload = load_json(STYLE_PRESETS)
    subtitle_fonts_payload = load_json(SUBTITLE_FONT_PRESETS)
    captions = captions_payload.get("cues", [])
    resolved_style = captions_payload.get("resolved_style", {})
    overlays = overlays_payload if isinstance(overlays_payload, list) else overlays_payload.get("overlays", [])
    if not isinstance(overlays, list):
        errors.append({"code": "overlay_manifest_invalid"})
        overlays = []
    decision_source = style_decision.get("source")
    decision_style_id = style_decision.get("style_id")
    decision_skin_id = style_decision.get("skin_id")
    decision_paint_sha256 = style_decision.get("paint_tokens_sha256")
    decision_subtitle_preset = style_decision.get("subtitle_font_preset")
    decision_font_family = style_decision.get("font_family_id")
    decision_animation_font_file = style_decision.get("animation_font_file")
    decision_animation_layout = style_decision.get("animation_layout")
    decision_animation_panel_mode = style_decision.get("animation_panel_mode")
    decision_information_model = style_decision.get("information_model")
    decision_motion_model = style_decision.get("motion_model")
    decision_component_skin = style_decision.get("component_skin")
    style_preset = (styles_payload.get("presets") or {}).get(decision_style_id)
    expected_paint_tokens = (
        style_preset.get("paint_tokens") if isinstance(style_preset, dict) else {}
    ) or {}
    expected_panel_rgba = [
        *(expected_paint_tokens.get("panel_rgb") or []),
        float(expected_paint_tokens.get("panel_opacity", -1)),
    ]
    expected_stage_feather_rgba = [
        *(expected_paint_tokens.get("stage_feather_rgb") or []),
        float(expected_paint_tokens.get("stage_feather_opacity", -1)),
    ]
    expected_source_background_policy = (
        "transparent-stage"
        if decision_style_id == "white-wall-fusion-fixed"
        else "transparent-overlay"
    )
    expected_build_inputs_sha256 = (
        semantic_stage_build_inputs_sha256(style_preset)
        if isinstance(style_preset, dict)
        else None
    )
    animation_contract = styles_payload.get("animation_contract") or {}
    subtitle_font_preset = (subtitle_fonts_payload.get("presets") or {}).get(decision_subtitle_preset)
    caption_font_validation: dict[str, Any] = {
        "ass_path": str(captions_ass_path),
        "expected_ass_font_name": None,
        "actual_ass_font_name": None,
        "expected_bold": None,
        "actual_bold": None,
        "embedded_font_file": None,
        "embedded_font_sha256": None,
        "ok": False,
    }
    planned_duration = sum(float(item["source_end"]) - float(item["source_start"]) for item in plan.get("segments", []))

    caption_structure_validation: dict[str, Any] = {
        "provided": True,
        "ok": False,
        "policy": caption_unit_audit.get("policy"),
        "unit_count": caption_unit_audit.get("unit_count"),
    }
    if caption_unit_audit.get("ok") is not True or caption_unit_audit.get("errors"):
        errors.append({"code": "caption_unit_audit_not_approved"})
    if (
        caption_unit_audit.get("schema_version") != 1
        or caption_unit_audit.get("policy") != "semantic-complete"
        or caption_unit_audit.get("hard_filler_count") != 0
        or caption_unit_audit.get("ambiguous_embedded_filler_count") != 0
    ):
        errors.append({"code": "caption_unit_audit_contract_invalid"})
    audit_inputs = caption_unit_audit.get("inputs") or {}
    for name, path in (
        ("transcript", transcript_path),
        ("plan", plan_path),
        ("units", caption_units_path),
    ):
        fingerprint = audit_inputs.get(name)
        if (
            not isinstance(fingerprint, dict)
            or fingerprint.get("sha256") != file_sha256(path)
        ):
            errors.append(
                {
                    "code": "caption_unit_audit_input_hash_mismatch",
                    "input": name,
                }
            )
    embedded_review_binding = audit_inputs.get("embedded_filler_review")
    if embedded_review_binding is not None:
        if (
            not args.embedded_filler_review
            or not isinstance(embedded_review_binding, dict)
            or embedded_review_binding.get("sha256")
            != file_sha256(Path(args.embedded_filler_review))
        ):
            errors.append({"code": "embedded_filler_review_hash_mismatch"})
    elif args.embedded_filler_review:
        errors.append({"code": "unexpected_embedded_filler_review"})
    timeline_inputs = timeline_payload.get("inputs") or {}
    for name, path in (
        ("transcript", transcript_path),
        ("plan", plan_path),
        ("caption_units", caption_units_path),
        ("caption_unit_audit", caption_unit_audit_path),
    ):
        fingerprint = timeline_inputs.get(name)
        if (
            not isinstance(fingerprint, dict)
            or fingerprint.get("sha256") != file_sha256(path)
        ):
            errors.append(
                {
                    "code": "caption_timeline_input_hash_mismatch",
                    "input": name,
                }
            )
    if not args.cut_manifest:
        errors.append({"code": "caption_timeline_cut_manifest_missing"})
    else:
        cut_manifest_binding = timeline_inputs.get("cut_manifest")
        if (
            not isinstance(cut_manifest_binding, dict)
            or cut_manifest_binding.get("sha256")
            != file_sha256(Path(args.cut_manifest))
        ):
            errors.append({"code": "caption_timeline_cut_manifest_hash_mismatch"})
    if args.rhythm_manifest:
        rhythm_manifest_path = Path(args.rhythm_manifest)
        rhythm_manifest = load_json(rhythm_manifest_path)
        rhythm_plan_path = Path(str((rhythm_manifest.get("plan") or {}).get("path") or ""))
        rhythm_plan_binding = timeline_inputs.get("rhythm_plan")
        pre_rhythm_binding = timeline_inputs.get("pre_rhythm_timeline")
        if (
            not rhythm_plan_path.is_file()
            or not isinstance(rhythm_plan_binding, dict)
            or rhythm_plan_binding.get("sha256") != file_sha256(rhythm_plan_path)
        ):
            errors.append({"code": "caption_timeline_rhythm_plan_hash_mismatch"})
        if (
            not isinstance(pre_rhythm_binding, dict)
            or not Path(str(pre_rhythm_binding.get("path") or "")).is_file()
            or pre_rhythm_binding.get("sha256")
            != file_sha256(Path(str(pre_rhythm_binding.get("path"))))
        ):
            errors.append({"code": "caption_timeline_pre_rhythm_hash_mismatch"})
    elif timeline_inputs.get("rhythm_plan") or timeline_inputs.get("pre_rhythm_timeline"):
        errors.append({"code": "unexpected_caption_timeline_rhythm_binding"})
    caption_audit_binding = captions_payload.get("caption_unit_audit")
    if (
        not isinstance(caption_audit_binding, dict)
        or caption_audit_binding.get("sha256") != file_sha256(caption_unit_audit_path)
    ):
        errors.append({"code": "captions_caption_unit_audit_hash_mismatch"})
    caption_timeline_binding = captions_payload.get("timeline")
    if (
        not isinstance(caption_timeline_binding, dict)
        or caption_timeline_binding.get("sha256") != file_sha256(timeline_path)
    ):
        errors.append({"code": "captions_timeline_hash_mismatch"})
    expected_units = caption_unit_audit.get("units")
    if not isinstance(expected_units, list):
        expected_units = []
        errors.append({"code": "caption_unit_audit_units_invalid"})
    flattened_word_ids = [
        str(word_id)
        for unit in expected_units
        if isinstance(unit, dict)
        for word_id in unit.get("word_ids", [])
    ]
    if flattened_word_ids != caption_unit_audit.get("retained_word_ids"):
        errors.append({"code": "caption_unit_retained_word_coverage_mismatch"})
    timeline_units = timeline_payload.get("caption_units")
    if not isinstance(timeline_units, list) or [
        unit.get("id") for unit in timeline_units
    ] != [unit.get("id") for unit in expected_units]:
        errors.append({"code": "caption_timeline_unit_order_mismatch"})
    else:
        for unit in timeline_units:
            duration = float(unit.get("end", 0.0)) - float(unit.get("start", 0.0))
            if duration > 5.5 + 0.001:
                errors.append(
                    {
                        "code": "caption_timeline_unit_exceeds_adaptive_max",
                        "unit_id": unit.get("id"),
                        "duration": round(duration, 3),
                        "adaptive_max": 5.5,
                    }
                )
            elif duration > 3.8 + 0.001:
                warnings.append(
                    {
                        "code": "caption_timeline_unit_uses_adaptive_window",
                        "unit_id": unit.get("id"),
                        "duration": round(duration, 3),
                        "preferred_max": 3.8,
                    }
                )
    if len(captions) != len(expected_units):
        errors.append(
            {
                "code": "caption_unit_cue_count_mismatch",
                "expected": len(expected_units),
                "actual": len(captions),
            }
        )
    for index, (cue, unit) in enumerate(zip(captions, expected_units), start=1):
        if cue.get("caption_unit_id") != unit.get("id"):
            errors.append({"code": "caption_unit_id_mismatch", "index": index})
        if cue.get("word_ids") != unit.get("word_ids"):
            errors.append({"code": "caption_unit_word_coverage_mismatch", "index": index})
        if cue.get("semantic_complete") is not True:
            errors.append({"code": "caption_unit_not_semantic_complete", "index": index})
    speech_cleanup = captions_payload.get("speech_cleanup") or {}
    segmentation = captions_payload.get("segmentation") or {}
    if (
        speech_cleanup.get("policy") != "remove-all-nonsemantic-hard-fillers"
        or speech_cleanup.get("retained_hard_filler_count") != 0
    ):
        errors.append({"code": "caption_speech_cleanup_contract_missing"})
    if (
        segmentation.get("policy") != "semantic-complete"
        or segmentation.get("one_unit_per_cue") is not True
    ):
        errors.append({"code": "caption_semantic_segmentation_contract_missing"})
    caption_structure_validation["ok"] = not any(
        str(item.get("code", "")).startswith(("caption_unit", "captions_caption", "caption_speech", "caption_semantic"))
        for item in errors
    )
    expected_duration = planned_duration
    duration_reference = "cut-plan-source-ranges"
    rhythm_validation: dict[str, Any] = {
        "provided": bool(args.rhythm_manifest),
        "ok": None,
    }
    cut_manifest: dict[str, Any] = {}
    manifest_output: Path | None = None
    if args.cut_manifest:
        cut_manifest_path = Path(args.cut_manifest)
        cut_manifest = load_json(cut_manifest_path)
        if cut_manifest.get("schema_version") != 2:
            errors.append({"code": "cut_manifest_schema_invalid"})
        expected_manifest_hashes = {
            "plan_sha256": file_sha256(plan_path),
            "source_sha256": file_sha256(Path(args.source)),
        }
        if args.audit_report:
            expected_manifest_hashes["audit_report_sha256"] = file_sha256(
                Path(args.audit_report)
            )
        for field, expected_sha256 in expected_manifest_hashes.items():
            if cut_manifest.get(field) != expected_sha256:
                errors.append(
                    {
                        "code": "cut_manifest_input_hash_mismatch",
                        "input": field,
                    }
                )
        manifest_output = Path(str(cut_manifest.get("output") or ""))
        if (
            not manifest_output.is_file()
            or cut_manifest.get("output_sha256") != file_sha256(manifest_output)
            or (
                not args.rhythm_manifest
                and
                args.base_video
                and manifest_output.resolve() != Path(args.base_video).resolve()
            )
        ):
            errors.append({"code": "cut_manifest_output_mismatch"})
        manifest_segments = cut_manifest.get("segments")
        plan_segments = plan.get("segments", [])
        if not isinstance(manifest_segments, list) or len(manifest_segments) != len(
            plan_segments
        ):
            errors.append({"code": "cut_manifest_segment_count_mismatch"})
        else:
            for planned, rendered in zip(plan_segments, manifest_segments):
                if (
                    str(planned.get("id")) != str(rendered.get("id"))
                    or abs(float(planned["source_start"]) - float(rendered["source_start"]))
                    > 0.0005
                    or abs(float(planned["source_end"]) - float(rendered["source_end"]))
                    > 0.0005
                ):
                    errors.append({"code": "cut_manifest_segment_mismatch"})
                    break
        encoded_duration = (cut_manifest.get("output_media") or {}).get("duration")
        if encoded_duration is None:
            actual_durations = [item.get("actual_duration") for item in cut_manifest.get("segments", [])]
            if actual_durations and all(value is not None for value in actual_durations):
                encoded_duration = sum(float(value) for value in actual_durations)
        if encoded_duration is None:
            errors.append({"code": "cut_manifest_duration_missing", "path": args.cut_manifest})
        else:
            expected_duration = float(encoded_duration)
            duration_reference = "cut-manifest-encoded-output"

    if args.rhythm_manifest:
        rhythm_manifest_path = Path(args.rhythm_manifest)
        rhythm_manifest = load_json(rhythm_manifest_path)
        rhythm_errors: list[dict[str, Any]] = []
        if rhythm_manifest.get("schema_version") != 1:
            rhythm_errors.append({"code": "rhythm_manifest_schema_invalid"})
        if rhythm_manifest.get("pipeline_version") != PIPELINE_VERSION:
            rhythm_errors.append(
                {
                    "code": "rhythm_manifest_pipeline_version_mismatch",
                    "expected": PIPELINE_VERSION,
                    "actual": rhythm_manifest.get("pipeline_version"),
                }
            )
        if rhythm_manifest.get("policy") != "adaptive-rhythm-conservative-v1":
            rhythm_errors.append({"code": "rhythm_manifest_policy_invalid"})
        if rhythm_manifest.get("ok") is not True:
            rhythm_errors.append({"code": "rhythm_manifest_not_ok"})

        rhythm_input = rhythm_manifest.get("input") or {}
        if (
            manifest_output is None
            or not manifest_output.is_file()
            or rhythm_input.get("sha256") != file_sha256(manifest_output)
            or (
                rhythm_input.get("path")
                and Path(str(rhythm_input["path"])).resolve() != manifest_output.resolve()
            )
        ):
            rhythm_errors.append({"code": "rhythm_manifest_cut_input_mismatch"})

        rhythm_plan_fingerprint = rhythm_manifest.get("plan") or {}
        rhythm_plan_path = Path(str(rhythm_plan_fingerprint.get("path") or ""))
        if (
            not rhythm_plan_path.is_file()
            or rhythm_plan_fingerprint.get("sha256") != file_sha256(rhythm_plan_path)
        ):
            rhythm_errors.append({"code": "rhythm_manifest_plan_hash_mismatch"})
        elif (
            (timeline_inputs.get("rhythm_plan") or {}).get("sha256")
            != rhythm_plan_fingerprint.get("sha256")
        ):
            rhythm_errors.append({"code": "rhythm_manifest_timeline_plan_mismatch"})

        rhythm_output = rhythm_manifest.get("output") or {}
        rhythm_output_path = Path(str(rhythm_output.get("path") or ""))
        if (
            not rhythm_output_path.is_file()
            or rhythm_output.get("sha256") != file_sha256(rhythm_output_path)
            or (
                args.base_video
                and rhythm_output_path.resolve() != Path(args.base_video).resolve()
            )
        ):
            rhythm_errors.append({"code": "rhythm_manifest_output_mismatch"})

        pieces = rhythm_manifest.get("pieces")
        if not isinstance(pieces, list) or not pieces:
            rhythm_errors.append({"code": "rhythm_manifest_pieces_missing"})
        else:
            previous_output_end = 0.0
            for piece in pieces:
                rate = float(piece.get("rate", 0.0))
                output_start = float(piece.get("output_start", -1.0))
                output_end = float(piece.get("output_end", -1.0))
                source_start = float(piece.get("source_start", -1.0))
                source_end = float(piece.get("source_end", -1.0))
                if (
                    rate < 1.0
                    or rate > 1.15 + 0.0005
                    or source_end <= source_start
                    or output_end <= output_start
                    or abs(output_start - previous_output_end) > 0.003
                ):
                    rhythm_errors.append(
                        {
                            "code": "rhythm_manifest_piece_invalid",
                            "piece_id": piece.get("id"),
                        }
                    )
                    break
                previous_output_end = output_end

        encoded_rhythm_duration = (rhythm_manifest.get("output_media") or {}).get(
            "duration"
        )
        if encoded_rhythm_duration is None:
            rhythm_errors.append({"code": "rhythm_manifest_duration_missing"})
        else:
            expected_duration = float(encoded_rhythm_duration)
            duration_reference = "adaptive-rhythm-encoded-output"

        rhythm_validation = {
            "provided": True,
            "ok": not rhythm_errors,
            "policy": rhythm_manifest.get("policy"),
            "piece_count": len(pieces) if isinstance(pieces, list) else 0,
            "maximum_rate": (
                max(float(piece.get("rate", 0.0)) for piece in pieces)
                if isinstance(pieces, list) and pieces
                else None
            ),
            "errors": rhythm_errors,
        }
        errors.extend(rhythm_errors)

    decode_validation = full_decode(final_path)
    if not decode_validation["ok"]:
        errors.append(
            {
                "code": "final_full_decode_failed",
                "error": decode_validation.get("error") or decode_validation.get("stderr"),
            }
        )

    audit_validation: dict[str, Any] = {"provided": bool(args.audit_report), "ok": None}
    if args.audit_report:
        audit_report = load_json(args.audit_report)
        audit_validation, audit_gate_errors = validate_audit_gate(
            audit_report,
            Path(args.plan),
            Path(args.source),
        )
        for item in audit_gate_errors:
            item.setdefault("path", args.audit_report)
        errors.extend(audit_gate_errors)

    visual_direction_validation: dict[str, Any] = {
        "provided": bool(args.visual_direction_audit),
        "ok": None,
    }
    if args.visual_direction_audit:
        visual_audit = load_json(args.visual_direction_audit)
        visual_errors = visual_audit.get("errors") or []
        visual_direction_validation.update(
            {
                "ok": visual_audit.get("ok") is True and not visual_errors,
                "beat_count": visual_audit.get("beat_count"),
                "major_count": visual_audit.get("major_count"),
                "density_profile": visual_audit.get("density_profile"),
            }
        )
        if visual_audit.get("ok") is not True or visual_errors:
            errors.append({"code": "visual_direction_audit_not_approved"})
        audit_inputs = visual_audit.get("inputs") if isinstance(visual_audit.get("inputs"), dict) else {}
        for label, actual_path in (
            ("direction", args.visual_direction),
            ("animation_plan", args.animation_plan),
        ):
            expected = audit_inputs.get(label)
            expected_sha256 = expected.get("sha256") if isinstance(expected, dict) else None
            if not actual_path or not expected_sha256:
                errors.append({"code": "visual_direction_audit_input_missing", "input": label})
            elif expected_sha256 != file_sha256(Path(actual_path)):
                errors.append({"code": "visual_direction_audit_hash_mismatch", "input": label})

    semantic_reveal_validation: dict[str, Any] = {
        "provided": bool(args.semantic_reveal_audit),
        "ok": None,
    }
    if args.semantic_reveal_audit:
        reveal_audit = load_json(args.semantic_reveal_audit)
        reveal_errors = reveal_audit.get("errors") or []
        semantic_reveal_validation.update(
            {
                "ok": reveal_audit.get("ok") is True and not reveal_errors,
                "policy": reveal_audit.get("policy"),
                "visual_unit_count": reveal_audit.get("visual_unit_count"),
                "event_count": reveal_audit.get("event_count"),
                "coverage_complete": reveal_audit.get("coverage_complete"),
            }
        )
        if (
            reveal_audit.get("ok") is not True
            or reveal_errors
            or reveal_audit.get("coverage_complete") is not True
            or reveal_audit.get("policy") != "exact-spoken-reveal"
        ):
            errors.append({"code": "semantic_reveal_audit_not_approved"})
        reveal_inputs = reveal_audit.get("inputs") if isinstance(reveal_audit.get("inputs"), dict) else {}
        for label, actual_path in (
            ("animation_plan", args.animation_plan),
            ("reveal_timeline", args.semantic_reveal_timeline),
        ):
            expected = reveal_inputs.get(label)
            expected_sha256 = expected.get("sha256") if isinstance(expected, dict) else None
            if not actual_path or not expected_sha256:
                errors.append({"code": "semantic_reveal_audit_input_missing", "input": label})
            elif expected_sha256 != file_sha256(Path(actual_path)):
                errors.append({"code": "semantic_reveal_audit_hash_mismatch", "input": label})
    else:
        errors.append({"code": "semantic_reveal_audit_missing"})

    render_log_validation: dict[str, Any] = {"provided": bool(args.render_log), "ok": None}
    if args.render_log:
        render_log_path = Path(args.render_log)
        if not render_log_path.is_file():
            errors.append({"code": "render_log_missing", "path": args.render_log})
            render_log_validation["ok"] = False
        else:
            render_log_text = render_log_path.read_text(encoding="utf-8", errors="replace").lower()
            matched_patterns = [pattern for pattern in FONT_RENDER_FAILURE_PATTERNS if pattern in render_log_text]
            render_log_validation.update({"ok": not matched_patterns, "matched_patterns": matched_patterns})
            if matched_patterns:
                errors.append({"code": "caption_font_render_fallback_detected", "patterns": matched_patterns})

    if not final["video"]:
        errors.append({"code": "missing_video_stream"})
    if not final["audio"]:
        errors.append({"code": "missing_audio_stream"})
    if source["video"] and final["video"]:
        if final["video"]["width"] != args.delivery_width:
            errors.append(
                {
                    "code": "video_width_wrong",
                    "expected": args.delivery_width,
                    "final": final["video"]["width"],
                }
            )
        if final["video"]["height"] != args.delivery_height:
            errors.append(
                {
                    "code": "video_height_wrong",
                    "expected": args.delivery_height,
                    "final": final["video"]["height"],
                }
            )
        if source["video"]["orientation"] != final["video"]["orientation"]:
            errors.append(
                {
                    "code": "video_orientation_changed",
                    "source": source["video"]["orientation"],
                    "final": final["video"]["orientation"],
                }
            )
        if source["video"]["fps"] and final["video"]["fps"] and abs(source["video"]["fps"] - final["video"]["fps"]) > 0.05:
            errors.append({"code": "fps_changed", "source": source["video"]["fps"], "final": final["video"]["fps"]})
    if source["audio"] and final["audio"] and source["audio"]["sample_rate"] != final["audio"]["sample_rate"]:
        errors.append(
            {
                "code": "audio_sample_rate_changed",
                "source": source["audio"]["sample_rate"],
                "final": final["audio"]["sample_rate"],
            }
        )
    if final["duration"] is None or abs(final["duration"] - expected_duration) > args.duration_tolerance:
        errors.append(
            {
                "code": "duration_mismatch",
                "expected": round(expected_duration, 3),
                "actual": final["duration"],
                "tolerance": args.duration_tolerance,
            }
        )

    if decision_source not in STYLE_DECISION_SOURCES:
        errors.append({"code": "style_decision_source_invalid", "value": decision_source})
    if style_decision.get("decision_version") != 2:
        errors.append(
            {
                "code": "style_decision_version_invalid",
                "value": style_decision.get("decision_version"),
                "expected": 2,
            }
        )
    if style_decision.get("locked_for_video") is not True:
        errors.append({"code": "style_decision_not_locked"})
    if not re.fullmatch(r"[0-9a-f]{64}", str(style_decision.get("input_fingerprint", ""))):
        errors.append({"code": "style_decision_fingerprint_missing"})
    if not isinstance(style_preset, dict):
        errors.append({"code": "style_decision_style_unknown", "value": decision_style_id})
    else:
        expected_skin_id = style_preset.get("skin_id")
        expected_paint_sha256 = canonical_json_sha256(style_preset.get("paint_tokens") or {})
        if decision_skin_id != expected_skin_id:
            errors.append(
                {
                    "code": "style_decision_skin_mismatch",
                    "actual": decision_skin_id,
                    "expected": expected_skin_id,
                }
            )
        if decision_paint_sha256 != expected_paint_sha256:
            errors.append(
                {
                    "code": "style_decision_paint_tokens_mismatch",
                    "actual": decision_paint_sha256,
                    "expected": expected_paint_sha256,
                }
            )
    if not isinstance(subtitle_font_preset, dict):
        errors.append({"code": "style_decision_subtitle_preset_unknown", "value": decision_subtitle_preset})
    if isinstance(style_preset, dict) and style_preset.get("subtitle_font_preset") != decision_subtitle_preset:
        errors.append(
            {
                "code": "style_decision_subtitle_mapping_mismatch",
                "style": decision_style_id,
                "expected": style_preset.get("subtitle_font_preset"),
                "actual": decision_subtitle_preset,
            }
        )
    if (
        isinstance(style_preset, dict)
        and isinstance(subtitle_font_preset, dict)
        and (
            style_preset.get("font_family_id") != decision_font_family
            or subtitle_font_preset.get("font_family_id") != decision_font_family
        )
    ):
        errors.append(
            {
                "code": "style_decision_font_family_mismatch",
                "decision": decision_font_family,
                "animation": style_preset.get("font_family_id"),
                "subtitle": subtitle_font_preset.get("font_family_id"),
            }
        )
    if (
        isinstance(style_preset, dict)
        and not style_preset.get("auto_eligible")
        and (
            decision_source != "user_override"
            or style_decision.get("user_confirmed") is not True
        )
    ):
        errors.append(
            {
                "code": "style_decision_manual_style_not_user_confirmed",
                "style": decision_style_id,
                "source": decision_source,
            }
        )
    if decision_source == "default_fallback" and decision_style_id != styles_payload.get("default"):
        errors.append(
            {
                "code": "style_decision_fallback_not_default",
                "style": decision_style_id,
                "default": styles_payload.get("default"),
            }
        )
    expected_animation_layout = animation_contract.get("layout")
    expected_animation_panel_mode = animation_contract.get("panel_mode")
    if decision_animation_layout != expected_animation_layout or decision_animation_layout != "reference-fixed-left":
        errors.append(
            {
                "code": "style_decision_animation_layout_mismatch",
                "actual": decision_animation_layout,
                "expected": expected_animation_layout,
            }
        )
    if decision_animation_panel_mode != expected_animation_panel_mode or decision_animation_panel_mode != "content-panel":
        errors.append(
            {
                "code": "style_decision_animation_panel_mode_mismatch",
                "actual": decision_animation_panel_mode,
                "expected": expected_animation_panel_mode,
            }
        )
    expected_animation_font_file = (
        style_preset.get("animation_font_file")
        if isinstance(style_preset, dict)
        else None
    )
    if (
        decision_animation_font_file != expected_animation_font_file
        or decision_animation_font_file != "fonts/NotoSansCJKsc-Bold.otf"
    ):
        errors.append(
            {
                "code": "style_decision_animation_font_mismatch",
                "actual": decision_animation_font_file,
                "expected": "fonts/NotoSansCJKsc-Bold.otf",
            }
        )
    for field, actual, expected in (
        ("information_model", decision_information_model, "persistent-layer-stack"),
        ("motion_model", decision_motion_model, "anchored-opacity"),
        ("component_skin", decision_component_skin, "type-specific-reference"),
    ):
        if actual != animation_contract.get(field) or actual != expected:
            errors.append(
                {
                    "code": f"style_decision_{field}_mismatch",
                    "actual": actual,
                    "expected": expected,
                }
            )

    if not captions_ass_path.is_file():
        errors.append({"code": "captions_ass_missing", "path": str(captions_ass_path)})
    elif isinstance(subtitle_font_preset, dict):
        ass_fonts = inspect_ass_fonts(captions_ass_path)
        expected_ass_font_name = subtitle_font_preset.get("ass_font_name") or subtitle_font_preset.get("font_name")
        expected_bold = -1 if subtitle_font_preset.get("bold", True) else 0
        expected_font_relative = subtitle_font_preset.get("font_file")
        expected_font_path = SUBTITLE_FONT_PRESETS.parent / str(expected_font_relative or "")
        expected_font_sha256 = (
            hashlib.sha256(expected_font_path.read_bytes()).hexdigest() if expected_font_path.is_file() else None
        )
        embedded_font_name = Path(str(expected_font_relative or "")).name
        embedded_font = (ass_fonts.get("attachments") or {}).get(embedded_font_name)
        caption_font_validation.update(
            {
                "expected_ass_font_name": expected_ass_font_name,
                "actual_ass_font_name": ass_fonts.get("style_font_name"),
                "expected_bold": expected_bold,
                "actual_bold": ass_fonts.get("style_bold"),
                "embedded_font_file": embedded_font_name,
                "embedded_font_sha256": (embedded_font or {}).get("sha256"),
            }
        )
        if resolved_style.get("ass_font_name") != expected_ass_font_name:
            errors.append(
                {
                    "code": "caption_resolved_ass_font_face_mismatch",
                    "expected": expected_ass_font_name,
                    "actual": resolved_style.get("ass_font_name"),
                }
            )
        if ass_fonts.get("style_font_name") != expected_ass_font_name:
            errors.append(
                {
                    "code": "caption_ass_font_face_mismatch",
                    "expected": expected_ass_font_name,
                    "actual": ass_fonts.get("style_font_name"),
                }
            )
        if ass_fonts.get("style_bold") != expected_bold:
            errors.append(
                {
                    "code": "caption_ass_bold_flag_mismatch",
                    "expected": expected_bold,
                    "actual": ass_fonts.get("style_bold"),
                }
            )
        if expected_font_sha256 is None:
            errors.append({"code": "caption_preset_font_file_missing", "path": str(expected_font_path)})
        elif not embedded_font:
            errors.append({"code": "caption_embedded_font_missing", "file": embedded_font_name})
        elif not embedded_font.get("ok"):
            errors.append(
                {
                    "code": "caption_embedded_font_decode_failed",
                    "file": embedded_font_name,
                    "error": embedded_font.get("error"),
                }
            )
        elif embedded_font.get("sha256") != expected_font_sha256:
            errors.append(
                {
                    "code": "caption_embedded_font_hash_mismatch",
                    "file": embedded_font_name,
                    "expected": expected_font_sha256,
                    "actual": embedded_font.get("sha256"),
                }
            )
        if resolved_style.get("embedded_font_sha256") != expected_font_sha256:
            errors.append(
                {
                    "code": "caption_resolved_embedded_font_hash_mismatch",
                    "expected": expected_font_sha256,
                    "actual": resolved_style.get("embedded_font_sha256"),
                }
            )
        caption_font_validation["ok"] = not any(
            item["code"].startswith(
                (
                    "caption_ass_",
                    "caption_embedded_",
                    "caption_preset_",
                    "caption_resolved_ass_",
                    "caption_resolved_embedded_",
                )
            )
            for item in errors
        )

    ass_dialogues: list[dict[str, Any]] = []
    if captions_ass_path.is_file():
        ass_dialogues = inspect_ass_dialogues(captions_ass_path)
        errors.extend(compare_ass_dialogues(captions, ass_dialogues))

    previous_caption_end = 0.0
    for cue in captions:
        start = float(cue["start"])
        end = float(cue["end"])
        if start < -0.001 or end > float(final["duration"] or 0) + 0.001 or end <= start:
            errors.append({"code": "caption_out_of_bounds", "caption": cue.get("id"), "range": [start, end]})
        if start < previous_caption_end - 0.001:
            errors.append({"code": "caption_overlap", "caption": cue.get("id"), "previous_end": previous_caption_end})
        if "\\N" in str(cue.get("text", "")) or "\n" in str(cue.get("text", "")):
            errors.append({"code": "caption_not_single_line", "caption": cue.get("id")})
        punctuation_probe = re.sub(r"(?<=\d)\.(?=\d)", "", str(cue.get("text", "")))
        if any(character in "，。！？；：、,.!?;:…“”‘’" for character in punctuation_probe):
            errors.append({"code": "caption_display_punctuation", "caption": cue.get("id"), "text": cue.get("text")})
        background = cue.get("background")
        if not background:
            errors.append({"code": "caption_background_missing", "caption": cue.get("id")})
        elif background.get("mode") != "rounded":
            errors.append({"code": "caption_background_not_rounded", "caption": cue.get("id"), "mode": background.get("mode")})
        previous_caption_end = end

    expected_caption_size = float((subtitle_font_preset or {}).get("font_size_at_1080", 0))
    actual_caption_size = float(resolved_style.get("font_size_at_1080", 0))
    if expected_caption_size <= 0 or abs(actual_caption_size - expected_caption_size) > 0.01:
        errors.append(
            {
                "code": "caption_font_size_differs_from_contract",
                "actual": actual_caption_size,
                "expected": expected_caption_size,
            }
        )
    if resolved_style.get("font_preset") != decision_subtitle_preset:
        errors.append({"code": "caption_single_font_preset_missing", "value": resolved_style.get("font_preset")})
    if resolved_style.get("font_preset") != decision_subtitle_preset:
        errors.append(
            {
                "code": "caption_font_preset_differs_from_style_decision",
                "caption": resolved_style.get("font_preset"),
                "decision": decision_subtitle_preset,
            }
        )
    expected_primary = (subtitle_font_preset or {}).get("primary_color")
    if resolved_style.get("primary_color") != expected_primary:
        errors.append(
            {
                "code": "caption_text_color_differs_from_contract",
                "actual": resolved_style.get("primary_color"),
                "expected": expected_primary,
            }
        )
    expected_outline = (subtitle_font_preset or {}).get("outline_color")
    if resolved_style.get("outline_color") != expected_outline:
        errors.append(
            {
                "code": "caption_outline_differs_from_contract",
                "actual": resolved_style.get("outline_color"),
                "expected": expected_outline,
            }
        )
    if not resolved_style.get("vertical_alignment_calibrated", False):
        errors.append({"code": "caption_font_vertical_alignment_not_calibrated", "font_preset": resolved_style.get("font_preset")})
    if "background_bottom_offset_at_1080" not in resolved_style:
        errors.append({"code": "caption_font_vertical_offset_missing", "font_preset": resolved_style.get("font_preset")})
    if not resolved_style.get("weight_calibrated", False) or resolved_style.get("weight_mode") not in {
        "native-black",
        "native-bold",
        "synthetic-bold",
    }:
        errors.append({"code": "caption_font_weight_not_calibrated", "font_preset": resolved_style.get("font_preset")})
    if not resolved_style.get("background_enabled", False):
        errors.append({"code": "caption_background_disabled"})
    if resolved_style.get("background_mode") != "rounded":
        errors.append({"code": "caption_background_not_rounded", "value": resolved_style.get("background_mode")})
    expected_background_opacity = float((subtitle_font_preset or {}).get("background_opacity", 0))
    if abs(float(resolved_style.get("background_opacity", 0)) - expected_background_opacity) > 0.01:
        errors.append(
            {
                "code": "caption_background_opacity_differs_from_contract",
                "actual": resolved_style.get("background_opacity"),
                "expected": expected_background_opacity,
            }
        )

    overlay_visual_inputs: list[dict[str, Any]] = []
    if len(overlays) > max(2, round(expected_duration / 30 * 2)):
        errors.append({"code": "overlay_density_exceeded", "count": len(overlays), "duration": expected_duration})
    overlay_skin_ids = {overlay.get("skin_id") for overlay in overlays}
    if len(overlay_skin_ids) > 1:
        errors.append(
            {
                "code": "mixed_overlay_skins",
                "skins": sorted(str(item) for item in overlay_skin_ids),
            }
        )
    for overlay in overlays:
        start = float(overlay["start"])
        end = float(overlay.get("end", start + float(overlay.get("duration", 0))))
        if start < 0 or end > float(final["duration"] or 0) + 0.001 or end <= start:
            errors.append({"code": "overlay_out_of_bounds", "overlay": overlay.get("id"), "range": [start, end]})
        anchor_start = overlay.get("anchor_start")
        if anchor_start is not None and start < float(anchor_start) - 0.001:
            errors.append(
                {"code": "overlay_starts_before_anchor", "overlay": overlay.get("id"), "start": start, "anchor_start": anchor_start}
            )
        overlay_path = Path(overlay["path"])
        if not overlay_path.is_file():
            errors.append({"code": "overlay_file_missing", "overlay": overlay.get("id"), "path": overlay["path"]})
            continue
        if overlay.get("media_sha256") != file_sha256(overlay_path):
            errors.append(
                {
                    "code": "overlay_media_hash_mismatch",
                    "overlay": overlay.get("id"),
                }
            )
        overlay_media = media_summary(overlay_path)
        overlay_video = overlay_media.get("video") or {}
        if "a" not in str(overlay_video.get("pix_fmt", "")):
            errors.append({"code": "overlay_missing_alpha", "overlay": overlay.get("id"), "pix_fmt": overlay_video.get("pix_fmt")})
        if (overlay_video.get("width"), overlay_video.get("height")) != (2560, 1440):
            errors.append(
                {
                    "code": "overlay_resolution_mismatch",
                    "overlay": overlay.get("id"),
                    "actual": [overlay_video.get("width"), overlay_video.get("height")],
                    "expected": [2560, 1440],
                }
            )
        if overlay.get("outer_background") != "transparent":
            errors.append({"code": "overlay_outer_background_not_transparent", "overlay": overlay.get("id")})
        if overlay.get("source_background_policy") != expected_source_background_policy:
            errors.append(
                {
                    "code": "overlay_source_background_policy_invalid",
                    "overlay": overlay.get("id"),
                    "actual": overlay.get("source_background_policy"),
                    "expected": expected_source_background_policy,
                }
            )
        template = overlay.get("template")
        if template is not None and template not in ALLOWED_OVERLAY_TEMPLATES:
            errors.append({"code": "overlay_template_not_allowed", "overlay": overlay.get("id"), "template": template})
        if overlay.get("style") != decision_style_id:
            errors.append(
                {
                    "code": "overlay_style_differs_from_style_decision",
                    "overlay": overlay.get("id"),
                    "overlay_style": overlay.get("style"),
                    "decision_style": decision_style_id,
                }
            )
        if overlay.get("skin_id") != decision_skin_id:
            errors.append(
                {
                    "code": "overlay_skin_differs_from_style_decision",
                    "overlay": overlay.get("id"),
                    "actual": overlay.get("skin_id"),
                    "expected": decision_skin_id,
                }
            )
        if overlay.get("paint_tokens_sha256") != decision_paint_sha256:
            errors.append(
                {
                    "code": "overlay_paint_tokens_differs_from_style_decision",
                    "overlay": overlay.get("id"),
                }
            )
        if overlay.get("build_inputs_sha256") != expected_build_inputs_sha256:
            errors.append(
                {
                    "code": "overlay_build_inputs_mismatch",
                    "overlay": overlay.get("id"),
                }
            )
        if overlay.get("animation_layout") != decision_animation_layout:
            errors.append(
                {
                    "code": "overlay_animation_layout_mismatch",
                    "overlay": overlay.get("id"),
                    "actual": overlay.get("animation_layout"),
                    "expected": decision_animation_layout,
                }
            )
        expected_panel_mode = "content-panel"
        if overlay.get("panel_mode") != expected_panel_mode:
            errors.append(
                {
                    "code": "overlay_panel_mode_invalid",
                    "overlay": overlay.get("id"),
                    "template": template,
                    "actual": overlay.get("panel_mode"),
                    "expected": expected_panel_mode,
                }
            )
        if overlay.get("information_model") != "persistent-layer-stack":
            errors.append(
                {
                    "code": "overlay_information_model_invalid",
                    "overlay": overlay.get("id"),
                    "actual": overlay.get("information_model"),
                    "expected": "persistent-layer-stack",
                }
            )
        if overlay.get("motion_model") != "anchored-opacity":
            errors.append(
                {
                    "code": "overlay_motion_model_invalid",
                    "overlay": overlay.get("id"),
                    "actual": overlay.get("motion_model"),
                    "expected": "anchored-opacity",
                }
            )
        if overlay.get("semantic_timing_model") != "exact-spoken-reveal":
            errors.append(
                {
                    "code": "overlay_semantic_timing_model_invalid",
                    "overlay": overlay.get("id"),
                    "actual": overlay.get("semantic_timing_model"),
                    "expected": "exact-spoken-reveal",
                }
            )
        if overlay.get("component_skin") != "type-specific-reference":
            errors.append(
                {
                    "code": "overlay_component_skin_invalid",
                    "overlay": overlay.get("id"),
                    "actual": overlay.get("component_skin"),
                    "expected": "type-specific-reference",
                }
            )
        selections = overlay.get("card_size_selections")
        if (
            overlay.get("card_sizing_model") != "spoken-first-content-height"
            or overlay.get("visual_grammar_model") != "spoken-first-relations"
            or overlay.get("stage_layout_model")
            != "measured-content-height-reflow-v1"
            or not isinstance(selections, list)
            or not selections
            or any(
                not isinstance(item, dict)
                or item.get("size") not in {"small", "medium"}
                or not str(item.get("content_structure") or "").strip()
                or not str(item.get("reason") or "").strip()
                or not str(item.get("relation_layout") or "").strip()
                or item.get("fidelity_mode") != "spoken-first"
                or not str(item.get("layout_reason") or "").strip()
                for item in selections
            )
        ):
            errors.append(
                {
                    "code": "overlay_card_sizing_contract_invalid",
                    "overlay": overlay.get("id"),
                }
            )
        layout_check = overlay.get("layout_check")
        if (
            not isinstance(layout_check, dict)
            or layout_check.get("policy") != "browser-measured-layout-gate"
            or layout_check.get("layout_model")
            != "measured-content-height-reflow-v1"
            or layout_check.get("ok") is not True
            or layout_check.get("container_overflow_count") != 0
        ):
            errors.append(
                {
                    "code": "overlay_browser_layout_check_invalid",
                    "overlay": overlay.get("id"),
                }
            )
        if overlay.get("animation_font_file") != "NotoSansCJKsc-Bold.otf":
            errors.append(
                {
                    "code": "overlay_animation_font_invalid",
                    "overlay": overlay.get("id"),
                    "actual": overlay.get("animation_font_file"),
                    "expected": "NotoSansCJKsc-Bold.otf",
                }
            )
        if overlay.get("pipeline_version") != PIPELINE_VERSION:
            errors.append(
                {
                    "code": "overlay_pipeline_version_invalid",
                    "overlay": overlay.get("id"),
                    "actual": overlay.get("pipeline_version"),
                    "expected": PIPELINE_VERSION,
                }
            )
        if (overlay.get("runtime") or {}).get("version") != HYPERFRAMES_VERSION:
            errors.append(
                {
                    "code": "overlay_runtime_version_invalid",
                    "overlay": overlay.get("id"),
                }
            )
        timeline_contract = overlay.get("timeline_contract") or {}
        if (
            timeline_contract.get("id") != "semantic-stage-timeline-v1"
            or timeline_contract.get("header_lead_seconds") != 0.30
            or timeline_contract.get("container_entry_seconds") != 0.22
            or timeline_contract.get("item_entry_seconds") != 0.15
            or timeline_contract.get("exit_seconds") != 0.22
            or any(
                not re.fullmatch(r"[0-9a-f]{64}", str(timeline_contract.get(field) or ""))
                for field in ("dom_sha256", "timeline_sha256", "assertions_sha256")
            )
        ):
            errors.append(
                {
                    "code": "overlay_timeline_contract_invalid",
                    "overlay": overlay.get("id"),
                }
            )
        reference_contract = overlay.get("reference_contract") or {}
        if (
            reference_contract.get("default_card_size") != "medium"
            or reference_contract.get("card_sizes")
            != {
                "small": {
                    "reference_width": 373,
                    "template_width": 746,
                    "canvas_ratio": 0.29140625,
                },
                "medium": {
                    "reference_width": 427,
                    "template_width": 854,
                    "canvas_ratio": 0.33359375,
                },
            }
            or reference_contract.get("maximum_card_width")
            != {
                "size": "medium",
                "reference_width": 427,
                "template_width": 854,
                "canvas_ratio": 0.33359375,
            }
        ):
            errors.append(
                {
                    "code": "overlay_card_size_reference_invalid",
                    "overlay": overlay.get("id"),
                }
            )
        if reference_contract.get("panel_rgba") != expected_panel_rgba:
            errors.append(
                {
                    "code": "overlay_panel_rgba_invalid",
                    "overlay": overlay.get("id"),
                    "actual": reference_contract.get("panel_rgba"),
                    "expected": expected_panel_rgba,
                }
            )
        if reference_contract.get("stage_feather_rgba") != expected_stage_feather_rgba:
            errors.append(
                {
                    "code": "overlay_stage_feather_invalid",
                    "overlay": overlay.get("id"),
                    "actual": reference_contract.get("stage_feather_rgba"),
                    "expected": expected_stage_feather_rgba,
                }
            )
        if reference_contract.get("free_text_primary") != expected_paint_tokens.get(
            "text_primary"
        ):
            errors.append(
                {
                    "code": "overlay_free_text_color_invalid",
                    "overlay": overlay.get("id"),
                }
            )
        if reference_contract.get("panel_text_primary") != expected_paint_tokens.get(
            "panel_text_primary"
        ):
            errors.append(
                {
                    "code": "overlay_panel_text_color_invalid",
                    "overlay": overlay.get("id"),
                }
            )
        if reference_contract.get("full_field_overlay_opacity") != float(
            expected_paint_tokens.get("fullscreen_opacity", -1)
        ):
            errors.append(
                {
                    "code": "overlay_full_field_opacity_invalid",
                    "overlay": overlay.get("id"),
                }
            )
        if decision_style_id == "white-wall-fusion-fixed" and (
            expected_paint_tokens.get("panel_rgb") != [10, 20, 27]
            or float(expected_paint_tokens.get("panel_opacity", -1)) != 0.82
            or expected_paint_tokens.get("text_primary") != "#17212B"
            or expected_paint_tokens.get("panel_text_primary") != "#F3F5F7"
            or float(expected_paint_tokens.get("stage_feather_opacity", -1)) != 0.0
            or float(expected_paint_tokens.get("fullscreen_opacity", -1)) != 0.0
        ):
            errors.append(
                {
                    "code": "white_wall_paint_role_contract_invalid",
                    "overlay": overlay.get("id"),
                }
            )
        layout = overlay.get("layout")
        if layout not in {"fixed-left", "fullscreen"}:
            errors.append({"code": "overlay_layout_policy_missing", "overlay": overlay.get("id"), "layout": layout})
        expected_lane = "full" if layout == "fullscreen" else "left"
        if overlay.get("lane") != expected_lane:
            errors.append(
                {
                    "code": "overlay_lane_invalid",
                    "overlay": overlay.get("id"),
                    "lane": overlay.get("lane"),
                    "expected": expected_lane,
                }
            )
        if overlay.get("coordinate_space") != "normalized":
            errors.append(
                {
                    "code": "overlay_coordinate_space_invalid",
                    "overlay": overlay.get("id"),
                    "coordinate_space": overlay.get("coordinate_space"),
                }
            )
        resolved_roi = overlay_roi(overlay, overlay_video, final.get("video") or {})
        if resolved_roi is None:
            errors.append({"code": "overlay_content_bounds_missing_or_invalid", "overlay": overlay.get("id")})
        else:
            overlay_visual_inputs.append(
                {
                    "overlay": overlay,
                    "path": overlay_path,
                    "roi": resolved_roi,
                    "media": overlay_media,
                }
            )
        reserve_ratio = float(overlay.get("platform_ui_reserved_ratio", 0.16))
        safe_right = float(final["video"].get("width", 0)) * (1.0 - reserve_ratio) if final.get("video") else 0
        resolved_max_x = resolved_roi[0] + resolved_roi[2] if resolved_roi else safe_right + 1
        if resolved_max_x > safe_right:
            errors.append(
                {
                    "code": "overlay_enters_platform_ui_zone",
                    "overlay": overlay.get("id"),
                    "max_x": resolved_max_x,
                    "safe_right": safe_right,
                }
            )
        if overlay.get("template") == "media-frame":
            caption_zone_top_ratio = float(overlay.get("caption_zone_top_ratio", 0.82))
            caption_zone_top = float(final["video"].get("height", 0)) * caption_zone_top_ratio if final.get("video") else 0
            resolved_max_y = resolved_roi[1] + resolved_roi[3] if resolved_roi else caption_zone_top + 1
            if resolved_max_y > caption_zone_top:
                errors.append(
                    {
                        "code": "media_frame_enters_caption_zone",
                        "overlay": overlay.get("id"),
                        "max_y": resolved_max_y,
                        "caption_zone_top": caption_zone_top,
                    }
                )
            if not str(overlay.get("label", "")).strip():
                errors.append({"code": "media_frame_label_missing", "overlay": overlay.get("id")})
        if overlay.get("template") == "prompt-card":
            source_reference = overlay.get("source_reference")
            if not source_reference or (isinstance(source_reference, list) and not any(str(item).strip() for item in source_reference)):
                errors.append({"code": "prompt_card_source_reference_missing", "overlay": overlay.get("id")})
            if not re.fullmatch(r"[0-9a-fA-F]{64}", str(overlay.get("body_sha256", ""))):
                errors.append({"code": "prompt_card_body_hash_missing", "overlay": overlay.get("id")})
            if "复制" in str(overlay.get("badge", "")) and overlay.get("copy_interaction_verified") is not True:
                errors.append({"code": "prompt_card_false_copy_claim", "overlay": overlay.get("id")})
            if float(overlay.get("font_size_at_1080", 0)) < 32:
                errors.append({"code": "prompt_card_font_too_small", "overlay": overlay.get("id")})
            page_count = int(overlay.get("page_count", 0))
            if not 1 <= page_count <= 3:
                errors.append({"code": "prompt_card_page_count_invalid", "overlay": overlay.get("id"), "page_count": page_count})
            if float(overlay.get("page_readable_seconds", 0)) < 2.2:
                errors.append({"code": "prompt_card_readability_too_short", "overlay": overlay.get("id")})
            if overlay.get("truncated") is True:
                errors.append({"code": "prompt_card_text_truncated", "overlay": overlay.get("id")})

    visual_evidence: dict[str, Any] = {
        "baseline": args.base_video,
        "captions": [],
        "overlays": [],
        "ok": None,
    }
    visuals_declared = bool(captions or overlays)
    baseline_path = Path(args.base_video).resolve() if args.base_video else None
    if visuals_declared and (baseline_path is None or not baseline_path.is_file()):
        errors.append({"code": "visual_baseline_missing"})
        visual_evidence["ok"] = False
    elif visuals_declared and baseline_path is not None:
        try:
            baseline_media = media_summary(baseline_path)
        except (FileNotFoundError, subprocess.CalledProcessError, ValueError) as error:
            errors.append({"code": "visual_baseline_probe_failed", "error": str(error)})
            visual_evidence["ok"] = False
        else:
            baseline_video = baseline_media.get("video") or {}
            final_video = final.get("video") or {}
            baseline_width = int(baseline_video.get("width") or 0)
            baseline_height = int(baseline_video.get("height") or 0)
            final_width = int(final_video.get("width") or 0)
            final_height = int(final_video.get("height") or 0)
            same_aspect = (
                baseline_width > 0
                and baseline_height > 0
                and final_width > 0
                and final_height > 0
                and baseline_width * final_height == baseline_height * final_width
            )
            if not same_aspect:
                errors.append(
                    {
                        "code": "visual_baseline_resolution_mismatch",
                        "baseline": [baseline_width, baseline_height],
                        "final": [final_width, final_height],
                    }
                )
            else:
                baseline_scale_to = (
                    (final_width, final_height)
                    if (baseline_width, baseline_height) != (final_width, final_height)
                    else None
                )
                caption_indexes = sorted({0, len(captions) // 2, len(captions) - 1}) if captions else []
                for index in caption_indexes:
                    cue = captions[index]
                    roi = caption_roi(cue, captions_payload.get("resolution") or {}, final_video)
                    if roi is None:
                        result = {"ok": False, "visible": False, "caption": cue.get("id"), "error": "roi_unavailable"}
                    else:
                        timestamp = (float(cue["start"]) + float(cue["end"])) / 2.0
                        result = pixel_difference(
                            baseline_path,
                            final_path,
                            timestamp,
                            roi,
                            baseline_scale_to=baseline_scale_to,
                        )
                        result["caption"] = cue.get("id")
                    visual_evidence["captions"].append(result)
                    if not result.get("ok"):
                        errors.append(
                            {
                                "code": "caption_pixel_evidence_unavailable",
                                "caption": cue.get("id"),
                                "error": result.get("error"),
                            }
                        )
                    elif not result.get("visible"):
                        errors.append({"code": "caption_pixels_not_detected", "caption": cue.get("id")})

                for item in overlay_visual_inputs:
                    overlay = item["overlay"]
                    start = float(overlay["start"])
                    end = float(overlay.get("end", start + float(overlay.get("duration", 0))))
                    candidates: list[dict[str, Any]] = []
                    for fraction in (0.35, 0.55, 0.75):
                        timestamp = start + max(0.0, end - start) * fraction
                        pixels = pixel_difference(
                            baseline_path,
                            final_path,
                            timestamp,
                            item["roi"],
                            baseline_scale_to=baseline_scale_to,
                        )
                        alpha = alpha_activity(item["path"], timestamp - start)
                        candidates.append(
                            {
                                **pixels,
                                "alpha": alpha,
                                "overlay": overlay.get("id"),
                            }
                        )
                    visible_candidates = [
                        candidate
                        for candidate in candidates
                        if candidate.get("ok")
                        and candidate.get("visible")
                        and candidate.get("alpha", {}).get("ok")
                        and candidate.get("alpha", {}).get("visible")
                    ]
                    best = max(
                        visible_candidates or candidates,
                        key=lambda candidate: (
                            bool(candidate.get("visible")),
                            float(candidate.get("mean_abs_difference", 0)),
                        ),
                    )
                    visual_evidence["overlays"].append(best)
                    if not best.get("ok") or not best.get("alpha", {}).get("ok"):
                        errors.append(
                            {
                                "code": "overlay_pixel_evidence_unavailable",
                                "overlay": overlay.get("id"),
                                "error": best.get("error") or best.get("alpha", {}).get("error"),
                            }
                        )
                    elif not best.get("alpha", {}).get("visible"):
                        errors.append({"code": "overlay_source_alpha_empty", "overlay": overlay.get("id")})
                    elif not best.get("visible"):
                        errors.append({"code": "overlay_pixels_not_detected", "overlay": overlay.get("id")})
                visual_evidence["ok"] = not any(
                    item["code"].startswith(("caption_pixel", "overlay_pixel", "overlay_source_alpha", "visual_baseline"))
                    for item in errors
                )
    else:
        visual_evidence["ok"] = True

    loudness = measure_loudness(final_path)
    audio_activity = measure_audio_activity(final_path, float(final["duration"] or 0))
    if not loudness["ok"]:
        errors.append({"code": "loudness_measurement_failed", "error": loudness.get("error")})
        if loudness.get("integrated_lufs") is None:
            errors.append({"code": "integrated_loudness_missing"})
        if loudness.get("true_peak_dbfs") is None:
            errors.append({"code": "true_peak_missing"})
    else:
        if not (-17.5 <= loudness["integrated_lufs"] <= -14.5):
            errors.append({"code": "integrated_loudness_out_of_range", "value": loudness["integrated_lufs"]})
        if loudness["true_peak_dbfs"] > -1.5:
            errors.append({"code": "true_peak_too_high", "value": loudness["true_peak_dbfs"]})
    if not audio_activity["ok"]:
        errors.append({"code": "audio_activity_measurement_failed"})
    elif audio_activity["active_ratio"] < 0.5:
        errors.append(
            {
                "code": "insufficient_active_audio",
                "active_ratio": audio_activity["active_ratio"],
                "active_seconds": audio_activity["active_seconds"],
            }
        )

    report = {
        "ok": not errors,
        "source_media": source,
        "final_media": final,
        "planned_duration": round(planned_duration, 3),
        "expected_duration": round(expected_duration, 3),
        "duration_reference": duration_reference,
        "caption_count": len(captions),
        "ass_dialogue_count": len(ass_dialogues),
        "overlay_count": len(overlays),
        "full_decode": decode_validation,
        "audit_gate": audit_validation,
        "rhythm_gate": rhythm_validation,
        "visual_direction_gate": visual_direction_validation,
        "semantic_reveal_gate": semantic_reveal_validation,
        "caption_structure_gate": caption_structure_validation,
        "render_log_validation": render_log_validation,
        "visual_evidence": visual_evidence,
        "style_decision": {
            "style_id": decision_style_id,
            "skin_id": decision_skin_id,
            "paint_tokens_sha256": decision_paint_sha256,
            "subtitle_font_preset": decision_subtitle_preset,
            "font_family_id": decision_font_family,
            "animation_font_file": decision_animation_font_file,
            "animation_layout": decision_animation_layout,
            "animation_panel_mode": decision_animation_panel_mode,
            "information_model": decision_information_model,
            "motion_model": decision_motion_model,
            "component_skin": decision_component_skin,
            "source": decision_source,
        },
        "caption_font_validation": caption_font_validation,
        "loudness": loudness,
        "audio_activity": audio_activity,
        "errors": errors,
        "warnings": warnings,
        "manual_checks_required": [
            "first_and_last_three_seconds",
            "cut_boundaries_plus_minus_300ms",
            "overlay_enter_readable_exit_frames",
            "semantic_reveal_before_trigger_after_rows",
            "semantic_card_meaning_and_anti_spoiler",
            "widest_caption_and_confirmed_terms",
            "caption_font_weight_and_embedding",
            "speech_fillers_zero",
            "caption_semantic_boundaries",
        ],
    }
    write_json(args.output, report)
    print(f"final QA: {'PASS' if report['ok'] else 'FAIL'} ({len(errors)} errors, {len(warnings)} warnings)")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
