#!/usr/bin/env python3
"""Generate a theme set through the same gated renderer as single outputs."""
import argparse
import html
import importlib.util
import json
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output_dir")
    parser.add_argument("styles", nargs="*")
    parser.add_argument("--mode", choices=("copy", "api"), default="copy")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--all", action="store_true")
    modes.add_argument("--preview", action="store_true")
    modes.add_argument("--style", nargs="+")
    args = parser.parse_args()
    renderer_path = Path(__file__).resolve().parents[2] / "duyi-wechat-paipan" / "scripts" / "render_wechat_html.py"
    spec = importlib.util.spec_from_file_location("wechat_renderer", renderer_path)
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)
    themes = renderer.load_themes()
    if args.styles and (args.all or args.preview or args.style):
        parser.error("choose a mode or positional styles")
    styles = args.style or args.styles or (["minimal", "medium", "stripe", "wired", "ft", "course"] if args.preview else list(themes))
    styles = list(dict.fromkeys(renderer.normalize_style(style) for style in styles))
    source, output_dir = Path(args.input).resolve(), Path(args.output_dir).resolve()
    text = source.read_text(encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)
    cards, rows, results = [], [], []
    assets = {}
    for style in styles:
        title, fragment = renderer.render_document(text, style)
        fragment = renderer.resolve_images(fragment, source.parent)
        gate = renderer.qa_gate(fragment)
        if not gate["ok"]:
            raise SystemExit(json.dumps({"style": style, **gate}, ensure_ascii=False))
        stem = f"{source.stem}-{style}-{args.mode}"
        delivery = output_dir / f"{stem}.html"
        preview, focus = [output_dir / f"{stem}-{suffix}.html" for suffix in ("preview", "focus")]
        if args.mode == "copy":
            content, images = renderer.make_copy_document(title, fragment)
            gate = renderer.qa_copy_gate(content)
            if not gate["ok"]:
                raise SystemExit(json.dumps({"style": style, **gate}, ensure_ascii=False))
            if not assets:
                assets = renderer.write_copy_assets(images, output_dir, source.stem)
        else:
            content = fragment
        delivery.write_text(content, encoding="utf-8")
        preview.write_text(renderer.render_standalone(title, fragment, image_base=source.parent), encoding="utf-8")
        soup = BeautifulSoup(fragment, "html.parser")
        block = soup.select_one('section[role="note"]')
        article = soup.select_one("#output > section")
        nodes = []
        if block:
            previous = block.find_previous_sibling()
            following = block.find_next_sibling()
            nodes = [node for node in (previous, block, following) if node]
        else:
            nodes = list(article.children)[:4]
        sample = '<section id="output" style="' + html.escape(soup.select_one("#output")["style"], quote=True) + '"><section style="' + html.escape(article["style"], quote=True) + '">' + "".join(str(node) for node in nodes) + "</section></section>"
        focus.write_text(renderer.render_standalone(title, sample, image_base=source.parent), encoding="utf-8")
        name = html.escape(themes[style]["name"])
        label = "打开复制版" if args.mode == "copy" else "查看 API 片段"
        cards.append(f'<article><h2>{name}</h2><iframe title="{name}" loading="lazy" src="{quote(focus.name)}"></iframe><a href="{quote(preview.name)}">含图全文预览</a><a href="{quote(delivery.name)}">{label}</a></article>')
        rows.append(f"| {style} | [{preview.name}]({quote(preview.name)}) | [{delivery.name}]({quote(delivery.name)}) |")
        results.append({"style": style, "name": themes[style]["name"], "mode": args.mode, "delivery": str(delivery), "preview": str(preview), "focus": str(focus), **gate})
    overview = output_dir / f"00_公众号风格总览-{args.mode}.html"
    overview.write_text('''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="wechat-delivery-mode" content="preview"><title>公众号排版风格</title><style>
body{margin:0;background:#f3f3f3;color:#222;font-family:-apple-system,"PingFang SC",sans-serif}main{max-width:1280px;margin:auto;padding:24px}h1{font-size:24px}main>p{line-height:1.7;color:#555}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px}article{background:#fff;border:1px solid #ddd;padding:16px}h2{font-size:18px;margin:0 0 16px}iframe{width:100%;height:480px;border:0;background:#fff}a{display:block;padding:14px 0 0;color:#333}
</style></head><body><main><h1>同一篇文章，不同排版</h1><p>比较重点段落的呈现，点击阅读全文查看整篇文章。</p><div class="grid">''' + "".join(cards) + "</div></main></body></html>", encoding="utf-8")
    (output_dir / f"风格目录-{args.mode}.md").write_text("# 公众号排版风格\n\n| 风格 | 含图全文预览 | 交付 HTML |\n|---|---|---|\n" + "\n".join(rows) + "\n", encoding="utf-8")
    (output_dir / f"渲染检查-{args.mode}.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"overview": str(overview), "mode": args.mode, "styles": len(results), "emphasis_blocks": results[0]["emphasis_blocks"], **assets}, ensure_ascii=False))


if __name__ == "__main__":
    main()
