#!/usr/bin/env python3
"""Extract timestamped keyframes from a local video file."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def ffprobe_duration(video: Path) -> float:
    proc = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video),
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffprobe failed")
    try:
        return max(0.0, float(proc.stdout.strip()))
    except ValueError as exc:
        raise RuntimeError(f"Unparseable duration: {proc.stdout!r}") from exc


def time_label(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}-{minutes:02d}-{sec:02d}"


def timestamps_for(duration: float, max_frames: int) -> list[float]:
    if duration <= 0:
        return [0.0]
    if duration <= 12:
        interval = 2.0
    elif duration <= 60:
        interval = 3.0
    elif duration <= 180:
        interval = 5.0
    else:
        interval = max(6.0, duration / max_frames)
    count = min(max_frames, max(1, math.ceil(duration / interval)))
    if count == 1:
        return [min(duration * 0.5, max(0.0, duration - 0.1))]
    return [min(duration - 0.1, i * duration / count + 0.25) for i in range(count)]


def extract_frame(video: Path, out_path: Path, seconds: float) -> bool:
    proc = run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{seconds:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            "scale=720:-2",
            "-q:v",
            "3",
            str(out_path),
        ]
    )
    return proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract video frames")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--max-frames", type=int, default=28)
    args = parser.parse_args()

    frames_dir = args.out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "ok": False,
        "video_path": str(args.video),
        "duration": None,
        "frames": [],
        "error": "",
    }
    try:
        duration = ffprobe_duration(args.video)
        manifest["duration"] = duration
        for index, seconds in enumerate(timestamps_for(duration, args.max_frames)):
            out_path = frames_dir / f"{index:04d}-{time_label(seconds)}.jpg"
            if extract_frame(args.video, out_path, seconds):
                manifest["frames"].append({"index": index, "time": seconds, "path": str(out_path)})
        manifest["ok"] = bool(manifest["frames"])
        if not manifest["ok"]:
            manifest["error"] = "No frames were extracted."
    except Exception as exc:  # noqa: BLE001
        manifest["error"] = f"{exc.__class__.__name__}: {exc}"

    (frames_dir / "frames.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
