#!/usr/bin/env python3
"""Create before/trigger/after evidence rows for every audited semantic reveal."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from common import load_json


SKILL_ROOT = Path(__file__).resolve().parents[1]
REGULAR_FONT = SKILL_ROOT / "assets" / "composition" / "fonts" / "NotoSansCJKsc-Regular.otf"
BOLD_FONT = SKILL_ROOT / "assets" / "composition" / "fonts" / "NotoSansCJKsc-Bold.otf"
FRAME_WIDTH = 480
FRAME_HEIGHT = 270
GAP = 10
ROW_TEXT_HEIGHT = 156


def event_points(event: dict[str, Any]) -> list[tuple[str, float]]:
    trigger = float(event["trigger_time"])
    visible = float(event["fully_visible_time"])
    chapter_start = float(event.get("chapter_start", 0.0))
    return [
        ("出现前", max(chapter_start, trigger - 0.18)),
        ("触发中", trigger + max(0.04, (visible - trigger) / 2)),
        ("出现后", visible + 0.12),
    ]


def run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for character in text:
        candidate = current + character
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > width:
            lines.append(current)
            current = character
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    audit = load_json(args.audit.resolve())
    if audit.get("ok") is not True:
        raise ValueError("semantic reveal audit must pass before evidence rendering")
    events = audit.get("mapped_events")
    if not isinstance(events, list) or not events:
        raise ValueError("semantic reveal audit contains no mapped events")
    if len(events) > 40:
        raise ValueError("semantic reveal evidence is intentionally bounded to 40 events")
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    regular = ImageFont.truetype(str(REGULAR_FONT), 24)
    small = ImageFont.truetype(str(REGULAR_FONT), 19)
    bold = ImageFont.truetype(str(BOLD_FONT), 26)
    total_width = FRAME_WIDTH * 3 + GAP * 4
    row_height = FRAME_HEIGHT + ROW_TEXT_HEIGHT + GAP
    sheet = Image.new("RGB", (total_width, row_height * len(events) + GAP), "#101820")
    draw = ImageDraw.Draw(sheet)

    with tempfile.TemporaryDirectory(prefix="duyi-semantic-reveal-") as folder:
        temporary = Path(folder)
        for event_index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            row_top = GAP + event_index * row_height
            for frame_index, (label, timestamp) in enumerate(event_points(event)):
                frame_path = temporary / f"{event_index:03d}-{frame_index}.jpg"
                run(
                    [
                        "ffmpeg",
                        "-y",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-ss",
                        f"{timestamp:.3f}",
                        "-i",
                        str(args.video.resolve()),
                        "-frames:v",
                        "1",
                        "-vf",
                        f"scale={FRAME_WIDTH}:{FRAME_HEIGHT}:force_original_aspect_ratio=decrease,"
                        f"pad={FRAME_WIDTH}:{FRAME_HEIGHT}:(ow-iw)/2:(oh-ih)/2:#05090d",
                        str(frame_path),
                    ]
                )
                frame = Image.open(frame_path).convert("RGB")
                left = GAP + frame_index * (FRAME_WIDTH + GAP)
                sheet.paste(frame, (left, row_top))
                draw.rounded_rectangle(
                    (left + 8, row_top + 8, left + 112, row_top + 46),
                    radius=8,
                    fill="#0A141BD9",
                )
                draw.text((left + 18, row_top + 12), label, font=small, fill="#F3F5F7")
                draw.text(
                    (left + 126, row_top + 13),
                    f"{timestamp:.2f}s",
                    font=small,
                    fill="#A7ADB4",
                )

            text_top = row_top + FRAME_HEIGHT + 12
            visual_id = str(event.get("visual_id") or "")
            role = str(event.get("role") or "")
            card_text = str(event.get("card_text") or "")
            spoken = str(event.get("spoken_excerpt") or "")
            draw.text(
                (GAP + 8, text_top),
                f"{event_index + 1:02d}  {visual_id} · {role}",
                font=small,
                fill="#20E5A0",
            )
            draw.text((GAP + 8, text_top + 32), f"卡片：{card_text}", font=bold, fill="#F3F5F7")
            spoken_lines = wrap_text(draw, f"原话：{spoken}", regular, total_width - 34)[:2]
            for line_index, line in enumerate(spoken_lines):
                draw.text(
                    (GAP + 8, text_top + 70 + line_index * 31),
                    line,
                    font=regular,
                    fill="#C9CDD1",
                )
            draw.line(
                (GAP, row_top + row_height - 1, total_width - GAP, row_top + row_height - 1),
                fill="#26333D",
                width=1,
            )

    sheet.save(output, quality=90, optimize=True)
    print(f"semantic reveal sheet: {len(events)} events -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
