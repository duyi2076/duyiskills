#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from common import file_fingerprint, media_summary, run, write_json
from contracts import EXIT_ENVIRONMENT, PIPELINE_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a talking-head source without modifying it.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--decode",
        choices=("full", "sample", "none"),
        default="full",
        help="Decode both streams; sample checks the first 10 seconds",
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()

    source = Path(args.input)
    errors: list[str] = []
    if not source.is_file():
        errors.append(f"input_not_found: {source}")
        report = {"ok": False, "input": str(source), "errors": errors}
        write_json(args.output, report)
        return EXIT_ENVIRONMENT

    try:
        media = media_summary(source)
    except Exception as exc:  # ffprobe failure must be preserved in report
        report = {"ok": False, "input": str(source.resolve()), "errors": [f"ffprobe_failed: {exc}"]}
        write_json(args.output, report)
        return EXIT_ENVIRONMENT

    if not media["video"]:
        errors.append("missing_video_stream")
    if not media["audio"]:
        errors.append("missing_audio_stream")
    if not media["duration"] or media["duration"] <= 0:
        errors.append("invalid_duration")

    decode = {"mode": args.decode, "ok": args.decode == "none", "error": None}
    if not errors and args.decode != "none":
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-i",
            str(source.resolve()),
        ]
        if args.decode == "sample":
            command.extend(["-t", "10"])
        command.extend(
            [
                "-map",
                "0:v:0",
                "-map",
                "0:a:0",
                "-f",
                "null",
                "-",
            ]
        )
        try:
            run(command, capture=True, timeout=args.timeout)
            decode["ok"] = True
        except subprocess.TimeoutExpired:
            decode["error"] = f"decode_timeout_after_{args.timeout:g}s"
            errors.append("decode_timeout")
        except subprocess.CalledProcessError as exc:
            decode["error"] = (exc.stderr or str(exc)).strip()
            errors.append("decode_failed")

    report = {
        "schema_version": 2,
        "pipeline_version": PIPELINE_VERSION,
        "ok": not errors,
        "input": file_fingerprint(source),
        "media": media,
        "decode": decode,
        "errors": errors,
    }
    write_json(args.output, report)
    print(f"preflight: {'PASS' if report['ok'] else 'FAIL'} -> {args.output}")
    return 0 if report["ok"] else EXIT_ENVIRONMENT


if __name__ == "__main__":
    sys.exit(main())
