#!/usr/bin/env python3
"""Render an article Markdown file as a self-contained, mobile-friendly HTML page."""

import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from markdown_it import MarkdownIt
except ImportError as exc:
    print("错误: 缺少依赖 markdown-it-py，请先安装后再运行。", file=sys.stderr)
    raise SystemExit(1) from exc


SUPPORTED = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
             ".webp": "image/webp", ".gif": "image/gif"}
IMAGE_PLACEHOLDER = "duyi-local-image://"


class RenderError(Exception):
    pass


def fail(message):
    raise RenderError(message)


def strip_frontmatter(text):
    """Remove only a valid, closed YAML frontmatter block; do not parse YAML."""
    opening = re.match(r"\A---[ \t]*(?:\r?\n|\Z)", text)
    if not opening:
        return text
    closing = re.search(r"(?m)^---[ \t]*$|^\.\.\.[ \t]*$", text[opening.end():])
    if not closing:
        fail("YAML frontmatter 未闭合")
    end = opening.end() + closing.end()
    return text[end:].lstrip("\r\n")


def safe_root(path):
    try:
        return path.expanduser().resolve(strict=True)
    except FileNotFoundError:
        fail(f"目录不存在: {path}")


def resolve_local(rel, roots, label):
    rel = unquote(rel.replace("\\", "/"))
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", rel):
        fail(f"{label} 不允许绝对路径: {rel}")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", rel):
        fail(f"{label} 不允许远程或带协议路径: {rel}")
    candidates = []
    for root in roots:
        candidate = (root / Path(rel)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            fail(f"{label} 超出允许目录: {rel}")
        if candidate.exists():
            candidates.append(candidate)
    unique = list(dict.fromkeys(candidates))
    if len(unique) > 1:
        fail(f"{label} 存在歧义（多个允许目录均有同名文件）: {rel}")
    if not unique:
        fail(f"图片不存在: {rel}")
    path = unique[0]
    if not path.is_file():
        fail(f"图片不是文件: {rel}")
    if path.suffix.lower() not in SUPPORTED:
        fail(f"不支持的图片格式: {path.suffix or '(无扩展名)'}")
    return path


def image_data(path):
    mime = SUPPORTED[path.suffix.lower()]
    return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode("ascii"))


def replace_obsidian_images(text, image_specs):
    pattern = re.compile(r"!\[\[([^\]|]+?)(?:\|([^\]]+))?\]\]")

    def repl(match):
        rel = match.group(1).strip()
        width = (match.group(2) or "").strip()
        if width and not re.fullmatch(r"[1-9][0-9]{0,3}", width):
            fail(f"Obsidian 图片宽度无效: {width}")
        key = f"{len(image_specs)}"
        image_specs[key] = (rel, width or None, "")
        return f"![{html.escape(Path(rel).stem)}]({IMAGE_PLACEHOLDER}{key})"

    return pattern.sub(repl, text)


def safe_href(href):
    parsed = urlparse(href.strip())
    scheme = parsed.scheme.lower()
    if scheme in {"javascript", "vbscript", "data", "file"}:
        fail("链接包含不安全协议")
    if scheme and scheme not in {"http", "https", "mailto", "tel"}:
        fail(f"不支持的链接协议: {scheme}")
    if href.strip().startswith("//"):
        return href.strip()
    return href.strip()


def render_markdown(body, title, roots):
    image_specs = {}
    body = replace_obsidian_images(body, image_specs)
    md = MarkdownIt("commonmark", {"html": False})
    md.enable("table")
    env = {"image_specs": image_specs, "roots": roots, "image_count": 0}

    def render_image(self, tokens, idx, options, env):
        token = tokens[idx]
        src = token.attrGet("src") or ""
        width = None
        if src.startswith(IMAGE_PLACEHOLDER):
            key = src[len(IMAGE_PLACEHOLDER):]
            try:
                rel, width, _ = env["image_specs"][key]
            except KeyError:
                fail("内部图片引用无效")
        else:
            if urlparse(src).scheme or src.startswith("//"):
                fail("图片不允许远程地址")
            rel = src
        path = resolve_local(rel, env["roots"], "图片")
        token.attrSet("src", image_data(path))
        env["image_count"] += 1
        # markdown-it stores the source alt text in token.content and puts an
        # empty placeholder in attrs['alt']; preserve the actual text here.
        alt = token.content or token.attrGet("alt") or ""
        attrs = [f'src="{html.escape(token.attrGet("src"), quote=True)}"',
                 f'alt="{html.escape(alt, quote=True)}"', 'class="article-image"']
        if width:
            attrs.append(f'style="max-width:{int(width)}px"')
        return "<img " + " ".join(attrs) + ">"

    def render_link_open(self, tokens, idx, options, env):
        token = tokens[idx]
        href = safe_href(token.attrGet("href") or "")
        token.attrSet("href", href)
        return self.renderToken(tokens, idx, options, env)

    md.add_render_rule("image", render_image)
    md.add_render_rule("link_open", render_link_open)
    md.add_render_rule("table_open", lambda self, tokens, idx, options, env: '<div class="table-wrap"><table>')
    md.add_render_rule("table_close", lambda self, tokens, idx, options, env: "</table></div>")
    tokens = md.parse(body, env)
    first_h1 = None
    for i, token in enumerate(tokens):
        if token.type == "heading_open" and token.tag == "h1":
            first_h1 = i
            break
    if first_h1 is not None:
        inline = tokens[first_h1 + 1]
        heading_text = re.sub(r"\s+", " ", inline.content).strip()
        if heading_text == title.strip():
            del tokens[first_h1:first_h1 + 3]
    content = md.renderer.render(tokens, md.options, env)
    return f'<h1 class="article-title">{html.escape(title)}</h1>\n{content}', env["image_count"]


