#!/usr/bin/env python3
"""把最终拆解报告与本地证据渲染成一个可本地打开的精美 HTML 页面。

呈现层，不是分析权威源：本脚本把最终 Markdown 报告与本地证据渲染成
一个供人在浏览器里阅读的 HTML 页面，默认写到 <run_dir>/拆解报告.html。

两种渲染模式：
- 金字塔版：<run_dir>/report-web.json 存在时启用。agent 写最终报告时同步产出
  这份结构化 JSON（层级定位、营销点、三个带走点、填空模板、评论选题、批判），
  页面按「结论先行、层层论证」组织。
- 基础版：JSON 缺失时降级为「Hero + Markdown 正文 + 证据面板」。

用法：
    python3 render_report_html.py \
      --run-dir /path/to/run \
      --final-report /path/to/完整拆解报告.md [--output /path/to/out.html]
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode

SCREENSHOT_CANDIDATES = (
    "source/对标数据截图.png",
    "source/对标数据截图.jpg",
    "source/对标数据截图.jpeg",
)
VIDEO_CANDIDATES = ("source/video.mp4", "source/video.mov", "source/video.webm")

# 四层创作者价值阶梯。报告只判断这条视频呈现出来的层级，
# 不把层级标签扩展成对作者整个人的定性。
CREATOR_LADDER = (
    ("L4", "哲学立旗型", "提炼世界观、抢概念定义权，拥有心智垄断"),
    ("L3", "同频旅程型", "公开构建、晒真金白银的试错，靠人格建立信任"),
    ("L2", "分析情报型", "客观实测、算账本、戳破泡沫，行业把关人"),
    ("L1", "实操教程型", "教功能、点按钮、给模板，替代性极高，最容易有流量也最容易贬值"),
)

SEG_KINDS = ("hook", "setup", "method", "turn", "cta")
SEG_KIND_LABELS = {"hook": "钩子", "setup": "铺垫", "method": "方法", "turn": "转场", "cta": "收束"}
BLANK_MARKS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"

BOUNDARY_TEXT = (
    "证据边界：公开互动数据与评论是抓取时的页面快照，不代表后台真实数据；"
    "评论只能作为需求线索，不能证明付费意愿；事实性主张仍需回到原始出处核验。"
)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def format_count(value) -> str:
    try:
        num = int(value or 0)
    except (TypeError, ValueError):
        return "0"
    if num >= 10000:
        text = f"{num / 10000:.1f}".rstrip("0").rstrip(".")
        return f"{text}万"
    return str(num)


def pick_comments(comments: list, limit: int = 20) -> list:
    scored = [
        (int(c.get("likes") or 0), c)
        for c in comments
        if len((c.get("text") or "").strip()) >= 2
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    return [c for _, c in scored[:limit]]


def split_report(text: str) -> tuple[str, str]:
    """剥离报告首个一级标题作为页面大标题，其余作为正文。"""
    lines = text.splitlines()
    title = ""
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            title = match.group(1).strip()
            del lines[index]
        break
    return title, "\n".join(lines).strip()


def strip_theory_annotations(text: str) -> str:
    """Theory is a Markdown analysis aid, not part of the HTML reading layer."""
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*(理论视角|理论依据|解释视角)\s*[：:]", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def find_first(run_dir: Path, candidates: tuple[str, ...]) -> str:
    for relative in candidates:
        if (run_dir / relative).is_file():
            return relative
    return ""


def collect_frames(run_dir: Path) -> list[dict]:
    manifest = read_json(run_dir / "frames" / "frames.json")
    frames = []
    for item in manifest.get("frames") or []:
        name = Path(str(item.get("path") or "")).name
        if not name or not (run_dir / "frames" / name).is_file():
            continue
        seconds = float(item.get("time") or 0)
        stamp = f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"
        frames.append({"src": f"frames/{name}", "name": name, "stamp": stamp})
    if frames:
        return frames
    # frames.json 缺失时退化为直接扫目录，呈现层不应因清单缺失而空。
    for path in sorted((run_dir / "frames").glob("*.jpg")) if (run_dir / "frames").is_dir() else []:
        if re.match(r"^\d{4}-", path.name):
            frames.append({"src": f"frames/{path.name}", "name": path.name, "stamp": ""})
    return frames


def read_transcript_rows(run_dir: Path, fallback_text: str) -> list[dict]:
    """优先用带时间戳的 transcript/transcript.md 分段，缺失时退回整段文本。"""
    path = run_dir / "transcript" / "transcript.md"
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\[(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\]\s*(.+)$", line.strip())
            if match:
                start = float(match.group(1))
                stamp = f"{int(start // 60)}:{int(start % 60):02d}"
                rows.append({"stamp": stamp, "text": match.group(3).strip()})
    if rows:
        return rows
    return [{"stamp": "", "text": fallback_text}] if fallback_text.strip() else []


def hero_meta(metadata: dict, report_title: str, run_dir: Path) -> dict:
    raw_title = (metadata.get("title") or "").strip()
    clean_title = re.sub(r"#\S+", "", raw_title).strip(" -—、,，")
    page_title = report_title or clean_title or run_dir.name
    author = (metadata.get("author") or "").strip() or "未知作者"
    meta_parts = [f"作者 {esc(author)}"]
    published = (metadata.get("publishedAt") or "").strip()
    if published:
        meta_parts.append(f"发布于 {esc(published)}")
    if clean_title and clean_title != page_title:
        short = clean_title if len(clean_title) <= 36 else clean_title[:36] + "…"
        meta_parts.append(f"原标题：{esc(short)}")
    return {
        "page_title": page_title,
        "author": author,
        "published": published,
        "collected": (metadata.get("collectedAt") or "")[:10],
        "url": (metadata.get("url") or metadata.get("input") or "").strip(),
        "meta_line": " · ".join(meta_parts),
    }


BASE_CSS = """
:root {
  --bg: #f6f3ed;
  --surface: #fffdf8;
  --ink: #2a251d;
  --ink-soft: #5d564a;
  --ink-faint: #8d8578;
  --line: #e6dfd2;
  --accent: #c0392b;
  --accent-deep: #9c2b20;
  --accent-soft: #faeceb;
  --hero-bg: #221d16;
  --hero-ink: #f4efe4;
  --amber: #c98a2b;
  --blue: #2e5f8a;
  --blue-soft: #eef3f8;
  --gray: #8d8578;
  --green: #3d7a52;
  --radius: 14px;
  --serif: "Noto Serif SC", "Songti SC", "STSong", "SimSun", serif;
  --sans: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB",
    "Microsoft YaHei", "Segoe UI", Roboto, sans-serif;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0; background: var(--bg); color: var(--ink);
  font-family: var(--sans); font-size: 16px; line-height: 1.8;
  -webkit-font-smoothing: antialiased;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

.hero { background: var(--hero-bg); color: var(--hero-ink); padding: 56px 24px 64px; }
.hero-inner { max-width: 1080px; margin: 0 auto; }
.topline {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 42px; font-size: 13px; color: #8f8674; letter-spacing: .08em;
}
.topline .brand { letter-spacing: .3em; color: #d8b98a; }
.hero h1 {
  margin: 0 0 22px; font-family: var(--serif);
  font-size: clamp(30px, 4.6vw, 50px); line-height: 1.35; font-weight: 700;
}
.verdict {
  margin: 0 0 36px; max-width: 760px;
  font-family: var(--serif);
  font-size: clamp(18px, 2.2vw, 24px); line-height: 1.75; color: #e8e1d2;
}
.verdict em { font-style: normal; color: #e0b45e; }
.hero .meta { margin: 0 0 26px; color: #b7ae9d; font-size: 15px; }
.statrow, .badges { display: flex; flex-wrap: wrap; gap: 12px; align-items: stretch; margin-bottom: 26px; }
.stat, .badge {
  min-width: 118px; padding: 12px 22px 10px;
  border: 1px solid rgba(244,239,228,.16);
  border-radius: 12px; background: rgba(244,239,228,.05);
}
.stat .num, .badge .num { display: block; font-size: 26px; font-weight: 700; line-height: 1.3; }
.stat .label, .badge .label { display: block; font-size: 12.5px; color: #b7ae9d; letter-spacing: .12em; }
.verdict-tag {
  display: flex; align-items: center; margin-left: 6px; padding: 0 20px;
  border-radius: 12px; background: var(--accent);
  color: #fdf6ee; font-size: 14px; font-weight: 600; line-height: 1.5;
}
.hero .source { margin: 26px 0 0; font-size: 13px; color: #8f8674; }
.hero .source a { color: #e0c9a0; }

.boundary {
  max-width: 1080px; margin: 24px auto 0; padding: 12px 20px;
  border-left: 4px solid var(--accent); border-radius: 8px;
  background: var(--accent-soft); color: var(--accent-deep);
  font-size: 13px; line-height: 1.7;
}

.section { max-width: 1080px; margin: 0 auto; padding: 52px 24px 8px; }
.section-kicker {
  margin: 0 0 6px; font-size: 12.5px; letter-spacing: .3em;
  color: var(--accent); font-weight: 600;
}
.section h2 { margin: 0 0 8px; font-family: var(--serif); font-size: clamp(22px, 3vw, 30px); }
.section .sub { margin: 0 0 26px; color: var(--ink-faint); font-size: 14px; }

.footer {
  max-width: 1080px; margin: 48px auto 0; padding: 26px 24px 42px;
  border-top: 1px solid var(--line);
  color: var(--ink-faint); font-size: 12.5px; line-height: 1.9;
  word-break: break-all;
}
.footer .boundary-note { color: var(--accent-deep); }

.evidence { max-width: 1080px; margin: 56px auto 0; padding: 0 24px; }
.evidence > h2 { margin: 0 0 6px; font-family: var(--serif); font-size: 26px; }
.evidence > .ev-sub { margin: 0 0 24px; color: var(--ink-faint); font-size: 13.5px; }
.ev-card {
  margin-bottom: 20px; padding: 24px 26px;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
}
.ev-card > h3 { margin: 0 0 14px; font-size: 16.5px; }
.ev-card .hint { margin: -6px 0 14px; font-size: 13px; color: var(--ink-faint); }
.ev-missing { margin: 0; color: var(--ink-faint); font-size: 14px; }
.ev-card details summary { cursor: pointer; font-weight: 600; color: var(--ink-soft); outline: none; }
.ev-card video { display: block; width: 100%; max-height: 70vh; margin-top: 14px; border-radius: 10px; background: #000; }
.shot { margin: 0; }
.shot img { width: 100%; border-radius: 10px; border: 1px solid var(--line); cursor: zoom-in; }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(148px, 1fr)); gap: 10px; }
.frame { position: relative; padding: 0; border: none; background: none; cursor: zoom-in; }
.frame img {
  display: block; width: 100%; aspect-ratio: 3 / 4; object-fit: cover;
  border-radius: 10px; transition: transform .18s ease, box-shadow .18s ease;
}
.frame:hover img { transform: scale(1.025); box-shadow: 0 6px 18px rgba(42,37,29,.18); }
.frame .stamp {
  position: absolute; right: 8px; bottom: 8px;
  padding: 2px 8px; border-radius: 999px;
  background: rgba(24,20,15,.78); color: #f4efe4;
  font-size: 11.5px; line-height: 1.6;
}
.comments { list-style: none; margin: 0; padding: 0; }
.comments li { padding: 14px 0; border-top: 1px solid var(--line); }
.comments li:first-child { border-top: none; padding-top: 0; }
.comment-likes {
  display: inline-block; margin-right: 10px; padding: 1px 10px; border-radius: 999px;
  background: var(--accent-soft); color: var(--accent-deep);
  font-size: 12.5px; font-weight: 600; vertical-align: 2px;
}
.comment-text { color: var(--ink); }
.comment-meta { display: block; margin-top: 4px; font-size: 12.5px; color: var(--ink-faint); }
.transcript {
  margin-top: 14px; padding: 18px 20px; border-radius: 10px;
  background: #faf7f0; color: var(--ink-soft);
  font-size: 14px; line-height: 2; white-space: pre-wrap; word-break: break-word;
}
.transcript .tline { display: grid; grid-template-columns: 44px 1fr; gap: 12px; padding: 3px 0; }
.transcript .tstamp { color: var(--ink-faint); font-size: 12px; font-variant-numeric: tabular-nums; padding-top: 2px; }

.lightbox {
  position: fixed; inset: 0; z-index: 60; display: none;
  align-items: center; justify-content: center;
  background: rgba(20,17,12,.92);
}
.lightbox.on { display: flex; }
.lightbox img { max-width: 92vw; max-height: 88vh; border-radius: 8px; }
.lb-cap { position: absolute; bottom: 22px; left: 0; right: 0; text-align: center; color: #cfc6b4; font-size: 13px; }
.lb-btn {
  position: absolute; top: 50%; transform: translateY(-50%);
  width: 46px; height: 46px; border: none; border-radius: 50%;
  background: rgba(244,239,228,.12); color: #f4efe4; font-size: 22px; cursor: pointer;
}
.lb-btn:hover { background: rgba(244,239,228,.25); }
.lb-prev { left: 22px; }
.lb-next { right: 22px; }
.lb-close { position: absolute; top: 18px; right: 24px; border: none; background: none; color: #f4efe4; font-size: 30px; cursor: pointer; }

/* ===== 基础版正文 ===== */
.layout {
  max-width: 1080px; margin: 36px auto 0; padding: 0 24px;
  display: grid; grid-template-columns: 218px minmax(0, 1fr); gap: 40px; align-items: start;
}
.toc { position: sticky; top: 28px; padding: 18px 0 18px 18px; border-left: 2px solid var(--line); font-size: 13.5px; line-height: 1.6; }
.toc .toc-title { margin: 0 0 10px; font-size: 12px; letter-spacing: .2em; color: var(--ink-faint); }
.toc a { display: block; padding: 5px 0; color: var(--ink-soft); border: none; }
.toc a:hover { color: var(--accent); text-decoration: none; }
.toc a.active { color: var(--accent); font-weight: 600; }
.report {
  background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--radius); padding: 48px 54px;
  box-shadow: 0 1px 3px rgba(42,37,29,.05);
}
.report h2 { margin: 2.1em 0 .9em; padding-top: .4em; border-top: 1px solid var(--line); font-family: var(--serif); font-size: 23px; line-height: 1.5; }
.report h2:first-child { margin-top: 0; padding-top: 0; border-top: none; }
.report h3 { margin: 1.7em 0 .7em; font-size: 17.5px; line-height: 1.6; }
.report p { margin: 1em 0; }
.report ul, .report ol { margin: 1em 0; padding-left: 1.5em; }
.report li { margin: .4em 0; }
.report blockquote {
  margin: 1.5em 0; padding: 14px 20px;
  border-left: 4px solid var(--accent); border-radius: 0 8px 8px 0;
  background: var(--accent-soft); color: var(--ink-soft);
}
.report blockquote p { margin: .3em 0; }
.report strong { color: var(--accent-deep); }
.report hr { border: none; border-top: 1px solid var(--line); margin: 2em 0; }
.twrap { margin: 1.4em 0; overflow-x: auto; border: 1px solid var(--line); border-radius: 10px; }
.report table { width: 100%; border-collapse: collapse; font-size: 14px; line-height: 1.7; }
.report th { padding: 11px 14px; background: #f3eee3; color: var(--ink); font-weight: 700; text-align: left; white-space: nowrap; }
.report td { padding: 11px 14px; border-top: 1px solid var(--line); vertical-align: top; }
.report tr:hover td { background: #faf7f0; }

/* ===== 金字塔版：透视区 ===== */
.lens { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.lens-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 24px 26px; }
.lens-card h3 { margin: 0 0 4px; font-size: 16.5px; }
.lens-card .note { margin: 0 0 16px; font-size: 12px; color: var(--ink-faint); }
.ladder { display: flex; flex-direction: column; gap: 8px; }
.rung { display: grid; grid-template-columns: 86px 1fr; gap: 12px; padding: 10px 14px; border-radius: 10px; border: 1px solid var(--line); background: #faf7f0; opacity: .62; }
.rung.on { opacity: 1; border-color: var(--accent); background: var(--accent-soft); box-shadow: 0 2px 10px rgba(192,57,43,.12); }
.rung .lv { font-weight: 700; font-size: 13.5px; color: var(--ink); }
.rung.on .lv { color: var(--accent-deep); }
.rung .lv-name { display: block; font-size: 12.5px; font-weight: 600; }
.rung .lv-desc { display: block; font-size: 12px; color: var(--ink-soft); line-height: 1.55; }
.rung .mark { display: inline-block; margin-left: 6px; padding: 0 7px; border-radius: 4px; background: var(--accent); color: #fdf6ee; font-size: 10.5px; font-weight: 700; vertical-align: 1px; }
.rung .tinge { font-size: 11px; color: var(--accent-deep); font-weight: 600; }
.lens-verdict { margin: 14px 0 0; font-size: 13px; line-height: 1.75; color: var(--ink-soft); }
.surface-vs { margin: 0 0 14px; padding: 12px 16px; border-radius: 10px; background: #faf7f0; font-size: 13.5px; line-height: 1.7; }
.surface-vs .vs-label { display: inline-block; margin-right: 8px; padding: 0 8px; border-radius: 4px; background: var(--blue-soft); color: var(--blue); font-size: 11px; font-weight: 700; }
.market-points { display: flex; flex-direction: column; gap: 12px; }
.mpoint { font-size: 13.5px; line-height: 1.7; }
.mpoint .m-no { display: inline-flex; width: 22px; height: 22px; border-radius: 50%; background: var(--accent-soft); color: var(--accent-deep); align-items: center; justify-content: center; font-size: 12px; font-weight: 700; margin-right: 8px; }
.mpoint .m-tag { font-size: 11px; color: var(--ink-faint); font-weight: 400; }
.mpoint blockquote { margin: 6px 0 0 30px; padding: 6px 12px; border-left: 3px solid var(--line); font-size: 12.5px; color: var(--ink-faint); line-height: 1.65; }

/* ===== 金字塔版：带走点 ===== */
.takeaway { display: flex; align-items: baseline; gap: 14px; margin-bottom: 6px; }
.takeaway .t-no { font-family: var(--serif); font-size: 34px; font-weight: 700; color: var(--accent); line-height: 1; }
.hook-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; display: grid; grid-template-columns: 300px 1fr; }
.hook-card .hook-frame { position: relative; min-height: 100%; }
.hook-card .hook-frame img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.hook-card .hook-body { padding: 30px 34px; }
.hook-tags { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
.hook-tag { padding: 3px 12px; border-radius: 999px; background: var(--accent); color: #fdf6ee; font-size: 12.5px; font-weight: 700; }
.hook-quote { margin: 0 0 16px; font-family: var(--serif); font-size: clamp(19px, 2.3vw, 25px); line-height: 1.75; color: var(--ink); }
.hook-quote::before { content: "「"; color: var(--accent); }
.hook-quote::after { content: "」"; color: var(--accent); }
.hook-why { margin: 0; font-size: 14px; color: var(--ink-soft); line-height: 1.8; }
.hook-why::before { content: "为什么有效"; display: inline-block; margin-right: 8px; padding: 0 8px; border-radius: 4px; background: var(--accent-soft); color: var(--accent-deep); font-size: 11px; font-weight: 700; vertical-align: 1px; }

.formula { display: flex; align-items: stretch; gap: 0; overflow-x: auto; padding-bottom: 6px; margin-bottom: 26px; }
.fstep { flex: none; text-align: center; }
.fstep .fbox { padding: 8px 14px; border-radius: 10px; background: var(--surface); border: 1px solid var(--line); font-size: 13px; font-weight: 700; white-space: nowrap; }
.fstep .fdemo { margin-top: 6px; font-size: 11px; color: var(--ink-faint); max-width: 108px; line-height: 1.5; }
.farrow { flex: none; align-self: flex-start; padding: 8px 5px 0; color: var(--ink-faint); font-size: 13px; }

.timeline-band { display: flex; border-radius: 12px; overflow: hidden; }
.seg { position: relative; padding: 14px 8px 12px; color: #fdf6ee; min-width: 68px; }
.seg .seg-fn { display: block; font-size: 12.5px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.seg .seg-time { display: block; font-size: 10.5px; opacity: .82; margin-top: 2px; }
.seg-hook  { background: var(--accent); }
.seg-setup { background: var(--amber); }
.seg-method{ background: var(--blue); }
.seg-turn  { background: var(--gray); }
.seg-cta   { background: var(--green); }
.legend { display: flex; flex-wrap: wrap; gap: 16px; margin: 12px 0 0; font-size: 12.5px; color: var(--ink-soft); }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; }

.node-list { margin-top: 24px; display: flex; flex-direction: column; gap: 14px; }
.node { display: grid; grid-template-columns: 150px 1fr; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
.node .frame { position: relative; }
.node .frame img { display: block; width: 100%; height: 100%; object-fit: cover; cursor: zoom-in; }
.node .body { padding: 18px 22px 16px; }
.node .tag { display: inline-block; padding: 2px 12px; border-radius: 999px; font-size: 12px; font-weight: 700; color: #fdf6ee; margin-bottom: 8px; }
.tag-hook  { background: var(--accent); }
.tag-setup { background: var(--amber); }
.tag-method{ background: var(--blue); }
.tag-turn  { background: var(--gray); }
.tag-cta   { background: var(--green); }
.node .time-range { margin-left: 8px; font-size: 12px; color: var(--ink-faint); }
.node blockquote { margin: 4px 0 8px; font-family: var(--serif); font-size: 16.5px; line-height: 1.7; color: var(--ink); }
.node blockquote::before { content: "「"; color: var(--accent); }
.node blockquote::after { content: "」"; color: var(--accent); }
.node .why { margin: 0; font-size: 13px; color: var(--ink-soft); line-height: 1.7; }
.node .why::before { content: "为什么有效"; display: inline-block; margin-right: 8px; padding: 0 8px; border-radius: 4px; background: var(--accent-soft); color: var(--accent-deep); font-size: 11px; font-weight: 700; vertical-align: 1px; }

.mech-sub { margin: 40px 0 16px; padding-top: 26px; border-top: 1px solid var(--line); font-family: var(--serif); font-size: 20px; font-weight: 700; }
.mech-sub span { display: block; margin-top: 4px; font-family: var(--sans); font-size: 13px; font-weight: 400; color: var(--ink-faint); }
.mech-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; }
.mech { padding: 22px 24px 20px; background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); }
.mech .head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.mech .step { font-family: var(--serif); font-size: 28px; font-weight: 700; color: var(--accent); line-height: 1; }
.mech h3 { margin: 0; font-size: 17px; }
.mech blockquote { margin: 0 0 10px; padding: 10px 14px; border-left: 3px solid var(--accent); border-radius: 0 8px 8px 0; background: var(--accent-soft); font-family: var(--serif); font-size: 14.5px; line-height: 1.7; color: var(--ink); }
.mech .attribution { margin: 0 0 8px; font-size: 11.5px; color: var(--ink-faint); }
.mech p { margin: 0; font-size: 13.5px; line-height: 1.75; color: var(--ink-soft); }

.fillblank { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 26px 30px; }
.fb-part { padding: 16px 0; border-top: 1px dashed var(--line); }
.fb-part:first-of-type { border-top: none; padding-top: 4px; }
.fb-part .fb-label { display: inline-block; margin-bottom: 10px; padding: 2px 10px; border-radius: 4px; background: var(--accent-soft); color: var(--accent-deep); font-size: 12px; font-weight: 700; }
.fb-script { margin: 0 0 10px; font-family: var(--serif); font-size: 15.5px; line-height: 2.1; color: var(--ink); }
.fb-script .blank { display: inline-block; min-width: 30px; padding: 0 6px; border-bottom: 2px solid var(--accent); color: var(--accent-deep); font-weight: 700; text-align: center; font-size: 13px; }
.fb-note { margin: 0; font-size: 12.5px; color: var(--ink-faint); line-height: 1.7; }
.fb-tip { margin: 18px 0 0; padding: 12px 16px; border-radius: 10px; background: #faf7f0; font-size: 12.5px; color: var(--ink-soft); line-height: 1.75; }

.cta-wrap { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.cta-card { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 24px 26px; }
.cta-card h3 { margin: 0 0 14px; font-size: 16px; }
.cta-quote { margin: 0 0 10px; font-family: var(--serif); font-size: 17px; line-height: 1.75; color: var(--ink); }
.cta-quote::before { content: "「"; color: var(--accent); }
.cta-quote::after { content: "」"; color: var(--accent); }
.cta-anatomy { display: flex; flex-direction: column; gap: 10px; }
.cta-piece { display: grid; grid-template-columns: 92px 1fr; gap: 10px; font-size: 13px; line-height: 1.65; }
.cta-piece .p-label { font-weight: 700; color: var(--accent-deep); font-size: 12.5px; }
.flow { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.flow .fnode { padding: 10px 16px; border-radius: 10px; background: #faf7f0; border: 1px solid var(--line); font-size: 13px; font-weight: 600; }
.flow .fnode.hot { background: var(--accent-soft); border-color: var(--accent); color: var(--accent-deep); }
.flow .farrow2 { color: var(--ink-faint); }
.flow-note { margin: 16px 0 0; font-size: 13px; color: var(--ink-soft); line-height: 1.75; }

.signal-list { display: flex; flex-direction: column; gap: 12px; }
.sig { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); padding: 18px 22px; }
.sig .sig-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.sig .sig-name { font-weight: 700; font-size: 15px; }
.sig .count { padding: 1px 9px; border-radius: 999px; background: var(--accent-soft); color: var(--accent-deep); font-size: 12px; font-weight: 700; }
.sig .sig-sample { margin: 8px 0; padding: 8px 14px; border-left: 3px solid var(--line); font-size: 13px; color: var(--ink-soft); line-height: 1.7; }
.sig .sig-topic { margin: 0; font-size: 13.5px; line-height: 1.7; }
.sig .sig-topic::before { content: "延伸选题"; display: inline-block; margin-right: 8px; padding: 0 8px; border-radius: 4px; background: var(--blue-soft); color: var(--blue); font-size: 11px; font-weight: 700; vertical-align: 1px; }

.critique { display: flex; flex-direction: column; gap: 12px; }
.crit { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--amber); border-radius: 10px; padding: 16px 22px; }
.crit h3 { margin: 0 0 6px; font-size: 15px; }
.crit p { margin: 0; font-size: 13.5px; color: var(--ink-soft); line-height: 1.75; }

@media (max-width: 1080px) {
  .layout { grid-template-columns: 1fr; }
  .toc { position: static; border-left: none; border-bottom: 1px solid var(--line); padding: 0 0 14px; }
  .report { padding: 30px 24px; }
  .lens, .cta-wrap { grid-template-columns: 1fr; }
  .hook-card { grid-template-columns: 1fr; }
  .hook-card .hook-frame { min-height: 260px; position: relative; }
  .node { grid-template-columns: 110px 1fr; }
  .topline { flex-direction: column; gap: 4px; }
}
"""

PAGE_JS = """
(function () {
  var lightbox = document.getElementById('lightbox');
  if (!lightbox) return;
  var img = lightbox.querySelector('img');
  var cap = lightbox.querySelector('.lb-cap');
  var prev = lightbox.querySelector('.lb-prev');
  var next = lightbox.querySelector('.lb-next');
  var items = [];
  var index = 0;

  function show() {
    var item = items[index];
    img.src = item.full;
    cap.textContent = item.cap || '';
    var many = items.length > 1;
    prev.style.display = many ? '' : 'none';
    next.style.display = many ? '' : 'none';
  }
  function open(list, i) {
    items = list; index = i; show();
    lightbox.classList.add('on');
    document.body.style.overflow = 'hidden';
  }
  function close() {
    lightbox.classList.remove('on');
    document.body.style.overflow = '';
  }
  function step(delta) { index = (index + delta + items.length) % items.length; show(); }

  var zoomables = Array.prototype.slice.call(document.querySelectorAll('[data-full]'));
  var galleryItems = zoomables.map(function (el) {
    return { full: el.getAttribute('data-full'), cap: el.getAttribute('data-cap') };
  });
  zoomables.forEach(function (el, i) {
    el.addEventListener('click', function () {
      var single = el.closest('.shot, .hook-frame, .node .frame');
      if (single) {
        open([{ full: el.getAttribute('data-full'), cap: el.getAttribute('data-cap') }], 0);
      } else {
        open(galleryItems, i);
      }
    });
  });

  lightbox.addEventListener('click', function (event) { if (event.target === lightbox) close(); });
  lightbox.querySelector('.lb-close').addEventListener('click', close);
  prev.addEventListener('click', function (event) { event.stopPropagation(); step(-1); });
  next.addEventListener('click', function (event) { event.stopPropagation(); step(1); });
  document.addEventListener('keydown', function (event) {
    if (!lightbox.classList.contains('on')) return;
    if (event.key === 'Escape') close();
    if (event.key === 'ArrowLeft') step(-1);
    if (event.key === 'ArrowRight') step(1);
  });

  var links = Array.prototype.slice.call(document.querySelectorAll('.toc a'));
  var map = {};
  links.forEach(function (link) { map[link.getAttribute('href').slice(1)] = link; });
  var headings = Array.prototype.slice.call(document.querySelectorAll('.report h2[id]'));
  if ('IntersectionObserver' in window && headings.length) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        links.forEach(function (link) { link.classList.remove('active'); });
        var link = map[entry.target.id];
        if (link) link.classList.add('active');
      });
    }, { rootMargin: '-20% 0px -70% 0px' });
    headings.forEach(function (heading) { observer.observe(heading); });
  }
})();
"""

LIGHTBOX_HTML = (
    '<div class="lightbox" id="lightbox">'
    '<button class="lb-close" aria-label="关闭">×</button>'
    '<button class="lb-btn lb-prev" aria-label="上一张">‹</button>'
    "<img alt=\"\">"
    '<button class="lb-btn lb-next" aria-label="下一张">›</button>'
    '<p class="lb-cap"></p>'
    "</div>"
)


def build_hero(meta: dict, metrics: dict, verdict_html: str = "", data_verdict: str = "") -> str:
    badges = []
    for key, label in (("likes", "点赞"), ("comments", "评论"), ("collects", "收藏"), ("shares", "分享")):
        badges.append(
            f'<div class="stat"><span class="num">{esc(format_count(metrics.get(key)))}</span>'
            f'<span class="label">{label}</span></div>'
        )
    if data_verdict:
        badges.append(f'<div class="verdict-tag">{esc(data_verdict)}</div>')
    source_parts = []
    url = meta["url"]
    if url.startswith("http://") or url.startswith("https://"):
        source_parts.append(f'<a href="{esc(url)}" rel="noreferrer">来源链接 ↗</a>')
    if meta["collected"]:
        source_parts.append(f"采集于 {esc(meta['collected'])}")
    topline_right = []
    if meta["author"] != "未知作者":
        topline_right.append(esc(meta["author"]))
    if meta["published"]:
        topline_right.append(f"发布于 {esc(meta['published'])}")
    parts = [
        '<header class="hero"><div class="hero-inner">',
        '<div class="topline"><span class="brand">抖音视频拆解</span>',
        f"<span>{' · '.join(topline_right)}</span></div>" if topline_right else "",
        f"<h1>{esc(meta['page_title'])}</h1>",
        f'<p class="verdict">{verdict_html}</p>' if verdict_html else f'<p class="meta">{meta["meta_line"]}</p>',
        f'<div class="statrow">{"".join(badges)}</div>',
        f'<p class="source">{" · ".join(source_parts)}</p>' if source_parts else "",
        "</div></header>",
    ]
    return "".join(part for part in parts if part)


def build_evidence(run_dir: Path, frames: list, comments: list, transcript_rows: list, screenshot: str, video: str) -> str:
    evidence = ['<section class="section evidence" style="padding-left:0;padding-right:0;">' '<p class="section-kicker">证据面板</p><h2>所有判断都能回到这里核验</h2>',
                '<p class="sub">以下证据均来自本地采集目录，仅用于复核分析，不代表后台真实数据。</p>']

    if video:
        duration = read_json(run_dir / "frames" / "frames.json").get("duration")
        length = ""
        if duration:
            total = int(float(duration))
            length = f"（{total // 60} 分 {total % 60:02d} 秒）"
        evidence.append(
            '<div class="ev-card"><h3>原视频</h3>'
            f"<details><summary>点击播放原视频{esc(length)}</summary>"
            f'<video controls preload="metadata" src="{esc(video)}"></video></details></div>'
        )

    evidence.append('<div class="ev-card"><h3>详情页数据截图</h3>')
    if screenshot:
        evidence.append(
            f'<figure class="shot"><img src="{esc(screenshot)}" data-full="{esc(screenshot)}" '
            'data-cap="详情页数据截图" alt="详情页数据截图"></figure>'
        )
    else:
        evidence.append('<p class="ev-missing">素材不足：本次未取到详情页数据截图。</p>')
    evidence.append("</div>")

    evidence.append(
        '<div class="ev-card"><h3>关键帧</h3>'
        '<p class="hint">按时间顺序抽取的画面证据，点击可放大复核字幕、场景与画面切换。</p>'
    )
    if frames:
        evidence.append('<div class="gallery">')
        for frame in frames:
            evidence.append(
                f'<button class="frame" data-full="{esc(frame["src"])}" data-cap="关键帧 {esc(frame["stamp"])}">'
                f'<img loading="lazy" src="{esc(frame["src"])}" alt="关键帧 {esc(frame["stamp"])}">'
            )
            if frame["stamp"]:
                evidence.append(f'<span class="stamp">{esc(frame["stamp"])}</span>')
            evidence.append("</button>")
        evidence.append("</div>")
    else:
        evidence.append('<p class="ev-missing">素材不足：本次未抽取到关键帧。</p>')
    evidence.append("</div>")

    evidence.append(
        '<div class="ev-card"><h3>代表性评论</h3>'
        '<p class="hint">按页面点赞排序，只代表本次加载到的公开评论样本。</p>'
    )
    if comments:
        evidence.append('<ul class="comments">')
        for comment in comments:
            meta = " · ".join(part for part in [comment.get("author"), comment.get("time")] if part)
            evidence.append(
                f'<li><span class="comment-likes">{esc(format_count(comment.get("likes")))} 赞</span>'
                f'<span class="comment-text">{esc((comment.get("text") or "").strip())}</span>'
            )
            if meta:
                evidence.append(f'<span class="comment-meta">{esc(meta)}</span>')
            evidence.append("</li>")
        evidence.append("</ul>")
    else:
        evidence.append('<p class="ev-missing">素材不足：本次未取到评论。</p>')
    evidence.append("</div>")

    evidence.append('<div class="ev-card"><h3>口播逐字稿</h3>')
    if transcript_rows:
        lines = []
        for row in transcript_rows:
            if row["stamp"]:
                lines.append(
                    f'<div class="tline"><span class="tstamp">{esc(row["stamp"])}</span>'
                    f"<span>{esc(row['text'])}</span></div>"
                )
            else:
                lines.append(f"<div>{esc(row['text'])}</div>")
        evidence.append(
            "<details><summary>展开逐字稿（本地 ASR 原文，无标点）</summary>"
            f'<div class="transcript">{"".join(lines)}</div></details>'
        )
    else:
        evidence.append('<p class="ev-missing">素材不足：本次未取到转写。</p>')
    evidence.append("</div></section>")
    return "".join(evidence)


def build_footer(run_dir: Path, report_path: Path) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        '<footer class="footer">'
        f'<div class="boundary-note">{esc(BOUNDARY_TEXT)}</div>'
        f"<div>本地证据目录：{esc(str(run_dir))}</div>"
        f"<div>最终报告来源：{esc(report_path.name)}</div>"
        f"<div>页面生成时间：{esc(generated_at)}</div>"
        "</footer>"
    )


def render_basic_page(run_dir: Path, report_path: Path, meta: dict, breakdown: dict) -> tuple[str, dict]:
    """基础版：Hero + Markdown 正文 + 证据面板。report-web.json 缺失时的降级形态。"""
    metadata = breakdown.get("metadata") or {}
    transcript = (breakdown.get("transcript_text") or "").strip()
    comments = pick_comments(metadata.get("comments") or [])
    frames = collect_frames(run_dir)
    screenshot = find_first(run_dir, SCREENSHOT_CANDIDATES)
    video = find_first(run_dir, VIDEO_CANDIDATES)

    report_title, body_md = split_report(report_path.read_text(encoding="utf-8"))
    body_md = strip_theory_annotations(body_md)
    md = markdown.Markdown(
        extensions=["tables", "toc"],
        extension_configs={"toc": {"slugify": slugify_unicode, "toc_depth": "2-3"}},
    )
    body_html = md.convert(body_md)
    body_html = body_html.replace("<table>", '<div class="twrap"><table>').replace("</table>", "</table></div>")
    toc_links = []
    for token in md.toc_tokens:
        if token.get("level") == 2:
            toc_links.append(f'<a href="#{esc(token["id"])}">{esc(token["name"])}</a>')
    toc_html = '<nav class="toc"><p class="toc-title">目录</p>' + "".join(toc_links) + "</nav>" if toc_links else ""

    transcript_rows = read_transcript_rows(run_dir, transcript)
    parts = [
        build_hero(meta, metadata.get("metrics") or {}),
        f'<div class="boundary">{esc(BOUNDARY_TEXT)}</div>',
        '<div class="layout">',
        toc_html,
        f'<main class="report">{body_html}</main>',
        "</div>",
        build_evidence(run_dir, frames, comments, transcript_rows, screenshot, video),
        build_footer(run_dir, report_path),
    ]
    stats = {
        "sections": len(toc_links),
        "frames": len(frames),
        "comments": len(comments),
    }
    return "".join(parts), stats


def emphasize(text: str, marks: list) -> str:
    """verdict 里的重点词换成 <em>，只替换第一次出现。"""
    result = esc(text)
    for mark in marks or []:
        result = result.replace(esc(mark), f"<em>{esc(mark)}</em>", 1)
    return result


def build_lens(web: dict) -> str:
    level = web.get("creator_level") or {}
    marketing = web.get("marketing_points") or {}
    if not level and not marketing:
        return ""
    parts = [
        '<section class="section"><p class="section-kicker">先看透这个人</p>',
        "<h2>这条视频的透视</h2>",
        '<p class="sub">左边回答「他在哪一层玩」，右边回答「表面这套动作底下实际在干什么」。</p>',
        '<div class="lens">',
    ]
    if level:
        primary = (level.get("primary") or "").strip().upper()
        tinges = level.get("tinges") or {}
        rungs = []
        for code, name, desc in CREATOR_LADDER:
            on = code == primary
            tinge = (tinges.get(code) or "").strip()
            mark = '<span class="mark">主体在这层</span>' if on else ""
            tinge_html = f'<span class="tinge">　↑ {esc(tinge)}</span>' if tinge and not on else ""
            rungs.append(
                f'<div class="rung{" on" if on else ""}"><span class="lv">{code}</span>'
                f'<span><span class="lv-name">{esc(name)}{mark}{tinge_html}</span>'
                f'<span class="lv-desc">{esc(desc)}</span></span></div>'
            )
        verdict = (level.get("verdict") or "").strip()
        parts.append(
            '<div class="lens-card"><h3>创作者层级定位</h3>'
            '<p class="note">仅限这条视频呈现出的层级，不是对作者整个人的定性。</p>'
            f'<div class="ladder">{"".join(rungs)}</div>'
            + (f'<p class="lens-verdict">{esc(verdict)}</p>' if verdict else "")
            + "</div>"
        )
    if marketing:
        points_html = []
        for index, point in enumerate(marketing.get("points") or [], 1):
            tag = (point.get("tag") or "").strip()
            points_html.append(
                f'<div class="mpoint"><span class="m-no">{index}</span>'
                f"<strong>{esc(point.get('title'))}</strong>"
                + (f'<span class="m-tag">（{esc(tag)}）</span>' if tag else "")
                + f"：{esc(point.get('desc'))}"
                + (f"<blockquote>原话：「{esc(point.get('quote'))}」</blockquote>" if point.get("quote") else "")
                + "</div>"
            )
        parts.append(
            '<div class="lens-card"><h3>营销点：表面与底层</h3>'
            '<p class="note">每条底层动作都挂原话证据，不是主观猜测。</p>'
            f'<p class="surface-vs"><span class="vs-label">表面在做</span>{esc(marketing.get("surface"))}</p>'
            f'<div class="market-points">{"".join(points_html)}</div></div>'
        )
    parts.append("</div></section>")
    return "".join(parts)


def build_hook(web: dict) -> str:
    hook = web.get("hook") or {}
    if not hook:
        return ""
    tags = "".join(f'<span class="hook-tag">{esc(tag)}</span>' for tag in hook.get("tags") or [])
    frame = (hook.get("frame") or "").strip()
    frame_html = (
        f'<div class="hook-frame"><img src="frames/{esc(frame)}" data-full="frames/{esc(frame)}" '
        'data-cap="开篇首帧" alt="开篇首帧"></div>' if frame else ""
    )
    return (
        '<section class="section"><p class="section-kicker">带走点 1</p>'
        '<div class="takeaway"><span class="t-no">01</span><h2>开篇怎么开</h2></div>'
        '<p class="sub">3 秒定生死，这条视频的开篇结构与表达方式。</p>'
        f'<div class="hook-card">{frame_html}'
        f'<div class="hook-body"><div class="hook-tags">{tags}</div>'
        f'<p class="hook-quote">{esc(hook.get("quote"))}</p>'
        f'<p class="hook-why">{esc(hook.get("why"))}</p></div></div></section>'
    )


def build_structure(web: dict) -> str:
    structure = web.get("structure") or {}
    if not structure:
        return ""
    parts = [
        '<section class="section"><p class="section-kicker">带走点 2</p>',
        '<div class="takeaway"><span class="t-no">02</span><h2>一种表达结构</h2></div>',
        '<p class="sub">一行公式 + 原作者示范。搬结构，不搬话术。</p>',
    ]
    formula = structure.get("formula") or []
    if formula:
        steps = []
        for index, step in enumerate(formula):
            if index:
                steps.append('<span class="farrow">→</span>')
            demo = (step.get("demo") or "").strip()
            steps.append(
                f'<div class="fstep"><div class="fbox">{esc(step.get("step"))}</div>'
                + (f'<div class="fdemo">{esc(demo)}</div>' if demo else "")
                + "</div>"
            )
        parts.append(f'<div class="formula">{"".join(steps)}</div>')

    timeline = structure.get("timeline") or []
    if timeline:
        segs = []
        used_kinds = []
        for seg in timeline:
            kind = seg.get("kind") if seg.get("kind") in SEG_KINDS else "method"
            if kind not in used_kinds:
                used_kinds.append(kind)
            seconds = max(float(seg.get("seconds") or 1), 1)
            segs.append(
                f'<div class="seg seg-{kind}" style="flex:{seconds:g}">'
                f'<span class="seg-fn">{esc(seg.get("fn"))}</span>'
                f'<span class="seg-time">{esc(seg.get("range"))}</span></div>'
            )
        legend = "".join(
            f'<span><i class="lg-{kind}" style="background:var(--{"accent" if kind=="hook" else kind if kind!="cta" else "green"})"></i>{SEG_KIND_LABELS[kind]}</span>'
            for kind in ("hook", "setup", "method", "turn", "cta") if kind in used_kinds
        )
        parts.append(f'<div class="timeline-band">{"".join(segs)}</div><div class="legend">{legend}</div>')

    nodes = structure.get("nodes") or []
    if nodes:
        cards = []
        for node in nodes:
            kind = node.get("kind") if node.get("kind") in SEG_KINDS else "method"
            frame = (node.get("frame") or "").strip()
            frame_html = (
                f'<div class="frame"><img loading="lazy" src="frames/{esc(frame)}" '
                f'data-full="frames/{esc(frame)}" data-cap="{esc(node.get("fn"))} {esc(node.get("stamp"))}" alt="">'
                f'<span class="stamp">{esc(node.get("stamp"))}</span></div>' if frame else ""
            )
            cards.append(
                f'<div class="node">{frame_html}<div class="body">'
                f'<span class="tag tag-{kind}">{esc(node.get("fn"))}</span>'
                f'<span class="time-range">{esc(node.get("range"))}</span>'
                f"<blockquote>{esc(node.get('quote'))}</blockquote>"
                f'<p class="why">{esc(node.get("why"))}</p></div></div>'
            )
        parts.append(f'<div class="node-list">{"".join(cards)}</div>')

    mechanisms = structure.get("mechanisms") or []
    if mechanisms:
        cards = []
        for index, mech in enumerate(mechanisms, 1):
            attribution = (mech.get("attribution") or "").strip()
            cards.append(
                f'<div class="mech"><div class="head"><span class="step">{index:02d}</span>'
                f"<h3>{esc(mech.get('title'))}</h3></div>"
                + (f"<blockquote>{esc(mech.get('quote'))}</blockquote>" if mech.get("quote") else "")
                + (f'<p class="attribution">{esc(attribution)}</p>' if attribution else "")
                + f"<p>{esc(mech.get('desc'))}</p></div>"
            )
        parts.append(
            '<h3 class="mech-sub">这个结构为什么有效<span>段卡证明每段做了什么，'
            "这里回答为什么观众会看完、会相信、会行动。</span></h3>"
            f'<div class="mech-grid">{"".join(cards)}</div>'
        )
    parts.append("</section>")
    return "".join(parts)


def build_fill_blank(web: dict) -> str:
    parts_data = web.get("fill_blank") or []
    if not parts_data:
        return ""
    marks = re.compile(f"([{BLANK_MARKS}])")

    def render_script(script: str) -> str:
        return marks.sub(r'<span class="blank">\1</span>', esc(script))

    items = []
    for part in parts_data:
        items.append(
            f'<div class="fb-part"><span class="fb-label">{esc(part.get("label"))}</span>'
            f'<p class="fb-script">{render_script(part.get("script"))}</p>'
            f'<p class="fb-note">{esc(part.get("notes"))}</p></div>'
        )
    return (
        '<section class="section">'
        '<h3 class="mech-sub" style="border-top:none;padding-top:0;margin-top:0;">把这条视频变成你的填空题'
        "<span>复制这个骨架，把空位换成你的材料。空位下的注释是填写要求和原作者示范，示范只供理解，不要照搬。</span></h3>"
        f'<div class="fillblank">{"".join(items)}'
        '<p class="fb-tip">用法：先通读一遍原文对应的段卡（带走点 2），理解每段在干什么，再回来填空。'
        "填完后通读你的版本，凡是听起来像原作者口气的地方，改成你自己的说法。</p>"
        "</div></section>"
    )


def build_cta(web: dict) -> str:
    cta = web.get("cta") or {}
    if not cta:
        return ""
    pieces = "".join(
        f'<div class="cta-piece"><span class="p-label">{esc(piece.get("label"))}</span>'
        f"<span>{esc(piece.get('desc'))}</span></div>"
        for piece in cta.get("pieces") or []
    )
    flow = cta.get("flow") or []
    hot = int(cta.get("flow_hot_index") or -1)
    flow_html = []
    for index, node in enumerate(flow):
        if index:
            flow_html.append('<span class="farrow2">→</span>')
        flow_html.append(f'<span class="fnode{" hot" if index == hot else ""}">{esc(node)}</span>')
    note = (cta.get("flow_note") or "").strip()
    return (
        '<section class="section"><p class="section-kicker">带走点 3</p>'
        '<div class="takeaway"><span class="t-no">03</span><h2>一种 CTA</h2></div>'
        '<p class="sub">不喊「点关注」，而是让观众为了拿到东西自己走进私域。</p>'
        '<div class="cta-wrap">'
        f'<div class="cta-card"><h3>CTA 原话与拆解</h3><p class="cta-quote">{esc(cta.get("quote"))}</p>'
        f'<div class="cta-anatomy">{pieces}</div></div>'
        f'<div class="cta-card"><h3>流量去向</h3><div class="flow">{"".join(flow_html)}</div>'
        + (f'<p class="flow-note">{esc(note)}</p>' if note else "")
        + "</div></div></section>"
    )


def build_signals(web: dict) -> str:
    signals = web.get("comment_signals") or []
    if not signals:
        return ""
    items = []
    for sig in signals:
        sample = (sig.get("sample") or "").strip()
        items.append(
            f'<div class="sig"><div class="sig-head"><span class="sig-name">{esc(sig.get("name"))}</span>'
            f'<span class="count">{esc(sig.get("count"))}</span></div>'
            + (f'<p class="sig-sample">{esc(sample)}</p>' if sample else "")
            + f'<p class="sig-topic">{esc(sig.get("topic"))}</p></div>'
        )
    return (
        '<section class="section"><p class="section-kicker">需求信号</p>'
        "<h2>评论区在问什么，能挖什么选题</h2>"
        '<p class="sub">评论是需求线索，每个高频问题都是一个选题候选；样本有限，不能证明付费意愿。</p>'
        f'<div class="signal-list">{"".join(items)}</div></section>'
    )


def build_critiques(web: dict) -> str:
    critiques = web.get("critiques") or []
    if not critiques:
        return ""
    items = "".join(
        f'<div class="crit"><h3>{esc(crit.get("title"))}</h3><p>{esc(crit.get("desc"))}</p></div>'
        for crit in critiques
    )
    return (
        '<section class="section"><p class="section-kicker">别全信</p>'
        "<h2>不能照搬与待验证的部分</h2>"
        '<p class="sub">传播结构值得学，但以下几个地方不能照单全收。</p>'
        f'<div class="critique">{items}</div></section>'
    )


def render_pyramid_page(run_dir: Path, report_path: Path, meta: dict, breakdown: dict, web: dict) -> tuple[str, dict]:
    """金字塔版：透视 → 三个带走点 → 填空模板 → CTA → 选题 → 批判 → 证据。"""
    metadata = breakdown.get("metadata") or {}
    transcript = (breakdown.get("transcript_text") or "").strip()
    comments = pick_comments(metadata.get("comments") or [])
    frames = collect_frames(run_dir)
    screenshot = find_first(run_dir, SCREENSHOT_CANDIDATES)
    video = find_first(run_dir, VIDEO_CANDIDATES)
    transcript_rows = read_transcript_rows(run_dir, transcript)

    verdict_html = emphasize(web.get("verdict") or "", web.get("verdict_emphasis") or [])
    sections = [
        build_hero(meta, metadata.get("metrics") or {}, verdict_html, web.get("data_verdict") or ""),
        f'<div class="boundary">{esc(BOUNDARY_TEXT)}</div>',
        build_lens(web),
        build_hook(web),
        build_structure(web),
        build_fill_blank(web),
        build_cta(web),
        build_signals(web),
        build_critiques(web),
        build_evidence(run_dir, frames, comments, transcript_rows, screenshot, video),
        build_footer(run_dir, report_path),
    ]
    stats = {
        "sections": sum(1 for part in sections if part),
        "frames": len(frames),
        "comments": len(comments),
    }
    return "".join(part for part in sections if part), stats


def render_page(run_dir: Path, report_path: Path) -> tuple[str, dict]:
    breakdown = read_json(run_dir / "breakdown.json")
    metadata = breakdown.get("metadata") or {}
    report_title, _ = split_report(report_path.read_text(encoding="utf-8"))
    meta = hero_meta(metadata, report_title, run_dir)
    meta["report_title"] = report_title

    web = read_json(run_dir / "report-web.json")
    if web and (web.get("verdict") or web.get("structure")):
        page, stats = render_pyramid_page(run_dir, report_path, meta, breakdown, web)
        stats["mode"] = "pyramid"
    else:
        page, stats = render_basic_page(run_dir, report_path, meta, breakdown)
        stats["mode"] = "basic"

    stats.update(
        {
            "title": meta["page_title"],
            "has_screenshot": bool(find_first(run_dir, SCREENSHOT_CANDIDATES)),
            "has_video": bool(find_first(run_dir, VIDEO_CANDIDATES)),
            "has_transcript": bool((breakdown.get("transcript_text") or "").strip()),
            "has_metadata": bool(metadata),
        }
    )
    head = (
        "<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(meta['page_title'])} · 抖音拆解</title>\n<style>{BASE_CSS}</style>\n</head>\n<body>\n"
    )
    tail = f"\n{LIGHTBOX_HTML}\n<script>{PAGE_JS}</script>\n</body>\n</html>"
    return head + page + tail, stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--final-report", required=True, help="经 AI 深度审阅后的最终拆解报告")
    parser.add_argument("--output", default="", help="默认写到 <run_dir>/拆解报告.html")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).expanduser().resolve()
    report_path = Path(args.final_report).expanduser().resolve()
    if not run_dir.is_dir():
        print(json.dumps({"ok": False, "error": f"run-dir 不存在: {run_dir}"}, ensure_ascii=False))
        return 2
    if not report_path.is_file():
        print(json.dumps({"ok": False, "error": f"最终拆解报告不存在: {report_path}"}, ensure_ascii=False))
        return 2

    output = Path(args.output).expanduser().resolve() if args.output else run_dir / "拆解报告.html"
    page, stats = render_page(run_dir, report_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    written = output.read_text(encoding="utf-8")
    result = {"ok": written == page, "html": str(output), "bytes": len(page.encode("utf-8")), **stats}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
