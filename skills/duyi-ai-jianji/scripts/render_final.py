#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from common import atomic_output_path, load_json, media_summary, run


FPS_PATTERN = re.compile(r"^(?:\d+(?:\.\d+)?|\d+/\d+)$")


def finite_number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def validate_fps(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not FPS_PATTERN.fullmatch(value):
        raise ValueError("fps must be a positive number or rational such as 30000/1001")
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = finite_number(denominator, "fps")
        if denominator_value == 0:
            raise ValueError("fps rational denominator must not be zero")
        fps = finite_number(numerator, "fps") / denominator_value
    else:
        fps = finite_number(value, "fps")
    if fps <= 0:
        raise ValueError("fps must be greater than 0")
    return value


def validate_overlay_timing(overlay: dict[str, object], index: int, base_duration: float) -> tuple[float, float, float, float]:
    prefix = f"overlay {index}"
    start = finite_number(overlay.get("start"), f"{prefix}.start")
    end_value = overlay.get("end")
    has_duration = "duration" in overlay
    if has_duration:
        duration = finite_number(overlay["duration"], f"{prefix}.duration")
        if duration <= 0 or duration > base_duration:
            raise ValueError(f"{prefix}.duration must be greater than 0 and within the base duration")
    elif end_value is None:
        duration = finite_number(5.0, f"{prefix}.duration")
    else:
        duration = 0.0
    end = finite_number(end_value, f"{prefix}.end") if end_value is not None else start + duration
    x = finite_number(overlay.get("x", 0), f"{prefix}.x")
    y = finite_number(overlay.get("y", 0), f"{prefix}.y")
    if start < 0 or start > base_duration:
        raise ValueError(f"{prefix}.start must be within the base duration")
    if end <= start or end > base_duration:
        raise ValueError(f"{prefix}.end must be after start and within the base duration")
    # Permit a partially off-canvas overlay, but reject values that cannot be meaningful coordinates.
    if abs(x) > 2_147_483_647 or abs(y) > 2_147_483_647:
        raise ValueError(f"{prefix}.x and {prefix}.y are outside the supported coordinate range")
    return start, end, x, y


def escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")


def analyze_loudness(
    path: Path,
    target_i: float,
    target_tp: float,
    target_lra: float,
    *,
    timeout: float,
) -> dict[str, str]:
    completed = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-af",
            f"loudnorm=I={target_i}:TP={target_tp}:LRA={target_lra}:dual_mono=true:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture=True,
        timeout=timeout,
    )
    matches = re.findall(r"\{\s*\"input_i\".*?\}", completed.stderr, flags=re.DOTALL)
    if not matches:
        raise RuntimeError("loudnorm analysis did not return JSON")
    return json.loads(matches[-1])


def embedded_font_attachments(ass_path: Path) -> list[str]:
    """Return valid ASS attachment names; reject truncated or empty font payloads."""
    text = ass_path.read_text(encoding="utf-8", errors="strict")
    match = re.search(r"(?ms)^\[Fonts\]\s*$([\s\S]*?)(?=^\[[^\]]+\]\s*$|\Z)", text)
    if not match:
        return []
    section = match.group(1)
    matches = list(
        re.finditer(
            r"(?ms)^fontname:\s*(?P<name>[^\r\n]+)\s*$\s*(?P<data>.*?)(?=^fontname:|\Z)",
            section,
        )
    )
    attachments: list[str] = []
    for item in matches:
        name = item.group("name").strip()
        payload = re.sub(r"\s+", "", item.group("data"))
        if not name or len(payload) < 128:
            raise ValueError(f"embedded ASS font attachment is missing or truncated: {name or '<unnamed>'}")
        attachments.append(name)
    if not attachments:
        raise ValueError("ASS contains a [Fonts] section but no valid font attachment")
    return attachments


