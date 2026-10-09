# 拆解质量标准

Read this before finalizing or manually improving a Douyin viral video breakdown. A working pipeline is not enough; the report must be useful as content-production evidence.

## Quality Bar

A qualified breakdown must answer:

1. Why does the viewer stop?
2. Why does the viewer continue?
3. Why does the viewer believe?
4. Why would the viewer comment, save, or share?
5. What can be migrated across topics, and what cannot?

## Required Distinctions

- Do not summarize the content. Extract the mechanism.
- Do not confuse public comments with proof of paid demand.
- Extract cross-topic structure slots when the user asks for reusable patterns, but do not generate cross-topic body copy.
- Describe the source expression as evidence only. Do not preserve or imitate it in user-facing edits.
- Do not cut timelines by equal duration when the transcript has clear argument turns.
- Do not replace source copy with summaries in node-level breakdowns. Each node must include the original copy and reusable mechanism; add a user-original mapping only when the user provides their own text.
- When the user asks for a V2 or deliverable-level breakdown, do not stop at node syntax. Use the layered standard in `layered-breakdown-v2.md`: business task, skeleton, transitions, flesh, and marketing/trust.

## Required Fields

For high-quality reports, include or manually add:

- `core_thesis`: The real thesis beneath the surface topic.
- `timeline_by_argument`: Time segments cut by argument turns.
- `source_expression_observation`: A descriptive record of the author's phrasing and rhythm, used only to explain the source rather than imitate it.
- `method_points[]`: Method points with original evidence, function, and migration condition.
- `node_breakdown[]`: For each script node, include original copy and reusable mechanism; optionally map the user's supplied original text.
- `argument_unit_breakdown[]`: For each principle or method point, break down claim, reason, example, objection handled, structural function, and viewer action inside the three-layer node.
- `layered_breakdown_v2`: For detailed copy anatomy, include business task layer, skeleton layer, transition layer, flesh layer, and marketing/trust layer.
- `proof_system`: Internal proof from the video, such as personal case, numbers, comparisons, screenshots, or tests.
- `retention_mechanism`: Why each section keeps people watching.
- `applicability_boundary`: Where the method works and where it should not be copied.
- `comment_sample_quality`: Whether visible comments are sufficient, weak, noisy, or mostly irrelevant.
- `visual_facts`: What keyframes actually show.
- `structure_slots`: Same-topic and cross-topic functional slots, with missing evidence marked `待补`.
- `risk_of_migration`: What would become misleading if copied directly.

## Timeline Rules

Prefer transcript anchors over duration buckets. Useful anchors include:

- 开头问题 / 结果承诺
- 提出方法数量或段落安排
- 第一 / 第二 / 第三 / 第四 / 第五
- 提前回应可能的反驳
- “比如 / 举个例子 / 我当时”
- “但是 / 真正的问题 / 限制条件”
- 提出即时练习
- 提出回看或收藏

If a report has fewer than one row per major argument turn, mark the timeline as too coarse.

## Three-Layer Node Rules

Every script node must be delivered in three layers:

| Layer | Requirement |
|---|---|
| 原文文案 | Paste the full original paragraph for this node when working with user-owned or authorized material. Do not summarize it. |
| 可迁移机制 | Extract the paragraph's functional role and variable slots without preserving the author's voice, rhythm, or sentence shell. |
| 用户原稿映射 | Only when the user supplies a spoken draft or original text, map those existing expressions into the slots. Otherwise list missing material and do not write body copy. |

The original-copy layer is not optional. If the source is third-party public content and the output cannot reproduce the full paragraph, cite the local transcript range and make the standard explicit: the actual working copy is the transcript paragraph, not a summary.

## Argument Unit Rules

Do not only name the principle. For every major principle, explain how it is argued.

Use this schema:

| Field | Question |
|---|---|
| Claim | What exactly is the principle? |
| Reason | Why does the author say it is true? |
| Example | What story, case, number, or comparison supports it? |
| Objection handled | What likely viewer objection does the author answer? |
| Structural function | What does this section do in the whole video? |
| Viewer action | What is the viewer supposed to do after hearing it? |

For example, when a method requires a prerequisite, identify how the author supports that prerequisite through reasons, examples, objections, and boundaries. Do not reduce the argument to the prerequisite sentence alone.

## Hook Rules

Hook can have multiple labels. Avoid forcing a single type.

Examples:

- 结果前置 + 清单承诺
- 反常识 + 冒犯式归因
- 身份召唤 + 痛点直戳
- 案例开场 + 结果证明

A single opening may combine “结果前置 + 清单承诺 + 反常识归因”. Assign each label only when the transcript or visual evidence supports it.

## Structure Mapping Rules

Structure mapping may preserve only the functional sequence, for example:

- Logical structure: result -> strong judgment -> standards -> proof -> boundary -> test.

Do not preserve the source author's expression style, pressure, catchphrases, rhythm, or sentence shell. Do not create a complete migrated paragraph from a topic.

When user-owned text exists, map it with this table:

| 来源功能槽位 | 用户原稿片段 | 初步调整建议 | 待补证据 |
|---|---|---|---|
| | | | |

Without user-owned text, return only the slots, evidence requirements, and missing-material list.

## Comment Evidence Rules

If visible comments are fewer than 20, mark them as weak evidence unless the user only asks for comment clues.

Classify comments as:

- 共鸣：agreeing with the thesis.
- 追问：asking how to do it.
- 复述：repeating or compressing the method.
- 争议：challenging the claim.
- 噪音/无关：ads, group invites, vague praise, unrelated chatter.

## Visual Evidence Rules

Keyframes are enough for factual visual claims such as:

-真人近景口播
- 字幕 style and placement
- fixed title card or visual anchor
- indoor/outdoor setting
- whether rhythm comes from cuts, gestures, subtitles, props, or screenshots

If the frames are not inspected, write “需结合关键帧确认”. If the frames are inspected, replace that with concrete visual facts.
