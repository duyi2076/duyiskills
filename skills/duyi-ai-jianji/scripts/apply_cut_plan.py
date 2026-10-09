#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from common import (
    atomic_output_path,
    atomic_write_text,
    load_json,
    media_summary,
    run,
    sha256_file,
    write_json,
)
from contracts import EXIT_BLOCKED, validate_audit_gate, validate_cut_plan


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract refined ranges, apply only quiet-zone audio fades, and concatenate."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument(
        "--audit-report",
        required=True,
        help="Approved audit_cut_plan.py report bound to this plan and source media",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--timeout", type=float, default=900.0, help="Timeout per ffmpeg command")
    args = parser.parse_args()

    source = Path(args.input).resolve()
    plan_path = Path(args.plan).resolve()
    output_dir = Path(args.output_dir).resolve()
    segments_dir = output_dir / "segments"
    output_dir.mkdir(parents=True, exist_ok=True)
    segments_dir.mkdir(parents=True, exist_ok=True)
    plan = validate_cut_plan(load_json(plan_path))
    source_sha256 = sha256_file(source)
    plan_sha256 = sha256_file(plan_path)
    audit_path = Path(args.audit_report).resolve()
    try:
        validate_audit_gate(
            load_json(audit_path),
            plan_sha256=plan_sha256,
            input_sha256=source_sha256,
        )
    except PermissionError as exc:
        print(f"blocked: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    except (OSError, ValueError) as exc:
        print(f"audit gate failed: {exc}", file=sys.stderr)
        return EXIT_BLOCKED

    summary = media_summary(source)
    if not summary["video"] or not summary["audio"]:
        raise SystemExit("Source must contain both video and audio streams")
    fps_fraction = summary["video"]["fps_fraction"] or "30"

    manifest_segments = []
    for index, segment in enumerate(plan.get("segments", []), start=1):
        start = float(segment["source_start"])
        end = float(segment["source_end"])
        duration = end - start
        if duration <= 0:
            raise SystemExit(f"Invalid segment duration: {segment}")
        boundary = segment.get("boundary_analysis") or {}
        if boundary.get("entry_clean") is not True or boundary.get("tail_clear") is not True:
            print(f"blocked: segment {segment.get('id', index)} lacks safe acoustic boundaries", file=sys.stderr)
            return EXIT_BLOCKED
        fade_in = min(0.012, max(0.0, float(boundary.get("fade_in_ms", 0.0)) / 1000.0))
        fade_out = min(0.012, max(0.0, float(boundary.get("fade_out_ms", 0.0)) / 1000.0))
        fade_out_start = max(0.0, duration - fade_out)
        segment_path = segments_dir / f"segment-{index:03d}.mp4"
        audio_filters = [
            f"atrim=start={start:.3f}:end={end:.3f}",
            "asetpts=PTS-STARTPTS",
        ]
        if fade_in > 0:
            audio_filters.append(f"afade=t=in:st=0:d={fade_in:.3f}")
        if fade_out > 0:
            audio_filters.append(
                f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f}"
            )
        filter_complex = (
            f"[0:v:0]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v];"
            f"[0:a:0]{','.join(audio_filters)}[a]"
        )
        with atomic_output_path(segment_path) as temporary_segment:
            run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(source),
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    "[v]",
                    "-map",
                    "[a]",
                    "-t",
                    f"{duration:.3f}",
                    "-r",
                    fps_fraction,
                    "-c:v",
                    "libx264",
                    "-preset",
                    args.preset,
                    "-crf",
                    str(args.crf),
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-ar",
                    str(summary["audio"]["sample_rate"] or 44100),
                    "-avoid_negative_ts",
                    "make_zero",
                    str(temporary_segment),
                ],
                timeout=args.timeout,
            )
        actual = media_summary(segment_path)["duration"]
        manifest_segments.append(
            {
                "id": segment.get("id", f"keep-{index:03d}"),
                "source_start": start,
                "source_end": end,
                "planned_duration": round(duration, 3),
                "actual_duration": actual,
                "fade_in_ms": round(fade_in * 1000.0, 3),
                "fade_out_ms": round(fade_out * 1000.0, 3),
                "entry_clean": True,
                "tail_clear": True,
                "path": str(segment_path),
            }
        )

    concat_path = output_dir / "concat.txt"
    concat_lines = []
    for segment in manifest_segments:
        escaped = segment["path"].replace("'", "'\\''")
        concat_lines.append(f"file '{escaped}'")
    atomic_write_text(concat_path, "\n".join(concat_lines) + "\n")

    cut_path = output_dir / "cut.mp4"
    with atomic_output_path(cut_path) as temporary_cut:
        run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_path),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(temporary_cut),
            ],
            timeout=args.timeout,
        )
    manifest = {
        "schema_version": 2,
        "source": str(source),
        "source_sha256": source_sha256,
        "plan": str(plan_path),
        "plan_sha256": plan_sha256,
        "audit_report": str(audit_path),
        "audit_report_sha256": sha256_file(audit_path),
        "audit_bypassed": False,
        "segments": manifest_segments,
        "output": str(cut_path),
        "output_sha256": sha256_file(cut_path),
        "output_media": media_summary(cut_path),
        "concat_command": f"ffmpeg -f concat -safe 0 -i {shlex.quote(str(concat_path))} -c copy {shlex.quote(str(cut_path))}",
    }
    write_json(output_dir / "cut-manifest.json", manifest)
    print(f"cut complete: {cut_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
