#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
"""Refine semantic cut bounds with ASR words and deterministic audio activity."""

from __future__ import annotations

import argparse
import math
import statistics
import sys
import tempfile
import wave
from array import array
from pathlib import Path
from typing import Any

from acoustic_vad import (
    candidate_speech_onset,
    speech_probabilities,
    speech_regions,
)
from common import (
    file_fingerprint,
    load_json,
    media_summary,
    run,
    sha256_file,
    write_json,
)
from contracts import EXIT_BLOCKED, PIPELINE_VERSION, validate_cut_plan
from speech_text import is_hard_filler


FRAME_SECONDS = 0.010
SAMPLE_RATE = 16000
MIN_HEADROOM = 0.020
OPENING_HEADROOM = 0.032
FILLER_HEADROOM = 0.030
NORMAL_HEADROOM = 0.055
MAX_OPENING_HEADROOM = 0.060
MAX_FILLER_HEADROOM = 0.060
MAX_NORMAL_HEADROOM = 0.090
MAX_FILLER_PREDECESSOR_GAP = 0.900
CONTINUOUS_FILLER_GAP_MAX = 0.012
CONTINUOUS_FILLER_OVERLAP_MAX = 0.020
CONTINUOUS_SPLICE_PREROLL = 0.004
CONTINUOUS_SPLICE_POSTROLL = 0.002
CONTINUOUS_SPLICE_FADE_MS = 4
MIN_TAILROOM = 0.020
TARGET_TAILROOM = 0.100
MAX_TAIL_SEARCH = 0.350
QUIET_RUN = 0.020
EPSILON = 0.0005
SILERO_MODEL = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "vad"
    / "silero_vad.onnx"
)


def _dbfs(samples: array) -> float:
    if not samples:
        return -96.0
    mean_square = sum(float(value) * float(value) for value in samples) / len(samples)
    if mean_square <= 1.0:
        return -96.0
    return 20.0 * math.log10(math.sqrt(mean_square) / 32768.0)


def extract_activity(
    source: Path,
) -> tuple[list[float], list[bool], float, float, float, array]:
    """Return energy activity plus the audio stream's media-timeline offset."""
    summary = media_summary(source)
    audio = summary.get("audio") or {}
    timeline_offset = float(audio.get("start_time") or 0.0)
    with tempfile.TemporaryDirectory(prefix="duyi-boundary-audio-") as folder:
        wav_path = Path(folder) / "mono.wav"
        run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(SAMPLE_RATE),
                "-c:a",
                "pcm_s16le",
                str(wav_path),
            ],
            timeout=900,
        )
        with wave.open(str(wav_path), "rb") as handle:
            if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
                raise ValueError("decoded boundary audio must be mono signed 16-bit PCM")
            samples = array("h")
            samples.frombytes(handle.readframes(handle.getnframes()))
            duration = len(samples) / float(handle.getframerate())

    frame_size = max(1, int(round(SAMPLE_RATE * FRAME_SECONDS)))
    levels = [_dbfs(samples[offset : offset + frame_size]) for offset in range(0, len(samples), frame_size)]
    if not levels:
        raise ValueError("source audio decoded to zero samples")
    ordered = sorted(levels)
    noise_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.20)))
    noise_floor = ordered[noise_index]
    threshold = max(-44.0, min(-30.0, noise_floor + 11.0))
    raw = [level >= threshold for level in levels]

    # Close isolated 10–20 ms holes inside speech and remove isolated one-frame spikes.
    closed = raw[:]
    for index in range(1, len(raw) - 1):
        if not raw[index] and raw[index - 1] and raw[index + 1]:
            closed[index] = True
    for index in range(2, len(raw) - 2):
        if not closed[index] and closed[index - 1] and closed[index - 2] and closed[index + 1] and closed[index + 2]:
            closed[index] = True
    smoothed = closed[:]
    for index in range(1, len(closed) - 1):
        if closed[index] and not closed[index - 1] and not closed[index + 1]:
            smoothed[index] = False
    return levels, smoothed, threshold, duration, timeline_offset, samples


