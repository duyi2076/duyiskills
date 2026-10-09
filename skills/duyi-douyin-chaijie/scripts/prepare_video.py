#!/usr/bin/env python3
"""Prepare a local or public video source for Douyin breakdown runs."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

try:
    import pwd
except ImportError:  # Windows has no pwd module.
    pwd = None


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_direct_media_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return False
    text = value.lower()
    return any(token in text for token in ["mime_type=video_mp4", "media-video", ".mp4", ".m3u8"])


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def operator_home() -> Path:
    """Return the macOS account home even when an isolated profile overrides HOME."""
    if pwd is not None:
        try:
            return Path(pwd.getpwuid(os.getuid()).pw_dir)
        except (KeyError, OSError):
            pass
    return Path.home()


def cookie_browser_name(browser: str) -> str:
    """Return only the browser label, never its local profile path."""
    value = str(browser or "").strip()
    return value.split(":", 1)[0] if ":" in value else value


def sanitize_cookie_error(text: str, cookie_spec: str) -> str:
    """Remove the resolved browser profile path from tool diagnostics."""
    cleaned = str(text or "")
    if cookie_spec and ":" in cookie_spec:
        cleaned = cleaned.replace(cookie_spec, f"{cookie_browser_name(cookie_spec)}:<browser-profile>")
        cleaned = cleaned.replace(cookie_spec.split(":", 1)[1], "<browser-profile>")
    return re.sub(
        r"(--cookies-from-browser\s+)([^\s]+)",
        rf"\1{re.escape(cookie_browser_name(cookie_spec)) or 'browser'}",
        cleaned,
        flags=re.IGNORECASE,
    )


def resolve_browser_cookie_spec(browser: str, home: Path | None = None) -> str:
    """Give yt-dlp an absolute browser root so Profile HOME cannot redirect it."""
    value = str(browser or "").strip()
    if not value or ":" in value:
        return value

    browser_roots = {
        "chrome": "Google/Chrome",
        "chromium": "Chromium",
        "brave": "BraveSoftware/Brave-Browser",
        "edge": "Microsoft Edge",
        "vivaldi": "Vivaldi",
    }
    relative = browser_roots.get(value.lower())
    if not relative:
        return value

    root = (home or operator_home()) / "Library" / "Application Support" / relative
    return f"{value}:{root}" if root.exists() else value


def media_stream_types(path: Path) -> set[str]:
    if not shutil.which("ffprobe"):
        return set()
    proc = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(path),
        ]
    )
    if proc.returncode != 0:
        return set()
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return set()
    return {
        str(item.get("codec_type") or "")
        for item in data.get("streams", [])
        if isinstance(item, dict) and item.get("codec_type")
    }


def download_direct_track(source: str, out: Path) -> dict:
    if not shutil.which("curl"):
        return {"ok": False, "error": "curl is not installed."}
    cmd = [
        "curl",
        "-L",
        "--fail",
        "--connect-timeout",
        "15",
        "-A",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "-e",
        "https://www.douyin.com/",
        source,
        "-o",
        str(out),
    ]
    proc = run(cmd)
    if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
        return {"ok": True, "path": str(out), "bytes": out.stat().st_size}
    return {
        "ok": False,
        "error": (proc.stderr or proc.stdout or "curl direct media download failed").strip()[-4000:],
    }


def find_downloaded_video(source_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in source_dir.glob("video.*")
            if path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
        ],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def prepare_url(
    source: str,
    source_dir: Path,
    no_download: bool,
    cookies_browser: str = "chrome",
    audio_source: str = "",
) -> dict:
    if no_download:
        return {"ok": False, "mode": "url", "url": source, "error": "Download disabled by --no-download."}
    if is_direct_media_url(source):
        if audio_source:
            return download_split_media(source, audio_source, source_dir)
        return download_direct_media(source, source_dir)
    if not shutil.which("yt-dlp"):
        return {"ok": False, "mode": "url", "url": source, "error": "yt-dlp is not installed."}

    output_template = str(source_dir / "video.%(ext)s")
    base_cmd = [
        "yt-dlp",
        "--no-playlist",
        "--restrict-filenames",
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
        source,
    ]

    # 抖音页面可能需要浏览器生成的设备指纹 Cookie。优先尝试用户指定的浏览器登录态，
    # 失败后再尝试匿名下载；匿名路径也适用于不需要 Cookie 的公开站点。
    attempts: list[tuple[str, list[str]]] = []
    cookie_spec = resolve_browser_cookie_spec(cookies_browser)
    if cookies_browser:
        attempts.append(
            ("cookies", base_cmd[:1] + ["--cookies-from-browser", cookie_spec] + base_cmd[1:])
        )
    attempts.append(("anonymous", base_cmd))

    last_error = "yt-dlp failed"
    attempt_results: list[dict] = []
    for mode, cmd in attempts:
        proc = run(cmd)
        videos = find_downloaded_video(source_dir)
        error = sanitize_cookie_error(
            (proc.stderr or proc.stdout or "yt-dlp failed").strip(), cookie_spec
        )[-4000:]
        attempt_results.append(
            {
                "mode": mode,
                "returncode": proc.returncode,
                "error": "" if proc.returncode == 0 and videos else error,
            }
        )
        if proc.returncode == 0 and videos:
            return {
                "ok": True,
                "mode": "url",
                "url": source,
                "video_path": str(videos[0]),
                "auth": mode,
                "cookies_browser": cookie_browser_name(cookies_browser) if mode == "cookies" else "",
                "attempts": attempt_results,
                "command": f"yt-dlp public video download ({mode})",
            }
        last_error = error

    return {
        "ok": False,
        "mode": "url",
        "url": source,
        "error": last_error,
        "tried": [mode for mode, _ in attempts],
        "cookies_browser": cookie_browser_name(cookies_browser),
        "attempts": attempt_results,
        "command": "yt-dlp --no-playlist --merge-output-format mp4",
    }


def download_direct_media(source: str, source_dir: Path) -> dict:
    out = source_dir / "video.mp4"
    result = download_direct_track(source, out)
    if result.get("ok"):
        return {
            "ok": True,
            "mode": "direct_media",
            "url": source,
            "video_path": str(out),
            "bytes": out.stat().st_size,
            "stream_types": sorted(media_stream_types(out)),
            "command": "curl direct media url",
        }
    return {
        "ok": False,
        "mode": "direct_media",
        "url": source,
        "error": result.get("error") or "curl direct media download failed",
        "command": "curl direct media url",
    }


def download_split_media(video_source: str, audio_source: str, source_dir: Path) -> dict:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        return {
            "ok": False,
            "mode": "direct_split_media",
            "error": "ffmpeg and ffprobe are required for split Douyin media.",
        }

    video_track = source_dir / "video-track.mp4"
    audio_track = source_dir / "audio-track.mp4"
    merged = source_dir / "video.mp4"
    video_result = download_direct_track(video_source, video_track)
    if not video_result.get("ok"):
        return {"ok": False, "mode": "direct_split_media", "error": video_result.get("error")}
    audio_result = download_direct_track(audio_source, audio_track)
    if not audio_result.get("ok"):
        return {"ok": False, "mode": "direct_split_media", "error": audio_result.get("error")}

    video_types = media_stream_types(video_track)
    audio_types = media_stream_types(audio_track)
    if "video" not in video_types or "audio" not in audio_types:
        return {
            "ok": False,
            "mode": "direct_split_media",
            "error": "Downloaded tracks did not contain the expected video/audio streams.",
            "video_stream_types": sorted(video_types),
            "audio_stream_types": sorted(audio_types),
        }

    proc = run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_track),
            "-i",
            str(audio_track),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c",
            "copy",
            "-shortest",
            str(merged),
        ]
    )
    merged_types = media_stream_types(merged) if proc.returncode == 0 else set()
    if proc.returncode != 0 or not {"video", "audio"}.issubset(merged_types):
        return {
            "ok": False,
            "mode": "direct_split_media",
            "error": (proc.stderr or proc.stdout or "ffmpeg merge failed").strip()[-4000:],
            "stream_types": sorted(merged_types),
        }
    return {
        "ok": True,
        "mode": "direct_split_media",
        "video_path": str(merged),
        "video_track_path": str(video_track),
        "audio_track_path": str(audio_track),
        "bytes": merged.stat().st_size,
        "stream_types": sorted(merged_types),
        "command": "curl split tracks + ffmpeg stream copy",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a public Douyin video source")
    parser.add_argument("--source", required=True, help="Public Douyin URL or direct media URL")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--audio-source", default="", help="Optional direct audio-track URL for DASH media")
    parser.add_argument(
        "--cookies-from-browser",
        default="chrome",
        help="下载被风控挡住时借用哪个浏览器的登录态，留空则不重试",
    )
    args = parser.parse_args()

    if not is_url(args.source):
        raise SystemExit("Public Douyin URL required; local video inputs are not supported.")

    source_dir = args.out_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    result = prepare_url(
        args.source,
        source_dir,
        args.no_download,
        args.cookies_from_browser,
        args.audio_source,
    )
    (source_dir / "download.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
