#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shlex
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_text(path: str | Path, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def write_json(path: str | Path, payload: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def append_jsonl(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Append one compact event. A partial final line is safe to ignore after a crash."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_fingerprint(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    stat = target.stat()
    return {
        "path": str(target),
        "sha256": sha256_file(target),
        "size_bytes": stat.st_size,
    }


def command_text(command: Sequence[str]) -> str:
    return shlex.join(str(item) for item in command)


def run(
    command: Sequence[str],
    *,
    capture: bool = False,
    timeout: float | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    log_path: str | Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run an argv command without a shell, with optional bounded execution and logs."""
    started = time.monotonic()
    completed: subprocess.CompletedProcess[str] | None = None
    try:
        completed = subprocess.run(
            [str(item) for item in command],
            check=False,
            text=True,
            stdout=subprocess.PIPE if capture or log_path else None,
            stderr=subprocess.PIPE if capture or log_path else None,
            timeout=timeout,
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
        )
    except subprocess.TimeoutExpired as exc:
        if log_path:
            atomic_write_text(
                log_path,
                "\n".join(
                    [
                        f"$ {command_text(command)}",
                        f"timeout_seconds={timeout}",
                        f"elapsed_seconds={time.monotonic() - started:.3f}",
                        "--- stdout ---",
                        _decode_timeout_output(exc.stdout),
                        "--- stderr ---",
                        _decode_timeout_output(exc.stderr),
                        "",
                    ]
                ),
            )
        raise

    if log_path:
        atomic_write_text(
            log_path,
            "\n".join(
                [
                    f"$ {command_text(command)}",
                    f"returncode={completed.returncode}",
                    f"elapsed_seconds={time.monotonic() - started:.3f}",
                    "--- stdout ---",
                    completed.stdout or "",
                    "--- stderr ---",
                    completed.stderr or "",
                    "",
                ]
            ),
        )
    if check and completed.returncode != 0:
        raise subprocess.CalledProcessError(
            completed.returncode,
            list(command),
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


@contextlib.contextmanager
def atomic_output_path(target: str | Path) -> Iterator[Path]:
    """Yield a same-directory temporary media path and publish it with os.replace."""
    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    suffix = "".join(destination.suffixes) or ".tmp"
    temporary = destination.parent / f".{destination.stem}.{uuid.uuid4().hex}.part{suffix}"
    try:
        yield temporary
        if not temporary.is_file():
            raise RuntimeError(f"expected output was not created: {temporary}")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class RunLock:
    """Small O_EXCL run lock. Stale locks are reported, never silently stolen."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.acquired = False

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"pid": os.getpid(), "created_at": time.time()},
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            details = ""
            try:
                details = f": {self.path.read_text(encoding='utf-8').strip()}"
            except OSError:
                pass
            raise RuntimeError(f"run is locked by another process{details}") from exc
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.acquired = True
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


def ffprobe(path: str | Path) -> dict[str, Any]:
    completed = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        capture=True,
    )
    return json.loads(completed.stdout)


def fraction_to_float(value: str | None) -> float | None:
    if not value or value in {"0/0", "N/A"}:
        return None
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else None
    return float(value)


def media_summary(path: str | Path) -> dict[str, Any]:
    payload = ffprobe(path)
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    duration = payload.get("format", {}).get("duration")
    width = int(video.get("width", 0)) if video else None
    height = int(video.get("height", 0)) if video else None
    if width and height:
        orientation = "landscape" if width > height else "portrait" if height > width else "square"
    else:
        orientation = None
    return {
        "path": str(Path(path).resolve()),
        "duration": float(duration) if duration not in {None, "N/A"} else None,
        "size_bytes": int(payload.get("format", {}).get("size", 0) or 0),
        "format_name": payload.get("format", {}).get("format_name"),
        "video": None
        if video is None
        else {
            "codec": video.get("codec_name"),
            "width": width,
            "height": height,
            "fps": fraction_to_float(video.get("r_frame_rate") or video.get("avg_frame_rate")),
            "fps_fraction": video.get("r_frame_rate") or video.get("avg_frame_rate"),
            "pix_fmt": video.get("pix_fmt"),
            "orientation": orientation,
            "start_time": (
                float(video["start_time"])
                if video.get("start_time") not in {None, "N/A"}
                else 0.0
            ),
        },
        "audio": None
        if audio is None
        else {
            "codec": audio.get("codec_name"),
            "sample_rate": int(audio.get("sample_rate", 0) or 0),
            "channels": int(audio.get("channels", 0) or 0),
            "channel_layout": audio.get("channel_layout"),
            "start_time": (
                float(audio["start_time"])
                if audio.get("start_time") not in {None, "N/A"}
                else 0.0
            ),
        },
    }
