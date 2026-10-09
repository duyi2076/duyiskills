#!/usr/bin/env python3
"""Create a bounded contact sheet from AIJianji chapter and state timestamps."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("plan must be a JSON object")
    return payload


def timestamps(plan: dict[str, Any], maximum: int) -> list[float]:
    anchors = plan.get("anchors")
    if not isinstance(anchors, list):
        raise ValueError("mapped plan must contain anchors")
    points: list[float] = []
    for anchor in anchors:
        if not isinstance(anchor, dict) or anchor.get("status") != "mapped":
            continue
        start = float(anchor["output_start"])
        end = float(anchor["output_end"])
        points.extend([start + 0.45, max(start + 0.45, end - 0.45)])
        config = anchor.get("config") or {}
        for state in config.get("states") or []:
            if not isinstance(state, dict) or state.get("action") not in {"enter", "update"}:
                continue
            points.append(start + float(state.get("reveal_at", 0)) + 0.34)
            for item in state.get("items") or []:
                if isinstance(item, dict):
                    points.append(start + float(item.get("reveal_at", 0)) + 0.3)
            for part in state.get("parts") or []:
                if isinstance(part, dict):
                    points.append(start + float(part.get("reveal_at", 0)) + 0.3)
    unique = sorted({round(max(0, point), 3) for point in points})
    if len(unique) <= maximum:
        return unique
    step = (len(unique) - 1) / (maximum - 1)
    return [unique[round(index * step)] for index in range(maximum)]


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--maximum", type=int, default=12)
    args = parser.parse_args()
    if args.maximum < 4 or args.maximum > 20:
        parser.error("--maximum must be between 4 and 20")
    points = timestamps(load_json(args.plan.resolve()), args.maximum)
    if not points:
        raise ValueError("mapped plan yielded no screenshot timestamps")
    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    columns = 4
    rows = math.ceil(len(points) / columns)
    with tempfile.TemporaryDirectory(prefix="composition-sheet-") as temporary:
        root = Path(temporary)
        for index, point in enumerate(points):
            run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{point:.3f}",
                    "-i",
                    str(args.video.resolve()),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=480:-2",
                    str(root / f"frame-{index:03d}.jpg"),
                ]
            )
        run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-framerate",
                "1",
                "-i",
                str(root / "frame-%03d.jpg"),
                "-frames:v",
                "1",
                "-vf",
                f"tile={columns}x{rows}:padding=8:margin=8:color=#111820",
                str(args.output.resolve()),
            ]
        )
    print(f"contact sheet: {len(points)} frames -> {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
