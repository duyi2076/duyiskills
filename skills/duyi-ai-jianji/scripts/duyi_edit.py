#!/usr/bin/env python3
# Copyright (c) 2026 杜一 (@duyi2076)
# Original source: https://github.com/duyi2076/duyi-scripted-video-edit
# Licensed under PolyForm Noncommercial 1.0.0; see LICENSE and NOTICE.md.
"""Deterministic AIJianji orchestrator with a locked reference composition."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from common import (
    RunLock,
    append_jsonl,
    atomic_output_path,
    canonical_json_sha256,
    file_fingerprint,
    load_json,
    media_summary,
    run,
    sha256_file,
    write_json,
)
from contracts import (
    EXIT_BLOCKED,
    EXIT_ENVIRONMENT,
    EXIT_LOCKED,
    EXIT_QA_FAILED,
    EXIT_SCHEMA,
    EXIT_STAGE_FAILED,
    EXIT_SUCCESS,
    FIXED_LEFT_CONTENT_BOUNDS,
    PIPELINE_VERSION,
    RUN_STATE_SCHEMA_VERSION,
    STAGE_ORDER,
    composition_contract,
    delivery_dimensions,
    validate_audit_gate,
    validate_run_state,
)
from agent_acceptance import build_brief as build_agent_review_brief
from agent_acceptance import validate_acceptance
from stage_layout import LAYOUT_MODEL_ID, automatic_reflow_strategy


SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSETS = SKILL_ROOT / "assets" / "composition"
VAD_ASSETS = SKILL_ROOT / "assets" / "vad"
SCRIPTS = SKILL_ROOT / "scripts"
STATE_NAME = "run-state.json"
HYPERFRAMES_VERSION = "0.7.69"


def semantic_stage_build_inputs_sha256(style: dict[str, Any]) -> str:
    builder_root = ASSETS / "semantic-stage"
    return canonical_json_sha256(
        {
            "builder": sha256_file(builder_root / "build.py"),
            "gsap": sha256_file(builder_root / "vendor" / "gsap.min.js"),
            "fonts": {
                name: sha256_file(ASSETS / "fonts" / name)
                for name in (
                    "NotoSansCJKsc-Bold.otf",
                    "NotoSansCJKsc-Regular.otf",
                    "NotoSansCJKsc-Medium.otf",
                    "SpaceMono-Bold.ttf",
                )
            },
            "style": style,
            "visual_grammar": load_json(ASSETS / "visual-grammar.json"),
            "stage_layout": sha256_file(SCRIPTS / "stage_layout.py"),
            "hyperframes_version": HYPERFRAMES_VERSION,
            "pipeline_version": PIPELINE_VERSION,
        }
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stage_template() -> dict[str, Any]:
    return {
        "status": "pending",
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "input_fingerprint": None,
        "outputs": [],
        "log": None,
        "message": None,
    }


def state_path(run_dir: Path) -> Path:
    return run_dir / STATE_NAME


def load_state(run_dir: Path) -> dict[str, Any]:
    state = load_json(state_path(run_dir))
    if not isinstance(state, dict):
        raise ValueError("run state must be a JSON object")
    stages = state.get("stages")
    if not isinstance(stages, dict):
        raise ValueError("run state stages must be a JSON object")
    missing_stages = [name for name in STAGE_ORDER if name not in stages]
    for name in missing_stages:
        stages.setdefault(name, stage_template())
    state = validate_run_state(state)
    if state.get("pipeline_version") != PIPELINE_VERSION or missing_stages:
        state["migration_required"] = {
            "from_pipeline_version": state.get("pipeline_version"),
            "to_pipeline_version": PIPELINE_VERSION,
            "missing_stages": missing_stages,
        }
        if state.get("status") == "READY":
            state["status"] = "BLOCKED"
    return state


def save_state(run_dir: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    validate_run_state(state)
    write_json(state_path(run_dir), state)


def event(run_dir: Path, stage: str, status: str, **details: Any) -> None:
    append_jsonl(
        run_dir / "logs" / "events.jsonl",
        {"at": utc_now(), "stage": stage, "status": status, **details},
    )


def set_stage(
    run_dir: Path,
    state: dict[str, Any],
    stage: str,
    status: str,
    *,
    exit_code: int | None = None,
    message: str | None = None,
    input_fingerprint: str | None = None,
    outputs: Iterable[Path] = (),
    log: Path | None = None,
) -> None:
    record = state["stages"][stage]
    if status == "running":
        record["started_at"] = utc_now()
        record["finished_at"] = None
    elif status in {"succeeded", "failed", "blocked", "skipped"}:
        record["finished_at"] = utc_now()
    record["status"] = status
    record["exit_code"] = exit_code
    record["message"] = message
    if input_fingerprint is not None:
        record["input_fingerprint"] = input_fingerprint
    record["outputs"] = [
        file_fingerprint(path) for path in outputs if path.is_file()
    ]
    record["log"] = str(log.resolve()) if log else record.get("log")
    event(run_dir, stage, status, exit_code=exit_code, message=message)
    save_state(run_dir, state)


def outputs_valid(record: dict[str, Any], input_fingerprint: str) -> bool:
    if record.get("status") != "succeeded":
        return False
    if record.get("input_fingerprint") != input_fingerprint:
        return False
    outputs = record.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        return False
    for output in outputs:
        try:
            path = Path(str(output["path"]))
            if not path.is_file() or sha256_file(path) != output["sha256"]:
                return False
        except (KeyError, OSError, TypeError):
            return False
    return True


def run_stage_command(
    run_dir: Path,
    state: dict[str, Any],
    stage: str,
    command: list[str],
    *,
    input_payload: Any,
    outputs: list[Path],
    timeout: float,
    accepted_codes: set[int] | None = None,
) -> int:
    fingerprint = canonical_json_sha256(input_payload)
    if outputs_valid(state["stages"][stage], fingerprint):
        return EXIT_SUCCESS
    log = run_dir / "logs" / f"{stage}.log"
    set_stage(
        run_dir,
        state,
        stage,
        "running",
        input_fingerprint=fingerprint,
        log=log,
    )
    try:
        completed = run(
            command,
            capture=True,
            timeout=timeout,
            cwd=SKILL_ROOT,
            log_path=log,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        set_stage(
            run_dir,
            state,
            stage,
            "failed",
            exit_code=EXIT_STAGE_FAILED,
            message=str(exc),
            input_fingerprint=fingerprint,
            log=log,
        )
        return EXIT_STAGE_FAILED
    allowed = accepted_codes or {0}
    if completed.returncode not in allowed:
        status = "blocked" if completed.returncode == EXIT_BLOCKED else "failed"
        set_stage(
            run_dir,
            state,
            stage,
            status,
            exit_code=completed.returncode,
            message=f"command exited {completed.returncode}",
            input_fingerprint=fingerprint,
            outputs=outputs,
            log=log,
        )
        return completed.returncode
    set_stage(
        run_dir,
        state,
        stage,
        "succeeded",
        exit_code=0,
        input_fingerprint=fingerprint,
        outputs=outputs,
        log=log,
    )
    return EXIT_SUCCESS


def command_version(command: list[str]) -> str | None:
    try:
        completed = run(command, capture=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    text = (completed.stdout or completed.stderr or "").strip()
    return text.splitlines()[0] if text else ""


def doctor_report() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: Any, *, warning: bool = False) -> None:
        checks.append({"name": name, "ok": bool(ok), "warning": warning, "detail": detail})

    python_ok = sys.version_info >= (3, 10)
    add("python", python_ok, sys.version.split()[0])
    add(
        "pillow",
        importlib.util.find_spec("PIL") is not None,
        "Pillow is required for font measurement and evidence sheets",
    )
    for tool in ("ffmpeg", "ffprobe", "node", "npx", "fc-scan"):
        path = shutil.which(tool)
        add(tool, bool(path), path, warning=tool == "fc-scan")

    node_version = command_version(["node", "--version"]) if shutil.which("node") else None
    node_major = 0
    if node_version:
        try:
            node_major = int(node_version.lstrip("v").split(".", 1)[0])
        except ValueError:
            node_major = 0
    add("node_version", node_major >= 22, node_version or "unavailable")

    ffmpeg_filters = ""
    ffmpeg_encoders = ""
    if shutil.which("ffmpeg"):
        try:
            ffmpeg_filters = run(
                ["ffmpeg", "-hide_banner", "-filters"],
                capture=True,
                timeout=30,
                check=False,
            ).stdout or ""
            ffmpeg_encoders = run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture=True,
                timeout=30,
                check=False,
            ).stdout or ""
        except (OSError, subprocess.TimeoutExpired):
            pass
    for feature, payload in (
        ("filter_subtitles", ffmpeg_filters),
        ("filter_loudnorm", ffmpeg_filters),
        ("encoder_libx264", ffmpeg_encoders),
        ("encoder_aac", ffmpeg_encoders),
    ):
        token = feature.split("_", 1)[1]
        add(feature, token in payload, token)

    codec_smoke_error: str | None = None
    if shutil.which("ffmpeg") and all(
        token in payload
        for token, payload in (
            ("libx264", ffmpeg_encoders),
            ("aac", ffmpeg_encoders),
        )
    ):
        try:
            with tempfile.TemporaryDirectory(prefix="duyi-doctor-") as folder:
                sample = Path(folder) / "codec-smoke.mp4"
                encoded = run(
                    [
                        "ffmpeg",
                        "-y",
                        "-v",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        "color=c=black:s=64x64:r=10:d=0.2",
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=r=44100:cl=stereo:d=0.2",
                        "-shortest",
                        "-c:v",
                        "libx264",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        str(sample),
                    ],
                    capture=True,
                    timeout=30,
                    check=False,
                )
                if encoded.returncode != 0:
                    codec_smoke_error = (encoded.stderr or "encode failed").strip()
                else:
                    decoded = run(
                        [
                            "ffmpeg",
                            "-v",
                            "error",
                            "-xerror",
                            "-i",
                            str(sample),
                            "-map",
                            "0:v:0",
                            "-map",
                            "0:a:0",
                            "-f",
                            "null",
                            "-",
                        ],
                        capture=True,
                        timeout=30,
                        check=False,
                    )
                    if decoded.returncode != 0:
                        codec_smoke_error = (decoded.stderr or "decode failed").strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            codec_smoke_error = str(exc)
    else:
        codec_smoke_error = "required encoders unavailable"
    add("codec_smoke", codec_smoke_error is None, codec_smoke_error or "encode and decode passed")

    font_manifest = ASSETS / "font-assets.json"
    font_errors: list[str] = []
    if font_manifest.is_file():
        for item in load_json(font_manifest).get("fonts", []):
            path = SKILL_ROOT / str(item.get("path", ""))
            if not path.is_file():
                font_errors.append(f"missing:{item.get('path')}")
                continue
            if sha256_file(path) != item.get("sha256"):
                font_errors.append(f"sha256:{item.get('path')}")
                continue
            if shutil.which("fc-scan") and path.suffix.lower() in {".otf", ".ttf"}:
                completed = run(
                    ["fc-scan", "--format", "%{family[0]}|%{fullname[0]}", str(path)],
                    capture=True,
                    timeout=20,
                    check=False,
                )
                actual = (completed.stdout or "").strip()
                expected = f"{item.get('family')}|{item.get('face')}"
                if completed.returncode != 0 or actual != expected:
                    font_errors.append(f"name:{item.get('path')}:{actual!r}!={expected!r}")
    else:
        font_errors.append("font manifest missing")
    add("font_assets", not font_errors, font_errors or "hashes and exact faces match")

    vad_errors: list[str] = []
    vad_manifest = VAD_ASSETS / "model.json"
    if importlib.util.find_spec("onnxruntime") is None:
        vad_errors.append("onnxruntime missing")
    if importlib.util.find_spec("numpy") is None:
        vad_errors.append("numpy missing")
    if not vad_manifest.is_file():
        vad_errors.append("VAD model manifest missing")
    else:
        vad_spec = load_json(vad_manifest)
        vad_model = SKILL_ROOT / str(vad_spec.get("path") or "")
        if not vad_model.is_file():
            vad_errors.append(f"missing:{vad_spec.get('path')}")
        elif sha256_file(vad_model) != vad_spec.get("sha256"):
            vad_errors.append(f"sha256:{vad_spec.get('path')}")
        vad_license = SKILL_ROOT / str(vad_spec.get("license_file") or "")
        if not vad_license.is_file():
            vad_errors.append(f"license:{vad_spec.get('license_file')}")
    add(
        "acoustic_vad",
        not vad_errors,
        vad_errors or "offline Silero ONNX model and runtime verified",
    )

    semantic_builder = ASSETS / "semantic-stage" / "build.py"
    pinned = semantic_builder.is_file() and f'HYPERFRAMES_VERSION = "{HYPERFRAMES_VERSION}"' in semantic_builder.read_text(
        encoding="utf-8"
    )
    add(
        "hyperframes_pin",
        pinned and bool(shutil.which("npx")),
        {"version": HYPERFRAMES_VERSION, "runtime_check": "performed by each builder check"},
    )

    disk = shutil.disk_usage(SKILL_ROOT)
    add("disk_free", disk.free >= 2 * 1024**3, {"free_bytes": disk.free, "minimum_bytes": 2 * 1024**3})
    hard_failures = [item for item in checks if not item["ok"] and not item["warning"]]
    return {
        "schema_version": 1,
        "pipeline_version": PIPELINE_VERSION,
        "ok": not hard_failures,
        "checks": checks,
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    payload = doctor_report()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for item in payload["checks"]:
            label = "PASS" if item["ok"] else "WARN" if item["warning"] else "FAIL"
            print(f"{label:4} {item['name']}: {item['detail']}")
    return EXIT_SUCCESS if payload["ok"] else EXIT_ENVIRONMENT


def cmd_init(args: argparse.Namespace) -> int:
    source = Path(args.input).resolve()
    asr = Path(args.asr).resolve()
    run_dir = Path(args.run_dir).resolve()
    if not source.is_file() or not asr.is_file():
        print("input video and ASR JSON must both exist", file=sys.stderr)
        return EXIT_ENVIRONMENT
    run_dir.mkdir(parents=True, exist_ok=True)
    if state_path(run_dir).exists():
        print(f"run already initialized: {run_dir}", file=sys.stderr)
        return EXIT_SCHEMA
    for relative in (
        "inputs",
        "artifacts",
        "review",
        "work/cut",
        "work/captions",
        "work/animations",
        "deliverable",
        "qa",
        "logs",
    ):
        (run_dir / relative).mkdir(parents=True, exist_ok=True)

    try:
        with RunLock(run_dir / "run.lock"):
            doctor = doctor_report()
            state: dict[str, Any] = {
                "schema_version": RUN_STATE_SCHEMA_VERSION,
                "pipeline_version": PIPELINE_VERSION,
                "status": "RUNNING",
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "run_dir": str(run_dir),
                "jobs": 2,
                "composition": composition_contract(args.speaker_lane),
                "inputs": {
                    "source": file_fingerprint(source),
                    "asr": file_fingerprint(asr),
                },
                "stages": {name: stage_template() for name in STAGE_ORDER},
            }
            write_json(
                run_dir / "inputs" / "manifest.json",
                {
                    "schema_version": 1,
                    "pipeline_version": PIPELINE_VERSION,
                    "source": state["inputs"]["source"],
                    "asr": state["inputs"]["asr"],
                    "composition": state["composition"],
                },
            )
            save_state(run_dir, state)
            set_stage(
                run_dir,
                state,
                "doctor",
                "succeeded" if doctor["ok"] else "failed",
                exit_code=0 if doctor["ok"] else EXIT_ENVIRONMENT,
                message=None if doctor["ok"] else "environment doctor failed",
                input_fingerprint=canonical_json_sha256(doctor),
                outputs=[],
            )
            write_json(run_dir / "artifacts" / "doctor.json", doctor)
            if not doctor["ok"]:
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return EXIT_ENVIRONMENT

            preflight = run_dir / "artifacts" / "preflight.json"
            code = run_stage_command(
                run_dir,
                state,
                "preflight",
                [
                    sys.executable,
                    str(SCRIPTS / "preflight.py"),
                    "--input",
                    str(source),
                    "--output",
                    str(preflight),
                    "--decode",
                    args.decode,
                ],
                input_payload={"source": state["inputs"]["source"], "decode": args.decode},
                outputs=[preflight],
                timeout=args.timeout,
            )
            if code:
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return code

            normalized = run_dir / "artifacts" / "normalized-transcript.json"
            code = run_stage_command(
                run_dir,
                state,
                "normalize",
                [
                    sys.executable,
                    str(SCRIPTS / "normalize_doubao_asr.py"),
                    "--input",
                    str(asr),
                    "--output",
                    str(normalized),
                ],
                input_payload=state["inputs"]["asr"],
                outputs=[normalized],
                timeout=120,
            )
            if code:
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return code
            asr_integrity = run_dir / "artifacts" / "asr-integrity.json"
            code = run_stage_command(
                run_dir,
                state,
                "asr_integrity",
                [
                    sys.executable,
                    str(SCRIPTS / "audit_asr_integrity.py"),
                    "--source",
                    str(source),
                    "--asr",
                    str(asr),
                    "--transcript",
                    str(normalized),
                    "--preflight",
                    str(preflight),
                    "--output",
                    str(asr_integrity),
                ],
                input_payload={
                    "source": state["inputs"]["source"],
                    "asr": state["inputs"]["asr"],
                    "normalized_transcript": file_fingerprint(normalized),
                    "preflight": file_fingerprint(preflight),
                    "pipeline_version": PIPELINE_VERSION,
                },
                outputs=[asr_integrity],
                timeout=120,
            )
            if code:
                state["status"] = "BLOCKED" if code == EXIT_BLOCKED else "FAILED"
                save_state(run_dir, state)
                return EXIT_BLOCKED if code == EXIT_BLOCKED else code
            set_stage(
                run_dir,
                state,
                "editorial_review",
                "blocked",
                exit_code=EXIT_BLOCKED,
                message=(
                    "AI must finish deletion, ASR correction, complete-sentence "
                    "and final subtitle-break decisions in "
                    "review/editorial-review-plan.json, then run prepare-review"
                ),
                input_fingerprint=sha256_file(normalized),
            )
            state["status"] = "BLOCKED"
            save_state(run_dir, state)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOCKED
    print(f"initialized and waiting for complete AI editorial review: {run_dir}")
    return EXIT_BLOCKED


def ensure_inputs_unchanged(state: dict[str, Any]) -> None:
    for key in ("source", "asr"):
        recorded = state["inputs"][key]
        path = Path(recorded["path"])
        if not path.is_file() or sha256_file(path) != recorded["sha256"]:
            raise ValueError(f"{key} changed after init; create a new run")


def require_locked_text_master(run_dir: Path) -> tuple[Path, str]:
    master = run_dir / "review" / "locked-editorial-master.json"
    if not master.is_file():
        raise PermissionError(
            "single human-confirmed editorial master is required before resume"
        )
    payload = load_json(master)
    if (
        payload.get("status") != "locked"
        or payload.get("policy") != "single-human-confirmed-editorial-master"
        or (payload.get("confirmation") or {}).get("user_confirmed") is not True
        or (payload.get("confirmation") or {}).get("review_count") != 1
    ):
        raise PermissionError("editorial master is not a valid single human lock")
    master_sha256 = sha256_file(master)
    bound_files = (
        run_dir / "review" / "asr-corrections.json",
        run_dir / "artifacts" / "corrected-transcript.json",
        run_dir / "review" / "cut-plan.json",
        run_dir / "review" / "caption-units.json",
        run_dir / "review" / "semantic-map.json",
    )
    for path in bound_files:
        if not path.is_file():
            raise PermissionError(f"locked editorial derivative is missing: {path.name}")
        if load_json(path).get("locked_text_master_sha256") != master_sha256:
            raise PermissionError(
                f"{path.name} is not bound to the current locked editorial master"
            )
    return master, master_sha256


def build_editorial_packet(
    run_dir: Path,
    state: dict[str, Any],
    *,
    timeout: float,
) -> int:
    source = Path(state["inputs"]["source"]["path"])
    normalized = run_dir / "artifacts" / "normalized-transcript.json"
    integrity = run_dir / "artifacts" / "asr-integrity.json"
    plan = run_dir / "review" / "editorial-review-plan.json"
    packet_json = run_dir / "review" / "editorial-review.json"
    packet_markdown = run_dir / "review" / "editorial-review.md"
    if not plan.is_file():
        set_stage(
            run_dir,
            state,
            "editorial_review",
            "blocked",
            exit_code=EXIT_BLOCKED,
            message=(
                "write review/editorial-review-plan.json only after AI has "
                "completed deletion, correction, sentence and subtitle decisions"
            ),
        )
        return EXIT_BLOCKED
    source_media = media_summary(source)
    width, height = delivery_dimensions(
        int(source_media["video"]["width"]),
        int(source_media["video"]["height"]),
    )
    return run_stage_command(
        run_dir,
        state,
        "editorial_review",
        [
            sys.executable,
            str(SCRIPTS / "build_editorial_review.py"),
            "--transcript",
            str(normalized),
            "--plan",
            str(plan),
            "--source",
            str(source),
            "--integrity",
            str(integrity),
            "--markdown-output",
            str(packet_markdown),
            "--json-output",
            str(packet_json),
            "--width",
            str(width),
            "--height",
            str(height),
        ],
        input_payload={
            "implementation": file_fingerprint(
                SCRIPTS / "build_editorial_review.py"
            ),
            "normalized_transcript": file_fingerprint(normalized),
            "editorial_plan": file_fingerprint(plan),
            "source": file_fingerprint(source),
            "asr_integrity": file_fingerprint(integrity),
            "delivery": {"width": width, "height": height},
            "pipeline_version": PIPELINE_VERSION,
        },
        outputs=[packet_json, packet_markdown],
        timeout=timeout,
    )


def cmd_prepare_review(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    try:
        with RunLock(run_dir / "run.lock"):
            state = load_state(run_dir)
            ensure_inputs_unchanged(state)
            code = build_editorial_packet(run_dir, state, timeout=args.timeout)
            if code:
                state["status"] = "BLOCKED" if code == EXIT_BLOCKED else "FAILED"
                save_state(run_dir, state)
                return code
            packet = run_dir / "review" / "editorial-review.json"
            packet_markdown = run_dir / "review" / "editorial-review.md"
            set_stage(
                run_dir,
                state,
                "human_lock",
                "blocked",
                exit_code=EXIT_BLOCKED,
                message=(
                    "show review/editorial-review.md to the user for the only "
                    "human review; after their response, apply requested edits "
                    "to the plan and run lock-review"
                ),
                input_fingerprint=sha256_file(packet),
                outputs=[packet, packet_markdown],
            )
            state["status"] = "BLOCKED"
            save_state(run_dir, state)
        print(f"single human-review packet ready: {packet_markdown}")
        return EXIT_BLOCKED
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOCKED
    except (OSError, ValueError, KeyError, PermissionError) as exc:
        print(f"prepare-review failed: {exc}", file=sys.stderr)
        return EXIT_SCHEMA


def cmd_lock_review(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    try:
        with RunLock(run_dir / "run.lock"):
            state = load_state(run_dir)
            ensure_inputs_unchanged(state)
            # Rebuild once from the current plan so the user's requested changes
            # are validated and locked without creating a second approval round.
            code = build_editorial_packet(run_dir, state, timeout=args.timeout)
            if code:
                state["status"] = "BLOCKED" if code == EXIT_BLOCKED else "FAILED"
                save_state(run_dir, state)
                return code
            packet = run_dir / "review" / "editorial-review.json"
            master = run_dir / "review" / "locked-editorial-master.json"
            corrected = run_dir / "artifacts" / "corrected-transcript.json"
            asr_corrections = run_dir / "review" / "asr-corrections.json"
            cut_plan = run_dir / "review" / "cut-plan.json"
            caption_units = run_dir / "review" / "caption-units.json"
            semantic_map = run_dir / "review" / "semantic-map.json"
            code = run_stage_command(
                run_dir,
                state,
                "human_lock",
                [
                    sys.executable,
                    str(SCRIPTS / "lock_editorial_review.py"),
                    "--packet",
                    str(packet),
                    "--confirmation-note",
                    args.confirmation_note,
                    "--user-confirmed",
                    "--output",
                    str(master),
                    "--corrected-transcript-output",
                    str(corrected),
                    "--asr-corrections-output",
                    str(asr_corrections),
                    "--cut-plan-output",
                    str(cut_plan),
                    "--caption-units-output",
                    str(caption_units),
                    "--semantic-map-output",
                    str(semantic_map),
                ],
                input_payload={
                    "implementation": file_fingerprint(
                        SCRIPTS / "lock_editorial_review.py"
                    ),
                    "packet": file_fingerprint(packet),
                    "confirmation_note": args.confirmation_note,
                    "pipeline_version": PIPELINE_VERSION,
                },
                outputs=[
                    master,
                    corrected,
                    asr_corrections,
                    cut_plan,
                    caption_units,
                    semantic_map,
                ],
                timeout=args.timeout,
            )
            if code:
                state["status"] = "BLOCKED" if code == EXIT_BLOCKED else "FAILED"
                save_state(run_dir, state)
                return code
            require_locked_text_master(run_dir)
            state["status"] = "BLOCKED"
            save_state(run_dir, state)
        print("editorial decisions locked after one human review; run resume")
        return EXIT_SUCCESS
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOCKED
    except (OSError, ValueError, KeyError, PermissionError) as exc:
        print(f"lock-review failed: {exc}", file=sys.stderr)
        return EXIT_SCHEMA


def materialize_overlays(
    run_dir: Path,
    state: dict[str, Any],
    plan_path: Path,
    style_decision_path: Path,
    visual_audit_path: Path,
    semantic_reveal_audit_path: Path,
) -> tuple[int, Path | None]:
    output = run_dir / "work" / "animations" / "animation-overlays.json"
    layout_fit_report_path = run_dir / "review" / "layout-fit-report.json"
    if not plan_path.is_file():
        set_stage(
            run_dir,
            state,
            "animations",
            "blocked",
            exit_code=EXIT_BLOCKED,
            message="write review/animation-plan.json; use an explicit empty overlays array for zero animations",
        )
        return EXIT_BLOCKED, None
    payload = load_json(plan_path)
    visual_audit = load_json(visual_audit_path)
    if visual_audit.get("ok") is not True or visual_audit.get("errors"):
        raise PermissionError("visual direction audit is not approved for rendering")
    semantic_reveal_audit = load_json(semantic_reveal_audit_path)
    if semantic_reveal_audit.get("ok") is not True or semantic_reveal_audit.get("errors"):
        raise PermissionError("semantic reveal audit is not approved for rendering")
    entries = None
    if isinstance(payload, dict):
        entries = payload.get("overlays")
        if entries is None:
            entries = payload.get("anchors")
    if not isinstance(entries, list):
        raise ValueError("mapped animation plan must contain an anchors or overlays array")
    decision = load_json(style_decision_path)
    style_presets = load_json(ASSETS / "style-presets.json")
    selected_preset = (style_presets.get("presets") or {}).get(decision.get("style_id"))
    if not isinstance(selected_preset, dict):
        raise ValueError("style-decision.json points to an unknown visual style")
    paint_tokens = selected_preset.get("paint_tokens") or {}
    expected_build_inputs_sha256 = semantic_stage_build_inputs_sha256(selected_preset)
    expected_panel_rgba = [
        *(paint_tokens.get("panel_rgb") or []),
        float(paint_tokens.get("panel_opacity", -1)),
    ]
    expected_stage_feather_rgba = [
        *(paint_tokens.get("stage_feather_rgb") or []),
        float(paint_tokens.get("stage_feather_opacity", -1)),
    ]
    expected_source_background_policy = (
        "transparent-stage"
        if decision.get("style_id") == "white-wall-fusion-fixed"
        else "transparent-overlay"
    )
    resolved: list[dict[str, Any]] = []
    layout_checks: list[dict[str, Any]] = []
    animations_root = (run_dir / "work" / "animations").resolve()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"animation overlay {index} must be an object")
        overlay_id = str(entry.get("id") or f"overlay-{index:04d}")
        if not overlay_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in overlay_id):
            raise ValueError(f"animation overlay {index} has an unsafe id: {overlay_id!r}")
        media_value = entry.get("path")
        project_value = entry.get("project_dir")
        project_dir = (
            Path(str(project_value)).resolve()
            if project_value
            else (animations_root / overlay_id / "project").resolve()
        )
        if not project_dir.is_relative_to(animations_root):
            raise ValueError(
                f"AIJianji animation project must stay inside the run directory: {project_dir}"
            )
        media = (
            Path(str(media_value)).resolve()
            if media_value
            else project_dir / str(entry.get("output", "overlay.mov"))
        )
        config = entry.get("config")
        if entry.get("template") == "semantic-stage":
            if not isinstance(config, dict):
                raise ValueError(f"animation overlay {index} is missing mapped config")
            expected_config_sha256 = canonical_json_sha256(config)
            existing_spec_path = project_dir / "overlay-spec.json"
            if existing_spec_path.is_file():
                existing_spec = load_json(existing_spec_path)
                existing_provenance = existing_spec.get("provenance") or {}
                existing_config_sha256 = str(
                    existing_provenance.get("config_sha256") or ""
                )
                cache_matches = (
                    existing_config_sha256 == expected_config_sha256
                    and existing_spec.get("style") == decision.get("style_id")
                    and existing_spec.get("skin_id") == decision.get("skin_id")
                    and existing_spec.get("paint_tokens_sha256")
                    == decision.get("paint_tokens_sha256")
                    and existing_spec.get("build_inputs_sha256")
                    == expected_build_inputs_sha256
                    and existing_spec.get("pipeline_version") == PIPELINE_VERSION
                )
                if not cache_matches:
                    if not media.is_relative_to(project_dir):
                        raise ValueError(
                            f"animation overlay {index} has stale external media and cannot be "
                            "safely rebuilt"
                        )
                    shutil.rmtree(project_dir)
        if not media.is_file() and not (project_dir / "index.html").is_file():
            if entry.get("render_approved") is not True:
                raise PermissionError(
                    f"animation overlay {index} requires render_approved=true before project build"
                )
            if entry.get("template") != "semantic-stage":
                raise ValueError(
                    f"AIJianji only builds semantic-stage overlays; got {entry.get('template')!r}"
                )
            project_dir.parent.mkdir(parents=True, exist_ok=True)
            config_path = project_dir.parent / "semantic-stage.config.json"
            write_json(config_path, config)
            build_log = run_dir / "logs" / f"animations-{index:04d}-build.log"
            built = run(
                [
                    sys.executable,
                    str(ASSETS / "semantic-stage" / "build.py"),
                    str(config_path),
                    str(project_dir),
                    "--style",
                    str(decision.get("style_id")),
                ],
                capture=True,
                timeout=120,
                log_path=build_log,
                check=False,
            )
            if built.returncode != 0:
                raise ValueError(f"animation overlay {index} project build failed")
        layout_check_summary: dict[str, Any] | None = None
        if project_dir and (project_dir / "index.html").is_file():
            layout_check_path = project_dir / "layout-check.json"
            index_html_sha256 = sha256_file(project_dir / "index.html")
            motion_sha256 = sha256_file(project_dir / "index.motion.json")
            if layout_check_path.is_file():
                cached_layout_check = load_json(layout_check_path)
                if (
                    cached_layout_check.get("layout_model") == LAYOUT_MODEL_ID
                    and cached_layout_check.get("index_html_sha256")
                    == index_html_sha256
                    and cached_layout_check.get("motion_sha256") == motion_sha256
                    and cached_layout_check.get("hyperframes_version")
                    == HYPERFRAMES_VERSION
                ):
                    layout_check_summary = cached_layout_check
            if layout_check_summary is None:
                check_log = run_dir / "logs" / f"animations-{index:04d}-check.log"
                check = run(
                    [
                        "npx",
                        "--yes",
                        f"hyperframes@{HYPERFRAMES_VERSION}",
                        "check",
                        "--json",
                        "--at-transitions",
                    ],
                    capture=True,
                    timeout=300,
                    cwd=project_dir,
                    log_path=check_log,
                    check=False,
                )
                if check.returncode != 0:
                    raise ValueError(
                        f"animation overlay {index} failed HyperFrames check"
                    )
                try:
                    check_payload = json.loads(check.stdout or "")
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"animation overlay {index} returned invalid HyperFrames JSON"
                    ) from exc
                layout_payload = check_payload.get("layout") or {}
                all_findings = (
                    layout_payload.get("findings")
                    if isinstance(layout_payload.get("findings"), list)
                    else []
                )
                overflow_findings = [
                    finding
                    for finding in all_findings
                    if isinstance(finding, dict)
                    and finding.get("code") == "container_overflow"
                ]
                layout_check_summary = {
                    "schema_version": 1,
                    "policy": "browser-measured-layout-gate",
                    "layout_model": LAYOUT_MODEL_ID,
                    "overlay_id": overlay_id,
                    "index_html_sha256": index_html_sha256,
                    "motion_sha256": motion_sha256,
                    "hyperframes_version": HYPERFRAMES_VERSION,
                    "ok": not overflow_findings,
                    "container_overflow_count": len(overflow_findings),
                    "container_overflow_findings": overflow_findings,
                    "layout_warning_count": int(
                        layout_payload.get("warningCount") or 0
                    ),
                    "layout_error_count": int(
                        layout_payload.get("errorCount") or 0
                    ),
                }
                write_json(layout_check_path, layout_check_summary)
            layout_checks.append(layout_check_summary)
            if layout_check_summary.get("container_overflow_count"):
                plan_sha256 = sha256_file(plan_path)
                event_path = run_dir / "logs" / "layout-reflow-events.jsonl"
                previous_plan_hashes: set[str] = set()
                if event_path.is_file():
                    for line in event_path.read_text(encoding="utf-8").splitlines():
                        try:
                            event_payload = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        previous_plan_hashes.add(
                            str(event_payload.get("animation_plan_sha256") or "")
                        )
                if plan_sha256 not in previous_plan_hashes:
                    append_jsonl(
                        event_path,
                        {
                            "event": "layout_reflow_required",
                            "at": utc_now(),
                            "overlay_id": overlay_id,
                            "animation_plan_sha256": plan_sha256,
                            "container_overflow_count": layout_check_summary[
                                "container_overflow_count"
                            ],
                        },
                    )
                    previous_plan_hashes.add(plan_sha256)
                attempt = len({item for item in previous_plan_hashes if item})
                exhausted = attempt >= 3
                write_json(
                    layout_fit_report_path,
                    {
                        "schema_version": 1,
                        "policy": "automatic-ai-layout-reflow",
                        "layout_model": LAYOUT_MODEL_ID,
                        "ok": False,
                        "status": "reflow-exhausted" if exhausted else "reflow-required",
                        "attempt": attempt,
                        "maximum_attempts": 3,
                        "human_review_required": False,
                        "animation_plan": file_fingerprint(plan_path),
                        "strategy_order": automatic_reflow_strategy(),
                        "checks": layout_checks,
                    },
                )
                if exhausted:
                    raise PermissionError(
                        "automatic layout reflow exhausted after three distinct plans; "
                        "report a technical blocker without rendering clipped cards"
                    )
                raise PermissionError(
                    "browser-measured card overflow requires automatic AI reflow; "
                    "read review/layout-fit-report.json, revise animation-plan.json and "
                    "semantic-reveal-timeline.json without asking the user, then resume"
                )

        if not media.is_file() and project_dir:
            if entry.get("render_approved") is not True:
                raise PermissionError(
                    f"animation overlay {index} requires render_approved=true before HyperFrames render"
                )
            if not (project_dir / "index.html").is_file():
                raise ValueError(f"animation overlay {index} project is missing index.html: {project_dir}")
            render_log = run_dir / "logs" / f"animations-{index:04d}-render.log"
            with atomic_output_path(media) as temporary_media:
                rendered = run(
                    [
                        "npx",
                        "--yes",
                        f"hyperframes@{HYPERFRAMES_VERSION}",
                        "render",
                        "--format",
                        "mov",
                        "--quality",
                        "high",
                        "--strict",
                        "--output",
                        str(temporary_media),
                    ],
                    capture=True,
                    timeout=1800,
                    cwd=project_dir,
                    log_path=render_log,
                    check=False,
                )
                if rendered.returncode != 0:
                    raise ValueError(f"animation overlay {index} failed HyperFrames render")
        if not media.is_file():
            raise ValueError(f"animation overlay {index} media missing: {media}")
        overlay_media = media_summary(media)
        pixel_format = str((overlay_media.get("video") or {}).get("pix_fmt") or "")
        if "a" not in pixel_format:
            raise ValueError(
                f"animation overlay {index} is not alpha-capable: pix_fmt={pixel_format!r}"
            )
        spec_value = entry.get("spec")
        spec_path = (
            Path(str(spec_value)).resolve()
            if spec_value
            else (project_dir / "overlay-spec.json" if project_dir else media.parent / "overlay-spec.json")
        )
        if not spec_path.is_file():
            raise ValueError(f"animation overlay {index} spec missing: {spec_path}")
        spec = load_json(spec_path)
        if spec.get("style") != decision.get("style_id"):
            raise ValueError(f"animation overlay {index} style differs from style-decision.json")
        if spec.get("skin_id") != decision.get("skin_id"):
            raise ValueError(f"animation overlay {index} skin differs from style-decision.json")
        if spec.get("paint_tokens_sha256") != decision.get("paint_tokens_sha256"):
            raise ValueError(
                f"animation overlay {index} paint tokens differ from style-decision.json"
            )
        if spec.get("build_inputs_sha256") != expected_build_inputs_sha256:
            raise ValueError(
                f"animation overlay {index} build inputs differ from current runtime assets"
            )
        if spec.get("template") != "semantic-stage":
            raise ValueError(f"animation overlay {index} is not a semantic-stage")
        if spec.get("animation_layout") != "reference-fixed-left":
            raise ValueError(f"animation overlay {index} changed the locked AIJianji layout")
        if spec.get("panel_mode") != "content-panel":
            raise ValueError(f"animation overlay {index} removed the reference card panel")
        if spec.get("source_background_policy") != expected_source_background_policy:
            raise ValueError(
                f"animation overlay {index} changed the source-background policy"
            )
        if spec.get("canvas") != {"width": 2560, "height": 1440}:
            raise ValueError(f"animation overlay {index} changed the 16:9 reference canvas")
        layout = spec.get("layout")
        if layout not in {"fixed-left", "fullscreen"}:
            raise ValueError(f"animation overlay {index} has invalid AIJianji layout {layout!r}")
        reference = spec.get("reference_contract") or {}
        expected_card_sizes = {
            "small": {
                "reference_width": 373,
                "template_width": 746,
                "canvas_ratio": 0.29140625,
            },
            "medium": {
                "reference_width": 427,
                "template_width": 854,
                "canvas_ratio": 0.33359375,
            },
        }
        if (
            reference.get("reference_canvas") != [1280, 720]
            or reference.get("stage") != [37, 29, 427]
            or reference.get("card_sizes") != expected_card_sizes
            or reference.get("default_card_size") != "medium"
            or reference.get("maximum_card_width")
            != {
                "size": "medium",
                "reference_width": 427,
                "template_width": 854,
                "canvas_ratio": 0.33359375,
            }
            or reference.get("panel_rgba") != expected_panel_rgba
            or reference.get("stage_feather_rgba") != expected_stage_feather_rgba
            or reference.get("free_text_primary") != paint_tokens.get("text_primary")
            or reference.get("panel_text_primary")
            != paint_tokens.get("panel_text_primary")
            or reference.get("full_field_overlay_opacity")
            != float(paint_tokens.get("fullscreen_opacity", -1))
            or reference.get("adaptive_repositioning") is not False
        ):
            raise ValueError(f"animation overlay {index} differs from the measured reference proportions")
        selections = spec.get("card_size_selections")
        if (
            spec.get("card_sizing_model") != "spoken-first-content-height"
            or spec.get("visual_grammar_model") != "spoken-first-relations"
            or spec.get("stage_layout_model") != LAYOUT_MODEL_ID
            or not isinstance(selections, list)
            or not selections
            or any(
                not isinstance(item, dict)
                or item.get("size") not in {"small", "medium"}
                or not str(item.get("content_structure") or "").strip()
                or not str(item.get("reason") or "").strip()
                or not str(item.get("relation_layout") or "").strip()
                or item.get("fidelity_mode") != "spoken-first"
                or not str(item.get("layout_reason") or "").strip()
                for item in selections
            )
        ):
            raise ValueError(
                f"animation overlay {index} is missing audited spoken-first card selections"
            )
        if decision.get("style_id") == "white-wall-fusion-fixed" and (
            paint_tokens.get("panel_rgb") != [10, 20, 27]
            or float(paint_tokens.get("panel_opacity", -1)) != 0.82
            or paint_tokens.get("text_primary") != "#17212B"
            or paint_tokens.get("panel_text_primary") != "#F3F5F7"
            or float(paint_tokens.get("stage_feather_opacity", -1)) != 0.0
            or float(paint_tokens.get("fullscreen_opacity", -1)) != 0.0
        ):
            raise ValueError(
                "white-wall skin must use its fixed transparent-stage paint roles"
            )
        if spec.get("information_model") != "persistent-layer-stack":
            raise ValueError(f"animation overlay {index} replaced the persistent layer model")
        if spec.get("motion_model") != "anchored-opacity":
            raise ValueError(f"animation overlay {index} changed the locked AIJianji motion model")
        if spec.get("semantic_timing_model") != "exact-spoken-reveal":
            raise ValueError(f"animation overlay {index} changed the semantic reveal model")
        if spec.get("component_skin") != "type-specific-reference":
            raise ValueError(f"animation overlay {index} collapsed reference components into a generic card")
        if spec.get("animation_font_file") != "NotoSansCJKsc-Bold.otf":
            raise ValueError(f"animation overlay {index} changed the locked card font")
        if spec.get("pipeline_version") != PIPELINE_VERSION:
            raise ValueError(f"animation overlay {index} uses an obsolete pipeline")
        if (spec.get("runtime") or {}).get("version") != HYPERFRAMES_VERSION:
            raise ValueError(f"animation overlay {index} changed the HyperFrames runtime")
        timeline_contract = spec.get("timeline_contract") or {}
        if (
            timeline_contract.get("id") != "semantic-stage-timeline-v1"
            or timeline_contract.get("header_lead_seconds") != 0.30
            or timeline_contract.get("container_entry_seconds") != 0.22
            or timeline_contract.get("item_entry_seconds") != 0.15
            or timeline_contract.get("exit_seconds") != 0.22
            or any(
                not isinstance(timeline_contract.get(field), str)
                or len(timeline_contract[field]) != 64
                for field in ("dom_sha256", "timeline_sha256", "assertions_sha256")
            )
        ):
            raise ValueError(f"animation overlay {index} changed the locked timeline contract")
        if (
            layout == "fixed-left"
            and spec.get("content_bounds") != FIXED_LEFT_CONTENT_BOUNDS
        ):
            raise ValueError(f"animation overlay {index} left stage bounds drifted")
        expected_lane = "full" if layout == "fullscreen" else "left"
        if spec.get("lane") != expected_lane:
            raise ValueError(f"animation overlay {index} lane differs from its locked layout")
        start = float(entry.get("start", entry.get("output_start")))
        end = float(entry.get("end", entry.get("output_end")))
        if end <= start:
            raise ValueError(f"animation overlay {index} must end after it starts")
        resolved.append(
            {
                "id": overlay_id,
                "path": str(media),
                "media_sha256": sha256_file(media),
                "start": start,
                "end": end,
                "layout_check": layout_check_summary,
                **spec,
            }
        )
    if len({item.get("skin_id") for item in resolved}) > 1:
        raise ValueError("one video cannot mix multiple animation skins")
    write_json(
        output,
        {
            "schema_version": "1.0.0",
            "pipeline_version": PIPELINE_VERSION,
            "overlays": resolved,
        },
    )
    write_json(
        layout_fit_report_path,
        {
            "schema_version": 1,
            "policy": "automatic-ai-layout-reflow",
            "layout_model": LAYOUT_MODEL_ID,
            "ok": True,
            "status": "passed",
            "human_review_required": False,
            "animation_plan": file_fingerprint(plan_path),
            "strategy_order": automatic_reflow_strategy(),
            "checks": layout_checks,
        },
    )
    fingerprint = canonical_json_sha256(
        {
            "plan": file_fingerprint(plan_path),
            "style": file_fingerprint(style_decision_path),
            "visual_direction_audit": file_fingerprint(visual_audit_path),
            "semantic_reveal_audit": file_fingerprint(semantic_reveal_audit_path),
            "layout_fit_report": file_fingerprint(layout_fit_report_path),
            "media": [file_fingerprint(item["path"]) for item in resolved],
        }
    )
    set_stage(
        run_dir,
        state,
        "animations",
        "succeeded",
        exit_code=0,
        input_fingerprint=fingerprint,
        outputs=[output, layout_fit_report_path],
    )
    return EXIT_SUCCESS, output


def cmd_resume(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    if not state_path(run_dir).is_file():
        print(f"not an initialized run: {run_dir}", file=sys.stderr)
        return EXIT_SCHEMA
    try:
        with RunLock(run_dir / "run.lock"):
            state = load_state(run_dir)
            if state.get("migration_required"):
                print(
                    "run was created by an older pipeline; preserve it read-only "
                    f"and create a fresh run with pipeline {PIPELINE_VERSION}",
                    file=sys.stderr,
                )
                return EXIT_BLOCKED
            ensure_inputs_unchanged(state)
            state["jobs"] = args.jobs
            source = Path(state["inputs"]["source"]["path"])
            locked_text_master, locked_text_master_sha256 = (
                require_locked_text_master(run_dir)
            )
            normalized = run_dir / "artifacts" / "normalized-transcript.json"
            normalized_input = normalized
            asr_integrity = run_dir / "artifacts" / "asr-integrity.json"
            if not asr_integrity.is_file() or load_json(asr_integrity).get("ok") is not True:
                print(
                    "ASR integrity must pass in the current run before resume",
                    file=sys.stderr,
                )
                return EXIT_BLOCKED
            asr_corrections = run_dir / "review" / "asr-corrections.json"
            corrected_transcript = run_dir / "artifacts" / "corrected-transcript.json"
            if not asr_corrections.is_file():
                set_stage(
                    run_dir,
                    state,
                    "asr_correction",
                    "blocked",
                    exit_code=EXIT_BLOCKED,
                    message=(
                        "asr-corrections.json is required; review every suspicious "
                        "ASR token against audio and context"
                    ),
                    input_fingerprint=sha256_file(normalized),
                )
                state["status"] = "BLOCKED"
                save_state(run_dir, state)
                return EXIT_BLOCKED
            code = run_stage_command(
                run_dir,
                state,
                "asr_correction",
                [
                    sys.executable,
                    str(SCRIPTS / "apply_asr_corrections.py"),
                    "--transcript",
                    str(normalized),
                    "--review",
                    str(asr_corrections),
                    "--source",
                    str(source),
                    "--integrity",
                    str(asr_integrity),
                    "--output",
                    str(corrected_transcript),
                ],
                input_payload={
                    "implementation": file_fingerprint(
                        SCRIPTS / "apply_asr_corrections.py"
                    ),
                    "normalized_transcript": file_fingerprint(normalized),
                    "asr_corrections": file_fingerprint(asr_corrections),
                    "source": file_fingerprint(source),
                    "asr_integrity": file_fingerprint(asr_integrity),
                    "pipeline_version": PIPELINE_VERSION,
                    "locked_text_master": file_fingerprint(locked_text_master),
                },
                outputs=[corrected_transcript],
                timeout=120,
            )
            if code:
                state["status"] = "BLOCKED" if code == EXIT_BLOCKED else "FAILED"
                save_state(run_dir, state)
                return EXIT_BLOCKED if code == EXIT_BLOCKED else code
            normalized = corrected_transcript
            semantic_map = run_dir / "review" / "semantic-map.json"
            semantic_cut_plan = run_dir / "review" / "cut-plan.json"
            caption_units = run_dir / "review" / "caption-units.json"
            embedded_filler_review = run_dir / "review" / "embedded-filler-review.json"
            if (
                not semantic_map.is_file()
                or not semantic_cut_plan.is_file()
                or not caption_units.is_file()
            ):
                set_stage(
                    run_dir,
                    state,
                    "semantic_review",
                    "blocked",
                    exit_code=EXIT_BLOCKED,
                    message=(
                        "semantic-map.json, cut-plan.json, and caption-units.json "
                        "are all required"
                    ),
                )
                state["status"] = "BLOCKED"
                save_state(run_dir, state)
                return EXIT_BLOCKED
            semantic_fingerprint = canonical_json_sha256(
                {
                    "transcript": file_fingerprint(normalized),
                    "normalized_transcript": file_fingerprint(normalized_input),
                    "asr_corrections": file_fingerprint(asr_corrections),
                    "semantic_map": file_fingerprint(semantic_map),
                    "cut_plan": file_fingerprint(semantic_cut_plan),
                    "caption_units": file_fingerprint(caption_units),
                    "embedded_filler_review": (
                        file_fingerprint(embedded_filler_review)
                        if embedded_filler_review.is_file()
                        else None
                    ),
                    "pipeline_version": PIPELINE_VERSION,
                    "locked_text_master_sha256": locked_text_master_sha256,
                }
            )
            set_stage(
                run_dir,
                state,
                "semantic_review",
                "succeeded",
                exit_code=0,
                input_fingerprint=semantic_fingerprint,
                outputs=[semantic_map, semantic_cut_plan, caption_units],
            )

            cut_plan = run_dir / "review" / "cut-plan.refined.json"
            boundary_report = run_dir / "review" / "acoustic-boundaries.json"
            code = run_stage_command(
                run_dir,
                state,
                "boundary_refine",
                [
                    sys.executable,
                    str(SCRIPTS / "refine_boundaries.py"),
                    "--input",
                    str(source),
                    "--transcript",
                    str(normalized),
                    "--plan",
                    str(semantic_cut_plan),
                    "--output",
                    str(cut_plan),
                    "--report",
                    str(boundary_report),
                ],
                input_payload={
                    "source": file_fingerprint(source),
                    "transcript": file_fingerprint(normalized),
                    "semantic_plan": file_fingerprint(semantic_cut_plan),
                    "locked_text_master": file_fingerprint(locked_text_master),
                    "pipeline_version": PIPELINE_VERSION,
                },
                outputs=[cut_plan, boundary_report],
                timeout=args.timeout,
                accepted_codes={0},
            )
            if code:
                state["status"] = "BLOCKED" if code == EXIT_BLOCKED else "FAILED"
                save_state(run_dir, state)
                return EXIT_BLOCKED if code == EXIT_BLOCKED else code

            audit = run_dir / "review" / "cut-plan.audit.json"
            audit_command = [
                sys.executable,
                str(SCRIPTS / "audit_cut_plan.py"),
                "--transcript",
                str(normalized),
                "--plan",
                str(cut_plan),
                "--boundary-report",
                str(boundary_report),
                "--input",
                str(source),
                "--output",
                str(audit),
            ]
            review_decisions = run_dir / "review" / "review-decisions.json"
            if review_decisions.is_file():
                audit_command.extend(["--review-decisions", str(review_decisions)])
            if embedded_filler_review.is_file():
                audit_command.extend(
                    ["--embedded-filler-review", str(embedded_filler_review)]
                )
            audit_input = {
                "transcript": file_fingerprint(normalized),
                "plan": file_fingerprint(cut_plan),
                "source": file_fingerprint(source),
                "boundary_report": file_fingerprint(boundary_report),
                "locked_text_master": file_fingerprint(locked_text_master),
                "review_decisions": file_fingerprint(review_decisions)
                if review_decisions.is_file()
                else None,
                "pipeline_version": PIPELINE_VERSION,
                "embedded_filler_review": (
                    file_fingerprint(embedded_filler_review)
                    if embedded_filler_review.is_file()
                    else None
                ),
            }
            code = run_stage_command(
                run_dir,
                state,
                "audit_gate",
                audit_command,
                input_payload=audit_input,
                outputs=[audit],
                timeout=120,
            )
            if code:
                state["status"] = "BLOCKED" if code == EXIT_BLOCKED else "FAILED"
                save_state(run_dir, state)
                return EXIT_BLOCKED if code == EXIT_BLOCKED else code
            validate_audit_gate(
                load_json(audit),
                plan_sha256=sha256_file(cut_plan),
                input_sha256=sha256_file(source),
            )

            caption_unit_audit = run_dir / "review" / "caption-units.audit.json"
            code = run_stage_command(
                run_dir,
                state,
                "caption_structure",
                [
                    sys.executable,
                    str(SCRIPTS / "audit_caption_units.py"),
                    "--transcript",
                    str(normalized),
                    "--plan",
                    str(cut_plan),
                    "--units",
                    str(caption_units),
                    "--output",
                    str(caption_unit_audit),
                ]
                + (
                    ["--embedded-filler-review", str(embedded_filler_review)]
                    if embedded_filler_review.is_file()
                    else []
                ),
                input_payload={
                    "transcript": file_fingerprint(normalized),
                    "plan": file_fingerprint(cut_plan),
                    "caption_units": file_fingerprint(caption_units),
                    "locked_text_master": file_fingerprint(locked_text_master),
                    "pipeline_version": PIPELINE_VERSION,
                    "embedded_filler_review": (
                        file_fingerprint(embedded_filler_review)
                        if embedded_filler_review.is_file()
                        else None
                    ),
                },
                outputs=[caption_unit_audit],
                timeout=120,
            )
            if code:
                state["status"] = "BLOCKED" if code == EXIT_BLOCKED else "FAILED"
                save_state(run_dir, state)
                return EXIT_BLOCKED if code == EXIT_BLOCKED else code

            cut_dir = run_dir / "work" / "cut"
            cut_manifest = cut_dir / "cut-manifest.json"
            cut_video = cut_dir / "cut.mp4"
            code = run_stage_command(
                run_dir,
                state,
                "cut",
                [
                    sys.executable,
                    str(SCRIPTS / "apply_cut_plan.py"),
                    "--input",
                    str(source),
                    "--plan",
                    str(cut_plan),
                    "--audit-report",
                    str(audit),
                    "--output-dir",
                    str(cut_dir),
                ],
                input_payload={
                    "source": file_fingerprint(source),
                    "plan": file_fingerprint(cut_plan),
                    "boundary_report": file_fingerprint(boundary_report),
                    "audit": file_fingerprint(audit),
                    "locked_text_master": file_fingerprint(locked_text_master),
                    "pipeline_version": PIPELINE_VERSION,
                },
                outputs=[cut_video, cut_manifest],
                timeout=args.timeout,
            )
            if code:
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return code

            pre_rhythm_timeline = (
                run_dir / "artifacts" / "mapped-timeline.pre-rhythm.json"
            )
            animation_plan = run_dir / "review" / "animation-plan.json"
            remap_command = [
                sys.executable,
                str(SCRIPTS / "remap_timeline.py"),
                "--transcript",
                str(normalized),
                "--plan",
                str(cut_plan),
                "--caption-units",
                str(caption_units),
                "--caption-unit-audit",
                str(caption_unit_audit),
                "--input",
                str(source),
                "--audit-report",
                str(audit),
                "--cut-manifest",
                str(cut_manifest),
                "--output",
                str(pre_rhythm_timeline),
            ]
            remap_outputs = [pre_rhythm_timeline]
            mapped_anchors = run_dir / "artifacts" / "mapped-animation-plan.json"
            code = run_stage_command(
                run_dir,
                state,
                "remap",
                remap_command,
                input_payload={
                    "transcript": file_fingerprint(normalized),
                    "plan": file_fingerprint(cut_plan),
                    "cut_manifest": file_fingerprint(cut_manifest),
                    "caption_units": file_fingerprint(caption_units),
                    "caption_unit_audit": file_fingerprint(caption_unit_audit),
                    "locked_text_master": file_fingerprint(locked_text_master),
                    "source": file_fingerprint(source),
                    "audit": file_fingerprint(audit),
                    "pipeline_version": PIPELINE_VERSION,
                },
                outputs=remap_outputs,
                timeout=120,
            )
            if code:
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return code

            rhythm_dir = run_dir / "work" / "rhythm"
            rhythm_video = rhythm_dir / "rhythm.mp4"
            timeline = run_dir / "artifacts" / "mapped-timeline.json"
            rhythm_plan = run_dir / "review" / "rhythm-plan.json"
            rhythm_manifest = rhythm_dir / "rhythm-manifest.json"
            rhythm_command = [
                sys.executable,
                str(SCRIPTS / "adaptive_rhythm.py"),
                "--input",
                str(cut_video),
                "--timeline",
                str(pre_rhythm_timeline),
                "--output-video",
                str(rhythm_video),
                "--output-timeline",
                str(timeline),
                "--plan-output",
                str(rhythm_plan),
                "--manifest-output",
                str(rhythm_manifest),
                "--timeout",
                str(args.timeout),
            ]
            rhythm_outputs = [
                rhythm_video,
                timeline,
                rhythm_plan,
                rhythm_manifest,
            ]
            if animation_plan.is_file():
                rhythm_command.extend(
                    [
                        "--animation-plan",
                        str(animation_plan),
                        "--anchors-output",
                        str(mapped_anchors),
                    ]
                )
                rhythm_outputs.append(mapped_anchors)
            code = run_stage_command(
                run_dir,
                state,
                "rhythm",
                rhythm_command,
                input_payload={
                    "implementation": file_fingerprint(
                        SCRIPTS / "adaptive_rhythm.py"
                    ),
                    "cut_video": file_fingerprint(cut_video),
                    "pre_rhythm_timeline": file_fingerprint(
                        pre_rhythm_timeline
                    ),
                    "animation_plan": (
                        file_fingerprint(animation_plan)
                        if animation_plan.is_file()
                        else None
                    ),
                    "locked_text_master": file_fingerprint(
                        locked_text_master
                    ),
                    "pipeline_version": PIPELINE_VERSION,
                },
                outputs=rhythm_outputs,
                timeout=args.timeout,
            )
            if code:
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return code
            cut_video = rhythm_video

            style_input = run_dir / "review" / "style-selection-input.json"
            if not style_input.is_file():
                write_json(style_input, {})
            style_decision = run_dir / "artifacts" / "style-decision.json"
            code = run_stage_command(
                run_dir,
                state,
                "style_lock",
                [
                    sys.executable,
                    str(SCRIPTS / "select_visual_style.py"),
                    "--input",
                    str(style_input),
                    "--output",
                    str(style_decision),
                ],
                input_payload={
                    "selection": file_fingerprint(style_input),
                    "routing": file_fingerprint(ASSETS / "style-routing.json"),
                    "styles": file_fingerprint(ASSETS / "style-presets.json"),
                    "subtitle_fonts": file_fingerprint(ASSETS / "subtitle-font-presets.json"),
                },
                outputs=[style_decision],
                timeout=120,
            )
            if code:
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return code

            style = load_json(style_decision)
            captions_dir = run_dir / "work" / "captions"
            captions_ass = captions_dir / "captions.ass"
            captions_json = captions_dir / "captions.json"
            base_media = media_summary(cut_video)
            delivery_width, delivery_height = delivery_dimensions(
                int(base_media["video"]["width"]),
                int(base_media["video"]["height"]),
            )
            caption_command = [
                sys.executable,
                str(SCRIPTS / "build_ass.py"),
                "--timeline",
                str(timeline),
                "--caption-unit-audit",
                str(caption_unit_audit),
                "--style",
                str(ASSETS / "subtitle-style.json"),
                "--font-preset",
                str(style["subtitle_font_preset"]),
                "--embed-fonts",
                "--width",
                str(delivery_width),
                "--height",
                str(delivery_height),
                "--output",
                str(captions_ass),
                "--captions-json",
                str(captions_json),
            ]
            code = run_stage_command(
                run_dir,
                state,
                "captions",
                caption_command,
                input_payload={
                    "implementation": file_fingerprint(SCRIPTS / "build_ass.py"),
                    "timeline": file_fingerprint(timeline),
                    "style": file_fingerprint(style_decision),
                    "delivery": {
                        "width": delivery_width,
                        "height": delivery_height,
                    },
                    "caption_unit_audit": file_fingerprint(caption_unit_audit),
                    "locked_text_master": file_fingerprint(locked_text_master),
                    "pipeline_version": PIPELINE_VERSION,
                },
                outputs=[captions_ass, captions_json],
                timeout=300,
            )
            if code:
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return code

            visual_brief = run_dir / "artifacts" / "visual-director-brief.json"
            code = run_stage_command(
                run_dir,
                state,
                "visual_direction",
                [
                    sys.executable,
                    str(SCRIPTS / "prepare_visual_brief.py"),
                    "--semantic-map",
                    str(semantic_map),
                    "--timeline",
                    str(timeline),
                    "--output",
                    str(visual_brief),
                ],
                input_payload={
                    "semantic_map": file_fingerprint(semantic_map),
                    "timeline": file_fingerprint(timeline),
                    "locked_text_master": file_fingerprint(locked_text_master),
                },
                outputs=[visual_brief],
                timeout=120,
            )
            if code:
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return code
            visual_direction = run_dir / "review" / "visual-direction.json"
            visual_audit = run_dir / "review" / "visual-direction.audit.json"
            if not visual_direction.is_file() or not animation_plan.is_file():
                set_stage(
                    run_dir,
                    state,
                    "visual_direction",
                    "blocked",
                    exit_code=EXIT_BLOCKED,
                    message=(
                        "act as video director: write review/visual-direction.json and "
                        "review/animation-plan.json from artifacts/visual-director-brief.json"
                    ),
                    input_fingerprint=canonical_json_sha256(
                        {
                            "brief": file_fingerprint(visual_brief),
                            "direction": None,
                            "animation_plan": None,
                        }
                    ),
                    outputs=[visual_brief],
                )
                state["status"] = "BLOCKED"
                save_state(run_dir, state)
                return EXIT_BLOCKED
            code = run_stage_command(
                run_dir,
                state,
                "visual_direction",
                [
                    sys.executable,
                    str(SCRIPTS / "audit_visual_direction.py"),
                    "--brief",
                    str(visual_brief),
                    "--timeline",
                    str(timeline),
                    "--direction",
                    str(visual_direction),
                    "--animation-plan",
                    str(animation_plan),
                    "--output",
                    str(visual_audit),
                ],
                input_payload={
                    "brief": file_fingerprint(visual_brief),
                    "timeline": file_fingerprint(timeline),
                    "direction": file_fingerprint(visual_direction),
                    "animation_plan": file_fingerprint(animation_plan),
                },
                outputs=[visual_brief, visual_direction, animation_plan, visual_audit],
                timeout=120,
            )
            if code:
                state["status"] = "BLOCKED" if code == EXIT_BLOCKED else "FAILED"
                save_state(run_dir, state)
                return EXIT_BLOCKED if code == EXIT_BLOCKED else code

            semantic_reveal_timeline = run_dir / "review" / "semantic-reveal-timeline.json"
            semantic_reveal_audit = run_dir / "review" / "semantic-reveal.audit.json"
            if not semantic_reveal_timeline.is_file():
                set_stage(
                    run_dir,
                    state,
                    "semantic_timing",
                    "blocked",
                    exit_code=EXIT_BLOCKED,
                    message=(
                        "write review/semantic-reveal-timeline.json from the exact mapped "
                        "words in artifacts/visual-director-brief.json"
                    ),
                    input_fingerprint=canonical_json_sha256(
                        {
                            "brief": file_fingerprint(visual_brief),
                            "timeline": file_fingerprint(timeline),
                            "animation_plan": file_fingerprint(animation_plan),
                            "semantic_reveal_timeline": None,
                        }
                    ),
                    outputs=[visual_brief],
                )
                state["status"] = "BLOCKED"
                save_state(run_dir, state)
                return EXIT_BLOCKED
            code = run_stage_command(
                run_dir,
                state,
                "semantic_timing",
                [
                    sys.executable,
                    str(SCRIPTS / "audit_semantic_reveal.py"),
                    "--brief",
                    str(visual_brief),
                    "--timeline",
                    str(timeline),
                    "--animation-plan",
                    str(animation_plan),
                    "--reveal-timeline",
                    str(semantic_reveal_timeline),
                    "--output",
                    str(semantic_reveal_audit),
                ],
                input_payload={
                    "brief": file_fingerprint(visual_brief),
                    "timeline": file_fingerprint(timeline),
                    "animation_plan": file_fingerprint(animation_plan),
                    "semantic_reveal_timeline": file_fingerprint(semantic_reveal_timeline),
                    "auditor": file_fingerprint(SCRIPTS / "audit_semantic_reveal.py"),
                },
                outputs=[semantic_reveal_timeline, semantic_reveal_audit],
                timeout=120,
            )
            if code:
                state["status"] = "BLOCKED" if code == EXIT_BLOCKED else "FAILED"
                save_state(run_dir, state)
                return EXIT_BLOCKED if code == EXIT_BLOCKED else code

            try:
                code, overlays = materialize_overlays(
                    run_dir,
                    state,
                    mapped_anchors if mapped_anchors.is_file() else animation_plan,
                    style_decision,
                    visual_audit,
                    semantic_reveal_audit,
                )
            except PermissionError as exc:
                set_stage(
                    run_dir,
                    state,
                    "animations",
                    "blocked",
                    exit_code=EXIT_BLOCKED,
                    message=str(exc),
                )
                state["status"] = "BLOCKED"
                save_state(run_dir, state)
                return EXIT_BLOCKED
            except (OSError, TypeError, ValueError, subprocess.TimeoutExpired) as exc:
                set_stage(
                    run_dir,
                    state,
                    "animations",
                    "failed",
                    exit_code=EXIT_STAGE_FAILED,
                    message=str(exc),
                )
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return EXIT_STAGE_FAILED
            if code or overlays is None:
                state["status"] = "BLOCKED" if code == EXIT_BLOCKED else "FAILED"
                save_state(run_dir, state)
                return code

            final = run_dir / "deliverable" / "final.mp4"
            render_log = run_dir / "logs" / "compose.log"
            code = run_stage_command(
                run_dir,
                state,
                "compose",
                [
                    sys.executable,
                    str(SCRIPTS / "render_final.py"),
                    "--base",
                    str(cut_video),
                    "--overlays",
                    str(overlays),
                    "--captions",
                    str(captions_ass),
                    "--true-peak",
                    "-2.0",
                    "--width",
                    str(delivery_width),
                    "--height",
                    str(delivery_height),
                    "--output",
                    str(final),
                ],
                input_payload={
                    "base": file_fingerprint(cut_video),
                    "overlays": file_fingerprint(overlays),
                    "captions": file_fingerprint(captions_ass),
                    "true_peak": -2.0,
                    "delivery": {
                        "width": delivery_width,
                        "height": delivery_height,
                    },
                },
                outputs=[final],
                timeout=args.timeout,
            )
            if code:
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return code

            qa = run_dir / "qa" / "report.json"
            code = run_stage_command(
                run_dir,
                state,
                "validate",
                [
                    sys.executable,
                    str(SCRIPTS / "validate_final.py"),
                    "--source",
                    str(source),
                    "--base-video",
                    str(cut_video),
                    "--final",
                    str(final),
                    "--plan",
                    str(cut_plan),
                    "--transcript",
                    str(normalized),
                    "--normalized-transcript",
                    str(normalized_input),
                    "--asr-corrections",
                    str(asr_corrections),
                    "--asr-integrity",
                    str(asr_integrity),
                    "--locked-text-master",
                    str(locked_text_master),
                    "--caption-units",
                    str(caption_units),
                    "--timeline",
                    str(timeline),
                    "--cut-manifest",
                    str(cut_manifest),
                    "--rhythm-manifest",
                    str(rhythm_manifest),
                    "--audit-report",
                    str(audit),
                    "--visual-direction-audit",
                    str(visual_audit),
                    "--visual-direction",
                    str(visual_direction),
                    "--animation-plan",
                    str(animation_plan),
                    "--semantic-reveal-audit",
                    str(semantic_reveal_audit),
                    "--semantic-reveal-timeline",
                    str(semantic_reveal_timeline),
                    "--captions",
                    str(captions_json),
                    "--caption-unit-audit",
                    str(caption_unit_audit),
                    "--captions-ass",
                    str(captions_ass),
                    "--overlays",
                    str(overlays),
                    "--style-decision",
                    str(style_decision),
                    "--render-log",
                    str(render_log),
                    "--delivery-width",
                    str(delivery_width),
                    "--delivery-height",
                    str(delivery_height),
                    "--output",
                    str(qa),
                ]
                + (
                    ["--embedded-filler-review", str(embedded_filler_review)]
                    if embedded_filler_review.is_file()
                    else []
                ),
                input_payload={
                    "source": file_fingerprint(source),
                    "base": file_fingerprint(cut_video),
                    "final": file_fingerprint(final),
                    "plan": file_fingerprint(cut_plan),
                    "transcript": file_fingerprint(normalized),
                    "normalized_transcript": file_fingerprint(normalized_input),
                    "asr_corrections": file_fingerprint(asr_corrections),
                    "asr_integrity": file_fingerprint(asr_integrity),
                    "locked_text_master": file_fingerprint(locked_text_master),
                    "caption_units": file_fingerprint(caption_units),
                    "timeline": file_fingerprint(timeline),
                    "cut_manifest": file_fingerprint(cut_manifest),
                    "rhythm_manifest": file_fingerprint(rhythm_manifest),
                    "rhythm_plan": file_fingerprint(rhythm_plan),
                    "embedded_filler_review": (
                        file_fingerprint(embedded_filler_review)
                        if embedded_filler_review.is_file()
                        else None
                    ),
                    "audit": file_fingerprint(audit),
                    "visual_direction_audit": file_fingerprint(visual_audit),
                    "visual_direction": file_fingerprint(visual_direction),
                    "animation_plan": file_fingerprint(animation_plan),
                    "semantic_reveal_audit": file_fingerprint(semantic_reveal_audit),
                    "semantic_reveal_timeline": file_fingerprint(semantic_reveal_timeline),
                    "captions": file_fingerprint(captions_json),
                    "caption_unit_audit": file_fingerprint(caption_unit_audit),
                    "captions_ass": file_fingerprint(captions_ass),
                    "overlays": file_fingerprint(overlays),
                    "style": file_fingerprint(style_decision),
                    "delivery": {
                        "width": delivery_width,
                        "height": delivery_height,
                    },
                },
                outputs=[qa],
                timeout=args.timeout,
            )
            if code:
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return EXIT_QA_FAILED
            if not load_json(qa).get("ok"):
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return EXIT_QA_FAILED
            semantic_reveal_sheet = run_dir / "review" / "semantic-reveal-sheet.jpg"
            evidence = run(
                [
                    sys.executable,
                    str(SCRIPTS / "make_semantic_reveal_sheet.py"),
                    "--video",
                    str(final),
                    "--audit",
                    str(semantic_reveal_audit),
                    "--output",
                    str(semantic_reveal_sheet),
                ],
                capture=True,
                timeout=600,
                cwd=SKILL_ROOT,
                log_path=run_dir / "logs" / "semantic-reveal-sheet.log",
                check=False,
            )
            if evidence.returncode != 0 or not semantic_reveal_sheet.is_file():
                set_stage(
                    run_dir,
                    state,
                    "validate",
                    "failed",
                    exit_code=EXIT_QA_FAILED,
                    message="semantic reveal evidence sheet failed",
                    outputs=[qa],
                )
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return EXIT_QA_FAILED
            contact_sheet = run_dir / "review" / "contact-sheet.jpg"
            contact = run(
                [
                    sys.executable,
                    str(SCRIPTS / "make_contact_sheet.py"),
                    "--video",
                    str(final),
                    "--plan",
                    str(mapped_anchors),
                    "--output",
                    str(contact_sheet),
                ],
                capture=True,
                timeout=600,
                cwd=SKILL_ROOT,
                log_path=run_dir / "logs" / "contact-sheet.log",
                check=False,
            )
            if contact.returncode != 0 or not contact_sheet.is_file():
                set_stage(
                    run_dir,
                    state,
                    "validate",
                    "failed",
                    exit_code=EXIT_QA_FAILED,
                    message="AIJianji contact sheet failed",
                    outputs=[qa, semantic_reveal_sheet],
                )
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return EXIT_QA_FAILED
            agent_review_brief = run_dir / "artifacts" / "agent-review-brief.json"
            brief = run(
                [
                    sys.executable,
                    str(SCRIPTS / "prepare_agent_review.py"),
                    "--run-dir",
                    str(run_dir),
                    "--style-decision",
                    str(style_decision),
                    "--output",
                    str(agent_review_brief),
                ],
                capture=True,
                timeout=120,
                cwd=SKILL_ROOT,
                log_path=run_dir / "logs" / "agent-review-brief.log",
                check=False,
            )
            if brief.returncode != 0 or not agent_review_brief.is_file():
                set_stage(
                    run_dir,
                    state,
                    "validate",
                    "failed",
                    exit_code=EXIT_QA_FAILED,
                    message="AI review brief generation failed",
                    outputs=[qa, semantic_reveal_sheet, contact_sheet],
                )
                state["status"] = "FAILED"
                save_state(run_dir, state)
                return EXIT_QA_FAILED
            set_stage(
                run_dir,
                state,
                "agent_review",
                "blocked",
                exit_code=EXIT_BLOCKED,
                message=(
                    "spawn a fresh-context AI lens to watch final.mp4 and inspect "
                    "artifacts/agent-review-brief.json; it writes review/ai-acceptance.json"
                ),
                input_fingerprint=sha256_file(agent_review_brief),
                outputs=[agent_review_brief, semantic_reveal_sheet, contact_sheet],
            )
            state["status"] = "BLOCKED"
            save_state(run_dir, state)
            print("mechanical QA passed; waiting for fresh AI-lens acceptance")
            return EXIT_BLOCKED
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOCKED
    except (KeyError, OSError, TypeError, ValueError, PermissionError) as exc:
        print(f"resume failed: {exc}", file=sys.stderr)
        return EXIT_SCHEMA


def cmd_status(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    try:
        state = load_state(run_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"status failed: {exc}", file=sys.stderr)
        return EXIT_SCHEMA
    next_action = next_action_for_state(state)
    if args.json:
        payload = dict(state)
        payload["next_action"] = next_action
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{state['status']}  pipeline={state['pipeline_version']}  {run_dir}")
        for name in STAGE_ORDER:
            stage = state["stages"][name]
            suffix = f" — {stage['message']}" if stage.get("message") else ""
            print(f"{name:16} {stage['status']}{suffix}")
        print(f"next_action      {next_action}")
    return EXIT_SUCCESS


def next_action_for_state(state: dict[str, Any]) -> str:
    if state.get("migration_required"):
        return "create_fresh_run"
    if state.get("status") == "READY":
        return "deliver_final"
    for name in STAGE_ORDER:
        stage = state["stages"][name]
        if stage.get("status") == "succeeded":
            continue
        if name == "asr_correction":
            return "ai_review_asr_words_then_resume"
        if name == "editorial_review":
            return "ai_finish_editorial_plan_then_prepare_review"
        if name == "human_lock":
            return "show_single_review_packet_then_lock_review"
        if name == "semantic_review":
            return "ai_write_semantic_cut_and_caption_plans_then_resume"
        if name == "visual_direction":
            return "ai_write_visual_direction_and_animation_plan_then_resume"
        if name == "semantic_timing":
            return "ai_write_semantic_reveal_timeline_then_resume"
        if name == "agent_review":
            return "spawn_fresh_ai_lens_write_ai_acceptance_then_verify"
        if stage.get("status") == "failed":
            return f"fix_{name}_failure"
        if stage.get("status") == "blocked":
            return f"resolve_{name}_blocker"
        return f"run_or_resume_{name}"
    return "inspect_run_state"


def cmd_verify(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    acceptance = run_dir / "review" / "ai-acceptance.json"
    agent_review_brief = run_dir / "artifacts" / "agent-review-brief.json"
    qa = run_dir / "qa" / "report.json"
    final = run_dir / "deliverable" / "final.mp4"
    try:
        with RunLock(run_dir / "run.lock"):
            state = load_state(run_dir)
            if state.get("migration_required") or state.get("pipeline_version") != PIPELINE_VERSION:
                print(
                    "manual verification requires a fresh run completed by the current pipeline",
                    file=sys.stderr,
                )
                return EXIT_BLOCKED
            ensure_inputs_unchanged(state)
            required_pipeline_stages = STAGE_ORDER[: STAGE_ORDER.index("agent_review")]
            incomplete_stages = [
                name
                for name in required_pipeline_stages
                if state["stages"][name].get("status") != "succeeded"
            ]
            if incomplete_stages:
                print(
                    "manual verification is blocked; required stages are incomplete: "
                    + ", ".join(incomplete_stages),
                    file=sys.stderr,
                )
                return EXIT_BLOCKED
            stale_stage_outputs = [
                name
                for name in required_pipeline_stages
                if state["stages"][name].get("outputs")
                and not outputs_valid(
                    state["stages"][name],
                    str(state["stages"][name].get("input_fingerprint") or ""),
                )
            ]
            if stale_stage_outputs:
                print(
                    "manual verification is blocked; stage outputs changed after approval: "
                    + ", ".join(stale_stage_outputs),
                    file=sys.stderr,
                )
                return EXIT_BLOCKED
            if not qa.is_file() or not final.is_file() or not load_json(qa).get("ok"):
                print("mechanical QA and final.mp4 must pass before verify", file=sys.stderr)
                return EXIT_QA_FAILED
            if not acceptance.is_file() or not agent_review_brief.is_file():
                print(
                    "fresh AI acceptance is required: review/ai-acceptance.json",
                    file=sys.stderr,
                )
                return EXIT_BLOCKED
            stored_brief = load_json(agent_review_brief)
            style_decision = load_json(run_dir / "artifacts" / "style-decision.json")
            current_brief = build_agent_review_brief(
                run_dir,
                skin_id=str(style_decision.get("skin_id") or ""),
            )
            if stored_brief != current_brief:
                print(
                    "AI review brief is stale; rerun resume to rebuild current evidence",
                    file=sys.stderr,
                )
                return EXIT_BLOCKED
            review = load_json(acceptance)
            review_errors = validate_acceptance(
                review,
                brief=current_brief,
            )
            if review_errors:
                print(
                    "AI acceptance is invalid: " + "; ".join(review_errors),
                    file=sys.stderr,
                )
                return EXIT_BLOCKED
            fingerprint = canonical_json_sha256(
                {
                    "qa": file_fingerprint(qa),
                    "final": file_fingerprint(final),
                    "agent_review_brief": file_fingerprint(agent_review_brief),
                    "ai_acceptance": file_fingerprint(acceptance),
                }
            )
            set_stage(
                run_dir,
                state,
                "agent_review",
                "succeeded",
                exit_code=0,
                input_fingerprint=fingerprint,
                outputs=[acceptance, agent_review_brief, qa, final],
            )
            state["status"] = "READY"
            state["deliverable"] = file_fingerprint(final)
            save_state(run_dir, state)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOCKED
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"verify failed: {exc}", file=sys.stderr)
        return EXIT_SCHEMA
    print(f"READY: {final}")
    return EXIT_SUCCESS


def cleanup_candidates(run_dir: Path, mode: str) -> list[Path]:
    candidates: set[Path] = set()
    patterns_by_mode = {
        "delivery": (
            "work/cut/segments",
            "work/animations/*/frames",
            "work/animations/*/snapshots",
            "work/animations/*/renders",
            "work/animations/*/node_modules",
            "work/animations/*/.hyperframes",
            "work/**/attempts",
        ),
        "audit": (
            "work/animations/*/frames",
            "work/animations/*/renders",
            "work/animations/*/node_modules",
            "work/animations/*/.hyperframes",
            "work/**/attempts",
        ),
        "debug": (),
    }
    for pattern in patterns_by_mode[mode]:
        candidates.update(run_dir.glob(pattern))
    forbidden_names = {
        ".browser-profile",
        "browser-profile",
        "chrome-profile",
        "user-data-dir",
        "Cookies",
        "History",
        "Login Data",
    }
    for path in run_dir.rglob("*"):
        if path.name in forbidden_names:
            candidates.add(path)
    safe: list[Path] = []
    for path in candidates:
        try:
            path.resolve().relative_to(run_dir.resolve())
        except ValueError:
            continue
        if path.exists():
            safe.append(path)
    return sorted(set(safe), key=lambda item: (len(item.parts), str(item)), reverse=True)


def path_size(path: Path) -> int:
    if path.is_file() or path.is_symlink():
        return path.lstat().st_size
    return sum(item.lstat().st_size for item in path.rglob("*") if item.is_file() or item.is_symlink())


def cmd_clean(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir).resolve()
    if not state_path(run_dir).is_file():
        print(f"not an initialized run: {run_dir}", file=sys.stderr)
        return EXIT_SCHEMA
    candidates = cleanup_candidates(run_dir, args.mode)
    total = sum(path_size(path) for path in candidates)
    action = "WOULD_REMOVE" if not args.apply else "REMOVE"
    for path in candidates:
        print(f"{action} {path.relative_to(run_dir)}")
    print(f"files_or_dirs={len(candidates)} bytes={total} mode={args.mode}")
    if not args.apply:
        return EXIT_SUCCESS
    try:
        with RunLock(run_dir / "run.lock"):
            for path in candidates:
                if not path.exists() and not path.is_symlink():
                    continue
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            event(run_dir, "clean", "succeeded", mode=args.mode, removed_bytes=total)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_LOCKED
    return EXIT_SUCCESS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Duyi scripted-video-edit AIJianji orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check deterministic runtime capabilities")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=cmd_doctor)

    init = subparsers.add_parser(
        "init",
        help="initialize a run and stop before the complete AI editorial review",
    )
    init.add_argument("--input", required=True)
    init.add_argument("--asr", required=True)
    init.add_argument("--run-dir", required=True)
    init.add_argument("--speaker-lane", choices=("left", "right"), default="left")
    init.add_argument("--decode", choices=("full", "sample"), default="full")
    init.add_argument("--timeout", type=float, default=1800.0)
    init.set_defaults(handler=cmd_init)

    prepare_review = subparsers.add_parser(
        "prepare-review",
        help="validate the complete AI editorial plan and build the only human-review packet",
    )
    prepare_review.add_argument("run_dir")
    prepare_review.add_argument("--timeout", type=float, default=300.0)
    prepare_review.set_defaults(handler=cmd_prepare_review)

    lock_review = subparsers.add_parser(
        "lock-review",
        help="lock the user's one reviewed editorial decision and materialize downstream plans",
    )
    lock_review.add_argument("run_dir")
    lock_review.add_argument("--confirmation-note", required=True)
    lock_review.add_argument("--timeout", type=float, default=300.0)
    lock_review.set_defaults(handler=cmd_lock_review)

    resume = subparsers.add_parser("resume", help="resume from the earliest incomplete stage")
    resume.add_argument("run_dir")
    resume.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    resume.add_argument("--timeout", type=float, default=1800.0)
    resume.set_defaults(handler=cmd_resume)

    status = subparsers.add_parser("status", help="show machine state and blockers")
    status.add_argument("run_dir")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=cmd_status)

    verify = subparsers.add_parser(
        "verify",
        help="promote a mechanically and fresh-AI-lens approved run to READY",
    )
    verify.add_argument("run_dir")
    verify.set_defaults(handler=cmd_verify)

    clean = subparsers.add_parser("clean", help="preview or apply bounded intermediate cleanup")
    clean.add_argument("run_dir")
    clean.add_argument("--mode", choices=("delivery", "audit", "debug"), required=True)
    clean_mode = clean.add_mutually_exclusive_group()
    clean_mode.add_argument("--dry-run", action="store_true", help="explicit preview; also the default")
    clean_mode.add_argument("--apply", action="store_true", help="remove only the listed generated intermediates")
    clean.set_defaults(handler=cmd_clean)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        print("cancelled", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
