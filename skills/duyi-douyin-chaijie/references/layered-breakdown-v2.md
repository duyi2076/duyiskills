# V2 层级式短视频文案拆解标准

Use this reference when the user wants a detailed, deliverable short-video copy breakdown rather than a summary or simple timeline.

## Core Principle

A strong short-video breakdown is not only “what did the author say”. It must explain why the copy works, how each layer pushes the viewer forward, and how another topic can reuse the mechanism.

V2 uses five layers:

1. 业务任务层：用户是谁，遇到什么问题，有什么需求或情绪，想完成什么任务，视频给了什么解决方案。
2. 骨架推动层：整条视频如何从开头推到结尾，观点如何被论证，用户如何被一步步带到行动。
3. 衔接层：开头、转场、承接、反驳、边界、结尾如何处理，让观众不断往下看。
4. 血肉填充层：每个骨架节点如何用案例、数字、口语、反问、类比、冒犯、边界来填充。
5. 营销可信层：视频如何让观点显得可信、可执行、有压力、有收藏价值、有购买或转化想象。

## Required Output Shape

Every V2 breakdown should include:

- `coverage_statement`: whether the breakdown covers the full transcript, selected segments, or only a sampled section.
- `layer_1_business_task`: user, problem, emotion, job-to-be-done, promised solution.
- `layer_2_skeleton`: argument map from hook to ending.
- `layer_3_transitions`: hook, transitions, objection handling, ending design.
- `layer_4_flesh`: node-by-node analysis with original copy, attribution, reusable syntax, migration direction.
- `layer_5_marketing_trust`: proof, credibility, retention, collect/share/comment triggers, conversion imagination.
- `source_to_user_mapping`: map source mechanisms onto the user's supplied spoken draft or original text; otherwise return structure slots and missing materials.
- `migration_boundary`: what can be copied and what must be rebuilt with new evidence.

## Three-Part Evidence Rule

For each important node, include three things:

| Part | Requirement |
|---|---|
| 原文 | Put the corresponding source copy in the node, or clearly state the source transcript range when full reproduction is not allowed. Do not use a summary as the original-copy layer. |
| 归因 | Explain why this sentence or paragraph works in the video. Name the structural function, viewer psychology, and argument role. |
| 可迁移方向 | Give a reusable syntax or direction that can be applied to another topic without copying surface words. |

## Granularity Rule

Do not default to word-by-word annotation.

Use this standard:

- 全文覆盖：all major transcript paragraphs are represented.
- 逐段拆解：each functional paragraph has original copy, attribution, and migration direction.
- 关键句逐句语法化：sentences that carry hook, claim, proof, transition, objection handling, boundary, or CTA must be converted into reusable syntax.

Only do literal word-by-word annotation when the user asks for phrase-level analysis of the source or initial polishing of their own text.

## Source-to-User Mapping Rule

This skill does not generate a complete imitation or publish-ready script from a topic.

When the user supplies a spoken draft or original text, map only that material into the selected functional sequence:

1. identify the source structure slots;
2. locate the user's existing expressions and evidence for each slot;
3. suggest initial movement, deletion, or connection without inventing new experiences or claims;
4. mark empty slots as `待补`.

If the user has not supplied their own expression, stop at:

- source mechanism;
- structure slots;
- evidence requirements;
- missing-material list.

Required shape when user-owned text exists:

| 来源结构槽位 | 用户原稿片段 | 初步调整建议 | 待补证据 |
|---|---|---|---|
| | | | |

Do not preserve the source author's voice, rhythm, catchphrases, pressure, or sentence shells. Reuse only the functional relationship between slots.

## Layer 1: 业务任务层

Answer:

- 用户是谁？
- 用户遇到了什么现实问题？
- 用户表层需求是什么？
- 用户深层情绪是什么？
- 用户想完成什么任务？
- 视频给出的解决方案是什么？
- 这条解决方案的行动门槛是什么？

Bad:

> 用户想赚钱，作者教他找对标。

Good:

> 用户不是抽象地“想赚钱”，而是想用更短路径拿到第一桶金，同时不愿承认自己需要先模仿一个已经被市场验证的人。视频的解决方案不是“找对标”这个词，而是把找对标压成五条可执行筛选标准，并用闭卷考试检验用户是否真的研究过对标。

## Layer 2: 骨架推动层

Map the whole video as a sequence of pressure:

1. 结果钩子：先给用户想要的结果。
2. 强判断：把复杂问题压成做与不做。
3. 大原则：用冒犯式归因制造停留。
4. 小原则：给出可执行标准。
5. 案例证明：用个人经历证明标准不是空话。
6. 借口切断：禁止讨论资源、偏好、现有条件。
7. 适用边界：告诉用户哪里能抄，哪里不能抄。
8. 闭卷考试：把观看者从“我懂了”逼到“我能不能写出来”。

## Layer 3: 衔接层

Look for bridge sentences:

- Hook bridge: “来吧，就三条。”
- Objection bridge: “先别急着喷我啊。”
- Section bridge: “下面说第二条标准。”
- Proof bridge: “那我的第一桶金怎么赚呢？”
- Boundary bridge: “那这五个标准叠加到一块呢。”
- Test bridge: “那有人说我就想当第一个成功案例，行不行？”
- Ending bridge: “那绕不过去又搞不清楚怎么办呢？”

For each bridge, explain what it connects and why it prevents the viewer from leaving.

## Layer 4: 血肉填充层

For each node, capture:

- 原文：source copy for the node.
- 骨架功能：claim, reason, example, objection, boundary, CTA.
- 填充方式：number, personal story, contrast, rhetorical question, ridicule, concrete task, scene, time cost, money amount.
- 归因：why this filling makes the skeleton believable or emotionally forceful.
- 可迁移机制：functional role and variable slots, without copying the author's voice or sentence shell.
- 迁移方向：what other topics can reuse it.

## Layer 5: 营销可信层

Analyze how the video sells the idea without necessarily selling a product:

- 结果承诺：what result is placed in front.
- 难度降维：how the author makes the path look simple enough to try.
- 门槛抬高：how the author prevents low-quality copying.
- 自我筛选：how the viewer is made to judge themselves.
- 可信证明：numbers, personal case, operational details, boundary statements.
- 收藏理由：why the viewer might need to rewatch.
- 评论理由：what the viewer may want to argue, ask, confess, or defend.
- 转化想象：if this author later sells a course, consulting, community, or template, why this video prepares trust.

## Final Judgment

A V2 breakdown is qualified when a future agent can:

1. See the full business task behind the video.
2. Reconstruct the argument skeleton.
3. Identify every transition function.
4. Map the functional mechanism onto the user's supplied expression when available.
5. Know which structure slots and evidence are still missing.
