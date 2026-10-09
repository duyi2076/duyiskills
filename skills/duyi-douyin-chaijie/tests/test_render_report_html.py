from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]


def load_renderer():
    path = SKILL_DIR / "scripts" / "render_report_html.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


RENDER = load_renderer()


class RenderReportHtmlTest(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path]:
        run_dir = root / "run"
        (run_dir / "frames").mkdir(parents=True)
        (run_dir / "source").mkdir(parents=True)
        metadata = {
            "title": "测试视频标题 #抖音",
            "author": "测试作者",
            "url": "https://www.douyin.com/video/123456",
            "publishedAt": "2026-08-01 10:00",
            "collectedAt": "2026-08-17T15:59:00Z",
            "detailEvidence": {"videoId": "123456"},
            "metrics": {"likes": 56000, "comments": 615, "collects": 67000, "shares": 12000},
            "comments": [
                {"author": "低赞用户", "likes": 0, "text": "低赞评论", "time": "1周前·北京"},
                {"author": "高赞用户", "likes": 1013, "text": "高赞<b>评论</b>", "time": "2周前·新疆"},
                {"author": "短评", "likes": 99, "text": "好", "time": "3天前"},
            ],
        }
        (run_dir / "breakdown.json").write_text(
            json.dumps({"metadata": metadata, "transcript_text": "逐字稿内容"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (run_dir / "frames" / "0000-00-00-00.jpg").write_bytes(b"\xff\xd8\xff")
        (run_dir / "frames" / "0001-00-00-09.jpg").write_bytes(b"\xff\xd8\xff")
        (run_dir / "frames" / "frames.json").write_text(
            json.dumps({
                "ok": True,
                "duration": 239.4,
                "frames": [
                    {"index": 0, "time": 0.25, "path": str(run_dir / "frames" / "0000-00-00-00.jpg")},
                    {"index": 1, "time": 8.8, "path": str(run_dir / "frames" / "0001-00-00-09.jpg")},
                ],
            }),
            encoding="utf-8",
        )
        (run_dir / "source" / "对标数据截图.png").write_bytes(b"\x89PNG")
        (run_dir / "source" / "video.mp4").write_bytes(b"fake")
        report = run_dir / "final.md"
        report.write_text(
            "# 测试报告标题\n\n## 1. 结论先行\n\n正文段落。\n\n## 2. 时间线\n\n"
            "| 时间 | 内容 |\n|---|---|\n| 0-3s | Hook |\n",
            encoding="utf-8",
        )
        return run_dir, report

    def run_render(self, run_dir: Path, report: Path) -> tuple[int, dict]:
        output = io.StringIO()
        argv = [
            "render_report_html.py",
            "--run-dir", str(run_dir),
            "--final-report", str(report),
        ]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(output):
            code = RENDER.main()
        return code, json.loads(output.getvalue())

    def test_render_full_page(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir, report = self.make_fixture(Path(temp))
            code, result = self.run_render(run_dir, report)
            self.assertEqual(code, 0)
            self.assertTrue(result["ok"])
            html_path = (run_dir / "拆解报告.html").resolve()
            self.assertEqual(Path(result["html"]), html_path)
            page = html_path.read_text(encoding="utf-8")

            self.assertIn("测试报告标题", page)
            self.assertIn("测试作者", page)
            self.assertIn("5.6万", page)
            self.assertIn("6.7万", page)
            # 评论按赞排序，且评论文本必须转义
            self.assertLess(page.index("高赞&lt;b&gt;评论&lt;/b&gt;"), page.index("低赞评论"))
            self.assertNotIn("高赞<b>评论</b>", page)
            # 少于 2 字的评论被过滤
            self.assertNotIn("短评", page)
            # 证据全部用 run 目录相对路径
            self.assertIn('src="frames/0001-00-00-09.jpg"', page)
            self.assertIn('src="source/对标数据截图.png"', page)
            self.assertIn('src="source/video.mp4"', page)
            self.assertIn("00:08", page)
            # 目录锚点与正文标题互相指向（slugify_unicode 保留中文）
            self.assertIn('<a href="#1-结论先行">', page)
            self.assertIn('<h2 id="1-结论先行">', page)
            # 任何外部资源引用都不允许出现（来源链接是可点外链，不是资源加载）
            for forbidden in ('<img src="http', "<script src", "<link ", 'url(http'):
                self.assertNotIn(forbidden, page)

    def test_missing_evidence_degrades_gracefully(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            run_dir = root / "run"
            run_dir.mkdir()
            (run_dir / "breakdown.json").write_text(
                json.dumps({"metadata": {"title": "只有标题"}, "transcript_text": ""}),
                encoding="utf-8",
            )
            report = run_dir / "final.md"
            report.write_text("## 只有正文\n\n没有一级标题。\n", encoding="utf-8")
            code, result = self.run_render(run_dir, report)
            self.assertEqual(code, 0)
            page = (run_dir / "拆解报告.html").read_text(encoding="utf-8")
            self.assertIn("只有标题", page)  # 无 h1 时回退到视频标题
            self.assertIn("素材不足", page)
            self.assertIn("未知作者", page)

    def test_theory_annotations_are_hidden_in_basic_html(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir, report = self.make_fixture(Path(temp))
            report.write_text(
                "# 测试报告标题\n\n## 结论\n\n正文。\n\n理论视角：戈夫曼·拟剧理论（1959）\n\n## 证据\n\n证据内容。\n",
                encoding="utf-8",
            )
            code, result = self.run_render(run_dir, report)
            self.assertEqual(code, 0)
            page = (run_dir / "拆解报告.html").read_text(encoding="utf-8")
            self.assertIn("正文。", page)
            self.assertIn("证据内容。", page)
            self.assertNotIn("理论视角", page)
            self.assertNotIn("拟剧理论", page)

    def test_missing_report_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir = Path(temp) / "run"
            run_dir.mkdir()
            code, result = self.run_render(run_dir, run_dir / "不存在.md")
            self.assertEqual(code, 2)
            self.assertFalse(result["ok"])


class RenderPyramidTest(unittest.TestCase):
    """report-web.json 存在时渲染金字塔版；字段缺失时对应区块隐藏。"""

    def make_web_json(self) -> dict:
        return {
            "verdict": "表面教蒸馏，实际是导流。",
            "verdict_emphasis": ["导流"],
            "data_verdict": "收藏高于点赞，教程型",
            "creator_level": {
                "primary": "L1",
                "tinges": {"L4": "造金句露出苗头"},
                "verdict": "主体是 L1 教程。",
            },
            "marketing_points": {
                "surface": "教你蒸馏",
                "points": [
                    {"title": "造金句", "tag": "L4 动作", "desc": "抢定义权", "quote": "蒸馏就是合法抢劫"},
                ],
            },
            "hook": {
                "tags": ["强比喻命名"],
                "quote": "蒸馏就是 AI 时代的合法抢劫",
                "why": "先给冲突感比喻。",
                "frame": "0000-00-00-00.jpg",
            },
            "structure": {
                "formula": [{"step": "强比喻", "demo": "合法抢劫"}],
                "timeline": [{"range": "0:00-0:25", "fn": "强比喻命名", "kind": "hook", "seconds": 25}],
                "nodes": [{
                    "fn": "强比喻命名", "kind": "hook", "range": "0:00-0:25",
                    "frame": "0000-00-00-00.jpg", "stamp": "0:00",
                    "quote": "蒸馏就是合法抢劫", "why": "锁定注意力。",
                }],
                "mechanisms": [{
                    "title": "让人停留", "quote": "合法抢劫",
                    "attribution": "0:00", "desc": "被比喻钩住。",
                }],
            },
            "fill_blank": [{
                "label": "开篇 · 钩子",
                "script": "「① 就是 ② 的合法抢劫。」",
                "notes": "① 核心动作 ② 时代背景",
            }],
            "cta": {
                "quote": "知识库是免费的",
                "pieces": [{"label": "免费资产", "desc": "降低门槛"}],
                "flow": ["视频", "粉丝群"],
                "flow_hot_index": 1,
                "flow_note": "教程即漏斗。",
            },
            "comment_signals": [{
                "name": "求入口", "count": "5 条",
                "sample": "「在哪找」", "topic": "免费知识库是钩子。",
            }],
            "critiques": [{"title": "实操没闭环", "desc": "停在复制提示词。"}],
        }

    def run_render(self, run_dir: Path, report: Path) -> tuple[int, dict, str]:
        fixture = RenderReportHtmlTest()
        output = io.StringIO()
        argv = ["render_report_html.py", "--run-dir", str(run_dir), "--final-report", str(report)]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(output):
            code = RENDER.main()
        page = (run_dir / "拆解报告.html").read_text(encoding="utf-8") if code == 0 else ""
        return code, json.loads(output.getvalue()), page

    def test_pyramid_mode_full(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = RenderReportHtmlTest()
            run_dir, report = base.make_fixture(Path(temp))
            (run_dir / "report-web.json").write_text(
                json.dumps(self.make_web_json(), ensure_ascii=False), encoding="utf-8"
            )
            code, result, page = self.run_render(run_dir, report)
            self.assertEqual(code, 0)
            self.assertEqual(result["mode"], "pyramid")
            for expected in (
                "表面教蒸馏，实际是", "<em>导流</em>", "收藏高于点赞，教程型",
                "实操教程型", "主体在这层", "造金句露出苗头",
                "教你蒸馏", "蒸馏就是合法抢劫",
                "带走点 1", "带走点 2", "带走点 3",
                "强比喻命名", "这个结构为什么有效",
                "把这条视频变成你的填空题", '<span class="blank">①</span>',
                "教程即漏斗", "求入口", "免费知识库是钩子",
                "实操没闭环", "证据面板",
            ):
                self.assertIn(expected, page)
            # 基础版的目录导航不应出现在金字塔版
            self.assertNotIn('class="toc"', page)

    def test_pyramid_partial_json_hides_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = RenderReportHtmlTest()
            run_dir, report = base.make_fixture(Path(temp))
            (run_dir / "report-web.json").write_text(
                json.dumps({"verdict": "只有判断。"}, ensure_ascii=False), encoding="utf-8"
            )
            code, result, page = self.run_render(run_dir, report)
            self.assertEqual(code, 0)
            self.assertEqual(result["mode"], "pyramid")
            self.assertIn("只有判断。", page)
            # 缺失模块整体隐藏，不留空壳（CSS 常量里有字样，断言 HTML 结构标记）
            for absent in ("这条视频的透视", "带走点 1", "带走点 2", "带走点 3", "把这条视频变成你的填空题"):
                self.assertNotIn(absent, page)
            for absent_class in ('class="sig-topic"', 'class="fb-script"', 'class="lens-card"', 'class="cta-card"'):
                self.assertNotIn(absent_class, page)
            # 证据面板永远存在
            self.assertIn("证据面板", page)

    def test_no_json_falls_back_to_basic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = RenderReportHtmlTest()
            run_dir, report = base.make_fixture(Path(temp))
            code, result, page = self.run_render(run_dir, report)
            self.assertEqual(code, 0)
            self.assertEqual(result["mode"], "basic")
            self.assertIn('class="toc"', page)


def load_finalizer():
    path = SKILL_DIR / "scripts" / "finalize_breakdown.py"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


FINALIZE = load_finalizer()


class FinalizeHtmlHookTest(unittest.TestCase):
    """finalize 只负责把最终报告交给 HTML 呈现层。"""

    def run_finalize(self, render_ok: bool) -> tuple[int, dict]:
        def fake_run_json(cmd: list[str]) -> tuple[int, dict, str]:
            self.assertEqual(Path(cmd[1]).name, "render_report_html.py")
            if render_ok:
                return 0, {"ok": True, "html": "/run/拆解报告.html"}, ""
            return 2, {"ok": False, "error": "渲染爆炸"}, ""

        argv = [
            "finalize_breakdown.py",
            "--run-dir", "/tmp/run",
            "--final-report", "/tmp/final.md",
        ]
        output = io.StringIO()
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(FINALIZE, "run_json", side_effect=fake_run_json),
            redirect_stdout(output),
        ):
            code = FINALIZE.main()
        return code, json.loads(output.getvalue())

    def test_render_success_adds_html_field(self) -> None:
        code, result = self.run_finalize(render_ok=True)
        self.assertEqual(code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["html"]["html"], "/run/拆解报告.html")

    def test_render_failure_returns_error(self) -> None:
        code, result = self.run_finalize(render_ok=False)
        self.assertEqual(code, 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["stage"], "html")


if __name__ == "__main__":
    unittest.main()
