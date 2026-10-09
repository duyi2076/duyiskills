import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from test_renderer import SCRIPT, renderer

SKILL_ROOT = SCRIPT.parents[3]
BATCH = SKILL_ROOT / "references/duyi-wechat-css-layer/scripts/render_style_set.py"
PUBLISHER = SKILL_ROOT / "references/duyi-wechat-fabu/scripts/wechat-posting-backend/wechat-api.ts"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl1QAAAAASUVORK5CYII=")


class DeliveryTests(unittest.TestCase):
    def test_copy_all_themes_preserve_source_words_and_emphasis(self):
        source = "# 标题\n\n开头，保留标点。\n\n::: emphasis\n只在**条件成立**时继续。\n:::\n\n> 原作者的引用。\n\n## 小节\n\n[来源文字](https://example.com)\n\n结尾。"
        expected = "开头，保留标点。只在条件成立时继续。原作者的引用。小节来源文字结尾。"
        for theme in renderer.load_themes():
            with self.subTest(theme=theme):
                title, fragment = renderer.render_document(source, theme)
                document, images = renderer.make_copy_document(title, fragment)
                soup = BeautifulSoup(document, "html.parser")
                self.assertEqual("".join(soup.body.stripped_strings), expected)
                self.assertEqual(images, [])
                self.assertEqual(len(soup.select('section[role="note"]')), 1)
                self.assertIsNotNone(soup.blockquote)
                self.assertEqual(soup.strong.get_text(), "条件成立")
                self.assertIsNone(soup.find(["style", "script", "img", "a"]))
                self.assertEqual(soup.body.find_all(recursive=False)[0].name, "p")
                self.assertTrue(renderer.qa_copy_gate(document)["ok"])
                for tag in soup.body.find_all(recursive=False):
                    self.assertNotIn(renderer.declarations(tag["style"]).get("background-color"), (None, "transparent"))

    def test_original_images_export_in_order_with_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "原 图.png").write_bytes(PNG)
            source = "# 标题\n\n图前句。\n\n![截图甲](原%20图.png)\n\n中间句，![截图乙](原%20图.png)同段句。\n\n图后句。"
            title, fragment = renderer.render_document(source)
            fragment = renderer.resolve_images(fragment, root)
            document, images = renderer.make_copy_document(title, fragment)
            soup = BeautifulSoup(document, "html.parser")
            self.assertEqual([tag.get_text() for tag in soup.select('[aria-label="图片位置"]')], ["[图片 1：截图甲]", "[图片 2：截图乙]"])
            self.assertIsNone(soup.select_one("p p"))
            self.assertEqual(images[0]["before"], "图前句。")
            self.assertEqual(images[0]["after"], "中间句，同段句。")
            self.assertTrue(renderer.qa_copy_gate(document)["ok"])
            assets = renderer.write_copy_assets(images, root / "output", "article")
            entries = json.loads(Path(assets["image_manifest"]).read_text())
            page = BeautifulSoup(Path(assets["image_copy_page"]).read_text(), "html.parser")
            self.assertEqual([entry["index"] for entry in entries], [1, 2])
            for entry, image in zip(entries, page.find_all("img")):
                self.assertEqual(Path(entry["file"]).read_bytes(), PNG)
                self.assertEqual(entry["sha256"], hashlib.sha256(PNG).hexdigest())
                self.assertEqual(base64.b64decode(image["src"].split(",", 1)[1]), PNG)
            self.assertEqual((root / "原 图.png").read_bytes(), PNG)
            self.assertEqual(assets["images"], 2)

    def test_remote_image_is_a_reference_without_download(self):
        _, fragment = renderer.render_document("正文。\n\n![远程原图](https://example.invalid/original.png)")
        document, images = renderer.make_copy_document("标题", fragment)
        self.assertTrue(renderer.qa_copy_gate(document)["ok"])
        with tempfile.TemporaryDirectory() as directory:
            assets = renderer.write_copy_assets(images, directory, "article")
            entries = json.loads(Path(assets["image_manifest"]).read_text())
            self.assertIsNone(entries[0]["file"])
            self.assertIsNone(entries[0]["sha256"])
            self.assertIn("https://example.invalid/original.png", Path(assets["image_copy_page"]).read_text())

    def test_copy_gate_rejects_editor_incompatible_content(self):
        _, fragment = renderer.render_document("正文。")
        document, _ = renderer.make_copy_document("标题", fragment)
        for extra in ('<style>p{color:red}</style>', '<button>复制</button>', '<img src="https://example.com/a.png">', '<p id="output">正文</p>', '<a href="https://example.com">链接</a>'):
            with self.subTest(extra=extra):
                self.assertFalse(renderer.qa_copy_gate(document.replace("</body>", extra + "</body>"))["ok"])
        soup = BeautifulSoup(document, "html.parser")
        del_style = renderer.declarations(soup.p["style"])
        del_style.pop("background-color")
        soup.p["style"] = renderer.style_text(del_style)
        self.assertIn("copy_depends_on_body_background", renderer.qa_copy_gate(str(soup))["issues"])

    def test_cli_defaults_to_copy_and_api_retains_original_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "photo.png").write_bytes(PNG)
            source = root / "article.md"
            source.write_text("# 标题\n\n正文。\n\n![照片](photo.png)")
            for mode in ("copy", "api"):
                output = root / f"article-{mode}.html"
                command = [sys.executable, str(SCRIPT), str(source), "--output", str(output)]
                if mode == "api":
                    command += ["--mode", "api"]
                proc = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["mode"], mode)
                soup = BeautifulSoup(output.read_text(), "html.parser")
                if mode == "copy":
                    self.assertIsNotNone(soup.find("meta", attrs={"name": "wechat-delivery-mode", "content": "copy"}))
                    self.assertIsNone(soup.img)
                    self.assertIsNone(soup.find(id=True))
                else:
                    self.assertEqual(len(soup.select("#output")), 1)
                    self.assertEqual(Path(soup.img["src"]), (root / "photo.png").resolve())

    def test_batch_style_selection_is_independent_of_delivery_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "article.md"
            source.write_text("# 标题\n\n正文。")
            for mode in ("copy", "api"):
                command = [sys.executable, str(BATCH), str(source), str(root / "out"), "--mode", mode, "--preview"]
                proc = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                report = json.loads(proc.stdout)
                self.assertEqual(report["styles"], 6)
                self.assertEqual(report["mode"], mode)
                entries = json.loads((root / "out" / f"渲染检查-{mode}.json").read_text())
                self.assertTrue(all(entry["ok"] for entry in entries))
                self.assertTrue(all(Path(entry["delivery"]).exists() for entry in entries))
            self.assertTrue((root / "out/00_公众号风格总览-copy.html").exists())
            self.assertTrue((root / "out/00_公众号风格总览-api.html").exists())

    def test_publisher_dry_run_rejects_copy_preview_and_accepts_api(self):
        bun = shutil.which("bun")
        if not bun:
            self.skipTest("Bun is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cover = root / "cover.png"
            cover.write_bytes(PNG)
            title, fragment = renderer.render_document("# 标题\n\n正文。")
            copy, _ = renderer.make_copy_document(title, fragment)
            preview = renderer.render_standalone(title, fragment)
            # Attribute order, quoting and case do not affect the guard.
            alternate = copy.replace('name="wechat-delivery-mode" content="copy"', "CONTENT='COPY' NAME='WECHAT-DELIVERY-MODE'")
            for mode, content in (("copy", copy), ("alternate", alternate), ("preview", preview), ("api", fragment)):
                output = root / f"article-{mode}.html"
                output.write_text(content)
                proc = subprocess.run([bun, str(PUBLISHER), str(output), "--title", title, "--cover", str(cover), "--dry-run"], cwd=root, capture_output=True, text=True)
                if mode != "api":
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertIn("--mode api", proc.stderr)
                else:
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    report = json.loads(proc.stdout)
                    self.assertEqual(report["title"], title)
                    self.assertTrue(report["coverExists"])
                    self.assertGreater(report["contentLength"], 0)
                    self.assertNotIn("media_id", report)


if __name__ == "__main__":
    unittest.main()
