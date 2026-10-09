#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

from common import load_json, write_json


def find_utterances(payload: Any) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    if isinstance(payload, dict):
        candidates.extend(
            [
                payload.get("utterances"),
                payload.get("result", {}).get("utterances") if isinstance(payload.get("result"), dict) else None,
                payload.get("raw", {}).get("result", {}).get("utterances")
                if isinstance(payload.get("raw"), dict)
                and isinstance(payload.get("raw", {}).get("result"), dict)
                else None,
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate
    raise ValueError("Cannot find Doubao utterances in input JSON")


def seconds(value: Any) -> float:
    return round(float(value or 0) / 1000.0, 3)


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Doubao word-level ASR JSON.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    payload = load_json(args.input)
    utterances = find_utterances(payload)
    normalized_utterances: list[dict[str, Any]] = []
    all_words: list[dict[str, Any]] = []
    word_index = 1
    ignored_separator_tokens = 0

    for utterance_index, utterance in enumerate(utterances, start=1):
        utterance_id = f"utt-{utterance_index:04d}"
        normalized_words: list[dict[str, Any]] = []
        for raw_word in utterance.get("words") or []:
            text = str(raw_word.get("text", ""))
            raw_start = raw_word.get("start_time")
            raw_end = raw_word.get("end_time")
            if not text.strip():
                ignored_separator_tokens += 1
                continue
            try:
                start_ms = float(raw_start)
                end_ms = float(raw_end)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"utterance {utterance_index} word {len(normalized_words) + 1} "
                    "has missing or non-numeric timing"
                ) from exc
            if (
                not math.isfinite(start_ms)
                or not math.isfinite(end_ms)
                or start_ms < 0
                or end_ms <= start_ms
            ):
                raise ValueError(
                    f"utterance {utterance_index} word {len(normalized_words) + 1} "
                    f"has invalid timing [{start_ms}, {end_ms}]"
                )
            word = {
                "word_id": f"word-{word_index:06d}",
                "utterance_id": utterance_id,
                "text": text,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "start": seconds(start_ms),
                "end": seconds(end_ms),
            }
            word_index += 1
            normalized_words.append(word)
            all_words.append(word)
        normalized_utterances.append(
            {
                "utterance_id": utterance_id,
                "text": str(utterance.get("text", "")),
                "start_ms": float(utterance.get("start_time", 0) or 0),
                "end_ms": float(utterance.get("end_time", 0) or 0),
                "start": seconds(utterance.get("start_time", 0)),
                "end": seconds(utterance.get("end_time", 0)),
                "word_ids": [word["word_id"] for word in normalized_words],
            }
        )

    result = {
        "version": 1,
        "provider": payload.get("provider", "doubao") if isinstance(payload, dict) else "doubao",
        "source": str(Path(args.input).resolve()),
        "duration": float(payload.get("duration", 0) or 0) if isinstance(payload, dict) else None,
        "text": payload.get("text", "") if isinstance(payload, dict) else "",
        "utterances": normalized_utterances,
        "words": all_words,
        "normalization": {
            "ignored_separator_tokens": ignored_separator_tokens,
            "meaningful_word_count": len(all_words),
        },
    }
    write_json(args.output, result)
    print(f"normalized {len(normalized_utterances)} utterances / {len(all_words)} words -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
