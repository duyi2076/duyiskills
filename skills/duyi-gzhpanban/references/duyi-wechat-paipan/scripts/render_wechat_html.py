#!/usr/bin/env python3
"""Render fixed inline themes and source-faithful emphasis blocks for WeChat."""
import argparse
import base64
import html
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import cssutils
import markdown
from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
STYLE_FILE = SCRIPT_DIR.parents[1] / "duyi-wechat-css-layer" / "templates" / "styles.md"
INLINE_CSS_SCRIPT = SCRIPT_DIR / "inline_css.mjs"
MD_EXTENSIONS = ["extra", "sane_lists"]
INHERITED = ("font-family", "font-size", "line-height", "color", "font-weight", "font-style", "text-align", "letter-spacing", "white-space")
cssutils.log.setLevel("FATAL")

def strip_frontmatter(text):
    return re.sub(r"^---\n.*?\n---\n?", "", text, flags=re.DOTALL)


def extract_title(text):
    text = text.replace("\r\n", "\n")
    title = "Untitled"
    frontmatter = re.match(r"^---\n(.*?)\n---(?:\n|$)", text, re.S)
    if frontmatter:
        import yaml
        metadata = yaml.safe_load(frontmatter.group(1))
        if isinstance(metadata, dict) and metadata.get("title"):
            title = str(metadata["title"])
        text = text[frontmatter.end():]
    lines = text.strip("\n").splitlines()
    if lines and re.match(r"^ {0,3}#\s+", lines[0]):
        heading = re.sub(r"^ {0,3}#\s+", "", lines.pop(0)).strip()
        title = BeautifulSoup(markdown.markdown(heading), "html.parser").get_text()
    return title, "\n".join(lines).strip("\n")


def read_braced(text, start):
    if start >= len(text) or text[start] != "{":
        return None, start
    depth = 0
    chars = []
    i = start
    while i < len(text):
        ch = text[i]
        if ch == "{":
            if depth:
                chars.append(ch)
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return "".join(chars), i + 1
            chars.append(ch)
        else:
            chars.append(ch)
        i += 1
    return None, start


def replace_underbrace(expr):
    needle = r"\underbrace"
    out = []
    i = 0
    while i < len(expr):
        idx = expr.find(needle, i)
        if idx < 0:
            out.append(expr[i:])
            break
        out.append(expr[i:idx])
        pos = idx + len(needle)
        inner, pos_after_inner = read_braced(expr, pos)
        if inner is None:
            out.append(needle)
            i = pos
            continue
        pos = pos_after_inner
        label = ""
        if pos < len(expr) and expr[pos] == "_":
            candidate, pos_after_label = read_braced(expr, pos + 1)
            if candidate is not None:
                label = latex_to_text(candidate)
                pos = pos_after_label
        inner_text = latex_to_text(inner)
        out.append(f"{inner_text}\uff08{label}\uff09" if label else inner_text)
        i = pos
    return "".join(out)


def replace_frac(expr):
    needle = r"\frac"
    out = []
    i = 0
    while i < len(expr):
        idx = expr.find(needle, i)
        if idx < 0:
            out.append(expr[i:])
            break
        out.append(expr[i:idx])
        pos = idx + len(needle)
        numerator, pos_after_num = read_braced(expr, pos)
        denominator, pos_after_den = read_braced(expr, pos_after_num)
        if numerator is None or denominator is None:
            out.append(needle)
            i = pos
            continue
        out.append(f"(({latex_to_text(numerator)}) / ({latex_to_text(denominator)}))")
        i = pos_after_den
    return "".join(out)