def frame_index(
    time_seconds: float,
    frame_count: int,
    timeline_offset: float = 0.0,
) -> int:
    decoded_time = time_seconds - timeline_offset
    return min(
        frame_count - 1,
        max(0, int(math.floor(decoded_time / FRAME_SECONDS))),
    )


def quiet_at(
    activity: list[bool],
    time_seconds: float,
    radius: float = 0.005,
    timeline_offset: float = 0.0,
) -> bool:
    start = frame_index(
        max(timeline_offset, time_seconds - radius),
        len(activity),
        timeline_offset,
    )
    end = frame_index(time_seconds + radius, len(activity), timeline_offset)
    return not any(activity[start : end + 1])


def choose_quiet_boundary(
    activity: list[bool],
    lower: float,
    upper: float,
    target: float,
    timeline_offset: float = 0.0,
) -> float | None:
    if upper < lower:
        return None
    start_index = frame_index(lower, len(activity), timeline_offset)
    end_index = frame_index(upper, len(activity), timeline_offset)
    candidates = [
        timeline_offset + index * FRAME_SECONDS
        for index in range(start_index, end_index + 1)
        if quiet_at(
            activity,
            timeline_offset + index * FRAME_SECONDS,
            timeline_offset=timeline_offset,
        )
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda value: (abs(value - target), value))


def choose_continuous_splice_boundary(
    samples: array,
    *,
    lower: float,
    upper: float,
    target: float,
    timeline_offset: float = 0.0,
) -> float:
    """Choose the closest sample-level zero crossing around an ASR token boundary."""
    if upper < lower:
        lower = upper = max(lower, upper)
    lower_sample = max(
        1,
        int(math.floor((lower - timeline_offset) * SAMPLE_RATE)),
    )
    upper_sample = min(
        len(samples) - 1,
        int(math.ceil((upper - timeline_offset) * SAMPLE_RATE)),
    )
    target_sample = min(
        len(samples) - 1,
        max(1, int(round((target - timeline_offset) * SAMPLE_RATE))),
    )
    candidates: list[int] = []
    for index in range(lower_sample, upper_sample + 1):
        previous = int(samples[index - 1])
        current = int(samples[index])
        if current == 0 or previous == 0 or (previous < 0 < current) or (previous > 0 > current):
            candidates.append(index)
    if not candidates:
        chosen = min(upper_sample, max(lower_sample, target_sample))
    else:
        # Preserve the retained syllable: at equal distance prefer a crossing
        # just before, rather than after, the ASR boundary.
        chosen = min(
            candidates,
            key=lambda index: (
                abs(index - target_sample),
                index > target_sample,
                index,
            ),
        )
    return timeline_offset + chosen / float(SAMPLE_RATE)


def first_quiet_run_after(
    activity: list[bool],
    start: float,
    upper: float,
    minimum_run: float = QUIET_RUN,
    timeline_offset: float = 0.0,
) -> tuple[float, float] | None:
    start_index = frame_index(start, len(activity), timeline_offset)
    end_index = frame_index(upper, len(activity), timeline_offset)
    required = max(1, int(math.ceil(minimum_run / FRAME_SECONDS)))
    run_start: int | None = None
    for index in range(start_index, end_index + 1):
        if not activity[index]:
            run_start = index if run_start is None else run_start
            if index - run_start + 1 >= required:
                return (
                    timeline_offset + run_start * FRAME_SECONDS,
                    timeline_offset + (index + 1) * FRAME_SECONDS,
                )
        else:
            run_start = None
    return None


def words_inside(
    words: list[dict[str, Any]],
    start: float,
    end: float,
    timeline_offset: float = 0.0,
) -> list[dict[str, Any]]:
    return [
        word
        for word in words
        if float(word["start"]) + timeline_offset >= start - EPSILON
        and float(word["end"]) + timeline_offset <= end + EPSILON
    ]


