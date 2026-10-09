#!/usr/bin/env python3
"""Render a reviewed breakdown report and its local evidence as HTML."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def run_json(cmd: list[str]) -> tuple[int, dict, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    payload = {}
    for stream in (proc.stdout, proc.stderr):
        try:
            payload = json.loads(stream)
            break
        except Exception:
            continue
    return proc.returncode, payload, (proc.stderr or proc.stdout).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a reviewed video breakdown as a self-contained HTML report")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--final-report", required=True, help="Reviewed final report, not the automatic draft")
    parser.add_argument("--output", default="", help="Optional output HTML path")
    args = parser.parse_args()

    skill_dir = Path(__file__).resolve().parents[1]
    run_dir = Path(args.run_dir).expanduser().resolve()
    final_report = Path(args.final_report).expanduser().resolve()
    render_cmd = [
        sys.executable,
        str(skill_dir / "scripts" / "render_report_html.py"),
        "--run-dir",
        str(run_dir),
        "--final-report",
        str(final_report),
    ]
    if args.output:
        render_cmd.extend(["--output", str(Path(args.output).expanduser().resolve())])

    code, rendered, error = run_json(render_cmd)
    if code != 0 or not rendered.get("ok"):
        print(json.dumps({"ok": False, "stage": "html", "error": rendered or error}, ensure_ascii=False, indent=2))
        return 2

    print(json.dumps({"ok": True, "html": rendered}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
