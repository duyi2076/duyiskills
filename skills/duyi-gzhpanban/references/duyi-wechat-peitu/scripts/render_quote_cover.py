#!/usr/bin/env python3
"""Render Du Yi quote-cover images with exact Chinese text."""

from __future__ import annotations

import argparse
import html
import subprocess
import tempfile
from pathlib import Path


CSS = r"""
:root {
  --ink: #1f2933;
  --blue: #17395a;
  --gold: #b88a45;
  --paper: #fbfaf6;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  background: #e8e8e8;
  font-family: "Songti SC", "STSong", "Noto Serif CJK SC", "Source Han Serif SC", serif;
}

.cover {
  width: 1200px;
  height: 630px;
  position: relative;
  overflow: hidden;
  background: #f8f8f8;
  color: #222;
}

.cover::before {
  content: "";
  position: absolute;
  inset: 0;
  opacity: 0;
  pointer-events: none;
  background:
    radial-gradient(circle at 18% 22%, rgba(0, 0, 0, 0.035), transparent 2px),
    radial-gradient(circle at 73% 64%, rgba(0, 0, 0, 0.026), transparent 2px),
    radial-gradient(circle at 44% 77%, rgba(184, 138, 69, 0.08), transparent 2px);
  background-size: 36px 36px, 44px 44px, 52px 52px;
}

.frame {
  position: absolute;
  inset: 48px;
  border: 3px solid currentColor;
}

.inner {
  position: absolute;
  inset: 90px 100px 82px;
}

.title {
  font-size: 58px;
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: 0.04em;
}

.top-line {
  margin-top: 34px;
  height: 2px;
  background: currentColor;
  opacity: 0.86;
}

.label {
  margin-top: 50px;
  font-size: 36px;
  color: rgba(31, 41, 51, 0.64);
  letter-spacing: 0.02em;
}

.quote {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 126px;
  font-size: 43px;
  font-weight: 700;
  line-height: 1.45;
  letter-spacing: 0.035em;
}

.bottom-line {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 72px;
  height: 2px;
  background: currentColor;
  opacity: 0.86;
}

.signature {
  position: absolute;
  right: 100px;
  bottom: 54px;
  font-family: "Courier New", "Songti SC", "STSong", serif;
  font-size: 28px;
  font-weight: 700;
  color: rgba(31, 41, 51, 0.66);
  letter-spacing: 0.02em;
}

.bw { color: #262626; }

.duyi {
  background: var(--paper);
  color: var(--blue);
}

.duyi .frame { border-color: var(--blue); }

.duyi .top-line,
.duyi .bottom-line {
  background: var(--gold);
  opacity: 0.8;
}

.duyi .label,
.duyi .signature {
  color: rgba(23, 57, 90, 0.58);
}

.paper {
  background: var(--paper);
  color: #203244;
}

.paper::before { opacity: 1; }

.paper .frame {
  border: 2px solid rgba(32, 50, 68, 0.88);
}

.paper .top-line,
.paper .bottom-line {
  height: 1px;
  background: rgba(184, 138, 69, 0.88);
}

.paper .title { color: var(--blue); }
.paper .quote { color: #24313f; }

.paper .label,
.paper .signature {
  color: rgba(32, 50, 68, 0.58);
}
"""


def break_quote(text: str) -> str:
    if "<br" in text:
        return text
    if len(text) <= 24:
        return html.escape(text)

    punctuation = "，。；：、"
    midpoint = len(text) // 2
    candidates = [i for i, ch in enumerate(text) if ch in punctuation and 10 <= i <= len(text) - 10]
    if candidates:
        split_at = min(candidates, key=lambda i: abs(i - midpoint)) + 1
    else:
        split_at = midpoint
    return f"{html.escape(text[:split_at])}<br />{html.escape(text[split_at:])}"


def render_html(title: str, label: str, quote: str, signature: str, variant: str) -> str:
    quote_html = break_quote(quote)
    return f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(title)}</title>
    <style>{CSS}</style>
  </head>
  <body>
    <section class="cover {html.escape(variant)}">
      <div class="frame"></div>
      <div class="inner">
        <div class="title">{html.escape(title)}</div>
        <div class="top-line"></div>
        <div class="label">{html.escape(label)}</div>
        <div class="quote">{quote_html}</div>
        <div class="bottom-line"></div>
      </div>
      <div class="signature">{html.escape(signature)}</div>
    </section>
  </body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a Du Yi quote-cover PNG.")
    parser.add_argument("--title", required=True, help="Cover title")
    parser.add_argument("--label", default="思考", help="Small category label")
    parser.add_argument("--quote", required=True, help="Core cover quote")
    parser.add_argument("--signature", default="杜一", help="Bottom-right signature")
    parser.add_argument("--variant", choices=["duyi", "bw", "paper"], default="duyi")
    parser.add_argument("--output", "-o", type=Path, required=True, help="PNG output path")
    parser.add_argument("--html-output", type=Path, help="Optional HTML output path")
    args = parser.parse_args()

    doc = render_html(args.title, args.label, args.quote, args.signature, args.variant)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    if args.html_output:
        args.html_output.parent.mkdir(parents=True, exist_ok=True)
        args.html_output.write_text(doc, encoding="utf-8")
        html_path = args.html_output
    else:
        tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".html", delete=False)
        with tmp:
            tmp.write(doc)
        html_path = Path(tmp.name)

    try:
        subprocess.run(
            [
                "npx",
                "playwright",
                "screenshot",
                "--viewport-size=1200,630",
                html_path.as_uri(),
                str(args.output),
            ],
            check=True,
        )
    finally:
        if not args.html_output:
            html_path.unlink(missing_ok=True)

    print(args.output)


if __name__ == "__main__":
    main()
