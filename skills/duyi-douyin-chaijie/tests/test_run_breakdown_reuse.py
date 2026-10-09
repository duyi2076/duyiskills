from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = SKILL_DIR / "scripts" / name
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


RUNNER = load_script("run_breakdown.py")


def write_metadata(run_dir: Path, source: str, video_id: str = "1234567890123456789") -> None:
    path = run_dir / "source" / "metadata.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "input": source,
                "url": source,
                "detailEvidence": {
                    "currentUrl": f"https://www.douyin.com/video/{video_id}",
                    "videoId": video_id,
                },
            }
        ),
        encoding="utf-8",
    )


class ExistingRunSelectionTest(unittest.TestCase):
    def test_public_douyin_url_requires_owned_hostname_and_no_credentials(self) -> None:
        valid = (
            "https://www.douyin.com/video/123",
            "https://sub.iesdouyin.com/video/123",
            "https://douyin.com/video/123",
        )
        invalid = (
            "https://douyin.com.evil.example/video/123",
            "https://user:pass@www.douyin.com/video/123",
            "https://example.com/video/123",
            "file:///tmp/video.mp4",
        )
        for value in valid:
            self.assertTrue(RUNNER.is_public_douyin_url(value), value)
        for value in invalid:
            self.assertFalse(RUNNER.is_public_douyin_url(value), value)

    def test_same_share_link_prefers_complete_run_over_newer_partial_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            complete = root / "20260803-1808-complete"
            partial = root / "20260803-2015-partial"
            source = "https://v.douyin.com/example-share/"
            write_metadata(complete, source)
            write_metadata(partial, source)
            (complete / "完整拆解报告.md").write_text("complete", encoding="utf-8")
            (partial / "source" / "video.mp4").write_bytes(b"video")

            selected = RUNNER.find_existing_run(root, source)

            self.assertEqual(selected, complete)

    def test_canonical_video_url_matches_existing_share_link_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            existing = root / "20260803-1808-existing"
            write_metadata(existing, "https://v.douyin.com/example-share/")

            selected = RUNNER.find_existing_run(
                root, "https://www.douyin.com/video/1234567890123456789?from=copy"
            )

            self.assertEqual(selected, existing)

    def test_new_source_does_not_reuse_unrelated_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            existing = root / "20260803-1808-existing"
            write_metadata(existing, "https://v.douyin.com/example-share/")

            selected = RUNNER.find_existing_run(root, "https://v.douyin.com/a-different-link/")

            self.assertIsNone(selected)


if __name__ == "__main__":
    unittest.main()
