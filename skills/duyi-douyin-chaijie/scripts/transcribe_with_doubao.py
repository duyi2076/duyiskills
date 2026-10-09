#!/usr/bin/env python3
"""Call Agent Plan ASR first, then fall back to local Whisper when needed."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    import pwd
except ImportError:  # Windows has no pwd module.
    pwd = None


DEFAULT_ASR_SCRIPT: Path | None = None
DEFAULT_ENV: Path | None = None
DEFAULT_MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
DEFAULT_OPENAI_WHISPER_MODEL = "turbo"
DEFAULT_AGENT_PLAN_CHUNK_SECONDS = 30.0


def resolve_operator_home(
    environ: dict[str, str] | None = None,
    *,
    os_home: Path | None = None,
) -> Path:
    """Resolve the real OS account home even when a profile isolates subprocess HOME."""
    env = environ or os.environ
    explicit = str(env.get("DUYI_OPERATOR_HOME") or "").strip()
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            raise ValueError("DUYI_OPERATOR_HOME must be an absolute path.")
        return candidate.resolve()
    if os_home is not None:
        return os_home.resolve()
    if pwd is not None:
        try:
            return Path(pwd.getpwuid(os.getuid()).pw_dir).resolve()
        except (KeyError, OSError):
            pass
    return Path.home().resolve()


def mlx_subprocess_env(
    environ: dict[str, str] | None = None,
    *,
    os_home: Path | None = None,
) -> dict[str, str]:
    """Restore HOME only for the mlx_whisper child; keep the caller profile isolated."""
    base = dict(environ or os.environ)
    base["HOME"] = str(resolve_operator_home(base, os_home=os_home))
    base.pop("PYTHONHOME", None)
    return base


def run_mlx_preflight(
    timeout: int = 30,
    *,
    environ: dict[str, str] | None = None,
    os_home: Path | None = None,
) -> dict:
    env = mlx_subprocess_env(environ, os_home=os_home)
    exe = shutil.which("mlx_whisper", path=env.get("PATH"))
    if not exe:
        return {"ok": False, "provider": "mlx_whisper", "error": "mlx_whisper not found on PATH"}
    try:
        proc = subprocess.run(
            [exe, "--help"],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "provider": "mlx_whisper",
            "executable": exe,
            "operator_home": env.get("HOME", ""),
            "error": f"mlx_whisper preflight timed out after {timeout}s",
        }
    if proc.returncode != 0:
        return {
            "ok": False,
            "provider": "mlx_whisper",
            "executable": exe,
            "operator_home": env.get("HOME", ""),
            "error": (proc.stderr or proc.stdout or "mlx_whisper preflight failed").strip()[-4000:],
        }
    return {
        "ok": True,
        "provider": "mlx_whisper",
        "executable": exe,
        "operator_home": env.get("HOME", ""),
    }


def collect_utterances(result: dict) -> list[dict]:
    raw = result.get("raw")
    if not isinstance(raw, dict):
        return []
    payload = raw.get("result") if isinstance(raw.get("result"), dict) else raw
    utterances = payload.get("utterances") if isinstance(payload, dict) else None
    if not isinstance(utterances, list):
        return []
    cleaned = []
    for item in utterances:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        cleaned.append(
            {
                "text": text,
                "start_time": item.get("start_time", item.get("start")),
                "end_time": item.get("end_time", item.get("end")),
            }
        )
    return cleaned


def display_time(result: dict, value) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if str(result.get("provider") or "").startswith("agent_plan"):
        number = number / 1000
    return f"{number:.2f}".rstrip("0").rstrip(".")


def write_transcript(out_dir: Path, result: dict) -> None:
    transcript_dir = out_dir / "transcript"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# ASR 转写", ""]
    if result.get("ok"):
        text = str(result.get("text") or "").strip()
        utterances = collect_utterances(result)
        if utterances:
            for item in utterances:
                start = item.get("start_time")
                end = item.get("end_time")
                stamp = ""
                if start is not None or end is not None:
                    stamp = f"[{display_time(result, start)}-{display_time(result, end)}] "
                lines.append(f"{stamp}{item['text']}")
        elif text:
            lines.append(text)
        else:
            lines.append("素材不足：ASR 返回成功但没有文本。")
    else:
        lines.append("素材不足：ASR 转写失败。")
        lines.append("")
        lines.append(str(result.get("error") or result.get("last_error") or "unknown error"))
    (transcript_dir / "transcript.md").write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def run_agent_plan_file(args: argparse.Namespace, video_path: Path, seconds: float | None = None) -> dict:
    if args.asr_script is None or args.env is None:
        return {
            "ok": False,
            "provider": "agent_plan",
            "error": "Agent Plan ASR requires --asr-script and --env; local mlx_whisper is the public default.",
        }
    cmd = [
        "python3",
        str(args.asr_script),
        str(video_path),
        "--env",
        str(args.env),
        "--timeout",
        str(args.timeout),
        "--json",
        "--raw",
    ]
    if seconds:
        cmd.extend(["--seconds", str(seconds)])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        result = {
            "ok": False,
            "provider": "agent_plan",
            "error": (proc.stderr or proc.stdout or "ASR command returned no JSON").strip()[-4000:],
        }
    if proc.returncode != 0 and result.get("ok") is not True:
        result.setdefault("error", (proc.stderr or "ASR command failed").strip()[-4000:])
    return result


def media_duration(path: Path) -> float | None:
    cmd = [
        "ffprobe",
        "-hide_banner",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nw=1:nk=1",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def shift_time(value, offset_ms: int):
    if value is None:
        return value
    try:
        return float(value) + offset_ms
    except (TypeError, ValueError):
        return value


def collect_agent_plan_utterances(result: dict) -> list[dict]:
    raw = result.get("raw")
    payload = raw.get("result") if isinstance(raw, dict) and isinstance(raw.get("result"), dict) else raw
    utterances = payload.get("utterances") if isinstance(payload, dict) else None
    return utterances if isinstance(utterances, list) else []


def shifted_utterance(item: dict, offset_ms: int) -> dict:
    shifted = dict(item)
    for key in ("start_time", "end_time", "start", "end"):
        if key in shifted:
            shifted[key] = shift_time(shifted.get(key), offset_ms)
    words = shifted.get("words")
    if isinstance(words, list):
        shifted_words = []
        for word in words:
            if not isinstance(word, dict):
                shifted_words.append(word)
                continue
            shifted_word = dict(word)
            for key in ("start_time", "end_time", "start", "end"):
                if key in shifted_word:
                    shifted_word[key] = shift_time(shifted_word.get(key), offset_ms)
            shifted_words.append(shifted_word)
        shifted["words"] = shifted_words
    return shifted


def run_agent_plan_chunked(args: argparse.Namespace) -> dict:
    chunk_seconds = args.agent_plan_chunk_seconds
    if args.seconds or not chunk_seconds or chunk_seconds <= 0:
        return run_agent_plan_file(args, args.video, args.seconds)

    duration = media_duration(args.video)
    if duration is None or duration <= chunk_seconds:
        return run_agent_plan_file(args, args.video)

    with tempfile.TemporaryDirectory(prefix="douyin-agent-plan-chunks-") as tmpdir:
        tmp = Path(tmpdir)
        chunk_pattern = tmp / "chunk-%04d.wav"
        segment_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(args.video),
            "-map",
            "0:a:0",
            "-vn",
            "-f",
            "segment",
            "-segment_time",
            str(chunk_seconds),
            "-reset_timestamps",
            "1",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(chunk_pattern),
        ]
        proc = subprocess.run(segment_cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return {
                "ok": False,
                "provider": "agent_plan_chunked",
                "error": (proc.stderr or "ffmpeg chunking failed").strip()[-4000:],
            }

        chunks = sorted(tmp.glob("chunk-*.wav"))
        if not chunks:
            return {"ok": False, "provider": "agent_plan_chunked", "error": "No audio chunks were created."}

        merged_utterances = []
        merged_text = []
        first_success = None
        for index, chunk_path in enumerate(chunks):
            offset_ms = int(round(index * chunk_seconds * 1000))
            result = run_agent_plan_file(args, chunk_path)
            if not result.get("ok"):
                result["provider"] = "agent_plan_chunked"
                result["chunk_index"] = index
                result["chunk_offset_ms"] = offset_ms
                return result
            if first_success is None:
                first_success = result
            if result.get("text"):
                merged_text.append(str(result.get("text") or "").strip())
            for item in collect_agent_plan_utterances(result):
                if isinstance(item, dict):
                    merged_utterances.append(shifted_utterance(item, offset_ms))

        return {
            "ok": True,
            "provider": "agent_plan_chunked",
            "auth_mode": first_success.get("auth_mode") if first_success else "",
            "resource_id": first_success.get("resource_id") if first_success else "",
            "ws_url": first_success.get("ws_url") if first_success else "",
            "key_suffix": first_success.get("key_suffix") if first_success else "",
            "chunk_seconds": chunk_seconds,
            "chunk_count": len(chunks),
            "duration": duration,
            "text": "".join(merged_text),
            "raw": {"result": {"utterances": merged_utterances}},
        }


def normalize_local_whisper(data: dict, *, provider: str, model: str, fallback_from: dict) -> dict:
    segments = data.get("segments") if isinstance(data.get("segments"), list) else []
    utterances = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        utterances.append(
            {
                "text": text,
                "start_time": segment.get("start"),
                "end_time": segment.get("end"),
            }
        )
    fallback_error = fallback_from.get("last_error") or fallback_from.get("error")
    return {
        "ok": True,
        "provider": provider,
        "model": model,
        "fallback_from": {
            "provider": fallback_from.get("provider", "agent_plan"),
            "error": fallback_error,
        },
        "text": str(data.get("text") or "").strip(),
        "raw": {
            "result": {"utterances": utterances},
            "whisper": data,
        },
    }


def run_mlx_whisper(args: argparse.Namespace, local_dir: Path, agent_result: dict) -> dict:
    preflight = run_mlx_preflight()
    if not preflight.get("ok"):
        return preflight
    exe = str(preflight["executable"])
    env = mlx_subprocess_env()

    output_name = "local"
    cmd = [
        exe,
        str(args.video),
        "--model",
        args.mlx_model,
        "--language",
        args.language,
        "--output-dir",
        str(local_dir),
        "--output-format",
        "json",
        "--output-name",
        output_name,
        "--verbose",
        "False",
    ]
    if args.seconds:
        cmd.extend(["--clip-timestamps", f"0,{args.seconds}"])
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.local_timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "provider": "mlx_whisper", "error": f"Timed out after {args.local_timeout}s"}

    json_path = local_dir / f"{output_name}.json"
    if proc.returncode != 0:
        return {
            "ok": False,
            "provider": "mlx_whisper",
            "error": (proc.stderr or proc.stdout or "mlx_whisper failed").strip()[-4000:],
        }
    if not json_path.exists():
        return {"ok": False, "provider": "mlx_whisper", "error": f"Missing output JSON: {json_path}"}
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "provider": "mlx_whisper", "error": f"Invalid JSON: {exc}"}
    return normalize_local_whisper(data, provider="mlx_whisper", model=args.mlx_model, fallback_from=agent_result)


def run_openai_whisper(args: argparse.Namespace, local_dir: Path, agent_result: dict) -> dict:
    exe = shutil.which("whisper")
    if not exe:
        return {"ok": False, "provider": "openai_whisper", "error": "whisper not found on PATH"}

    cmd = [
        exe,
        str(args.video),
        "--model",
        args.openai_whisper_model,
        "--language",
        args.language,
        "--output_dir",
        str(local_dir),
        "--output_format",
        "json",
        "--verbose",
        "False",
    ]
    if args.seconds:
        cmd.extend(["--clip_timestamps", f"0,{args.seconds}"])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.local_timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "provider": "openai_whisper", "error": f"Timed out after {args.local_timeout}s"}

    candidates = sorted(local_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if proc.returncode != 0:
        return {
            "ok": False,
            "provider": "openai_whisper",
            "error": (proc.stderr or proc.stdout or "whisper failed").strip()[-4000:],
        }
    if not candidates:
        return {"ok": False, "provider": "openai_whisper", "error": f"Missing output JSON in {local_dir}"}
    try:
        data = json.loads(candidates[0].read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"ok": False, "provider": "openai_whisper", "error": f"Invalid JSON: {exc}"}
    return normalize_local_whisper(
        data,
        provider="openai_whisper",
        model=args.openai_whisper_model,
        fallback_from=agent_result,
    )


def run_local_asr(args: argparse.Namespace, agent_result: dict) -> dict:
    local_dir = args.out_dir / "transcript" / "local-whisper"
    local_dir.mkdir(parents=True, exist_ok=True)

    result = run_mlx_whisper(args, local_dir, agent_result)
    if result.get("ok"):
        return result
    if not args.allow_slow_whisper:
        return {
            "ok": False,
            "provider": "local_whisper",
            "error": "mlx_whisper failed; slow CPU Whisper fallback is disabled by default.",
            "mlx_whisper": result,
        }
    openai_result = run_openai_whisper(args, local_dir, agent_result)
    if openai_result.get("ok"):
        openai_result["previous_local_error"] = result
        return openai_result
    return {
        "ok": False,
        "provider": "local_whisper",
        "error": "Both mlx_whisper and openai_whisper failed.",
        "mlx_whisper": result,
        "openai_whisper": openai_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Transcribe with Doubao Agent Plan ASR, with local Whisper fallback")
    parser.add_argument("--video", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--asr-script", type=Path, default=DEFAULT_ASR_SCRIPT, help="Optional private Agent Plan ASR adapter")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV, help="Optional private ASR credential env file")
    parser.add_argument("--seconds", type=float, default=None)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--mlx-model", default=DEFAULT_MLX_MODEL)
    parser.add_argument("--openai-whisper-model", default=DEFAULT_OPENAI_WHISPER_MODEL)
    parser.add_argument("--local-timeout", type=int, default=420)
    parser.add_argument("--agent-plan-chunk-seconds", type=float, default=DEFAULT_AGENT_PLAN_CHUNK_SECONDS)
    parser.add_argument("--prefer-local", action="store_true")
    parser.add_argument("--no-local-fallback", action="store_true")
    parser.add_argument(
        "--allow-slow-whisper",
        action="store_true",
        help="Explicitly allow the much slower CPU OpenAI Whisper fallback.",
    )
    parser.add_argument("--preflight", action="store_true", help="Verify mlx_whisper in the current runtime and exit.")
    args = parser.parse_args()

    if args.preflight:
        result = run_mlx_preflight()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok") else 2
    if not args.video or not args.out_dir:
        parser.error("--video and --out-dir are required unless --preflight is used.")

    transcript_dir = args.out_dir / "transcript"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    if args.prefer_local:
        result = run_local_asr(
            args,
            {"ok": False, "provider": "agent_plan", "error": "Skipped by --prefer-local"},
        )
    else:
        result = run_agent_plan_chunked(args)
        if not result.get("ok") and not args.no_local_fallback:
            local_result = run_local_asr(args, result)
            if local_result.get("ok"):
                result = local_result
            else:
                result["local_fallback"] = local_result

    (transcript_dir / "asr.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_transcript(args.out_dir, result)
    print(
        json.dumps(
            {
                "ok": bool(result.get("ok")),
                "provider": result.get("provider"),
                "asr_json": str(transcript_dir / "asr.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
