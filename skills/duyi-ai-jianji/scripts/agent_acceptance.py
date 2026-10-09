#!/usr/bin/env python3
"""Create and validate the fresh-AI-lens acceptance contract."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common import file_fingerprint
from contracts import PIPELINE_VERSION


CHECKS: tuple[tuple[str, str, str], ...] = (
    ("opening-complete", "片头紧凑进入完整第一句话且首声前无气口", "all"),
    ("asr-word-corrections", "明确的机器误听已纠正且没有改写真实口误", "all"),
    ("speech-fillers-zero", "全片听不到已识别的硬填充词", "all"),
    ("segment-entry-clean", "每个剪后句首无上一段或填充词尾巴且首字完整", "all"),
    ("speech-tail-complete", "句尾尾音完整且没有提前截字", "all"),
    ("caption-semantic-boundaries", "字幕语义完整且没有跨句错位", "all"),
    ("stage-fixed-left", "左上舞台位置固定", "all"),
    ("chapter-build-sequence", "栏目按竖线到英文到中文建立并常驻", "all"),
    ("first-layer-after-header", "首层内容在栏目建立后出现", "all"),
    ("anchored-fade-motion", "普通容器固定坐标短渐显", "all"),
    ("persistent-layer-stack", "新信息追加且旧信息没有整卡替换", "all"),
    ("progressive-item-timing", "并列项按口述逐项出现", "all"),
    ("type-specific-components", "不同语义使用对应版式", "all"),
    ("animation-not-caption-duplicate", "动画提炼结构而非重复字幕", "all"),
    ("caption-readability-font", "字幕清楚且没有字体回退或遮挡", "all"),
    ("fullscreen-transition-restraint", "全屏转场只用于真正升级", "all"),
    ("framing-adjustability", "画面可用于判断后续拍摄站位", "all"),
    ("semantic-card-meaning", "卡片含义精准对应当下原话", "all"),
    ("semantic-trigger-timing", "动画触发时机自然", "all"),
    ("semantic-no-spoiler", "没有提前展示未来信息", "all"),
    ("semantic-hold-relevance", "旧信息保留期间持续相关", "all"),
    ("white-wall-fusion-readability", "白墙版融合且清晰可读", "white-wall"),
    ("white-wall-transparent-stage", "白墙版为透明舞台与局部内容板", "white-wall"),
    ("card-size-semantic-fit", "小中卡与信息结构匹配且任何卡片宽度不超过画布33.4%", "all"),
    (
        "card-content-height-fit",
        "短内容卡片按内容自然收口，没有与信息量不匹配的大面积空底板",
        "all",
    ),
    (
        "spoken-expression-fidelity",
        "信息节点、顺序、人物与关系忠于真实口述，没有为了形式整齐而改写",
        "all",
    ),
    (
        "card-layout-grammar",
        "关系卡无右侧大块空白；3至4项铺满一行，5至12项按合同均衡换行",
        "all",
    ),
    (
        "stage-overflow-zero",
        "所有逐层增加后的卡片完整可见，没有截断、越界或用遮挡豁免隐藏问题",
        "all",
    ),
    (
        "speech-rhythm-natural",
        "口播紧凑但自然，局部节奏处理无机械感、音高异常、吞字或视听错位",
        "all",
    ),
)


def required_artifact_paths(run_dir: Path) -> dict[str, Path]:
    return {
        "source_media": Path(
            json.loads((run_dir / "run-state.json").read_text(encoding="utf-8"))["inputs"][
                "source"
            ]["path"]
        ),
        "corrected_transcript": run_dir / "artifacts" / "corrected-transcript.json",
        "asr_integrity": run_dir / "artifacts" / "asr-integrity.json",
        "cut_plan": run_dir / "review" / "cut-plan.refined.json",
        "acoustic_boundaries": run_dir / "review" / "acoustic-boundaries.json",
        "final": run_dir / "deliverable" / "final.mp4",
        "qa_report": run_dir / "qa" / "report.json",
        "contact_sheet": run_dir / "review" / "contact-sheet.jpg",
        "semantic_reveal_sheet": run_dir / "review" / "semantic-reveal-sheet.jpg",
        "layout_fit_report": run_dir / "review" / "layout-fit-report.json",
        "visual_direction": run_dir / "review" / "visual-direction.json",
        "animation_plan": run_dir / "review" / "animation-plan.json",
        "semantic_reveal_timeline": run_dir
        / "review"
        / "semantic-reveal-timeline.json",
        "semantic_reveal_audit": run_dir / "review" / "semantic-reveal.audit.json",
        "style_decision": run_dir / "artifacts" / "style-decision.json",
        "rhythm_plan": run_dir / "review" / "rhythm-plan.json",
        "rhythm_manifest": run_dir / "work" / "rhythm" / "rhythm-manifest.json",
    }


def expected_inputs(run_dir: Path) -> dict[str, dict[str, Any]]:
    paths = required_artifact_paths(run_dir)
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise ValueError(
            "agent acceptance evidence is incomplete: " + ", ".join(sorted(missing))
        )
    return {name: file_fingerprint(path) for name, path in paths.items()}


def build_brief(run_dir: Path, *, skin_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "pipeline_version": PIPELINE_VERSION,
        "policy": "fresh-ai-lens-acceptance",
        "skin_id": skin_id,
        "inputs": expected_inputs(run_dir),
        "checks": [
            {
                "id": check_id,
                "question": question,
                "applicability": applicability,
                "required_status": (
                    "not_applicable"
                    if applicability == "white-wall"
                    and skin_id != "white-wall-fusion-fixed"
                    else "passed"
                ),
            }
            for check_id, question, applicability in CHECKS
        ],
        "instructions": [
            "由没有本任务上下文的 AI 镜头连续观看当前 final.mp4。",
            "同时逐行检查 contact sheet、semantic reveal sheet、QA 与语义揭示证据。",
            "每项写 passed、failed 或 not_applicable，并给出具体可核对的 evidence。",
            "任一适用项 failed 时 decision 必须为 rejected，不得为了交付改成 passed。",
        ],
        "output": str((run_dir / "review" / "ai-acceptance.json").resolve()),
    }


def validate_acceptance(
    review: Any,
    *,
    brief: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(review, dict):
        return ["ai-acceptance.json must be a JSON object"]
    if review.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if review.get("pipeline_version") != PIPELINE_VERSION:
        errors.append("pipeline_version does not match the current Skill")
    if review.get("policy") != "fresh-ai-lens-acceptance":
        errors.append("policy must be fresh-ai-lens-acceptance")
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, dict):
        errors.append("reviewer must be an object")
    else:
        if reviewer.get("type") != "ai-agent":
            errors.append("reviewer.type must be ai-agent")
        if reviewer.get("context_mode") != "fresh":
            errors.append("reviewer.context_mode must be fresh")
        if not str(reviewer.get("reviewed_at") or "").strip():
            errors.append("reviewer.reviewed_at is required")
    if review.get("inputs") != brief.get("inputs"):
        errors.append("review inputs do not match the current video and evidence hashes")

    checks = review.get("checks")
    if not isinstance(checks, list):
        return errors + ["checks must be an array"]
    check_by_id: dict[str, dict[str, Any]] = {}
    for item in checks:
        if not isinstance(item, dict):
            errors.append("every check must be an object")
            continue
        check_id = str(item.get("id") or "")
        if not check_id or check_id in check_by_id:
            errors.append(f"duplicate or missing check id: {check_id!r}")
            continue
        check_by_id[check_id] = item
    expected_ids = {item["id"] for item in brief.get("checks", [])}
    unknown = sorted(set(check_by_id) - expected_ids)
    if unknown:
        errors.append("unknown checks: " + ", ".join(unknown))
    for expected in brief.get("checks", []):
        check_id = expected["id"]
        item = check_by_id.get(check_id)
        if item is None:
            errors.append(f"missing check: {check_id}")
            continue
        if item.get("status") != expected["required_status"]:
            errors.append(
                f"{check_id} must be {expected['required_status']}, "
                f"got {item.get('status')!r}"
            )
        if not str(item.get("evidence") or "").strip():
            errors.append(f"{check_id} requires concrete evidence")
    if review.get("decision") != "approved":
        errors.append("decision must be approved")
    return errors
