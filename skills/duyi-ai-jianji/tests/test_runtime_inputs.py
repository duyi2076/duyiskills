from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from render_final import validate_fps, validate_overlay_timing  # noqa: E402


ASR_SCRIPT = SCRIPTS / "generate_doubao_asr.py"


class RuntimeInputTests(unittest.TestCase):
    def fake_asr(
        self,
        folder: Path,
        *,
        provider: str = "agent_plan",
        resource_id: str = "volc.seedasr.sauc.duration",
        word: dict[str, object] | None = None,
    ) -> Path:
        tool = folder / "fake_asr.py"
        word = word or {"text": "测试", "start_time": 0, "end_time": 1000}
        payload = {
            "ok": True,
            "provider": provider,
            "resource_id": resource_id,
            "raw": {"result": {"utterances": [{"words": [word]}]}},
        }
        tool.write_text(
            "import json\n"
            f"print({json.dumps(payload, ensure_ascii=False)!r})\n",
            encoding="utf-8",
        )
        env_file = folder / "asr.env"
        env_file.write_text("TEST_ONLY=1\n", encoding="utf-8")
        return tool

    def run_asr(self, folder: Path, *extra: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        source = folder / "source.mp4"
        source.write_bytes(b"source")
        output = folder / "asr.json"
        command = [sys.executable, str(ASR_SCRIPT), "--input", str(source), "--output", str(output), *extra]
        if env is None:
            env = os.environ.copy()
            for name in ("DUYI_ASR_TOOL", "DUYI_ASR_ENV", "DOUYI_DOUBAO_ASR_TOOL", "DOUYI_DOUBAO_ASR_ENV"):
                env.pop(name, None)
        return subprocess.run(command, text=True, capture_output=True, env=env)

    def test_fake_tool_success_and_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            tool = self.fake_asr(folder)
            result = self.run_asr(folder, "--tool", str(tool), "--env", str(folder / "asr.env"))
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads((folder / "asr.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["asr_contract"]["provider"], "agent_plan")
            self.assertEqual(payload["asr_contract"]["resource_id"], "volc.seedasr.sauc.duration")
            self.assertEqual(len(payload["source_media"]["sha256"]), 64)
            normalized = folder / "normalized.json"
            normalize = subprocess.run(
                [sys.executable, str(SCRIPTS / "normalize_doubao_asr.py"), "--input", str(folder / "asr.json"), "--output", str(normalized)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(normalize.returncode, 0, normalize.stderr)
            normalized_payload = json.loads(normalized.read_text(encoding="utf-8"))
            self.assertEqual(normalized_payload["words"][0]["start_ms"], 0)
            self.assertEqual(normalized_payload["words"][0]["end_ms"], 1000)

    def test_environment_configuration_and_missing_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            tool = self.fake_asr(folder)
            missing = self.run_asr(folder)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("missing tool", missing.stderr)
            env = os.environ.copy()
            env["DUYI_ASR_TOOL"] = str(tool)
            env["DUYI_ASR_ENV"] = str(folder / "asr.env")
            configured = self.run_asr(folder, env=env)
            self.assertEqual(configured.returncode, 0, configured.stderr)

    def test_wrong_source_and_existing_output_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            for kwargs, expected in (
                ({"provider": "other"}, "provider"),
                ({"resource_id": "wrong.resource"}, "resource_id"),
                ({"word": {"text": "测试", "start_time": 0, "end_time": None}}, "start_time"),
                ({"word": {"text": "测试", "start_time": "nan", "end_time": 1000}}, "invalid timing"),
                ({"word": {"text": "测试", "start_time": 1000, "end_time": 1000}}, "invalid timing"),
            ):
                tool = self.fake_asr(folder, **kwargs)
                wrong = self.run_asr(folder, "--tool", str(tool), "--env", str(folder / "asr.env"))
                self.assertNotEqual(wrong.returncode, 0)
                self.assertIn(expected, wrong.stderr)
            tool = self.fake_asr(folder)
            output = folder / "asr.json"
            output.write_text("existing", encoding="utf-8")
            protected = self.run_asr(folder, "--tool", str(tool), "--env", str(folder / "asr.env"))
            self.assertNotEqual(protected.returncode, 0)
            self.assertIn("overwrite", protected.stderr)

    def test_fps_accepts_rational_and_rejects_invalid_values(self) -> None:
        self.assertEqual(validate_fps("30000/1001"), "30000/1001")
        self.assertEqual(validate_fps("29.97"), "29.97")
        self.assertEqual(validate_fps("300"), "300")
        for value in ("nan", "inf", "1/0", "30;drawtext=text=x"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_fps(value)

    def test_overlay_timing_rejects_nonfinite_and_filter_expressions(self) -> None:
        valid = {"start": 0.25, "duration": 1.5, "x": 12, "y": 20}
        self.assertEqual(validate_overlay_timing(valid, 1, 10.0)[:2], (0.25, 1.75))
        self.assertEqual(validate_overlay_timing({"start": 0, "end": 1}, 1, 2.0)[:2], (0.0, 1.0))
        for field, value in (("x", "0;drawtext=text=x"), ("y", "nan"), ("start", float("inf")), ("end", "1|scale=1")):
            overlay = dict(valid)
            overlay[field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_overlay_timing(overlay, 1, 10.0)


if __name__ == "__main__":
    unittest.main()
