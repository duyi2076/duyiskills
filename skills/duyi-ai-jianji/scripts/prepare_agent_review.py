#!/usr/bin/env python3
"""Prepare a hash-bound brief for a fresh AI acceptance lens."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_acceptance import build_brief
from common import load_json, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--style-decision", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    style = load_json(args.style_decision)
    skin_id = str(style.get("skin_id") or "")
    if not skin_id:
        raise ValueError("style decision has no skin_id")
    brief = build_brief(Path(args.run_dir).resolve(), skin_id=skin_id)
    write_json(args.output, brief)
    print(f"agent review brief -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
