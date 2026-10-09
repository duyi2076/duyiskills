#!/usr/bin/env python3
"""Generate source-bound word-level Doubao ASR for a AIJianji video run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import math
from pathlib import Path
from typing import Any


EXPECTED_PROVIDER = "agent_plan"
EXPECTED_RESOURCE_ID = "volc.seedasr.sauc.duration"
TOOL_ENV_VARS = ("DUYI_ASR_TOOL", "DOUYI_DOUBAO_ASR_TOOL")
CONFIG_ENV_VARS = ("DUYI_ASR_ENV", "DOUYI_DOUBAO_ASR_ENV")


def configured_path(explicit: Path | None, names: tuple[str, ...], label: str) -> Path:
    """Resolve a required local dependency without embedding a machine path."""
    if explicit is not None:
        return explicit
    for name in names:
        value = os.environ.get(name)
        if value:
            return Path(value)
    joined = " or ".join(f"${name}" for name in names)
    raise SystemExit(f"missing {label}: provide --{label} or set {joined}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_word_timing(word: dict[str, Any], index: str | int) -> None:
    text = str(word.get("text") or "").strip()
    if not text:
        return
    try:
        start = float(word["start_time"])
        end = float(word["end_time"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"word {index} has missing or non-numeric start_time/end_time"
        ) from exc
    if (
        isinstance(word["start_time"], bool)
        or isinstance(word["end_time"], bool)
        or not math.isfinite(start)
        or not math.isfinite(end)
        or start < 0
        or end <= start
    ):
        raise ValueError(f"word {index} has invalid timing [{start}, {end}]")


def validate_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ValueError("Doubao ASR did not return ok=true")
    if payload.get("provider") != EXPECTED_PROVIDER:
        raise ValueError(
            f"ASR provider must be {EXPECTED_PROVIDER!r}, got "
            f"{payload.get('provider')!r}"
        )
    if payload.get("resource_id") != EXPECTED_RESOURCE_ID:
        raise ValueError(
            f"ASR resource_id must be {EXPECTED_RESOURCE_ID!r}, got "
            f"{payload.get('resource_id')!r}"
        )
    raw = payload.get("raw")
    result = raw.get("result") if isinstance(raw, dict) else None
    utterances = result.get("utterances") if isinstance(result, dict) else None
    if not isinstance(utterances, list) or not utterances:
        raise ValueError("Doubao ASR response has no utterances")
    meaningful_words: list[dict[str, Any]] = []
    for utterance_index, utterance in enumerate(utterances, start=1):
        if not isinstance(utterance, dict):
            continue
        for word_index, word in enumerate(utterance.get("words") or [], start=1):
            if isinstance(word, dict) and str(word.get("text") or "").strip():
                validate_word_timing(word, f"{utterance_index}.{word_index}")
                meaningful_words.append(word)
    if not meaningful_words:
        raise ValueError("Doubao ASR response has no word-level timing")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--tool",
        type=Path,
        help="Local ASR adapter path; may also be set with DUYI_ASR_TOOL",
    )
    parser.add_argument(
        "--env",
        type=Path,
        help="Local ASR environment file; may also be set with DUYI_ASR_ENV",
    )
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    source = args.input.resolve()
    output = args.output.resolve()
    tool = configured_path(args.tool, TOOL_ENV_VARS, "tool").resolve()
    env_file = configured_path(args.env, CONFIG_ENV_VARS, "env").resolve()
    if not source.is_file():
        raise SystemExit(f"source video not found: {source}")
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing ASR: {output}")
    if not tool.is_file():
        raise SystemExit(f"Doubao ASR tool not found: {tool}")
    if not env_file.is_file():
        raise SystemExit(f"Doubao ASR environment not found: {env_file}")

    completed = subprocess.run(
        [
            sys.executable,
            str(tool),
            str(source),
            "--env",
            str(env_file),
            "--json",
            "--raw",
        ],
        capture_output=True,
        text=True,
        timeout=args.timeout,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise SystemExit(f"Doubao ASR failed: {message}")
    try:
        payload = validate_result(json.loads(completed.stdout))
    except (json.JSONDecodeError, ValueError) as error:
        raise SystemExit(f"invalid Doubao ASR result: {error}") from error

    payload.pop("key_suffix", None)
    payload["asr_contract"] = {
        "provider_family": "doubao-asr",
        "provider": EXPECTED_PROVIDER,
        "resource_id": EXPECTED_RESOURCE_ID,
        "word_timing_required": True,
        "local_asr_forbidden": True,
    }
    payload["source_media"] = {
        "path": str(source),
        "size_bytes": source.stat().st_size,
        "sha256": sha256_file(source),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Doubao word-level ASR -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
