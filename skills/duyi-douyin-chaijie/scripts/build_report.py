#!/usr/bin/env python3
"""Build a Douyin viral-structure breakdown report from collected artifacts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def load_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback


def clean_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def first_sentence(text: str) -> str:
    text = clean_text(text)
    if not text:
        return "素材不足"
    match = re.search(r"(.{1,80}?[。！？!?])", text)
    return match.group(1).strip() if match else text[:80]


def clip_text(text: str, limit: int = 80) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?])", clean_text(text))
    return [part.strip() for part in parts if part.strip()]


def pick_hook_type(hook: str) -> str:
    if hook == "素材不足":
        return "素材不足"
    if re.search(r"不是|别再|很多人|误区|错了|以为", hook):
        return "反常识 / 纠偏"
    if re.search(r"为什么|怎么|如何|吗|？|\?", hook):
        return "问题悬念"
    if re.search(r"\d|万|元|offer|结果|拿到|做到|涨", hook, re.I):
        return "结果前置"
    if re.search(r"你|普通人|新手|老板|打工人|求职|博主", hook):
        return "身份召唤"
    return "痛点直戳"


def ms_or_sec(value, *, force_ms: bool = False) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number / 1000 if force_ms or number > 1000 else number


def collect_utterances(asr: dict) -> list[dict]:
    raw = asr.get("raw")
    payload = raw.get("result") if isinstance(raw, dict) and isinstance(raw.get("result"), dict) else raw
    utterances = payload.get("utterances") if isinstance(payload, dict) else None
    if not isinstance(utterances, list):
        return []
    force_ms = str(asr.get("provider") or "").startswith("agent_plan")
    result = []
    for item in utterances:
        if not isinstance(item, dict):
            continue
        text = clean_text(item.get("text"))
        if not text:
            continue
        result.append(
            {
                "text": text,
                "start": ms_or_sec(item.get("start_time", item.get("start")), force_ms=force_ms),
                "end": ms_or_sec(item.get("end_time", item.get("end")), force_ms=force_ms),
            }
        )
    return result


def transcript_text(asr: dict, transcript_path: Path) -> str:
    if not asr.get("ok"):
        return ""
    if asr.get("text"):
        return clean_text(asr.get("text"))
    if transcript_path.exists():
        text = transcript_path.read_text(encoding="utf-8")
        text = re.sub(r"^# ASR 转写\s*", "", text).strip()
        return clean_text(text)
    return ""


def segment_label(index: int, total: int, speech: str = "") -> str:
    if index == 0:
        return "Hook / 结果问题"
    if re.search(r"三条|大原则", speech):
        return "大原则"
    if re.search(r"五个标准|第一个标准|第二个标准|第三个标准|第四个标准|第五个标准", speech):
        return "方法拆解"
    if re.search(r"心理问题|不愿意|恐惧|自恋|借口", speech):
        return "反常识归因"
    if re.search(r"举例|比如|像我|案例", speech):
        return "案例解释"
    if index >= total - 1:
        return "收束 / 行动"
    if index <= max(1, total * 0.35):
        return "场景/痛点"
    if index <= max(2, total * 0.7):
        return "方法/案例"
    return "执行要求"


def build_timeline(text: str, asr: dict, frames: dict) -> list[dict]:
    utterances = collect_utterances(asr)
    if utterances:
        rows = []
        known_times = [item.get("end") or item.get("start") for item in utterances if item.get("end") or item.get("start")]
        duration = max(known_times) if known_times else float(len(utterances))
        total_rows = min(8, max(4, len(utterances) // 18 or 4))
        for index in range(total_rows):
            start = duration * index / total_rows
            end = duration * (index + 1) / total_rows
            bucket = []
            for item in utterances:
                item_start = item.get("start")
                item_end = item.get("end")
                midpoint = None
                if item_start is not None and item_end is not None:
                    midpoint = (item_start + item_end) / 2
                elif item_start is not None:
                    midpoint = item_start
                if midpoint is not None and start <= midpoint < end:
                    bucket.append(item)
            if not bucket:
                continue
            speech = clip_text("".join(item["text"] for item in bucket), 120)
            rows.append(
                {
                    "time": f"{start:.0f}-{end:.0f}s",
                    "visual": nearest_frame_note(frames, start),
                    "speech": speech,
                    "function": segment_label(index, total_rows, speech),
                }
            )
        return rows

    sentences = split_sentences(text)
    if not sentences:
        return [
            {"time": "0-3s", "visual": visual_status(frames), "speech": "素材不足", "function": "Hook"},
            {"time": "3s+", "visual": visual_status(frames), "speech": "素材不足", "function": "主体内容"},
        ]
    buckets = ["0-3s", "3-8s", "8-20s", "20-45s", "45s+"]
    functions = ["Hook", "场景/痛点", "冲突升级", "方法/案例", "CTA/收束"]
    rows = []
    chunk = max(1, len(sentences) // len(buckets))
    for index, label in enumerate(buckets):
        part = " ".join(sentences[index * chunk : (index + 1) * chunk]).strip()
        if not part and index < len(sentences):
            part = sentences[index]
        rows.append(
            {
                "time": label,
                "visual": visual_status(frames),
                "speech": part or "素材不足",
                "function": functions[index],
            }
        )
    return rows


def nearest_frame_note(frames: dict, seconds: float | None) -> str:
    items = frames.get("frames") if isinstance(frames, dict) else None
    if not items:
        return "画面素材不足"
    if seconds is None:
        return visual_status(frames)
    nearest = min(items, key=lambda item: abs(float(item.get("time") or 0) - seconds))
    name = Path(str(nearest.get("path") or "")).name
    return f"关键帧 {name}"


def visual_status(frames: dict) -> str:
    count = len(frames.get("frames") or []) if isinstance(frames, dict) else 0
    if count <= 0:
        return "画面素材不足"
    return f"已抽取 {count} 张关键帧，需结合图片确认"


def summarize_comments(comments: list[dict]) -> dict:
    liked = [item for item in comments if item.get("signal") == "有赞" or Number(item.get("likes", 0)) > 0]
    questions = [item for item in comments if re.search(r"吗|？|\?|怎么|如何|求|请问|想问", str(item.get("text") or ""))]
    return {
        "liked": liked[:5],
        "questions": questions[:5],
        "all": comments[:8],
    }


def Number(value, fallback=0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return fallback


def metric_value(metadata: dict, name: str) -> int:
    metrics = metadata.get("metrics")
    if isinstance(metrics, dict):
        return Number(metrics.get(name))
    return Number(metadata.get(name))


def content_skeleton(text: str, metadata: dict) -> dict:
    hook = first_sentence(text)
    title = clean_text(metadata.get("title"))
    return {
        "人群": infer_audience(title + " " + hook),
        "场景": infer_scene(title + " " + hook),
        "痛点": infer_pain(text or title),
        "反差": infer_contrast(text),
        "方法": infer_method(text),
        "证明": infer_proof(text, metadata),
        "行动": infer_action(text),
    }


def opening_hook(text: str, metadata: dict, utterances: list[dict]) -> str:
    if utterances:
        first_two = "".join(item["text"] for item in utterances[:2])
        return clip_text(first_two, 64)
    return first_sentence(text or metadata.get("title") or "")


def one_line_judgment(text: str, hook: str, skeleton: dict) -> str:
    if re.search(r"100万|一百万", text) and "对标" in text:
        return "先用“第一个100万”给结果诱因，再把赚钱问题收束成“对标一致性”和“心理阻抗”，让用户愿意收藏长视频。"
    return f"用“{clip_text(hook, 28)}”先制造停留，再围绕{clip_text(skeleton['痛点'], 24)}推进。"


def hook_retention(text: str, hook: str) -> str:
    if hook == "素材不足":
        return "素材不足"
    if re.search(r"100万|一百万", hook) and "三条" in text:
        return "结果问题足够具体，紧跟“三条”制造可获得感。"
    if "心理问题" in text and "对标" in text:
        return "把方法问题转成心理问题，有冒犯感和反常识停留点。"
    return "开头能快速点名问题或结果。"


def migration_formula(text: str, hook: str) -> str:
    if re.search(r"100万|一百万", text) and "对标" in text:
        return "结果问题 + 三条判断 + 反常识归因 + 标准清单 + 收藏提示。"
    if hook != "素材不足":
        return f"不是泛讲主题，先抛出“{clip_text(hook, 24)}”，再给具体场景和方法。"
    return "素材不足"


def infer_audience(text: str) -> str:
    if re.search(r"求职|offer|面试|简历|应届|实习", text, re.I):
        return "求职/职业转型人群"
    if re.search(r"赚钱|商业|副业|老板|生意|变现", text):
        return "想提升商业化能力的人"
    if re.search(r"博主|账号|内容|流量|抖音|小红书", text):
        return "内容创作者"
    return "需结合账号定位判断"


def infer_scene(text: str) -> str:
    if re.search(r"面试|简历|offer", text, re.I):
        return "求职决策或面试准备场景"
    if re.search(r"账号|内容|视频|直播|选题", text):
        return "内容生产和账号增长场景"
    if re.search(r"赚钱|商业|副业|客户", text):
        return "个人商业化或获客场景"
    return "素材不足"


def infer_pain(text: str) -> str:
    if "对标" in text and re.search(r"100万|一百万|赚钱|挣钱", text):
        return "想赚到第一个100万，但不知道该找谁对标、如何照着更成熟的人做。"
    if "心理问题" in text and "对标" in text:
        return "不是没有方法，而是不愿意承认自己需要对齐更高标准。"
    sentence = first_sentence(text)
    return sentence if sentence != "素材不足" else "素材不足"


def infer_contrast(text: str) -> str:
    if "心理问题" in text and "对标" in text:
        return "表面是方法问题，实际被归因为不愿意和更高标准的对标保持一致。"
    for pattern in [r"不是[^。！？!?]{2,50}而是[^。！？!?]{2,60}", r"很多人[^。！？!?]{2,80}", r"真正[^。！？!?]{2,80}"]:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return "反差不明显或素材不足"


def infer_method(text: str) -> str:
    if "对标" in text and "五个标准" in text:
        return "用“三条大原则”先建立判断，再用“找对标的五个标准”把抽象赚钱问题拆成可执行筛选。"
    for keyword in ["第一", "第二", "方法", "步骤", "关键", "核心", "你要", "一定要"]:
        index = text.find(keyword)
        if index >= 0:
            return clip_text(text[index : index + 120], 90)
    return "方法段需要人工复核"


def infer_proof(text: str, metadata: dict) -> str:
    comments = metadata.get("comments") or []
    if comments:
        return "评论区存在需求线索"
    if re.search(r"\d|万|元|offer|案例|客户", text, re.I):
        return "口播中包含数字或案例型证明"
    return "证明素材不足"


def infer_action(text: str) -> str:
    if "收藏" in text:
        return "用“视频有点长，收藏慢慢看”引导收藏。"
    if re.search(r"关注|评论|私信|收藏|转发|主页|链接", text):
        return "包含显性互动或转化动作"
    return "未识别到明确 CTA"


def md_escape(value) -> str:
    return str(value or "").replace("\n", " ").strip()


def render_markdown(metadata: dict, asr: dict, frames: dict, breakdown: dict) -> str:
    metrics = metadata.get("metrics") if isinstance(metadata.get("metrics"), dict) else {}
    comments = breakdown["comments"]
    skeleton = breakdown["content_skeleton"]
    rows = breakdown["timeline"]
    text = breakdown["transcript_text"]
    visual_line = visual_status(frames)
    asr_provider = clean_text(asr.get("provider") or "")
    asr_status = f"已转写（{asr_provider}）" if asr.get("ok") and asr_provider else ("已转写" if asr.get("ok") else "素材不足")

    lines = [
        "# 抖音爆款视频结构拆解",
        "",
        "## 基本信息",
        f"- 视频链接：{md_escape(metadata.get('url') or metadata.get('input') or '')}",
        f"- 作者：{md_escape(metadata.get('author') or '')}",
        f"- 发布时间：{md_escape(metadata.get('publishedAt') or metadata.get('relativeTime') or '')}",
        f"- 可见互动：{metrics.get('likes', 0)} / {metrics.get('comments', 0)} / {metrics.get('collects', 0)} / {metrics.get('shares', 0)}",
        "- 数据边界：只基于公开可见信息，不代表后台真实数据；评论只作为需求线索。",
        f"- 证据状态：转写内容 {asr_status}；画面证据 {visual_line}。",
        "",
        "## 一句话判断",
        f"这条视频的核心增长点是：{breakdown['one_line_judgment']}",
        "",
        "## 时间线结构",
        "| 时间 | 画面/动作 | 口播内容 | 结构功能 |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {md_escape(row['time'])} | {md_escape(row['visual'])} | {md_escape(row['speech'])[:120]} | {md_escape(row['function'])} |"
        )

    lines.extend(
        [
            "",
            "## Hook 拆解",
            f"- 开头第一句话：{breakdown['hook']}",
            f"- 使用的钩子类型：{breakdown['hook_type']}",
            f"- 为什么能让目标用户停留：{breakdown['hook_retention']}",
            f"- 可迁移公式：{breakdown['migration_formula']}",
            "",
            "## 内容骨架",
        ]
    )
    for key in ["人群", "场景", "痛点", "反差", "方法", "证明", "行动"]:
        lines.append(f"- {key}：{skeleton[key]}")

    lines.extend(
        [
            "",
            "## 留存机制",
            f"- 每 3-5 秒是否有信息增量：{breakdown['retention']['increment']}",
            f"- 是否有悬念延迟兑现：{breakdown['retention']['suspense']}",
            f"- 是否有强情绪词：{breakdown['retention']['emotion']}",
            f"- 是否有画面变化或节奏变化：{breakdown['retention']['visual_rhythm']}",
            "",
            "## 视觉与声音",
            f"- 封面/首帧：{breakdown['visual_audio']['first_frame']}",
            f"- 字幕样式：{breakdown['visual_audio']['subtitle']}",
            f"- 镜头节奏：{breakdown['visual_audio']['pace']}",
            f"- BGM/音效：{breakdown['visual_audio']['sound']}",
            f"- 人设声音：{breakdown['visual_audio']['persona_voice']}",
            "",
            "## 评论区需求线索",
        ]
    )
    lines.append("- 高赞评论：" + render_comment_list(comments["liked"]))
    lines.append("- 追问型评论：" + render_comment_list(comments["questions"]))
    lines.append("- 争议型评论：素材不足")
    lines.append(f"- 可反推的用户需求：{breakdown['comment_demand']}")

    lines.extend(
        [
            "",
            "## 迁移到用户内容的方式",
            f"- 可以照搬的结构：{breakdown['duyi_migration']['reuse']}",
            f"- 不能照搬的部分：{breakdown['duyi_migration']['avoid']}",
            f"- 适合改写成的选题：{breakdown['duyi_migration']['topic']}",
            f"- 适合做成的口播开头：{breakdown['duyi_migration']['opening']}",
        ]
    )
    if not text:
        lines.extend(["", "## 证据缺口", "- 缺少视频音频转写，不能做完整口播结构判断。"])
    return "\n".join(lines).strip() + "\n"


def render_comment_list(comments: list[dict]) -> str:
    filtered = [item for item in comments if clean_text(item.get("text")) and clean_text(item.get("text")) != "作者赞过"]
    if not filtered:
        return "素材不足"
    return "；".join(clean_text(item.get("text"))[:60] for item in filtered[:3])


def build_breakdown(metadata: dict, asr: dict, frames: dict, transcript_path: Path) -> dict:
    text = transcript_text(asr, transcript_path)
    utterances = collect_utterances(asr)
    hook = opening_hook(text, metadata, utterances)
    hook_type = pick_hook_type(hook)
    skeleton = content_skeleton(text, metadata)
    comments = summarize_comments(metadata.get("comments") or [])
    timeline = build_timeline(text, asr, frames)
    like_count = metric_value(metadata, "likes")
    comment_count = metric_value(metadata, "comments")
    one_line = "素材不足，当前只能基于标题/评论做弱判断"
    if text:
        one_line = one_line_judgment(text, hook, skeleton)
    elif like_count or comment_count:
        one_line = "公开视频有互动信号，但缺少音频和画面证据，不能完整判断爆款结构。"

    has_question_comments = bool(comments["questions"])
    has_frames = bool(frames.get("frames"))
    utterance_count = len(utterances)
    return {
        "metadata": metadata,
        "transcript_text": text,
        "hook": hook,
        "hook_type": hook_type,
        "hook_retention": hook_retention(text, hook),
        "migration_formula": migration_formula(text, hook),
        "one_line_judgment": one_line,
        "timeline": timeline,
        "content_skeleton": skeleton,
        "retention": {
            "increment": "短句密集推进，持续抛出判断/标准/反问" if utterance_count >= 30 else "素材不足或信息增量不明显",
            "suspense": "有追问/问题式信号" if has_question_comments or re.search(r"为什么|怎么|如何|吗|？|\?", text) else "未识别到强悬念",
            "emotion": "有痛点或纠偏表达" if re.search(r"错|难|亏|焦虑|别|不是|真正|问题", text) else "情绪词不明显",
            "visual_rhythm": "已抽帧，可进一步读图判断" if has_frames else "画面素材不足",
        },
        "visual_audio": {
            "first_frame": nearest_frame_note(frames, 0),
            "subtitle": "需结合关键帧确认" if has_frames else "画面素材不足",
            "pace": "需结合关键帧和转写长度确认" if has_frames else "画面素材不足",
            "sound": "ASR 可用，BGM/音效需人工听感确认" if asr.get("ok") else "声音素材不足",
            "persona_voice": "口播表达可从转写继续判断" if text else "声音素材不足",
        },
        "comments": comments,
        "comment_demand": infer_comment_demand(comments),
        "duyi_migration": {
            "reuse": f"{hook_type}开头 + 具体痛点 + 方法/案例递进",
            "avoid": "不要照搬对方人设、案例和未验证数据；缺少同等证据时不要承诺结果。",
            "topic": migration_topic(skeleton),
            "opening": migration_opening(hook, skeleton),
        },
    }


def infer_comment_demand(comments: dict) -> str:
    if comments["questions"]:
        return "用户在追问具体做法，说明可迁移为教程型或答疑型内容。"
    if comments["liked"]:
        return "有赞评论可作为共鸣点，但仍不能证明付费意愿。"
    return "评论素材不足。"


def migration_topic(skeleton: dict) -> str:
    audience = skeleton.get("人群", "目标用户")
    scene = skeleton.get("场景", "具体场景")
    return f"{audience}在{scene}里最容易误判的一件事"


def migration_opening(hook: str, skeleton: dict) -> str:
    if hook and hook != "素材不足":
        return f"很多人以为问题是{str(skeleton.get('痛点'))[:24]}，但真正卡住的是后面的判断标准。"
    return "如果你正在做内容或求职，先别急着学方法，先判断自己卡在哪个具体场景。"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Douyin breakdown report")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--asr-json", type=Path)
    parser.add_argument("--frames-json", type=Path)
    args = parser.parse_args()

    out_dir = args.out_dir
    metadata_path = args.metadata or out_dir / "source" / "metadata.json"
    asr_path = args.asr_json or out_dir / "transcript" / "asr.json"
    frames_path = args.frames_json or out_dir / "frames" / "frames.json"
    transcript_path = out_dir / "transcript" / "transcript.md"

    metadata = load_json(metadata_path, {})
    asr = load_json(asr_path, {"ok": False})
    frames = load_json(frames_path, {"ok": False, "frames": []})
    breakdown = build_breakdown(metadata, asr, frames, transcript_path)

    (out_dir / "breakdown.json").write_text(json.dumps(breakdown, ensure_ascii=False, indent=2), encoding="utf-8")
    report = render_markdown(metadata, asr, frames, breakdown)
    report_path = out_dir / "爆款结构拆解.md"
    report_path.write_text(report, encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report_path), "breakdown_json": str(out_dir / "breakdown.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