def filtered_fonts_dir(source: Path, destination: Path) -> int:
    extensions = {".otf", ".ttf", ".ttc", ".woff", ".woff2"}
    count = 0
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        if item.is_file() and item.suffix.lower() in extensions:
            target = destination / item.name
            try:
                os.symlink(item.resolve(), target)
            except OSError:
                shutil.copy2(item, target)
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Composite alpha overlays, burn ASS captions last, normalize loudness.")
    parser.add_argument("--base", required=True)
    parser.add_argument("--overlays", required=True, help="JSON file with an overlays array; may be empty")
    parser.add_argument("--captions", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--lufs", type=float, default=-16.0)
    parser.add_argument(
        "--true-peak",
        type=float,
        default=-2.0,
        help="Render target; -2.0 dBTP leaves headroom for the -1.5 dBTP acceptance ceiling",
    )
    parser.add_argument("--lra", type=float, default=11.0)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--fps", help="Explicit output frame rate, e.g. 28 or 30000/1001")
    parser.add_argument("--width", type=int, help="Delivery width; must be provided with --height")
    parser.add_argument("--height", type=int, help="Delivery height; must be provided with --width")
    parser.add_argument("--timeout", type=float, default=1800.0, help="Timeout per ffmpeg pass")
    parser.add_argument(
        "--allow-system-fonts",
        action="store_true",
        help="Allow captions without embedded ASS fonts; normal AIJianji runs must not use this",
    )
    parser.add_argument("--fonts-dir", help="Fallback font source used only with --allow-system-fonts")
    args = parser.parse_args()

    try:
        fps = validate_fps(args.fps)
    except ValueError as error:
        parser.error(str(error))

    base = Path(args.base).resolve()
    captions = Path(args.captions).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    for required in (base, captions, Path(args.overlays).resolve()):
        if not required.is_file():
            parser.error(f"required file not found: {required}")
    attachments = embedded_font_attachments(captions)
    if not attachments and not args.allow_system_fonts:
        parser.error(
            "captions ASS has no embedded font; rebuild with build_ass.py --embed-fonts "
            "or explicitly opt into --allow-system-fonts"
        )
    overlays_payload = load_json(args.overlays)
    overlays = (
        overlays_payload
        if isinstance(overlays_payload, list)
        else overlays_payload.get("overlays", [])
        if isinstance(overlays_payload, dict)
        else None
    )
    if not isinstance(overlays, list):
        parser.error("--overlays must contain an array or an object with an overlays array")
    loudness = analyze_loudness(
        base,
        args.lufs,
        args.true_peak,
        args.lra,
        timeout=args.timeout,
    )
    loudnorm_filter = (
        f"loudnorm=I={args.lufs}:TP={args.true_peak}:LRA={args.lra}:"
        f"measured_I={loudness['input_i']}:measured_TP={loudness['input_tp']}:"
        f"measured_LRA={loudness['input_lra']}:measured_thresh={loudness['input_thresh']}:"
        f"offset={loudness['target_offset']}:linear=true:dual_mono=true"
    )
    base_media = media_summary(base)
    base_duration = base_media["duration"]
    audio_sample_rate = base_media["audio"]["sample_rate"] if base_media.get("audio") else 44100
    if (args.width is None) != (args.height is None):
        parser.error("--width and --height must be provided together")
    base_video = base_media.get("video") or {}
    delivery_width = int(args.width or base_video.get("width") or 0)
    delivery_height = int(args.height or base_video.get("height") or 0)
    if delivery_width <= 0 or delivery_height <= 0:
        parser.error("delivery dimensions must be positive")

    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(base)]
    for overlay in overlays:
        if not isinstance(overlay, dict):
            parser.error("every overlay must be an object")
        overlay_path = overlay.get("path")
        if not isinstance(overlay_path, str) or not overlay_path.strip():
            parser.error("overlay.path must be a non-empty path")
        command.extend(["-i", str(Path(overlay_path).resolve())])

    filters: list[str] = []
    current_video = "[0:v]"
    if (
        int(base_video.get("width") or 0),
        int(base_video.get("height") or 0),
    ) != (delivery_width, delivery_height):
        filters.append(
            f"[0:v]scale={delivery_width}:{delivery_height}:flags=lanczos,setsar=1[basev]"
        )
        current_video = "[basev]"
    for index, overlay in enumerate(overlays, start=1):
        try:
            start, end, x, y = validate_overlay_timing(overlay, index, float(base_duration))
        except ValueError as error:
            parser.error(str(error))
        overlay_path = str(overlay["path"])
        # Overlays are authored on the template canvas (2560x1440); scale them
        # onto the base frame when the base uses a smaller delivery resolution.
        overlay_media = media_summary(Path(overlay_path).resolve())
        overlay_video = overlay_media.get("video") or {}
        scale_filter = ""
        if overlay_video.get("width") and (
            overlay_video["width"] != delivery_width
            or overlay_video["height"] != delivery_height
        ):
            scale_filter = f"scale={delivery_width}:{delivery_height},"
        filters.append(f"[{index}:v]{scale_filter}setpts=PTS-STARTPTS+{start:.3f}/TB[ov{index}]")
        out_label = f"[v{index}]"
        filters.append(
            f"{current_video}[ov{index}]overlay=x={x}:y={y}:enable='between(t,{start:.3f},{end:.3f})':eof_action=pass{out_label}"
        )
        current_video = out_label

    ass_path = escape_filter_path(captions)
    with contextlib.ExitStack() as stack:
        fonts_option = ""
        if not attachments:
            bundled_fonts = (
                Path(args.fonts_dir).resolve()
                if args.fonts_dir
                else Path(__file__).resolve().parents[1] / "assets" / "composition" / "fonts"
            )
            if not bundled_fonts.is_dir():
                parser.error(f"fallback fonts directory not found: {bundled_fonts}")
            temporary_fonts_root = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="duyi-fonts-")))
            if filtered_fonts_dir(bundled_fonts, temporary_fonts_root) == 0:
                parser.error(f"fallback fonts directory has no supported font files: {bundled_fonts}")
            fonts_option = f":fontsdir='{escape_filter_path(temporary_fonts_root)}'"

        filters.append(f"{current_video}subtitles=filename='{ass_path}'{fonts_option}[vout]")
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-map",
                "0:a:0",
                "-af",
                loudnorm_filter,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                str(args.crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                str(audio_sample_rate or 44100),
                "-movflags",
                "+faststart",
                "-shortest",
                "-t",
                f"{base_duration:.6f}",
            ]
        )
        if fps:
            command.extend(["-r", fps])
        with atomic_output_path(output) as temporary_output:
            run([*command, str(temporary_output)], timeout=args.timeout)
    print(f"final render -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
