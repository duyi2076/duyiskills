#!/usr/bin/env python3
"""Apply conservative pause compression and capped local speech acceleration."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from common import (
    atomic_output_path,
    file_fingerprint,
    load_json,
    media_summary,
    run,
    sha256_file,
    write_json,
)
from contracts import PIPELINE_VERSION
from remap_timeline import resolve_nested_triggers


SCHEMA_VERSION = 1
PREFERRED_CUE_DURATION = 3.8
ADAPTIVE_CUE_DURATION = 5.5
MIN_ANALYSIS_SYLLABLES = 8.0
MIN_ANALYSIS_DURATION = 4.0
SLOW_ARTICULATION_RATE = 3.0
HIGH_PAUSE_RATIO = 0.28
COMPRESSIBLE_PAUSE = 0.45
TARGET_INTERNAL_PAUSE = 0.24
MAX_AUTOMATIC_SPEED = 1.15
EPSILON = 0.0005
ASCII_TERM = re.compile(r"[A-Za-z0-9]")
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
ASCII_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[+.#_-][A-Za-z0-9]+)*")


def syllable_units(text: str) -> float:
    """Estimate spoken units without pretending English spelling equals syllables."""
    cjk = len(CJK.findall(text))
    ascii_tokens = len(ASCII_TOKEN.findall(text))
    return float(cjk + ascii_tokens)


def speed_factor_for(articulation_rate: float) -> float:
    if articulation_rate < 2.4:
        return 1.12
    if articulation_rate < 2.7:
        return 1.08
    if articulation_rate < SLOW_ARTICULATION_RATE:
        return 1.05
    return 1.0


def analyze_word_span(
    words: list[dict[str, Any]],
    *,
    start_key: str = "start",
    end_key: str = "end",
) -> dict[str, Any]:
    if not words:
        raise ValueError("rhythm analysis requires at least one word")
    start = float(words[0][start_key])
    end = float(words[-1][end_key])
    span = max(0.020, end - start)
    active_duration = sum(
        max(0.020, float(word[end_key]) - float(word[start_key]))
        for word in words
    )
    gaps = []
    for previous, current in zip(words, words[1:]):
        gap = max(
            0.0,
            float(current[start_key]) - float(previous[end_key]),
        )
        if gap > EPSILON:
            gaps.append(
                {
                    "after_word_id": str(previous["word_id"]),
                    "before_word_id": str(current["word_id"]),
                    "start": float(previous[end_key]),
                    "end": float(current[start_key]),
                    "duration": gap,
                }
            )
    pause_duration = sum(item["duration"] for item in gaps)
    text = "".join(str(word.get("text") or "") for word in words)
    units = max(1.0, syllable_units(text))
    articulation_rate = units / active_duration
    speech_rate = units / span
    pause_ratio = min(1.0, pause_duration / span)
    protected_reasons = []
    if ASCII_TERM.search(text):
        protected_reasons.append("mixed-language-or-number")
    if units < MIN_ANALYSIS_SYLLABLES:
        protected_reasons.append("too-few-syllables")
    if span < MIN_ANALYSIS_DURATION:
        protected_reasons.append("too-short-for-local-speed-change")

    speed_factor = speed_factor_for(articulation_rate)
    if protected_reasons:
        speed_factor = 1.0
    speed_factor = min(MAX_AUTOMATIC_SPEED, max(1.0, speed_factor))

    pause_edits = []
    for gap in gaps:
        if gap["duration"] <= COMPRESSIBLE_PAUSE:
            continue
        target_output = TARGET_INTERNAL_PAUSE
        target_source = target_output * speed_factor
        removal = gap["duration"] - target_source
        if removal <= 0.040:
            continue
        remove_start = gap["start"] + target_source / 2.0
        remove_end = gap["end"] - target_source / 2.0
        pause_edits.append(
            {
                **gap,
                "target_output_duration": target_output,
                "remove_start": remove_start,
                "remove_end": remove_end,
                "removed_duration": remove_end - remove_start,
            }
        )

    removed = sum(item["removed_duration"] for item in pause_edits)
    projected_duration = (span - removed) / speed_factor
    if speed_factor > 1.0 and pause_edits:
        diagnosis = "pause-and-articulation-slow"
        action = "compress-pauses-and-speed"
    elif speed_factor > 1.0:
        diagnosis = "articulation-slow"
        action = "speed-local-speech"
    elif pause_edits:
        diagnosis = "excessive-pause"
        action = "compress-pauses-only"
    else:
        diagnosis = "natural-rhythm"
        action = "keep"

    return {
        "text": text,
        "start": round(start, 6),
        "end": round(end, 6),
        "original_duration": round(span, 6),
        "syllable_units": round(units, 3),
        "active_duration": round(active_duration, 6),
        "pause_duration": round(pause_duration, 6),
        "articulation_rate": round(articulation_rate, 3),
        "speech_rate": round(speech_rate, 3),
        "pause_ratio": round(pause_ratio, 3),
        "protected": bool(protected_reasons),
        "protected_reasons": protected_reasons,
        "diagnosis": diagnosis,
        "action": action,
        "speed_factor": round(speed_factor, 3),
        "pause_edits": pause_edits,
        "projected_duration": round(projected_duration, 6),
        "duration_class": (
            "preferred"
            if projected_duration <= PREFERRED_CUE_DURATION
            else "adaptive"
            if projected_duration <= ADAPTIVE_CUE_DURATION
            else "too-long"
        ),
    }


def analyze_timeline(timeline: dict[str, Any]) -> dict[str, Any]:
    words = timeline.get("words")
    units = timeline.get("caption_units")
    if not isinstance(words, list) or not words:
        raise ValueError("mapped timeline has no words")
    if not isinstance(units, list) or not units:
        raise ValueError("mapped timeline has no caption units")
    word_by_id = {str(word["word_id"]): word for word in words}
    decisions = []
    for unit in units:
        mapped_ids = unit.get("mapped_word_ids") or [
            str(word["word_id"])
            for word in words
            if str(word.get("caption_unit_id")) == str(unit.get("id"))
        ]
        unit_words = [word_by_id[str(word_id)] for word_id in mapped_ids]
        analysis = analyze_word_span(unit_words)
        decisions.append(
            {
                "unit_id": str(unit["id"]),
                "sentence_id": str(unit.get("sentence_id") or ""),
                "start_word_id": str(unit_words[0]["word_id"]),
                "end_word_id": str(unit_words[-1]["word_id"]),
                **analysis,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "policy": "adaptive-rhythm-conservative-v1",
        "thresholds": {
            "preferred_cue_duration": PREFERRED_CUE_DURATION,
            "adaptive_cue_duration": ADAPTIVE_CUE_DURATION,
            "minimum_analysis_syllables": MIN_ANALYSIS_SYLLABLES,
            "minimum_analysis_duration": MIN_ANALYSIS_DURATION,
            "slow_articulation_rate": SLOW_ARTICULATION_RATE,
            "high_pause_ratio": HIGH_PAUSE_RATIO,
            "compressible_pause": COMPRESSIBLE_PAUSE,
            "target_internal_pause": TARGET_INTERNAL_PAUSE,
            "maximum_automatic_speed": MAX_AUTOMATIC_SPEED,
        },
        "decisions": decisions,
    }


def build_pieces(
    duration: float,
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    removals = []
    speed_regions = []
    for decision in decisions:
        speed_regions.append(
            {
                "start": float(decision["start"]),
                "end": float(decision["end"]),
                "rate": float(decision["speed_factor"]),
                "unit_id": decision["unit_id"],
            }
        )
        for edit in decision["pause_edits"]:
            removals.append(
                {
                    "start": float(edit["remove_start"]),
                    "end": float(edit["remove_end"]),
                    "unit_id": decision["unit_id"],
                }
            )
    removals.sort(key=lambda item: item["start"])
    for previous, current in zip(removals, removals[1:]):
        if current["start"] < previous["end"] - EPSILON:
            raise ValueError("rhythm pause removals overlap")

    points = {0.0, float(duration)}
    for item in removals + speed_regions:
        points.add(max(0.0, min(float(duration), float(item["start"]))))
        points.add(max(0.0, min(float(duration), float(item["end"]))))
    ordered = sorted(points)
    pieces = []
    output_cursor = 0.0
    for start, end in zip(ordered, ordered[1:]):
        if end - start <= EPSILON:
            continue
        midpoint = (start + end) / 2.0
        removed = any(
            item["start"] - EPSILON <= midpoint <= item["end"] + EPSILON
            for item in removals
        )
        if removed:
            continue
        region = next(
            (
                item
                for item in speed_regions
                if item["start"] - EPSILON <= midpoint <= item["end"] + EPSILON
            ),
            None,
        )
        rate = float(region["rate"]) if region else 1.0
        unit_id = region["unit_id"] if region else None
        output_duration = (end - start) / rate
        piece = {
            "id": f"rhythm-piece-{len(pieces) + 1:04d}",
            "source_start": round(start, 6),
            "source_end": round(end, 6),
            "rate": round(rate, 3),
            "unit_id": unit_id,
            "output_start": round(output_cursor, 6),
            "output_end": round(output_cursor + output_duration, 6),
        }
        if (
            pieces
            and math.isclose(
                float(pieces[-1]["source_end"]),
                start,
                abs_tol=EPSILON,
            )
            and math.isclose(float(pieces[-1]["rate"]), rate, abs_tol=EPSILON)
            and pieces[-1]["unit_id"] == unit_id
        ):
            pieces[-1]["source_end"] = round(end, 6)
            pieces[-1]["output_end"] = round(
                float(pieces[-1]["output_start"])
                + (end - float(pieces[-1]["source_start"])) / rate,
                6,
            )
        else:
            pieces.append(piece)
        output_cursor = float(pieces[-1]["output_end"])
    if not pieces:
        raise ValueError("rhythm plan removed the entire media")
    return pieces


def map_time(value: float, pieces: list[dict[str, Any]]) -> float:
    for piece in pieces:
        start = float(piece["source_start"])
        end = float(piece["source_end"])
        if start - EPSILON <= value <= end + EPSILON:
            clamped = min(end, max(start, value))
            return float(piece["output_start"]) + (clamped - start) / float(
                piece["rate"]
            )
    previous = [piece for piece in pieces if float(piece["source_end"]) < value]
    if previous:
        return float(previous[-1]["output_end"])
    return float(pieces[0]["output_start"])


def remap_timeline(
    timeline: dict[str, Any],
    pieces: list[dict[str, Any]],
    *,
    actual_duration: float | None = None,
) -> dict[str, Any]:
    mapped_words = []
    source_to_output = {}
    previous_end = 0.0
    for word in timeline["words"]:
        mapped = dict(word)
        start = max(previous_end, map_time(float(word["start"]), pieces))
        end = max(start + 0.020, map_time(float(word["end"]), pieces))
        mapped["pre_rhythm_start"] = word["start"]
        mapped["pre_rhythm_end"] = word["end"]
        mapped["start"] = round(start, 3)
        mapped["end"] = round(end, 3)
        mapped_words.append(mapped)
        source_to_output[str(word["word_id"])] = {
            "start": mapped["start"],
            "end": mapped["end"],
        }
        previous_end = end

    mapped_units = []
    words_by_unit: dict[str, list[dict[str, Any]]] = {}
    for word in mapped_words:
        words_by_unit.setdefault(str(word.get("caption_unit_id")), []).append(word)
    for unit in timeline["caption_units"]:
        unit_words = words_by_unit.get(str(unit["id"]), [])
        if not unit_words:
            raise ValueError(f"rhythm remap lost caption unit {unit['id']}")
        mapped_units.append(
            {
                **unit,
                "pre_rhythm_start": unit.get("start"),
                "pre_rhythm_end": unit.get("end"),
                "start": unit_words[0]["start"],
                "end": unit_words[-1]["end"],
            }
        )

    mapped_segments = []
    for segment in timeline.get("segments", []):
        mapped = dict(segment)
        mapped["pre_rhythm_output_start"] = segment.get("output_start")
        mapped["pre_rhythm_output_end"] = segment.get("output_end")
        mapped["output_start"] = round(
            map_time(float(segment["output_start"]), pieces),
            3,
        )
        mapped["output_end"] = round(
            map_time(float(segment["output_end"]), pieces),
            3,
        )
        mapped["duration"] = round(
            float(mapped["output_end"]) - float(mapped["output_start"]),
            3,
        )
        mapped_segments.append(mapped)

    planned_duration = float(pieces[-1]["output_end"])
    result = {
        **timeline,
        "version": max(3, int(timeline.get("version", 0))),
        "pipeline_version": PIPELINE_VERSION,
        "duration": round(actual_duration or planned_duration, 3),
        "pre_rhythm_duration": timeline.get("duration"),
        "rhythm_planned_duration": round(planned_duration, 6),
        "segments": mapped_segments,
        "words": mapped_words,
        "caption_units": mapped_units,
        "source_to_output": source_to_output,
    }
    return result


def render(
    source: Path,
    output: Path,
    pieces: list[dict[str, Any]],
    *,
    crf: int,
    preset: str,
    timeout: float,
) -> None:
    summary = media_summary(source)
    if not summary["video"] or not summary["audio"]:
        raise ValueError("rhythm input must contain video and audio")
    filters = []
    concat_inputs = []
    for index, piece in enumerate(pieces):
        start = float(piece["source_start"])
        end = float(piece["source_end"])
        rate = float(piece["rate"])
        filters.append(
            f"[0:v:0]trim=start={start:.6f}:end={end:.6f},"
            f"setpts=(PTS-STARTPTS)/{rate:.6f}[v{index}]"
        )
        filters.append(
            f"[0:a:0]atrim=start={start:.6f}:end={end:.6f},"
            f"asetpts=PTS-STARTPTS,atempo={rate:.6f}[a{index}]"
        )
        concat_inputs.append(f"[v{index}][a{index}]")
    filters.append(
        "".join(concat_inputs)
        + f"concat=n={len(pieces)}:v=1:a=1[vout][aout]"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with atomic_output_path(output) as temporary:
        run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-r",
                str(summary["video"]["fps_fraction"] or "30"),
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                str(summary["audio"]["sample_rate"] or 44100),
                "-movflags",
                "+faststart",
                str(temporary),
            ],
            timeout=timeout,
        )


def map_anchors(
    animation_plan: dict[str, Any],
    source_to_output: dict[str, dict[str, float]],
    output_duration: float,
) -> dict[str, Any]:
    anchors = animation_plan.get("segments")
    if not isinstance(anchors, list):
        raise ValueError("animation-plan.json must contain a segments array")
    mapped_anchors = []
    for anchor in anchors:
        mapped = dict(anchor)
        word_ids = [str(value) for value in mapped.get("source_word_ids", [])]
        if not word_ids:
            nested_word_ids = []
            for node in mapped.get("nodes", []):
                if isinstance(node, dict):
                    nested_word_ids.extend(
                        str(value) for value in node.get("source_word_ids", [])
                    )
            word_ids = list(dict.fromkeys(nested_word_ids))
            mapped["source_word_ids"] = word_ids
        available = [
            source_to_output[word_id]
            for word_id in word_ids
            if word_id in source_to_output
        ]
        if not available:
            mapped.update(
                {"status": "dropped", "output_start": None, "output_end": None}
            )
            mapped_anchors.append(mapped)
            continue
        output_start = min(float(item["start"]) for item in available)
        output_end = max(float(item["end"]) for item in available)
        output_start = max(
            0.0,
            output_start + float(mapped.get("start_offset_seconds", 0.0)),
        )
        if mapped.get("duration_seconds") is not None:
            output_end = output_start + float(mapped["duration_seconds"])
        output_end = min(output_duration, output_end)
        mapped["status"] = "mapped"
        mapped["output_start"] = round(output_start, 3)
        mapped["output_end"] = round(output_end, 3)
        mapped = resolve_nested_triggers(
            mapped,
            source_to_output=source_to_output,
            output_start=output_start,
            output_end=output_end,
        )
        missing = [word_id for word_id in word_ids if word_id not in source_to_output]
        if missing:
            mapped["missing_source_word_ids"] = missing
        mapped_anchors.append(mapped)
    return {"version": 1, "anchors": mapped_anchors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--output-video", required=True)
    parser.add_argument("--output-timeline", required=True)
    parser.add_argument("--plan-output", required=True)
    parser.add_argument("--manifest-output", required=True)
    parser.add_argument("--animation-plan")
    parser.add_argument("--anchors-output")
    parser.add_argument("--crf", type=int, default=18)
    parser.add_argument("--preset", default="medium")
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()

    source = Path(args.input).resolve()
    timeline_path = Path(args.timeline).resolve()
    timeline = load_json(timeline_path)
    source_summary = media_summary(source)
    plan = analyze_timeline(timeline)
    plan["inputs"] = {
        "video": file_fingerprint(source),
        "timeline": file_fingerprint(timeline_path),
    }
    pieces = build_pieces(float(source_summary["duration"]), plan["decisions"])
    plan["pieces"] = pieces
    plan["summary"] = {
        "caption_units": len(plan["decisions"]),
        "pause_compressions": sum(
            len(item["pause_edits"]) for item in plan["decisions"]
        ),
        "locally_sped_units": sum(
            float(item["speed_factor"]) > 1.0 for item in plan["decisions"]
        ),
        "maximum_speed_factor": max(
            float(item["speed_factor"]) for item in plan["decisions"]
        ),
        "input_duration": round(float(source_summary["duration"]), 6),
        "planned_output_duration": round(float(pieces[-1]["output_end"]), 6),
    }
    write_json(args.plan_output, plan)

    output_video = Path(args.output_video).resolve()
    render(
        source,
        output_video,
        pieces,
        crf=args.crf,
        preset=args.preset,
        timeout=args.timeout,
    )
    output_summary = media_summary(output_video)
    mapped = remap_timeline(
        timeline,
        pieces,
        actual_duration=float(output_summary["duration"]),
    )
    mapped["inputs"]["rhythm_plan"] = file_fingerprint(args.plan_output)
    mapped["inputs"]["pre_rhythm_timeline"] = file_fingerprint(timeline_path)
    write_json(args.output_timeline, mapped)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "pipeline_version": PIPELINE_VERSION,
        "policy": "adaptive-rhythm-conservative-v1",
        "input": file_fingerprint(source),
        "timeline": file_fingerprint(timeline_path),
        "plan": file_fingerprint(args.plan_output),
        "output": file_fingerprint(output_video),
        "output_media": output_summary,
        "pieces": pieces,
        "ok": (
            bool(output_summary["video"])
            and bool(output_summary["audio"])
            and max(float(item["rate"]) for item in pieces)
            <= MAX_AUTOMATIC_SPEED + EPSILON
        ),
    }
    write_json(args.manifest_output, manifest)
    if manifest["ok"] is not True:
        raise ValueError("adaptive rhythm manifest failed")

    if args.animation_plan:
        if not args.anchors_output:
            raise ValueError("--anchors-output is required with --animation-plan")
        animation_plan = load_json(args.animation_plan)
        write_json(
            args.anchors_output,
            map_anchors(
                animation_plan,
                mapped["source_to_output"],
                float(mapped["duration"]),
            ),
        )
    print(json.dumps(plan["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
