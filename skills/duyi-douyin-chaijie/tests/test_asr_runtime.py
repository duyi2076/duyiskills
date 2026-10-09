from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "transcribe_with_doubao.py"
SPEC = importlib.util.spec_from_file_location("transcribe_with_doubao", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class AsrRuntimeTest(unittest.TestCase):
    def test_operator_home_falls_back_without_pwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(MODULE, "pwd", None), mock.patch.object(
            MODULE.Path, "home", return_value=Path(tmp)
        ):
            self.assertEqual(MODULE.resolve_operator_home(), Path(tmp).resolve())

    def test_mlx_environment_restores_only_the_operator_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_home = root / "profile"
            operator_home = root / "operator"
            base = {
                "HOME": str(profile_home),
                "PATH": "/safe/bin",
                "KEEP": "yes",
                "PYTHONHOME": "/wrong/python",
            }

            actual = MODULE.mlx_subprocess_env(base, os_home=operator_home)

            self.assertEqual(actual["HOME"], str(operator_home.resolve()))
            self.assertEqual(actual["PATH"], "/safe/bin")
            self.assertEqual(actual["KEEP"], "yes")
            self.assertNotIn("PYTHONHOME", actual)
            self.assertEqual(base["HOME"], str(profile_home))

    def test_mlx_preflight_runs_with_restored_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile_home = root / "profile"
            operator_home = root / "operator"
            base = {"HOME": str(profile_home), "PATH": "/safe/bin"}
            completed = subprocess.CompletedProcess(
                ["/safe/bin/mlx_whisper", "--help"], 0, stdout="usage", stderr=""
            )

            with (
                mock.patch.object(MODULE.shutil, "which", return_value="/safe/bin/mlx_whisper"),
                mock.patch.object(MODULE.subprocess, "run", return_value=completed) as run,
            ):
                actual = MODULE.run_mlx_preflight(
                    environ=base,
                    os_home=operator_home,
                )

            self.assertTrue(actual["ok"])
            self.assertEqual(run.call_args.kwargs["env"]["HOME"], str(operator_home.resolve()))
            self.assertEqual(run.call_args.kwargs["env"]["PATH"], "/safe/bin")

    def test_slow_cpu_fallback_is_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(out_dir=Path(tmp), allow_slow_whisper=False)
            mlx_failure = {
                "ok": False,
                "provider": "mlx_whisper",
                "error": "import failed",
            }

            with (
                mock.patch.object(MODULE, "run_mlx_whisper", return_value=mlx_failure),
                mock.patch.object(MODULE, "run_openai_whisper") as slow_whisper,
            ):
                actual = MODULE.run_local_asr(args, {"provider": "agent_plan"})

            self.assertFalse(actual["ok"])
            self.assertIn("disabled by default", actual["error"])
            self.assertEqual(actual["mlx_whisper"], mlx_failure)
            slow_whisper.assert_not_called()


if __name__ == "__main__":
    unittest.main()
