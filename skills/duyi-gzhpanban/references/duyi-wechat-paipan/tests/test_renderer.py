import base64
import importlib.util
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "render_wechat_html.py"
spec = importlib.util.spec_from_file_location("renderer", SCRIPT)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class RendererTests(unittest.TestCase):
    def test_emphasis_keeps_words_order_and_punctuation(self):
        source = "# 文章标题\n\n开头的句子。\n\n::: emphasis\n这是**带条件的重点**，不能删句号。\n:::\n\n最后一句。"
        title, fragment = renderer.render_document(source, "event")
        soup = BeautifulSoup(fragment, "html.parser")
        self.assertEqual(title, "文章标题")
        self.assertEqual(soup.get_text().strip(), "开头的句子。\n这是带条件的重点，不能删句号。\n最后一句。")
        self.assertEqual(len(soup.select('section[role="note"]')), 1)
        self.assertTrue(renderer.qa_gate(fragment)["ok"])

    def test_all_themes_style_every_text_node_and_keep_emphasis(self):
        source = "# 标题\n\n普通正文。\n\n::: emphasis\n只有先验证，**再投入**才有依据。\n:::\n\n> 作者的原话。\n\n## 真实章节\n\n结尾。"
        for theme in renderer.load_themes():
            with self.subTest(theme=theme):
                _, fragment = renderer.render_document(source, theme)
                gate = renderer.qa_gate(fragment)
                self.assertTrue(gate["ok"], gate)
                self.assertEqual(gate["emphasis_blocks"], 1)
                soup = BeautifulSoup(fragment, "html.parser")
                self.assertNotIn("::: emphasis", soup.get_text())
                self.assertNotIn("标题", soup.get_text())
                block = soup.select_one('section[role="note"]')
                plain = soup.find("p")
                self.assertNotEqual(block["style"], plain["style"])

    def test_nested_lists_code_tables_and_math_survive(self):
        source = """# 标题

1. 第一项
    - 子项甲
    - 子项乙
2. 第二项

| 类型 | 说明 |
|---|---|
| 甲 | 内容 |

```python
print('literal\\n')
::: emphasis
```

$$收入 = 单价 \\times 人数$$

行内 $a + b$ 完整保留。
"""
        _, fragment = renderer.render_document(source, "linear")
        soup = BeautifulSoup(fragment, "html.parser")
        gate = renderer.qa_gate(fragment)
        self.assertTrue(gate["ok"], gate)
        self.assertEqual(len(soup.find_all("table")), 1)
        self.assertEqual(len(soup.select('section[role="note"]')), 0)
        self.assertIn("literal\\n", soup.code.get_text())
        for text in ("第一项", "子项甲", "子项乙", "第二项", "类型", "收入 = 单价 × 人数", "a + b"):
            self.assertIn(text, soup.get_text())
        self.assertEqual(soup.get_text().count("子项甲"), 1)

    def test_code_is_not_processed_as_math_or_highlight(self):
        source = "# 标题\n\n`$x$ ==plain== \\times`\n\n```python\n$x$\n  ==plain==\n::: emphasis\n```"
        _, fragment = renderer.render_document(source)
        soup = BeautifulSoup(fragment, "html.parser")
        self.assertEqual(soup.find("code").get_text(), "$x$ ==plain== \\times")
        self.assertEqual(soup.pre.code.get_text(), "$x$\n  ==plain==\n::: emphasis\n")
        self.assertEqual(renderer.declarations(soup.pre["style"])["white-space"], "pre")
        self.assertEqual(len(soup.find_all("mark")), 0)
        self.assertTrue(renderer.qa_gate(fragment)["ok"])

    def test_formula_in_emphasis_and_unknown_command_boundary(self):
        _, fragment = renderer.render_document("# 标题\n\n::: emphasis\n只在 $\\alpha + \\beta = \\sqrt{x^2 + y^2}$ 成立时才继续。\n:::")
        soup = BeautifulSoup(fragment, "html.parser")
        self.assertIn("α + β = √(x² + y²)", soup.get_text())
        self.assertTrue(renderer.qa_gate(fragment)["ok"])
        with self.assertRaisesRegex(ValueError, "unsupported formula commands"):
            renderer.render_document("# 标题\n\n$\\unknown{x}$")
        _, fragment = renderer.render_document("# 标题\n\n$\\frac{a+b}{c-d}$")
        self.assertIn("((a + b) / (c - d))", BeautifulSoup(fragment, "html.parser").get_text())

    def test_indented_code_and_escaped_prices_preserve_source(self):
        source = '# 标题\n\n价格是 \\$199 和 \\$299。\n\n    const price="$x$"\n    const mark="==plain=="\n'
        _, fragment = renderer.render_document(source)
        soup = BeautifulSoup(fragment, "html.parser")
        self.assertIn("价格是 $199 和 $299。", soup.get_text())
        self.assertEqual(soup.pre.get_text(), 'const price="$x$"\nconst mark="==plain=="\n')
        self.assertTrue(renderer.qa_gate(fragment)["ok"])
        _, fragment = renderer.render_document('    const price="$x$"\n    const mark="==plain=="\n\n正文。')
        self.assertIn('const price="$x$"', BeautifulSoup(fragment, "html.parser").pre.get_text())

    def test_numbered_list_decoration_becomes_real_text(self):
        _, fragment = renderer.render_document("# 标题\n\n- 甲\n- 乙", "stripe")
        soup = BeautifulSoup(fragment, "html.parser")
        spans = soup.find_all("span")
        self.assertEqual([span.get_text() for span in spans], ["01 ", "02 "])
        self.assertEqual(renderer.declarations(spans[0]["style"])["font-size"], "12px")
        self.assertEqual(renderer.declarations(spans[0]["style"])["color"], "#635bff")

    def test_code_heading_is_not_consumed_as_article_title(self):
        source = "```python\n# 代码里的一行\n$x$\n```\n\n正文。"
        title, fragment = renderer.render_document(source)
        soup = BeautifulSoup(fragment, "html.parser")
        self.assertEqual(title, "Untitled")
        self.assertIn("# 代码里的一行\n$x$", soup.pre.get_text())
        self.assertIn("正文。", soup.get_text())
        title, fragment = renderer.render_document('---\ntitle: "元信息标题"\n---\n\n正文。')
        self.assertEqual(title, "元信息标题")

    def test_invalid_emphasis_fails_instead_of_leaving_markers(self):
        for body in ("::: emphasis\n未闭合", "::: emphasis\n\n:::", "::: emphasis\n## 标题\n:::"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                renderer.render_document(body)

    def test_gate_rejects_unsafe_html_and_missing_styles(self):
        for fragment in ('<section id="output"><p>正文</p></section>', '<section id="output"><script>alert(1)</script></section>', '<section id="output"><a href="javascript:alert(1)">正文</a></section>'):
            self.assertFalse(renderer.qa_gate(fragment)["ok"])
        _, fragment = renderer.render_document("# 标题\n\n正文。")
        for css in ("position:fixed;", "background-image:url(https://example.com/image.png);"):
            soup = BeautifulSoup(fragment, "html.parser")
            soup.p["style"] += css
            self.assertIn("unsupported_css", renderer.qa_gate(str(soup))["issues"])

    def test_missing_local_picture_stops_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            _, fragment = renderer.render_document("# 标题\n\n![图](missing.png)")
            with self.assertRaisesRegex(ValueError, "local image not found"):
                renderer.resolve_images(fragment, directory)
            self.assertIn("missing_local_image", renderer.qa_gate(fragment)["issues"])

    def test_publisher_extraction_keeps_dark_theme_container(self):
        _, fragment = renderer.render_document("# 标题\n\n正文。", "linear")
        soup = BeautifulSoup(fragment, "html.parser")
        inner = soup.select_one("#output > section")
        self.assertEqual(renderer.declarations(inner["style"])["background-color"], "#111114")
        self.assertEqual(renderer.declarations(inner.p["style"])["color"], "#d7d7e1")

    def test_mobile_preview_keeps_local_picture_and_has_no_second_padding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "图片.png"
            path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1QAAAAASUVORK5CYII="))
            title, fragment = renderer.render_document("# 标题\n\n![原图](图片.png)")
            preview = renderer.render_standalone(title, fragment, image_base=directory)
            soup = BeautifulSoup(preview, "html.parser")
            self.assertTrue(soup.img["src"].startswith("data:image/png;base64,"))
            self.assertIn("padding:0", soup.style.get_text())
            self.assertEqual(renderer.declarations(soup.select_one("#output > section")["style"])["padding"], "24px 22px")


if __name__ == "__main__":
    unittest.main()