def build_html(title, content):
    return """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%s</title>
<style>
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #fff; color: #202124; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; font-size: 20px; line-height: 1.8; }
main { max-width: 720px; margin: 0 auto; padding: 28px 20px 64px; overflow-wrap: anywhere; }
.article-title { font-size: 1.7em; line-height: 1.35; margin: 0 0 1.1em; }
h2, h3, h4 { line-height: 1.4; margin-top: 1.4em; }
p, ul, ol, blockquote, pre, table { margin: 0 0 1em; }
a { color: #1769aa; }
img.article-image { display: block; max-width: 100%%; height: auto; margin: 1em auto; cursor: zoom-in; }
blockquote { border-left: 4px solid #d7dbe0; padding-left: 1em; color: #5f6368; }
pre { overflow-x: auto; padding: 12px; background: #f5f6f7; border-radius: 6px; }
code { font-size: .88em; }
.table-wrap { overflow-x: auto; margin-bottom: 1em; }
table { border-collapse: collapse; min-width: 100%%; }
th, td { border: 1px solid #d7dbe0; padding: 6px 10px; text-align: left; }
dialog { max-width: 96vw; max-height: 96vh; padding: 0; border: 0; background: transparent; }
dialog::backdrop { background: rgba(0,0,0,.75); }
dialog img { display: block; max-width: 100%%; height: auto; object-fit: contain; }
.dialog-scroll { max-width: 96vw; max-height: 84vh; overflow: auto; background: #111; }
.dialog-scroll.zoomed img { max-width: none; max-height: none; }
.dialog-toolbar { display: flex; justify-content: flex-end; gap: 8px; padding: 6px; background: #222; }
.dialog-toolbar button { padding: 5px 12px; border: 0; border-radius: 4px; cursor: pointer; }
</style>
</head>
<body><main>%s</main>
<dialog id="image-dialog"><div class="dialog-toolbar"><button id="zoom-toggle" type="button">放大</button><button id="dialog-close" type="button" aria-label="关闭">关闭</button></div><div class="dialog-scroll"><img alt=""></div></dialog>
<script>
const d = document.getElementById('image-dialog');
const scroll = d.querySelector('.dialog-scroll');
const zoom = document.getElementById('zoom-toggle');
document.querySelectorAll('img.article-image').forEach(img => img.addEventListener('click', () => { d.querySelector('img').src = img.src; d.querySelector('img').alt = img.alt; scroll.classList.remove('zoomed'); zoom.textContent = '放大'; d.showModal(); }));
zoom.addEventListener('click', () => { const on = scroll.classList.toggle('zoomed'); zoom.textContent = on ? '还原' : '放大'; });
document.getElementById('dialog-close').addEventListener('click', () => d.close());
d.addEventListener('click', e => { if (e.target === d) d.close(); });
</script>
</body></html>""" % (html.escape(title), content)


def main(argv=None):
    parser = argparse.ArgumentParser(description="将中文图文 Markdown 渲染为独立 HTML")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--asset-root")
    parser.add_argument("--title")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    input_path = Path(args.input).expanduser().resolve(strict=True)
    if not input_path.is_file():
        fail(f"输入不是文件: {input_path}")
    output_path = Path(args.output).expanduser().resolve()
    if output_path == input_path:
        fail("输出不能覆盖输入 Markdown 文件")
    if output_path.exists() and not args.overwrite:
        fail(f"输出已存在，使用 --overwrite 才能覆盖: {output_path}")
    roots = [safe_root(input_path.parent)]
    if args.asset_root:
        root = safe_root(Path(args.asset_root))
        if root not in roots:
            roots.append(root)
    body = strip_frontmatter(input_path.read_text(encoding="utf-8"))
    title = args.title
    if not title:
        heading = re.search(r"(?m)^#\s+(.+?)\s*$", body)
        title = heading.group(1).strip() if heading else input_path.stem
    content, image_count = render_markdown(body, title, roots)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_html(title, content), encoding="utf-8")
    print(json.dumps({"output": str(output_path), "image_count": image_count, "title": title}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RenderError, OSError, UnicodeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(1)