def is_filler(word: dict[str, Any]) -> bool:
    return is_hard_filler(word.get("text", ""))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refine a semantic cut plan using ASR word bounds and decoded audio activity."
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--plan", required=True, help="Agent-authored semantic cut plan")
    parser.add_argument("--output", required=True, help="Refined cut plan")
    parser.add_argument("--report", required=True, help="Acoustic boundary report")
    args = parser.parse_args()

    source_path = Path(args.input).resolve()
    transcript_path = Path(args.transcript).resolve()
    raw_plan_path = Path(args.plan).resolve()
    output_path = Path(args.output).resolve()
    report_path = Path(args.report).resolve()
    transcript = load_json(transcript_path)
    raw_plan = validate_cut_plan(load_json(raw_plan_path))
    words = transcript.get("words", [])
    if not isinstance(words, list) or not words:
        raise ValueError("normalized transcript must contain words")
    word_by_id = {str(word["word_id"]): word for word in words}
    word_position = {str(word["word_id"]): index for index, word in enumerate(words)}
    (
        levels,
        activity,
        threshold,
        decoded_audio_duration,
        timeline_offset,
        audio_samples,
    ) = extract_activity(source_path)
    probabilities = speech_probabilities(audio_samples, SILERO_MODEL)
    detected_speech_regions = speech_regions(
        probabilities,
        timeline_offset=timeline_offset,
        decoded_duration=decoded_audio_duration,
    )
    media_audio_end = timeline_offset + decoded_audio_duration

    source_window = raw_plan.get("source_window") or {}
    window_start = max(
        timeline_offset,
        timeline_offset + float(source_window.get("start", 0.0)),
    )
    window_end = min(
        media_audio_end,
        timeline_offset
        + float(
            source_window.get("end", decoded_audio_duration)
            or decoded_audio_duration
        ),
    )
    raw_segments = raw_plan.get("segments", [])
    refined_segments: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    previous_refined_end = window_start

    for segment_index, segment in enumerate(raw_segments):
        segment_id = str(segment.get("id") or f"keep-{segment_index + 1:03d}")
        raw_asr_start = float(segment["source_start"])
        raw_asr_end = float(segment["source_end"])
        raw_start = raw_asr_start + timeline_offset
        raw_end = raw_asr_end + timeline_offset
        listed_ids = [str(item) for item in segment.get("source_word_ids", [])]
        listed_words = [word_by_id[item] for item in listed_ids if item in word_by_id]
        contained = words_inside(
            words,
            raw_start,
            raw_end,
            timeline_offset,
        )
        if not listed_words:
            listed_words = contained
        if not listed_words:
            errors.append({"code": "boundary_segment_has_no_words", "segment": segment_id})
            continue

        first_word = listed_words[0]
        last_word = listed_words[-1]
        leading_removed: list[str] = []
        first_position = word_position[str(first_word["word_id"])]
        last_position = word_position[str(last_word["word_id"])]
        while is_filler(first_word) and first_position < last_position:
            leading_removed.append(str(first_word["word_id"]))
            first_position += 1
            first_word = words[first_position]
        first_start = float(first_word["start"]) + timeline_offset
        last_end = float(last_word["end"]) + timeline_offset

        predecessor = words[first_position - 1] if first_position > 0 else None
        predecessor_end = (
            float(predecessor["end"]) + timeline_offset
            if predecessor is not None
            else None
        )
        predecessor_is_discarded_filler = bool(
            predecessor
            and is_filler(predecessor)
            and str(predecessor["word_id"]) not in listed_ids
            and first_start - float(predecessor_end)
            <= MAX_FILLER_PREDECESSOR_GAP
        )
        filler_gap = (
            first_start - float(predecessor_end)
            if predecessor_is_discarded_filler
            and predecessor_end is not None
            else None
        )
        continuous_filler_boundary = bool(
            filler_gap is not None
            and -CONTINUOUS_FILLER_OVERLAP_MAX
            <= filler_gap
            <= CONTINUOUS_FILLER_GAP_MAX
        )
        entry_context = (
            "opening"
            if segment_index == 0
            else "after-filler"
            if predecessor_is_discarded_filler
            else "normal"
        )
        base_minimum_start = max(
            window_start,
            previous_refined_end + (0.010 if segment_index else 0.0),
        )
        minimum_start = base_minimum_start
        if predecessor is not None and not continuous_filler_boundary:
            # A quiet energy frame can still sit inside a low-energy consonant or
            # trailing word. Never choose a boundary until the preceding ASR word
            # has ended; the audit gate must not be the first place to catch it.
            minimum_start = max(minimum_start, float(predecessor_end) + 0.005)
        if predecessor_is_discarded_filler and not continuous_filler_boundary:
            minimum_start = max(minimum_start, float(predecessor_end) + 0.015)

        vad_onset = (
            None
            if continuous_filler_boundary
            else candidate_speech_onset(
                detected_speech_regions,
                first_word_start=first_start,
                entry_context=entry_context,
                predecessor_end=predecessor_end,
            )
        )
        search_lower = minimum_start
        search_upper = first_start - MIN_HEADROOM
        if continuous_filler_boundary:
            onset_probability = None
            speech_onset = first_start
            search_lower = max(
                base_minimum_start,
                float(predecessor_end) - CONTINUOUS_SPLICE_PREROLL,
            )
            search_upper = min(
                raw_end - 0.25,
                first_start + CONTINUOUS_SPLICE_POSTROLL,
            )
            if search_upper < search_lower:
                search_lower = search_upper = first_start
            refined_start = choose_continuous_splice_boundary(
                audio_samples,
                lower=search_lower,
                upper=search_upper,
                target=first_start,
                timeline_offset=timeline_offset,
            )
            headroom = max(0.0, speech_onset - refined_start)
            entry_clean = (
                refined_start
                >= float(predecessor_end) - CONTINUOUS_SPLICE_PREROLL - EPSILON
                and refined_start
                <= first_start + CONTINUOUS_SPLICE_POSTROLL + EPSILON
            )
            entry_strategy = "continuous-speech-zero-cross-splice"
        elif vad_onset is not None:
            speech_onset, onset_probability = vad_onset
            requested_headroom = (
                OPENING_HEADROOM
                if entry_context == "opening"
                else FILLER_HEADROOM
                if entry_context == "after-filler"
                else NORMAL_HEADROOM
            )
            refined_start = max(minimum_start, speech_onset - requested_headroom)
            headroom = max(0.0, speech_onset - refined_start)
            entry_clean = headroom >= MIN_HEADROOM - EPSILON
            entry_strategy = "silero-speech-onset"
        else:
            onset_probability = None
            speech_onset = first_start
            requested_headroom = (
                OPENING_HEADROOM
                if entry_context == "opening"
                else FILLER_HEADROOM
                if entry_context == "after-filler"
                else NORMAL_HEADROOM
            )
            maximum_headroom = (
                MAX_OPENING_HEADROOM
                if entry_context == "opening"
                else MAX_FILLER_HEADROOM
                if entry_context == "after-filler"
                else MAX_NORMAL_HEADROOM
            )
            search_lower = max(minimum_start, first_start - maximum_headroom)
            search_upper = min(first_start - MIN_HEADROOM, raw_end - 0.25)
            target = max(search_lower, first_start - requested_headroom)
            refined_start = choose_quiet_boundary(
                activity,
                search_lower,
                search_upper,
                target,
                timeline_offset,
            )
            entry_clean = refined_start is not None
            if refined_start is None:
                refined_start = max(
                    search_lower,
                    min(search_upper, first_start - MIN_HEADROOM),
                )
            headroom = max(0.0, speech_onset - refined_start)
            entry_strategy = "energy-trough-near-asr"

        next_raw_start = (
            float(raw_segments[segment_index + 1]["source_start"])
            + timeline_offset
            if segment_index + 1 < len(raw_segments)
            else window_end
        )
        next_word = words[last_position + 1] if last_position + 1 < len(words) else None
        upper_tail = min(window_end, raw_end + MAX_TAIL_SEARCH, next_raw_start - 0.010)
        if next_word and str(next_word["word_id"]) not in listed_ids:
            next_start = float(next_word["start"]) + timeline_offset
            if next_start >= last_end:
                upper_tail = min(upper_tail, next_start)
        quiet_run = first_quiet_run_after(
            activity,
            max(last_end - 0.020, timeline_offset),
            upper_tail,
            timeline_offset=timeline_offset,
        )
        if quiet_run:
            speech_offset = max(last_end, quiet_run[0])
            refined_end = min(upper_tail, speech_offset + TARGET_TAILROOM)
            tail_clear = refined_end - speech_offset >= MIN_TAILROOM - EPSILON
        else:
            speech_offset = last_end
            refined_end = min(upper_tail, max(raw_end, last_end + MIN_TAILROOM))
            tail_clear = False
        refined_end = max(refined_end, last_end + min(MIN_TAILROOM, max(0.0, upper_tail - last_end)))
        tailroom = max(0.0, refined_end - speech_offset)

        if not entry_clean:
            errors.append(
                {
                    "code": (
                        "unsafe_continuous_splice_boundary"
                        if continuous_filler_boundary
                        else "no_quiet_entry_boundary"
                    ),
                    "segment": segment_id,
                    "search_window": [
                        round(search_lower, 3),
                        round(search_upper, 3),
                    ],
                }
            )
        if (
            predecessor_is_discarded_filler
            and not continuous_filler_boundary
            and refined_start <= float(predecessor_end) + EPSILON
        ):
            entry_clean = False
            errors.append(
                {
                    "code": "discarded_filler_tail_may_leak",
                    "segment": segment_id,
                    "filler_word_id": predecessor["word_id"],
                }
            )
        if not tail_clear:
            errors.append(
                {
                    "code": "no_confirmed_quiet_tail",
                    "segment": segment_id,
                    "search_end": round(upper_tail, 3),
                }
            )
        if refined_end <= refined_start:
            errors.append({"code": "invalid_refined_bounds", "segment": segment_id})

        fade_in_ms = (
            CONTINUOUS_SPLICE_FADE_MS
            if entry_clean and continuous_filler_boundary
            else 8
            if entry_clean and headroom >= 0.040
            else 0
        )
        fade_out_ms = 8 if tail_clear and tailroom >= 0.020 else 0
        analysis = {
            "first_meaningful_word_id": first_word["word_id"],
            "first_meaningful_word": first_word["text"],
            "last_word_id": last_word["word_id"],
            "last_word": last_word["text"],
            "removed_leading_filler_word_ids": leading_removed,
            "discarded_predecessor_filler_word_id": (
                predecessor["word_id"] if predecessor_is_discarded_filler else None
            ),
            "entry_clean": entry_clean,
            "tail_clear": tail_clear,
            "entry_context": entry_context,
            "entry_strategy": entry_strategy,
            "speech_onset_seconds": round(speech_onset, 3),
            "speech_onset_probability": (
                round(onset_probability, 4)
                if onset_probability is not None
                else None
            ),
            "asr_first_word_start_seconds": round(first_start, 3),
            "asr_to_acoustic_delta_seconds": round(
                speech_onset - first_start,
                3,
            ),
            "continuous_filler_gap_seconds": (
                round(float(filler_gap), 4)
                if filler_gap is not None
                else None
            ),
            "headroom_seconds": round(headroom, 3),
            "speech_offset": round(speech_offset, 3),
            "tailroom_seconds": round(tailroom, 3),
            "fade_in_ms": fade_in_ms,
            "fade_out_ms": fade_out_ms,
            "activity_threshold_dbfs": round(threshold, 2),
        }
        refined = dict(segment)
        refined["semantic_source_start"] = raw_start
        refined["semantic_source_end"] = raw_end
        refined["semantic_asr_start"] = raw_asr_start
        refined["semantic_asr_end"] = raw_asr_end
        refined["source_start"] = round(refined_start, 3)
        refined["source_end"] = round(refined_end, 3)
        refined["source_word_ids"] = [str(first_word["word_id"]), str(last_word["word_id"])]
        refined["boundary_analysis"] = analysis
        refined_segments.append(refined)
        checks.append(
            {
                "segment": segment_id,
                "semantic_bounds": [raw_start, raw_end],
                "refined_bounds": [refined["source_start"], refined["source_end"]],
                **analysis,
            }
        )
        previous_refined_end = refined_end

    refined_plan = dict(raw_plan)
    refined_plan["pipeline_version"] = PIPELINE_VERSION
    refined_plan["plan_version"] = "3.0"
    refined_plan["source_plan"] = file_fingerprint(raw_plan_path)
    refined_plan["boundary_refinement"] = {
        "method": "asr-plus-silero-vad-plus-energy",
        "frame_seconds": FRAME_SECONDS,
        "activity_threshold_dbfs": round(threshold, 2),
        "source_timeline_offset_seconds": round(timeline_offset, 6),
        "silero_model_sha256": sha256_file(SILERO_MODEL),
        "dynamic_headroom_seconds": {
            "opening": OPENING_HEADROOM,
            "after_filler": FILLER_HEADROOM,
            "normal": NORMAL_HEADROOM,
        },
        "minimum_headroom_seconds": MIN_HEADROOM,
        "continuous_speech_splice": {
            "enabled": True,
            "maximum_filler_gap_seconds": CONTINUOUS_FILLER_GAP_MAX,
            "maximum_filler_overlap_seconds": CONTINUOUS_FILLER_OVERLAP_MAX,
            "maximum_preroll_seconds": CONTINUOUS_SPLICE_PREROLL,
            "maximum_postroll_seconds": CONTINUOUS_SPLICE_POSTROLL,
            "fade_in_ms": CONTINUOUS_SPLICE_FADE_MS,
        },
        "minimum_tailroom_seconds": MIN_TAILROOM,
    }
    refined_plan["segments"] = refined_segments
    write_json(output_path, refined_plan)

    report = {
        "schema_version": 1,
        "pipeline_version": PIPELINE_VERSION,
        "ok": not errors and len(refined_segments) == len(raw_segments),
        "method": "asr-plus-silero-vad-plus-energy",
        "inputs": {
            "source_media": file_fingerprint(source_path),
            "transcript": file_fingerprint(transcript_path),
            "semantic_plan": file_fingerprint(raw_plan_path),
            "refined_plan": file_fingerprint(output_path),
        },
        "audio": {
            "sample_rate": SAMPLE_RATE,
            "frame_seconds": FRAME_SECONDS,
            "decoded_duration": round(decoded_audio_duration, 3),
            "media_timeline_start": round(timeline_offset, 6),
            "media_timeline_end": round(media_audio_end, 6),
            "noise_floor_dbfs_p20": round(statistics.quantiles(levels, n=5)[0], 2)
            if len(levels) >= 5
            else round(min(levels), 2),
            "activity_threshold_dbfs": round(threshold, 2),
            "speech_region_count": len(detected_speech_regions),
            "silero_model": file_fingerprint(SILERO_MODEL),
        },
        "segment_count": len(refined_segments),
        "checks": checks,
        "errors": errors,
    }
    write_json(report_path, report)
    state = "PASS" if report["ok"] else "BLOCKED"
    print(f"boundary refine: {state} ({len(refined_segments)} segments, {len(errors)} errors)")
    if report["ok"]:
        print(f"refined plan sha256: {sha256_file(output_path)}")
        return 0
    return EXIT_BLOCKED


if __name__ == "__main__":
    sys.exit(main())
