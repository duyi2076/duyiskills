#!/usr/bin/env python3
"""Lock the single confirmed editorial packet and materialize downstream plans."""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any

from apply_asr_corrections import apply_corrections
from common import load_json, media_summary, write_json


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retained_segments(
    words: list[dict[str, Any]],
    deleted_ids: set[str],
) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for word in words:
        if str(word["word_id"]) in deleted_ids:
            if current:
                groups.append(current)
                current = []
        else:
            current.append(word)
    if current:
        groups.append(current)
    return [
        {
            "id": f"keep-{index:03d}",
            "source_start": float(group[0]["start"]),
            "source_end": float(group[-1]["end"]),
            "source_word_ids": [group[0]["word_id"], group[-1]["word_id"]],
            "reason": "由用户确认的文字母版保留范围生成",
            "sentence_boundary_review": {
                "entry_complete": True,
                "exit_complete": True,
                "approved": True,
            },
        }
        for index, group in enumerate(groups, start=1)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", required=True)
    parser.add_argument("--confirmation-note", required=True)
    parser.add_argument("--user-confirmed", action="store_true")
    parser.add_argument("--output", required=True)
    parser.add_argument("--corrected-transcript-output", required=True)
    parser.add_argument("--asr-corrections-output", required=True)
    parser.add_argument("--cut-plan-output", required=True)
    parser.add_argument("--caption-units-output", required=True)
    parser.add_argument("--semantic-map-output", required=True)
    args = parser.parse_args()
    if not args.user_confirmed:
        raise SystemExit("blocked: explicit --user-confirmed is required")
    if not args.confirmation_note.strip():
        raise SystemExit("blocked: confirmation note is required")

    packet_path = Path(args.packet).resolve()
    packet = load_json(packet_path)
    if packet.get("status") != "awaiting_single_human_review":
        raise SystemExit("blocked: packet is not awaiting the single human review")
    inputs = packet["inputs"]
    transcript_path = Path(inputs["normalized_transcript"]["path"])
    plan_path = Path(inputs["editorial_review_plan"]["path"])
    source_path = Path(inputs["source_media"]["path"])
    integrity_path = Path(inputs["asr_integrity"]["path"])
    for label, input_key, path in (
        ("normalized transcript", "normalized_transcript", transcript_path),
        ("editorial plan", "editorial_review_plan", plan_path),
        ("source media", "source_media", source_path),
        ("ASR integrity", "asr_integrity", integrity_path),
    ):
        if sha256(path) != inputs[input_key]["sha256"]:
            raise SystemExit(f"blocked: {label} changed after review packet generation")

    locked = {
        "schema_version": 1,
        "status": "locked",
        "policy": "single-human-confirmed-editorial-master",
        "locked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "confirmation": {
            "user_confirmed": True,
            "note": args.confirmation_note.strip(),
            "review_count": 1,
        },
        "hashes": {
            "normalized_transcript_sha256": sha256(transcript_path),
            "editorial_review_plan_sha256": sha256(plan_path),
            "editorial_review_packet_sha256": sha256(packet_path),
            "source_media_sha256": sha256(source_path),
            "asr_integrity_sha256": sha256(integrity_path),
            "decision_sha256": packet["decision_sha256"],
        },
        "subtitle_contract": packet["subtitle_contract"],
        "asr_review": packet["asr_review"],
        "speaker_issues": packet["speaker_issues"],
        "deletions": packet["deletions"],
        "sentences": packet["sentences"],
        "caption_units": packet["caption_units"],
        "semantic_map": packet["semantic_map"],
        "retained_word_ids": packet["retained_word_ids"],
        "deleted_word_ids": packet["deleted_word_ids"],
    }
    output = Path(args.output).resolve()
    if output.is_file():
        existing = load_json(output)
        if (
            existing.get("status") != "locked"
            or existing.get("policy") != locked["policy"]
            or existing.get("confirmation") != locked["confirmation"]
            or existing.get("hashes") != locked["hashes"]
            or existing.get("subtitle_contract") != locked["subtitle_contract"]
            or existing.get("asr_review") != locked["asr_review"]
            or existing.get("speaker_issues") != locked["speaker_issues"]
            or existing.get("deletions") != locked["deletions"]
            or existing.get("sentences") != locked["sentences"]
            or existing.get("caption_units") != locked["caption_units"]
            or existing.get("semantic_map") != locked["semantic_map"]
            or existing.get("retained_word_ids") != locked["retained_word_ids"]
            or existing.get("deleted_word_ids") != locked["deleted_word_ids"]
        ):
            raise SystemExit(
                "blocked: an existing editorial master cannot be replaced by a "
                "different decision or confirmation"
            )
        locked = existing
    else:
        write_json(output, locked)
    master_sha256 = sha256(output)

    asr_review = copy.deepcopy(packet["asr_review"])
    asr_review["locked_text_master_sha256"] = master_sha256
    write_json(args.asr_corrections_output, asr_review)
    corrected = apply_corrections(
        load_json(transcript_path),
        asr_review,
        transcript_sha256=sha256(transcript_path),
        source_media_sha256=sha256(source_path),
        asr_integrity_sha256=sha256(integrity_path),
    )
    corrected["inputs"] = {
        "normalized_transcript_sha256": sha256(transcript_path),
        "asr_corrections_sha256": sha256(Path(args.asr_corrections_output)),
        "source_media_sha256": sha256(source_path),
        "asr_integrity_sha256": sha256(integrity_path),
        "locked_text_master_sha256": master_sha256,
    }
    corrected["locked_text_master_sha256"] = master_sha256
    write_json(args.corrected_transcript_output, corrected)

    corrected_words = corrected["words"]
    deleted_ids = set(packet["deleted_word_ids"])
    segments = retained_segments(corrected_words, deleted_ids)
    if not segments:
        raise SystemExit("blocked: human-confirmed master deletes the entire video")
    source_media_duration = float(media_summary(source_path)["duration"])
    write_json(
        args.cut_plan_output,
        {
            "schema_version": 1,
            "policy": "locked-editorial-master-only",
            "locked_text_master_sha256": master_sha256,
            "source_window": {
                "start": 0.0,
                "end": source_media_duration,
            },
            "segments": segments,
        },
    )
    write_json(
        args.caption_units_output,
        {
            "schema_version": 1,
            "policy": "semantic-complete",
            "locked_text_master_sha256": master_sha256,
            "units": [
                {
                    "id": row["id"],
                    "sentence_id": row["sentence_id"],
                    "full_sentence_text": row["full_sentence_text"],
                    "start_word_id": row["start_word_id"],
                    "end_word_id": row["end_word_id"],
                    "boundary_reason": row["boundary_reason"],
                    "approved": True,
                }
                for row in packet["caption_units"]
            ],
        },
    )
    semantic_map = copy.deepcopy(packet["semantic_map"])
    semantic_map["locked_text_master_sha256"] = master_sha256
    write_json(args.semantic_map_output, semantic_map)
    print(
        json.dumps(
            {
                "status": "locked",
                "locked_text_master_sha256": master_sha256,
                "sentences": len(packet["sentences"]),
                "subtitle_cues": len(packet["caption_units"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
