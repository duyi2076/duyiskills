#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
"""Offline Silero VAD inference and deterministic speech-region post-processing."""

from __future__ import annotations

from array import array
from pathlib import Path
from typing import Any


SAMPLE_RATE = 16000
WINDOW_SAMPLES = 512
WINDOW_SECONDS = WINDOW_SAMPLES / SAMPLE_RATE
CONTEXT_SAMPLES = 64
ENTER_THRESHOLD = 0.50
EXIT_THRESHOLD = 0.35
MIN_EXIT_SILENCE_SECONDS = 0.064


def speech_probabilities(samples: array, model_path: Path) -> list[float]:
    """Return one speech probability for every 32 ms frame."""
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(
            "onnxruntime and numpy are required for acoustic speech detection"
        ) from exc

    if not model_path.is_file():
        raise FileNotFoundError(f"Silero VAD model is missing: {model_path}")

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    audio = np.frombuffer(samples.tobytes(), dtype=np.int16).astype(np.float32)
    audio /= 32768.0
    state = np.zeros((2, 1, 128), dtype=np.float32)
    context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)
    sample_rate = np.array(SAMPLE_RATE, dtype=np.int64)
    probabilities: list[float] = []

    for offset in range(0, len(audio), WINDOW_SAMPLES):
        chunk = audio[offset : offset + WINDOW_SAMPLES]
        if len(chunk) < WINDOW_SAMPLES:
            chunk = np.pad(chunk, (0, WINDOW_SAMPLES - len(chunk)))
        model_input = np.concatenate([context, chunk.reshape(1, -1)], axis=1)
        output, state = session.run(
            None,
            {"input": model_input, "state": state, "sr": sample_rate},
        )
        probabilities.append(float(output[0, 0]))
        context = model_input[:, -CONTEXT_SAMPLES:]
    return probabilities


def speech_regions(
    probabilities: list[float],
    *,
    timeline_offset: float,
    decoded_duration: float,
    enter_threshold: float = ENTER_THRESHOLD,
    exit_threshold: float = EXIT_THRESHOLD,
    min_exit_silence: float = MIN_EXIT_SILENCE_SECONDS,
) -> list[dict[str, Any]]:
    """Convert frame probabilities into hysteretic media-timeline speech regions."""
    regions: list[dict[str, Any]] = []
    active = False
    start_frame: int | None = None
    below_frame: int | None = None
    peak_probability = 0.0
    required_exit_frames = max(
        1,
        int(round(min_exit_silence / WINDOW_SECONDS)),
    )

    for frame, probability in enumerate(probabilities):
        if not active:
            if probability >= enter_threshold:
                active = True
                start_frame = frame
                below_frame = None
                peak_probability = probability
            continue

        peak_probability = max(peak_probability, probability)
        if probability < exit_threshold:
            below_frame = frame if below_frame is None else below_frame
            if frame - below_frame + 1 >= required_exit_frames:
                regions.append(
                    {
                        "start": round(
                            timeline_offset + start_frame * WINDOW_SECONDS,
                            6,
                        ),
                        "end": round(
                            timeline_offset + below_frame * WINDOW_SECONDS,
                            6,
                        ),
                        "peak_probability": round(peak_probability, 6),
                    }
                )
                active = False
                start_frame = None
                below_frame = None
                peak_probability = 0.0
        else:
            below_frame = None

    if active and start_frame is not None:
        regions.append(
            {
                "start": round(
                    timeline_offset + start_frame * WINDOW_SECONDS,
                    6,
                ),
                "end": round(timeline_offset + decoded_duration, 6),
                "peak_probability": round(peak_probability, 6),
            }
        )
    return regions


def candidate_speech_onset(
    regions: list[dict[str, Any]],
    *,
    first_word_start: float,
    entry_context: str,
    predecessor_end: float | None,
) -> tuple[float, float] | None:
    """Find a credible new speech onset near one retained segment entry."""
    if entry_context not in {"opening", "after-filler", "normal"}:
        raise ValueError(f"unsupported entry context: {entry_context}")

    if entry_context == "opening":
        lower = max(0.0, first_word_start - 0.30)
        upper = first_word_start + 0.60
    elif entry_context == "after-filler":
        if predecessor_end is None:
            return None
        lower = max(predecessor_end + 0.040, first_word_start - 0.12)
        upper = first_word_start + 0.60
    else:
        lower = first_word_start - 0.080
        upper = first_word_start + 0.45

    candidates = [
        region
        for region in regions
        if lower <= float(region["start"]) <= upper
        and float(region["end"]) >= first_word_start - 0.040
    ]
    if not candidates:
        return None
    chosen = min(
        candidates,
        key=lambda region: (
            abs(float(region["start"]) - first_word_start),
            float(region["start"]),
        ),
    )
    return float(chosen["start"]), float(chosen["peak_probability"])
