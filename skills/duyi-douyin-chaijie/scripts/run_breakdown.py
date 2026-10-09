#!/usr/bin/env python3
"""End-to-end runner for Douyin video breakdown evidence packs."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse


DEFAULT_OUT_ROOT = Path.home() / "douyin-video-breakdowns"
PUBLIC_DOUYIN_HOSTS = ("douyin.com", "iesdouyin.com")


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_public_douyin_url(value: str) -> bool:
    """Accept only credential-free public pages on Douyin-owned hostnames."""
    try:
        parsed = urlparse(str(value or "").strip())
        hostname = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not hostname:
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    return any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in PUBLIC_DOUYIN_HOSTS)


def slugify(value: str) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", value or "douyin-video", flags=re.UNICODE)
    text = re.sub(r"-+", "-", text).strip("-")
    return (text or "douyin-video")[:48]


def normalize_source(value: str) -> str:
    """Normalize a source identifier without resolving the network URL."""
    value = str(value or "").strip()
    if not value:
        return ""
    if not is_url(value):
        try:
            return str(Path(value).expanduser().resolve())
        except OSError:
            return value
    parsed = urlparse(value)
    # Douyin share-link queries are tracking noise; the path is the stable part.
    query = "" if parsed.netloc.lower().endswith("douyin.com") else parsed.query
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") or "/",
            "",
            query,
            "",
        )
    )


def extract_douyin_video_id(value: str) -> str:
    match = re.search(r"(?:douyin\.com/video/|\b)(\d{15,22})(?:\b|/)", str(value or ""))
    return match.group(1) if match else ""


def metadata_source_values(metadata: dict) -> set[str]:
    detail = metadata.get("detailEvidence") if isinstance(metadata.get("detailEvidence"), dict) else {}
    values = {
        normalize_source(metadata.get("input", "")),
        normalize_source(metadata.get("url", "")),
        normalize_source(detail.get("currentUrl", "")),
    }
    return {value for value in values if value}


def evidence_score(run_dir: Path) -> int:
    """Rank matching runs by durable outputs, not by recency."""
    weighted_paths = {
        "完整拆解报告.md": 32,
        "report-web.json": 16,
        "breakdown.json": 8,
        "transcript/transcript.md": 4,
        "frames/frames.json": 2,
        "source/video.mp4": 1,
    }
    return sum(
        weight
        for relative, weight in weighted_paths.items()
        if (run_dir / relative).is_file() and (run_dir / relative).stat().st_size > 0
    )


def find_existing_run(out_root: Path, source: str, incoming_metadata: dict | None = None) -> Path | None:
    requested_values = {normalize_source(source)} if source else set()
    if incoming_metadata:
        requested_values.update(metadata_source_values(incoming_metadata))
    requested_values.discard("")
    requested_video_ids = {extract_douyin_video_id(value) for value in requested_values}
    requested_video_ids.discard("")
    if not requested_values and not requested_video_ids:
        return None

    matches: list[Path] = []
    for metadata_path in out_root.glob("*/source/metadata.json"):
        metadata = load_json(metadata_path, {})
        existing_values = metadata_source_values(metadata)
        detail = metadata.get("detailEvidence") if isinstance(metadata.get("detailEvidence"), dict) else {}
        existing_video_ids = {
            extract_douyin_video_id(value) for value in existing_values
        } | {str(detail.get("videoId") or "")}
        existing_video_ids.discard("")
        if requested_values & existing_values or requested_video_ids & existing_video_ids:
            matches.append(metadata_path.parents[1])

    if not matches:
        return None
    # Prefer the run with the richest existing evidence. For an exact tie, keep
    # the older run so retries do not drift toward a newer partial duplicate.
    return max(matches, key=lambda path: (evidence_score(path), -path.stat().st_mtime))


def existing_video(run_dir: Path) -> Path | None:
    candidates = [
        path
        for path in (run_dir / "source").glob("video.*")
        if path.is_file() and path.stat().st_size > 0
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def has_valid_transcript(run_dir: Path) -> bool:
    transcript = run_dir / "transcript" / "transcript.md"
    asr = load_json(run_dir / "transcript" / "asr.json", {})
    return transcript.is_file() and transcript.stat().st_size > 0 and bool(asr.get("ok"))


def has_valid_frames(run_dir: Path) -> bool:
    data = load_json(run_dir / "frames" / "frames.json", {})
    return bool(data.get("ok") and data.get("frames"))


def emit_stage(stage: str, status: str, **details) -> None:
    payload = {"stage": stage, "status": status, **details}
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def run(cmd: list[str], *, stage: str, allow_fail: bool = True) -> dict:
    emit_stage(stage, "running")
    started = time.monotonic()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    result = {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "duration_seconds": round(time.monotonic() - started, 2),
    }
    emit_stage(
        stage,
        "ok" if proc.returncode == 0 else "failed",
        returncode=proc.returncode,
        duration_seconds=result["duration_seconds"],
        error=(proc.stderr or proc.stdout or "").strip()[-800:] if proc.returncode else "",
    )
    if proc.returncode != 0 and not allow_fail:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"Command failed: {cmd}")
    return result


def record_step(run_dir: Path, manifest: dict, name: str, result: dict) -> None:
    manifest["steps"].append({"name": name, **result})
    write_json(run_dir / "manifest.json", manifest)


def parse_json_output(result: dict) -> dict:
    for stream_name in ("stdout", "stderr"):
        text = result.get(stream_name) or ""
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end >= start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {}


def load_json(path: Path, fallback=None):
    if fallback is None:
        fallback = {}
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_minimal_metadata(path: Path, source: str, title: str) -> dict:
    metadata = {
        "input": source,
        "url": source if is_url(source) else "",
        "title": title or Path(source).stem,
        "author": "",
        "publishedAt": "",
        "metrics": {"likes": 0, "comments": 0, "collects": 0, "shares": 0},
        "comments": [],
        "dataBoundary": ["Public Douyin metadata only; media download was not collected."],
    }
    write_json(path, metadata)
    return metadata


def unique_urls(items) -> list[str]:
    found: list[str] = []
    for item in items if isinstance(items, list) else []:
        value = str(item or "").strip()
        if is_url(value) and value not in found:
            found.append(value)
    return found


def select_media_tracks(metadata: dict) -> tuple[str, str]:
    media_urls = unique_urls(metadata.get("media_urls"))
    audio_urls = unique_urls(metadata.get("audio_urls"))
    video_urls = unique_urls(metadata.get("video_only_urls"))

    # 兼容旧采集结果：旧版把 media-audio 也放进了 video_only_urls，且 audio_urls 可能为空。
    audio_candidates = unique_urls(audio_urls + [url for url in media_urls if "media-audio" in url.lower()])
    video_candidates = unique_urls(
        [url for url in video_urls + media_urls if "media-audio" not in url.lower()]
    )
    return (
        video_candidates[0] if video_candidates else "",
        audio_candidates[0] if audio_candidates else "",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a public Douyin video breakdown")
    parser.add_argument("--source", help="Public Douyin URL")
    parser.add_argument("--metadata", type=Path, help="Existing metadata JSON")
    parser.add_argument("--title", default="")
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--run-dir", type=Path, help="Resume this exact existing run directory")
    parser.add_argument("--new-run", action="store_true", help="Intentionally start a separate run")
    parser.add_argument(
        "--allow-test-out-root",
        action="store_true",
        help="Test-only: allow a noncanonical --out-root such as a temporary directory.",
    )
    parser.add_argument("--refresh-collection", action="store_true", help="Refresh public metadata and screenshot")
    parser.add_argument("--max-frames", type=int, default=28)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--no-asr", action="store_true")
    parser.add_argument("--asr-seconds", type=float, default=None)
    # 默认走本机 Apple Silicon 上的 mlx-whisper：不依赖凭证、不花额度、可离线，
    # 挂 cron 时不会因为 Agent Plan 401 半夜静默失败。
    parser.add_argument("--prefer-local-asr", action="store_true", default=True,
                        help="（默认开启）用本地 mlx-whisper 转写")
    parser.add_argument("--use-doubao", dest="prefer_local_asr", action="store_false",
                        help="改用豆包 Agent Plan ASR")
    parser.add_argument("--asr-script", type=Path, default=None,
                        help="可选：私有 Agent Plan ASR 适配器脚本")
    parser.add_argument("--asr-env", type=Path, default=None,
                        help="可选：私有 ASR 凭证环境文件，不会写入证据目录")
    parser.add_argument("--no-local-asr-fallback", action="store_true")
    parser.add_argument("--allow-slow-whisper", action="store_true")
    parser.add_argument("--local-asr-timeout", type=int, default=None)
    parser.add_argument("--agent-plan-chunk-seconds", type=float, default=None)
    args = parser.parse_args()

    if not args.source and not args.metadata:
        raise SystemExit("Provide --source or --metadata.")
    if args.source and not is_public_douyin_url(args.source):
        raise SystemExit("Credential-free public Douyin URL required; local or non-Douyin inputs are not supported.")

    skill_dir = Path(__file__).resolve().parents[1]
    args.out_root = args.out_root.expanduser().resolve()
    if (
        not args.run_dir
        and args.out_root != DEFAULT_OUT_ROOT.resolve()
        and not args.allow_test_out_root
    ):
        raise SystemExit(
            "Refusing noncanonical --out-root. Resume the authoritative run with --run-dir, "
            "or use --allow-test-out-root only for an intentional isolated test."
        )
    args.out_root.mkdir(parents=True, exist_ok=True)
    incoming_metadata = load_json(args.metadata, {}) if args.metadata else {}
    if args.run_dir:
        run_dir = args.run_dir.expanduser().resolve()
        if not run_dir.is_dir():
            raise SystemExit(f"--run-dir does not exist or is not a directory: {run_dir}")
        reused_run = True
    elif not args.new_run:
        run_dir = find_existing_run(args.out_root, args.source or "", incoming_metadata)
        reused_run = run_dir is not None
    else:
        run_dir = None
        reused_run = False
    if run_dir is None:
        source_for_slug = args.title or (args.source or args.metadata.stem)
        run_dir = args.out_root / f"{datetime.now().strftime('%Y%m%d-%H%M')}-{slugify(source_for_slug)}"
    (run_dir / "source").mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "ok": False,
        "run_dir": str(run_dir),
        "reused_run": reused_run,
        "steps": [],
    }
    write_json(run_dir / "manifest.json", manifest)

    metadata_path = run_dir / "source" / "metadata.json"
    raw_extract_path = run_dir / "source" / "douyin-extract.md"
    source_screenshot_path = run_dir / "source" / "对标数据截图.png"
    source = args.source or ""

    if args.metadata:
        if args.metadata.expanduser().resolve() != metadata_path.resolve():
            shutil.copy2(args.metadata, metadata_path)
        metadata = load_json(metadata_path, {})
        source = source or metadata.get("url") or metadata.get("input") or ""
        if source and not is_public_douyin_url(source):
            raise SystemExit("Metadata must contain a credential-free public Douyin URL.")
    elif source and is_url(source):
        can_reuse_collection = (
            not args.refresh_collection
            and metadata_path.is_file()
            and metadata_path.stat().st_size > 0
            and source_screenshot_path.is_file()
            and source_screenshot_path.stat().st_size > 0
        )
        if can_reuse_collection:
            metadata = load_json(metadata_path, {})
            record_step(
                run_dir,
                manifest,
                "collect_douyin",
                {"skipped": True, "reason": "existing evidence"},
            )
        else:
            collect_cmd = [
                "node",
                str(skill_dir / "scripts" / "collect_douyin_video.mjs"),
                "--url",
                source,
                "--out",
                str(metadata_path),
                "--raw-out",
                str(raw_extract_path),
                "--screenshot-out",
                str(source_screenshot_path),
            ]
            step = run(collect_cmd, stage="collect_douyin")
            record_step(run_dir, manifest, "collect_douyin", step)
            metadata = load_json(metadata_path, {})
    else:
        metadata = write_minimal_metadata(metadata_path, source, args.title)

    if metadata.get("title") and not args.title:
        manifest["title"] = metadata.get("title")

    video_source, audio_source = select_media_tracks(metadata)
    prepare_source = video_source or source or metadata.get("url") or metadata.get("input") or ""
    if video_source and audio_source:
        manifest["download_source"] = "browser_split_media_urls"
    elif video_source:
        manifest["download_source"] = "browser_media_url"
    video_path = ""
    saved_video = existing_video(run_dir)
    if saved_video:
        video_path = str(saved_video)
        record_step(
            run_dir,
            manifest,
            "prepare_video",
            {"skipped": True, "reason": "existing evidence", "video_path": video_path},
        )
    elif prepare_source:
        prepare_cmd = [
            sys.executable,
            str(skill_dir / "scripts" / "prepare_video.py"),
            "--source",
            prepare_source,
            "--out-dir",
            str(run_dir),
        ]
        if args.no_download:
            prepare_cmd.append("--no-download")
        if audio_source:
            prepare_cmd.extend(["--audio-source", audio_source])
        step = run(prepare_cmd, stage="prepare_video")
        record_step(run_dir, manifest, "prepare_video", step)
        prepared = parse_json_output(step)
        if prepared.get("ok") and prepared.get("video_path"):
            video_path = prepared["video_path"]

    if video_path:
        if has_valid_transcript(run_dir):
            record_step(
                run_dir,
                manifest,
                "transcribe",
                {"skipped": True, "reason": "existing evidence"},
            )
        elif not args.no_asr:
            asr_cmd = [
                sys.executable,
                str(skill_dir / "scripts" / "transcribe_with_doubao.py"),
                "--video",
                video_path,
                "--out-dir",
                str(run_dir),
            ]
            if args.asr_seconds:
                asr_cmd.extend(["--seconds", str(args.asr_seconds)])
            if args.prefer_local_asr:
                asr_cmd.append("--prefer-local")
            if args.no_local_asr_fallback:
                asr_cmd.append("--no-local-fallback")
            if args.allow_slow_whisper:
                asr_cmd.append("--allow-slow-whisper")
            if args.local_asr_timeout:
                asr_cmd.extend(["--local-timeout", str(args.local_asr_timeout)])
            if args.agent_plan_chunk_seconds:
                asr_cmd.extend(["--agent-plan-chunk-seconds", str(args.agent_plan_chunk_seconds)])
            if args.asr_script:
                asr_cmd.extend(["--asr-script", str(args.asr_script.expanduser().resolve())])
            if args.asr_env:
                asr_cmd.extend(["--env", str(args.asr_env.expanduser().resolve())])
            step = run(asr_cmd, stage="transcribe")
            record_step(run_dir, manifest, "transcribe", step)
        else:
            record_step(
                run_dir,
                manifest,
                "transcribe",
                {"skipped": True, "reason": "disabled by --no-asr"},
            )
        if has_valid_frames(run_dir):
            record_step(
                run_dir,
                manifest,
                "extract_frames",
                {"skipped": True, "reason": "existing evidence"},
            )
        else:
            frame_cmd = [
                sys.executable,
                str(skill_dir / "scripts" / "extract_frames.py"),
                "--video",
                video_path,
                "--out-dir",
                str(run_dir),
                "--max-frames",
                str(args.max_frames),
            ]
            step = run(frame_cmd, stage="extract_frames")
            record_step(run_dir, manifest, "extract_frames", step)
    else:
        (run_dir / "transcript").mkdir(exist_ok=True)
        (run_dir / "frames").mkdir(exist_ok=True)
        if not (run_dir / "transcript" / "asr.json").exists():
            write_json(run_dir / "transcript" / "asr.json", {"ok": False, "error": "No downloaded video available."})
        if not (run_dir / "transcript" / "transcript.md").exists():
            (run_dir / "transcript" / "transcript.md").write_text(
                "# ASR 转写\n\n素材不足：没有可用的已下载视频。\n", encoding="utf-8"
            )
        if not (run_dir / "frames" / "frames.json").exists():
            write_json(run_dir / "frames" / "frames.json", {"ok": False, "frames": [], "error": "No downloaded video available."})

    report_cmd = [
        sys.executable,
        str(skill_dir / "scripts" / "build_report.py"),
        "--out-dir",
        str(run_dir),
    ]
    step = run(report_cmd, stage="build_report", allow_fail=False)
    record_step(run_dir, manifest, "build_report", step)
    report_info = parse_json_output(step)
    manifest.update(report_info)
    failed_stages: list[str] = []
    if source and is_url(source):
        if not metadata_path.is_file() or not source_screenshot_path.is_file():
            failed_stages.append("collect_douyin")
    if not video_path:
        failed_stages.append("prepare_video")
    else:
        if not has_valid_transcript(run_dir):
            failed_stages.append("transcribe")
        if not has_valid_frames(run_dir):
            failed_stages.append("extract_frames")

    manifest["draft_ok"] = bool(report_info.get("ok"))
    manifest["failed_stages"] = list(dict.fromkeys(failed_stages))
    manifest["evidence_complete"] = not manifest["failed_stages"]
    manifest["ok"] = bool(manifest["draft_ok"] and manifest["evidence_complete"])
    if manifest["failed_stages"]:
        resume_command = [
            sys.executable,
            str(skill_dir / "scripts" / "run_breakdown.py"),
            "--run-dir",
            str(run_dir),
        ]
        if source:
            resume_command.extend(["--source", source])
        manifest["next_step"] = {
            "required": "修复失败阶段后，在同一证据目录续跑",
            "failed_stages": manifest["failed_stages"],
            "resume_command": resume_command,
            "note": "不要改 --out-root，不要使用 --new-run，也不要在 /tmp 手工重建证据。",
        }
    else:
        manifest["next_step"] = {
            "required": "AI 深读证据并产出最终拆解报告",
            "finalize_command": [
                sys.executable,
                str(skill_dir / "scripts" / "finalize_breakdown.py"),
                "--run-dir",
                str(run_dir),
                "--final-report",
                "/path/to/完整拆解报告.md",
            ],
            "note": "自动报告只是初稿；请先由 AI 读取证据并写出最终报告，再运行 finalize_breakdown.py 生成 HTML。",
        }
    write_json(run_dir / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if manifest["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
