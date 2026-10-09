#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def parse_size(raw: str) -> tuple[int, int]:
    try:
        width, height = raw.lower().split("x", 1)
        return int(width), int(height)
    except Exception as exc:
        raise argparse.ArgumentTypeError("Use WIDTHxHEIGHT, for example 1280x720") from exc


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def paste_shadow(
    canvas: Image.Image,
    xy: tuple[int, int],
    size: tuple[int, int],
    radius: int,
    blur: int = 24,
    offset: tuple[int, int] = (0, 18),
    alpha: int = 76,
) -> None:
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    mask = rounded_mask(size, radius).filter(ImageFilter.GaussianBlur(blur))
    mask = mask.point(lambda value: int(value * alpha / 255))
    shadow.putalpha(mask)
    canvas.alpha_composite(shadow, (xy[0] + offset[0], xy[1] + offset[1]))


def make_background(width: int, height: int, seed: int = 12) -> Image.Image:
    bg = Image.new("RGB", (width, height))
    pix = bg.load()
    colors = [
        (255, 139, 113),
        (85, 166, 224),
        (83, 205, 170),
        (207, 78, 165),
    ]

    for y in range(height):
        fy = y / (height - 1)
        for x in range(width):
            fx = x / (width - 1)
            weights = [
                max(0, 1 - math.hypot(fx - 0.05, fy - 0.05) * 1.2) + 0.15,
                max(0, 1 - math.hypot(fx - 0.95, fy - 0.12) * 1.15) + 0.15,
                max(0, 1 - math.hypot(fx - 0.86, fy - 0.92) * 1.08) + 0.15,
                max(0, 1 - math.hypot(fx - 0.15, fy - 1.04) * 1.0) + 0.15,
            ]
            total = sum(weights)
            pix[x, y] = tuple(
                int(sum(color[channel] * weight for color, weight in zip(colors, weights)) / total)
                for channel in range(3)
            )

    bg_rgba = bg.convert("RGBA")

    bands = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(bands)
    draw.polygon(
        [(-120, 84), (430, -80), (width + 160, height * 0.74), (width * 0.88, height + 40)],
        fill=(255, 255, 255, 34),
    )
    draw.polygon(
        [(130, height + 40), (650, height * 0.5), (width + 170, height), (width + 10, height + 130)],
        fill=(41, 98, 165, 35),
    )
    draw.polygon(
        [(-220, height * 0.75), (280, 190), (890, height + 60), (420, height + 140)],
        fill=(255, 185, 126, 36),
    )
    bg_rgba = Image.alpha_composite(bg_rgba, bands.filter(ImageFilter.GaussianBlur(36)))

    random.seed(seed)
    grain = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gp = grain.load()
    for y in range(height):
        for x in range(width):
            noise = random.randint(-7, 7)
            if noise >= 0:
                gp[x, y] = (255, 255, 255, min(9, noise))
            else:
                gp[x, y] = (0, 0, 0, min(7, -noise))
    return Image.alpha_composite(bg_rgba, grain)