def latex_to_text(expr):
    expr = expr.strip()
    previous = None
    while previous != expr:
        previous = expr
        expr = replace_underbrace(expr)
        expr = replace_frac(expr)
    expr = re.sub(r"\\text\{([^{}]*)\}", r"\1", expr)
    while r"\sqrt" in expr:
        pos = expr.index(r"\sqrt")
        inner, end = read_braced(expr, pos + len(r"\sqrt"))
        if inner is None:
            raise ValueError("unsupported root notation; retain the source formula and provide a formula image")
        expr = expr[:pos] + "√(" + latex_to_text(inner) + ")" + expr[end:]
    replacements = {
        r"\times": "\u00d7",
        r"\cdot": "\u00b7",
        r"\rightarrow": "\u2192",
        r"\Rightarrow": "\u21d2",
        r"\leftarrow": "\u2190",
        r"\to": "\u2192",
        r"\leq": "\u2264",
        r"\geq": "\u2265",
        r"\neq": "\u2260",
        r"\approx": "\u2248",
        r"\%": "%",
        r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
        r"\epsilon": "ε", r"\theta": "θ", r"\lambda": "λ", r"\mu": "μ",
        r"\sigma": "σ", r"\pi": "π", r"\omega": "ω", r"\Delta": "Δ",
        r"\infty": "∞", r"\pm": "±", r"\div": "÷",
    }
    expr = re.sub(r"\\(?:[a-zA-Z]+|%)", lambda m: replacements.get(m.group(0), m.group(0)), expr)
    unknown = re.findall(r"\\[a-zA-Z]+", expr)
    if unknown:
        raise ValueError("unsupported formula commands: " + ", ".join(sorted(set(unknown))) + "; preserve the source and provide a formula image")
    for marker, alphabet in (("^", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁽⁾"), ("_", "₀₁₂₃₄₅₆₇₈₉₊₋₍₎")):
        mapping = str.maketrans("0123456789+-()", alphabet)
        pos = 0
        while (pos := expr.find(marker, pos)) >= 0:
            start = pos + 1
            if start >= len(expr):
                raise ValueError("incomplete formula script")
            if expr[start] == "{":
                content, end = read_braced(expr, start)
                if content is None: raise ValueError("unclosed formula script")
                content = latex_to_text(content)
            else:
                content, end = expr[start], start + 1
            replacement = content.translate(mapping) if all(ch in "0123456789+-()" for ch in content) else marker + "(" + content + ")"
            expr = expr[:pos] + replacement + expr[end:]
            pos += len(replacement)
    expr = expr.replace("{", "(").replace("}", ")")
    expr = re.sub(r"\s+", " ", expr)
    expr = re.sub(r"\s*([=+\-\u00d7\u00b7\u2192\u21d2\u2190\u2264\u2265\u2260\u2248])\s*", r" \1 ", expr)
    expr = re.sub(r"\(\s+", "(", expr)
    expr = re.sub(r"\s+\)", ")", expr)
    return re.sub(r"\s+", " ", expr).strip()


def math_block_html(raw):
    text = html.escape(latex_to_text(raw))
    return f'\n<section class="duyi-math-block" aria-label="公式">{text}</section>\n'


def math_inline_html(raw):
    text = html.escape(latex_to_text(raw))
    return f'<span class="duyi-math-inline" aria-label="公式">{text}</span>'


def protect_math(text):
    text = re.sub(
        r"(?ms)^[ \t]*\$\$[ \t]*\n(.*?)[ \t]*\n[ \t]*\$\$[ \t]*(?=\n|$)",
        lambda m: math_block_html(m.group(1)),
        text,
    )
    text = re.sub(
        r"(?ms)^[ \t]*\\\[(.*?)\\\][ \t]*(?=\n|$)",
        lambda m: math_block_html(m.group(1)),
        text,
    )
    text = re.sub(
        r"(?m)^[ \t]*\$\$(.+?)\$\$[ \t]*$",
        lambda m: math_block_html(m.group(1)),
        text,
    )
    text = re.sub(
        r"(?m)^[ \t]*\\\[(.+?)\\\][ \t]*$",
        lambda m: math_block_html(m.group(1)),
        text,
    )
    text = re.sub(r"\\\((.+?)\\\)", lambda m: math_inline_html(m.group(1)), text)
    text = re.sub(
        r"(?<![\\$])\$(?!\$)([^$\n]+?)(?<![\\$])\$(?!\$)",
        lambda m: math_inline_html(m.group(1)),
        text,
    )
    return text



def load_themes():
    source = STYLE_FILE.read_text(encoding="utf-8")
    entries = re.findall(r"^## \d+ ([a-z]+)：([^\n]+)\n.*?```css\n(.*?)\n```", source, re.M | re.S)
    if len(entries) != 15 or len({entry[0] for entry in entries}) != 15:
        raise ValueError("styles.md must define exactly 15 distinct themes")
    return {key: {"name": name, "css": css} for key, name, css in entries}


def normalize_style(style):
    themes = load_themes()
    key = style.strip().lower()
    if key not in themes:
        key = next((key for key, theme in themes.items() if theme["name"].lower() == style.lower()), "")
    if key not in themes:
        raise ValueError("unknown style; choose " + ", ".join(themes))
    return key


def declarations(value):
    return {prop.name: prop.value for prop in cssutils.parseStyle(value)}


def style_text(values):
    return ";".join(f"{key}:{value}" for key, value in values.items()) + ";"


def compatible_style(style):
    values = {}
    for prop in style:
        key, value = prop.name, prop.value
        if key in ("box-shadow", "counter-reset", "counter-increment", "content"):
            continue
        if key == "background":
            key = "background-color"
            if "gradient(" in value:
                colors = re.findall(r"#[0-9a-fA-F]{3,8}\b", value)
                value = colors[-1] if colors else "transparent"
            elif value == "none":
                value = "transparent"
        values[key] = value
    return values


def build_theme_css(style):
    sheet = cssutils.parseString(load_themes()[normalize_style(style)]["css"])
    rules, body, quote, pre = [], {}, {}, {}
    for rule in sheet:
        if rule.type != rule.STYLE_RULE:
            continue
        selectors = [part.strip() for part in rule.selectorText.split(",") if ":" not in part]
        if not selectors:
            continue
        values = compatible_style(rule.style)
        if "body" in selectors:
            body = values.copy()
        if "blockquote" in selectors:
            quote = values.copy()
        if "pre" in selectors:
            pre = values.copy()
        selectors = [".duyi-article" if part == "body" else part for part in selectors]
        if "blockquote" in selectors:
            selectors.append(".duyi-emphasis")
        if "ul" in selectors:
            selectors.append("ol")
        rules.append(",".join(selectors) + "{" + style_text(values) + "}")
    rules.extend([
        "#output{margin:0;padding:0;" + style_text({key: body[key] for key in INHERITED if key in body}) + "}",
        "section,figure,img,table{box-sizing:border-box;}",
        "figure{margin:20px 0;padding:0;}",
        "img{display:block;max-width:100%;width:100%;height:auto;margin:0 auto;}",
        "blockquote p,.duyi-emphasis p{margin:0 0 8px;}",
        "blockquote p:last-child,.duyi-emphasis p:last-child{margin-bottom:0;}",
        "li>p{margin:0;}",
        ".duyi-table-wrap{max-width:100%;overflow-x:auto;margin:20px 0;}",
        "table{width:100%;border-collapse:collapse;}",
        "th,td{padding:8px 10px;border:1px solid #aaa;text-align:left;}",
        ".duyi-math-block{" + style_text(pre) + "max-width:100%;white-space:normal;overflow-wrap:anywhere;}",
        ".duyi-math-text{white-space:normal;overflow-wrap:anywhere;}",
        ".duyi-math-inline{font-family:monospace;}",
        "mark{" + style_text(quote) + "display:inline;margin:0;padding:0 3px;border:none;}",
        "a{color:inherit;}",
        "em{font-style:italic;}",
        "s,del{text-decoration:line-through;}",
        "pre{max-width:100%;box-sizing:border-box;white-space:pre;}",
    ])
    return "\n".join(rules)


def convert_emphasis(body):
    lines, result, block = body.splitlines(), [], None
    fence = None
    for line in lines:
        stripped = line.strip()
        code_fence = re.match(r"^(`{3,}|~{3,})", stripped)
        if code_fence and block is None:
            token = code_fence.group(1)[0]
            fence = None if fence == token else token
        if fence is None and stripped == "::: emphasis":
            if block is not None:
                raise ValueError("nested emphasis block")
            block = []
        elif fence is None and stripped == ":::" and block is not None:
            parsed = markdown.markdown("\n".join(block), extensions=MD_EXTENSIONS)
            soup = BeautifulSoup(parsed, "html.parser")
            if not soup.get_text(strip=True) or any(tag.name not in ("p", "strong", "em", "a", "code", "mark", "br", "span") for tag in soup.find_all(True)):
                raise ValueError("emphasis must contain source sentences or paragraphs, without headings, lists or pictures")
            result.extend(["", '<section class="duyi-emphasis" role="note" aria-label="重点">' + str(soup) + "</section>", ""])
            block = None
        elif block is not None:
            block.append(line)
        else:
            result.append(line)
    if block is not None:
        raise ValueError("unclosed emphasis block")
    return "\n".join(result)


def protect_code(body):
    prefix = "DUYI_PROTECTED_CODE_"
    while prefix in body: prefix += "X"
    snippets = {}
    def stash(match):
        source = match.group(0)
        code = BeautifulSoup(markdown.markdown(source, extensions=MD_EXTENSIONS), "html.parser")
        fragment = code.find("pre") or code.find("code")
        if fragment is None:
            fragment = BeautifulSoup(source, "html.parser").find(("pre", "code"))
        token = prefix + str(len(snippets)) + "_END"
        snippets[token] = str(fragment)
        return "\n\n" + token + "\n\n" if getattr(fragment, "name", None) == "pre" else token
    body = re.sub(r"(?m)^[ \t]{0,3}(`{3,}|~{3,})[^\n]*\n[\s\S]*?^[ \t]{0,3}\1[ \t]*(?=\n|$)", stash, body)
    body = re.sub(r"<(pre|code)\b[^>]*>[\s\S]*?</\1>", stash, body, flags=re.I)
    # Use the Markdown parser to recognize indented code in its list context.
    pristine = BeautifulSoup(markdown.markdown(body, extensions=MD_EXTENSIONS), "html.parser")
    for pre in pristine.find_all("pre"):
        code_lines = pre.get_text().rstrip("\n").splitlines()
        pattern = r"(?m)^" + "\n".join(r"(?: {4,}|\t+)" + re.escape(line) if line else r"[ \t]*" for line in code_lines) + r"(?:\n|$)"
        token = prefix + str(len(snippets)) + "_END"
        replaced, count = re.subn(pattern, "\n\n" + token + "\n\n", body, count=1)
        if count:
            snippets[token] = str(pre)
            body = replaced
    body = re.sub(r"(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)", stash, body)
    return body, snippets


def markdown_to_soup(body):
    protected, snippets = protect_code(body)
    protected = protect_math(protected)
    protected = re.sub(r"(?<!\\)\\\$", "$", protected)
    protected = re.sub(r"(?<![=])==([^=\n]+)==(?![=])", lambda m: "<mark>" + html.escape(m.group(1)) + "</mark>", protected)
    protected = convert_emphasis(protected)
    for token, snippet in snippets.items(): protected = protected.replace(token, snippet)
    soup = BeautifulSoup(markdown.markdown(protected, extensions=MD_EXTENSIONS, output_format="html5"), "html.parser")
    for block in soup.select(".duyi-emphasis"):
        if block.find(("pre", "img", "table", "h1", "h2", "h3", "ul", "ol")):
            raise ValueError("emphasis must contain source sentences or paragraphs")
    for paragraph in list(soup.find_all("p")):
        if paragraph.find(("pre", "section"), recursive=False): paragraph.unwrap()
    for heading in soup.find_all("h1"):
        heading.name = "h2"
    for paragraph in list(soup.find_all("p")):
        if len(list(paragraph.children)) == 1 and paragraph.img:
            paragraph.name = "figure"
    for table in list(soup.find_all("table")):
        wrapper = soup.new_tag("section", attrs={"class": "duyi-table-wrap"})
        table.wrap(wrapper)
    for br in soup.find_all("br"):
        br.replace_with(" ")
    return soup


def inline_css(fragment, css):
    proc = subprocess.run(["node", str(INLINE_CSS_SCRIPT)], input=json.dumps({"html": fragment, "css": css}), text=True, capture_output=True)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError("CSS inliner failed: " + (proc.stderr or "empty output")[:1000])
    return proc.stdout


def rgb(value):
    value = value.strip().lower()
    if value == "white": return (255, 255, 255)
    if value == "black": return (0, 0, 0)
    if re.fullmatch(r"#[0-9a-f]{3}", value):
        return tuple(int(ch * 2, 16) for ch in value[1:])
    if re.fullmatch(r"#[0-9a-f]{6}", value):
        return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
    match = re.fullmatch(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", value)
    return tuple(map(int, match.groups())) if match else None


def contrast(first, second):
    colors = rgb(first), rgb(second)
    if any(color is None for color in colors): return None
    luminances = []
    for color in colors:
        normalized = [channel / 255 for channel in color]
        linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4 for channel in normalized]
        luminances.append(sum(channel * weight for channel, weight in zip(linear, (.2126, .7152, .0722))))
    return (max(luminances) + .05) / (min(luminances) + .05)


def expand_inheritance(soup):
    defaults = {"font-family": "sans-serif", "font-size": "16px", "line-height": "1.82", "color": "#2b2b2b", "font-weight": "400", "font-style": "normal", "text-align": "left", "letter-spacing": "normal", "white-space": "normal"}
    def visit(tag, inherited, background):
        values = declarations(tag.get("style", ""))
        for key in INHERITED:
            if key not in values or values[key] in ("inherit", "unset"):
                values[key] = inherited[key]
        if values.get("background-color") not in (None, "transparent"):
            background = values["background-color"]
        # A nested strong may use the same color as its quote background.
        if tag.name in ("strong", "mark", "code") and (tag.find_parent(attrs={"role": "note"}) or tag.find_parent("blockquote")):
            ratio = contrast(values["color"], background)
            if ratio is not None and ratio < 4.5:
                inherited_ratio = contrast(inherited["color"], background)
                if inherited_ratio is not None and inherited_ratio >= 4.5:
                    values["color"] = inherited["color"]
        tag["style"] = style_text(values)
        new_inherited = {key: values[key] for key in INHERITED}
        for child in tag.children:
            if getattr(child, "name", None): visit(child, new_inherited, background)
    visit(soup.find("section"), defaults, "#fff")


def postprocess_wechat_html(fragment, style="minimal"):
    soup = BeautifulSoup(fragment, "html.parser")
    expand_inheritance(soup)
    counter_style = None
    for rule in cssutils.parseString(load_themes()[normalize_style(style)]["css"]):
        if rule.type == rule.STYLE_RULE and rule.selectorText in ("li:before", "li::before") and "counter(" in rule.style.getPropertyValue("content"):
            counter_style = compatible_style(rule.style)
    for container in list(soup.find_all(("ul", "ol"))):
        ordered = container.name == "ol"
        try: start = int(container.get("start", 1))
        except ValueError: start = 1
        for number, item in enumerate(container.find_all("li", recursive=False), start):
            marker = soup.new_tag("span")
            values = {key: value for key, value in declarations(item["style"]).items() if key in INHERITED}
            if counter_style:
                values.update(counter_style)
            values["margin-right"] = "0.5em"
            marker["style"] = style_text(values)
            marker.string = f"{number:02d} " if counter_style else (f"{number}. " if ordered else "• ")
            item.insert(0, marker)
            item.name = "section"
        container.name = "section"
    for tag in soup.find_all(True):
        tag.attrs.pop("class", None)
        if tag.get("id") != "output": tag.attrs.pop("id", None)
        for attr in list(tag.attrs):
            if attr.startswith("data-"): tag.attrs.pop(attr, None)
    return str(soup).strip() + "\n"


def qa_gate(fragment):
    soup, issues = BeautifulSoup(fragment, "html.parser"), []
    if len(soup.select("#output")) != 1: issues.append("missing_or_duplicate_output_wrapper")
    if re.search(r"<(style|script|iframe|object|form)\b", fragment, re.I): issues.append("forbidden_element")
    allowed = {"section", "div", "p", "h2", "h3", "h4", "h5", "h6", "blockquote", "strong", "mark", "em", "s", "del", "span", "code", "pre", "a", "img", "figure", "figcaption", "hr", "table", "thead", "tbody", "tr", "th", "td", "sup", "sub"}
    for tag in soup.find_all(True):
        if tag.name not in allowed: issues.append("unsupported_element:" + tag.name)
        if not tag.get("style"): issues.append("missing_inline_style:" + tag.name)
        props = declarations(tag.get("style", ""))
        if props.get("position") in ("fixed", "sticky") or "background-image" in props or any("url(" in value.lower() or "expression(" in value.lower() for value in props.values()):
            issues.append("unsupported_css")
        if not all(props.get(key) for key in ("font-family", "font-size", "line-height", "color")):
            issues.append("incomplete_text_style:" + tag.name)
        for attr in tag.attrs:
            if attr == "class" or attr.startswith(("data-", "on")) or attr == "id" and tag.get("id") != "output":
                issues.append("forbidden_attribute:" + attr)
        for attr in ("src", "href"):
            if urlparse(tag.get(attr, "")).scheme.lower() in ("javascript", "vbscript"): issues.append("unsafe_url")
        if tag.name == "img":
            source = tag.get("src", "")
            parsed = urlparse(source)
            if not source:
                issues.append("missing_image_source")
            elif parsed.scheme in ("", "file") and not Path(unquote(parsed.path)).is_file():
                issues.append("missing_local_image")
        if tag.name == "p" and not tag.find_parent(("pre", "code")):
            text = "".join(node for node in tag.find_all(string=True) if not node.find_parent(("pre", "code")))
            if re.search(r":::|\$\$|\\(?:text|times|rightarrow|underbrace)\b|\\n", text): issues.append("raw_markup")
    for block in soup.select('section[role="note"],blockquote'):
        parent_style = declarations(block.get("style", ""))
        background = parent_style.get("background-color")
        ancestor = block.parent
        while (not background or background == "transparent") and getattr(ancestor, "name", None):
            background = declarations(ancestor.get("style", "")).get("background-color")
            ancestor = ancestor.parent
        background = background or "#fff"
        for tag in [block, *block.find_all(True)]:
            own = declarations(tag.get("style", ""))
            ratio = contrast(own.get("color", ""), own.get("background-color") if own.get("background-color") not in (None, "transparent") else background)
            if ratio is not None and ratio < 4.5: issues.append("low_contrast_emphasis")
    return {"ok": not issues, "issues": sorted(set(issues)), "emphasis_blocks": len(soup.select('section[role="note"]'))}


def render_document(markdown_text, style="minimal"):
    style = normalize_style(style)
    title, body = extract_title(markdown_text)
    soup = markdown_to_soup(body)
    body_html = "\n".join(str(node) for node in soup.contents).strip()
    fragment = '<section id="output"><section class="duyi-article">' + body_html + "</section></section>"
    return title, postprocess_wechat_html(inline_css(fragment, build_theme_css(style)), style)


def resolve_images(fragment, image_base, embed=False):
    soup = BeautifulSoup(fragment, "html.parser")
    for image in soup.find_all("img"):
        source = image.get("src", "")
        parsed = urlparse(source)
        if parsed.scheme not in ("", "file"): continue
        path = Path(unquote(parsed.path))
        if not path.is_absolute(): path = Path(image_base) / path
        path = path.resolve()
        if not path.is_file():
            raise ValueError("local image not found: " + str(path))
        if embed and path.is_file():
            mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            image["src"] = "data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        else:
            image["src"] = str(path)
    return str(soup)


def render_standalone(title, fragment, base_href="", image_base="."):
    fragment = resolve_images(fragment, image_base, embed=True)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="wechat-delivery-mode" content="preview"><title>{html.escape(title)}</title>
<style>body{{margin:0;background:#f2f2f2}}.phone{{width:100%;max-width:390px;min-height:844px;margin:0 auto;padding:0;background:#fff}}</style></head>
<body><main class="phone">{fragment}</main></body></html>\n'''


def make_copy_document(title, fragment):
    soup = BeautifulSoup(fragment, "html.parser")
    article = soup.select_one("#output > section")
    if article is None:
        raise ValueError("copy conversion requires the rendered article")
    body_style = declarations(article["style"])
    images = []
    for number, image in enumerate(list(article.find_all("img")), 1):
        container = image.find_parent("figure") or image.find_parent("p") or image
        before, after = container.find_previous_sibling(), container.find_next_sibling()
        description = image.get("alt", "").strip() or "原图"
        images.append({"index": number, "description": description, "source": image["src"],
                       "before": before.get_text("", strip=True)[-100:] if before else "",
                       "after": after.get_text("", strip=True)[:100] if after else ""})
        # Keep inline pictures inside their paragraph; a nested p would be
        # repaired differently by the browser and the target editor.
        placeholder = soup.new_tag("p" if container.name == "figure" else "span", attrs={"aria-label": "图片位置"})
        values = {key: value for key, value in declarations(image["style"]).items() if key in INHERITED}
        values.update({"overflow-wrap": "anywhere"})
        if placeholder.name == "p":
            values["margin"] = "20px 0"
        placeholder["style"] = style_text(values)
        placeholder.string = f"[图片 {number}：{description}]"
        image.replace_with(placeholder)
        if container.name == "figure":
            container.unwrap()
    for link in article.find_all("a"):
        link.name = "span"
        for attr in ("href", "target", "rel"):
            link.attrs.pop(attr, None)
    block_tags = {"section", "div", "p", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "figure", "figcaption", "hr", "table", "thead", "tbody", "tr", "th", "td"}
    def visit(tag, background):
        values = declarations(tag["style"])
        background = values.get("background-color") if values.get("background-color") not in (None, "transparent") else background
        if tag.name in block_tags:
            values["background-color"] = background
        tag["style"] = style_text(values)
        for attr in list(tag.attrs):
            if attr in ("id", "class") or attr.startswith(("data-", "on")):
                tag.attrs.pop(attr, None)
        for child in tag.children:
            if getattr(child, "name", None):
                visit(child, background)
    visit(article, body_style.get("background-color", "#fff"))
    body_style.update({"max-width": "390px", "box-sizing": "border-box", "margin": "0 auto"})
    body_html = "\n".join(str(node) for node in article.contents)
    document = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="wechat-delivery-mode" content="copy"><title>{html.escape(title)}</title></head>
<body style="{html.escape(style_text(body_style), quote=True)}">{body_html}</body></html>\n'''
    return document, images


def qa_copy_gate(document):
    soup = BeautifulSoup(document, "html.parser")
    issues = []
    if soup.body is None:
        return {"ok": False, "issues": ["missing_copy_body"], "emphasis_blocks": 0}
    if soup.find(("style", "script", "button", "iframe", "form", "object")):
        issues.append("forbidden_copy_element")
    if soup.find("img") or soup.find("a", href=True):
        issues.append("copy_requires_image_positions_and_plain_links")
    for tag in soup.find_all(True):
        if any(attr in ("id", "class") or attr.startswith(("data-", "on")) for attr in tag.attrs):
            issues.append("forbidden_copy_attribute")
    for tag in soup.body.find_all(recursive=False):
        if declarations(tag.get("style", "")).get("background-color") in (None, "transparent"):
            issues.append("copy_depends_on_body_background")
    wrapped = '<section id="output" style="' + html.escape(soup.body.get("style", ""), quote=True) + '">' + "".join(str(node) for node in soup.body.contents) + "</section>"
    gate = qa_gate(wrapped)
    issues.extend(gate["issues"])
    return {"ok": not issues, "issues": sorted(set(issues)), "emphasis_blocks": gate["emphasis_blocks"]}


def write_copy_assets(images, output_dir, stem):
    output_dir = Path(output_dir)
    asset_dir = output_dir / f"{stem}-原图"
    asset_dir.mkdir(parents=True, exist_ok=True)
    entries, cards = [], []
    for image in images:
        entry = dict(image)
        parsed = urlparse(image["source"])
        picture = ""
        if parsed.scheme in ("", "file"):
            original = Path(unquote(parsed.path)).resolve()
            if not original.is_file():
                raise ValueError("local image not found: " + str(original))
            copied = asset_dir / f"{image['index']:02d}-{original.name}"
            if copied.resolve() != original:
                shutil.copy2(original, copied)
            data = original.read_bytes()
            entry.update({"file": str(copied), "sha256": hashlib.sha256(data).hexdigest()})
            mime = mimetypes.guess_type(original.name)[0] or "application/octet-stream"
            uri = "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
            picture = '<img alt="' + html.escape(image["description"], quote=True) + '" src="' + uri + '" style="display:block;max-width:100%;height:auto">'
        else:
            entry.update({"file": None, "sha256": None})
            picture = "<p>原图引用：" + html.escape(image["source"]) + "</p>"
        cards.append(f'<section style="margin:32px 0"><h2>图片 {image["index"]}</h2><p>前文：{html.escape(image["before"])}</p>{picture}<p>后文：{html.escape(image["after"])}</p></section>')
        entries.append(entry)
    manifest = output_dir / f"{stem}-配图清单.json"
    manifest.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    page = output_dir / f"{stem}-配图复制.html"
    page.write_text('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="wechat-delivery-mode" content="preview"><title>配图</title></head><body style="max-width:780px;margin:auto;padding:24px;font:16px/1.8 sans-serif">' + "".join(cards) + "</body></html>\n", encoding="utf-8")
    instructions = output_dir / f"{stem}-复制使用说明.md"
    instructions.write_text(
        "# 复制到公众号\n\n"
        "1. 打开选定样式的 copy.html，用全选、复制，将正文粘贴到微信后台正文编辑器。\n"
        "2. 打开配图复制页，对原图点击右键复制图片，在对应编号的位置粘贴图片，再删除占位文字。也可以从原图目录选取图片。\n"
        "3. 标题、作者、封面在后台对应栏目填写。\n"
        "4. 用微信后台手机预览检查重点、深色背景、段落和图片顺序。\n\n"
        "含图预览和总览页用于比较样式；复制正文使用专用 copy.html。整篇带图一次粘贴是否保留完整，以微信后台实测为准。\n"
        "文件生成不操作剪贴板、不上传图片、不保存草稿。远程图片如未附原文件，按清单另行准备。\n",
        encoding="utf-8")
    return {"images": len(entries), "image_manifest": str(manifest), "image_copy_page": str(page), "instructions": str(instructions)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?")
    parser.add_argument("--style", default="minimal")
    parser.add_argument("--mode", choices=("copy", "api"), default="copy")
    parser.add_argument("--output")
    parser.add_argument("--standalone", action="store_true", help="api: browser preview only; never submit this output")
    parser.add_argument("--list-styles", action="store_true")
    parser.add_argument("--no-gate", action="store_true", help="debug only; never use for delivery")
    args = parser.parse_args()
    if args.list_styles:
        print("\n".join(load_themes()))
        return
    if not args.input or not args.output: parser.error("input and --output are required")
    input_path, output_path = Path(args.input).resolve(), Path(args.output).resolve()
    try:
        title, fragment = render_document(input_path.read_text(encoding="utf-8"), args.style)
        fragment = resolve_images(fragment, input_path.parent)
        gate = qa_gate(fragment)
        if not gate["ok"] and not args.no_gate:
            print(json.dumps(gate, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(2)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        assets = {}
        if args.mode == "copy":
            output, images = make_copy_document(title, fragment)
            gate = qa_copy_gate(output)
            if not gate["ok"] and not args.no_gate:
                print(json.dumps(gate, ensure_ascii=False), file=sys.stderr)
                raise SystemExit(2)
            assets = write_copy_assets(images, output_path.parent, input_path.stem)
        else:
            output = render_standalone(title, fragment, image_base=input_path.parent) if args.standalone else fragment
        output_path.write_text(output, encoding="utf-8")
        print(json.dumps({"output": str(output_path), "style": normalize_style(args.style), "mode": args.mode, **gate, **assets}, ensure_ascii=False))
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