def screenshot_crop(src: Image.Image, target_size: tuple[int, int], focus: float) -> Image.Image:
    target_w, target_h = target_size
    src_w, src_h = src.size
    aspect = target_w / target_h

    crop_h = min(src_h, int(src_w / aspect))
    if crop_h == src_h:
        crop_w = min(src_w, int(src_h * aspect))
        x0 = max(0, (src_w - crop_w) // 2)
        crop = src.crop((x0, 0, x0 + crop_w, src_h))
    else:
        y0 = int(src_h * focus)
        y0 = max(0, min(y0, src_h - crop_h))
        crop = src.crop((0, y0, src_w, y0 + crop_h))

    return crop.resize(target_size, Image.Resampling.LANCZOS).convert("RGBA")


def screenshot_fit(src: Image.Image, target_size: tuple[int, int]) -> Image.Image:
    target_w, target_h = target_size
    src_w, src_h = src.size
    scale = min(target_w / src_w, target_h / src_h)
    resized = src.resize((int(src_w * scale), int(src_h * scale)), Image.Resampling.LANCZOS).convert("RGBA")
    page = Image.new("RGBA", target_size, (250, 250, 249, 255))
    page.alpha_composite(resized, ((target_w - resized.width) // 2, (target_h - resized.height) // 2))
    return page


def render_light_shell(input_path: Path, output_path: Path, canvas_size: tuple[int, int]) -> None:
    width, height = canvas_size
    bg = make_background(width, height, seed=21)

    src = Image.open(input_path).convert("RGBA")
    white = Image.new("RGBA", src.size, (255, 255, 255, 255))
    white.alpha_composite(src)
    src_rgb = white.convert("RGB")

    max_w = int(width * 0.936)
    max_h = int(height * 0.84)
    src_w, src_h = src_rgb.size
    scale = min(max_w / src_w, max_h / src_h)
    shot = src_rgb.resize((int(src_w * scale), int(src_h * scale)), Image.Resampling.LANCZOS).convert("RGBA")

    radius = max(18, int(width * 0.016))
    x = (width - shot.width) // 2
    y = (height - shot.height) // 2

    shot.putalpha(rounded_mask(shot.size, radius))
    bg.alpha_composite(shot, (x, y))

    border = Image.new("RGBA", shot.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(border)
    draw.rounded_rectangle((1, 1, shot.width - 2, shot.height - 2), radius=radius - 1, outline=(255, 255, 255, 115), width=2)
    bg.alpha_composite(border, (x, y))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, quality=96)


def render_card(input_path: Path, output_path: Path, canvas_size: tuple[int, int], focus: float, fit: str) -> None:
    width, height = canvas_size
    bg = make_background(width, height)

    window_margin_x = int(width * 0.075)
    window_margin_y = int(height * 0.08)
    wx, wy = window_margin_x, window_margin_y
    ww, wh = width - 2 * window_margin_x, height - int(height * 0.16)
    radius = max(18, int(width * 0.019))

    paste_shadow(bg, (wx, wy), (ww, wh), radius, blur=30, offset=(0, int(height * 0.03)), alpha=86)

    window = Image.new("RGBA", (ww, wh), (250, 250, 249, 255))
    draw = ImageDraw.Draw(window)
    draw.rounded_rectangle(
        (0, 0, ww - 1, wh - 1),
        radius=radius,
        fill=(250, 250, 249, 255),
        outline=(224, 228, 232, 230),
        width=1,
    )

    title_h = max(48, int(height * 0.08))
    draw.rounded_rectangle((0, 0, ww - 1, title_h + 18), radius=radius, fill=(246, 247, 248, 255))
    draw.rectangle((0, title_h, ww, title_h + 20), fill=(246, 247, 248, 255))
    draw.line((0, title_h, ww, title_h), fill=(229, 232, 235, 255), width=1)

    dot_y = int(title_h * 0.36)
    for i, color in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        x = 22 + i * 24
        draw.ellipse((x, dot_y, x + 12, dot_y + 12), fill=color)

    addr_x, addr_y = 132, max(12, int(title_h * 0.24))
    addr_w, addr_h = int(ww * 0.59), max(24, int(title_h * 0.48))
    draw.rounded_rectangle((addr_x, addr_y, addr_x + addr_w, addr_y + addr_h), radius=12, fill=(235, 238, 241, 255))
    for i in range(3):
        bx = ww - 154 + i * 38
        draw.rounded_rectangle((bx, addr_y + 3, bx + 28, addr_y + addr_h - 4), radius=8, fill=(235, 238, 241, 255))

    src = Image.open(input_path).convert("RGBA")
    white = Image.new("RGBA", src.size, (255, 255, 255, 255))
    white.alpha_composite(src)
    src_rgb = white.convert("RGB")

    content_margin = max(18, int(width * 0.019))
    cx, cy = content_margin, title_h + 18
    cw, ch = ww - content_margin * 2, wh - title_h - 38
    if fit == "contain":
        shot = screenshot_fit(src_rgb, (cw, ch))
    else:
        shot = screenshot_crop(src_rgb, (cw, ch), focus=focus)
    shot.putalpha(rounded_mask((cw, ch), 14))
    window.alpha_composite(shot, (cx, cy))
    draw.rounded_rectangle((cx, cy, cx + cw - 1, cy + ch - 1), radius=14, outline=(230, 233, 237, 255), width=1)

    shine = Image.new("RGBA", (ww, wh), (0, 0, 0, 0))
    shine_draw = ImageDraw.Draw(shine)
    shine_draw.rounded_rectangle((2, 2, ww - 3, wh - 3), radius=radius - 1, outline=(255, 255, 255, 90), width=2)
    window = Image.alpha_composite(window, shine)
    window.putalpha(rounded_mask((ww, wh), radius))
    bg.alpha_composite(window, (wx, wy))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    bg.convert("RGB").save(output_path, quality=96)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a screenshot into a polished desktop-window article image.")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--size", type=parse_size, default=(1280, 720))
    parser.add_argument("--focus", type=float, default=0.23, help="Vertical focus from 0.0 to 1.0 for tall screenshots.")
    parser.add_argument("--fit", choices=("cover", "contain"), default="cover")
    parser.add_argument("--shell", choices=("browser", "light"), default="browser")
    args = parser.parse_args()

    if args.shell == "light":
        render_light_shell(args.input, args.output, args.size)
    else:
        render_card(args.input, args.output, args.size, max(0.0, min(1.0, args.focus)), args.fit)
    print(args.output)


if __name__ == "__main__":
    main()
