# 验收标准

## 自动门禁

- 最终视频可完整解码。
- `asr-integrity.json` 必须确认输入来自豆包 Agent Plan 的 `volc.seedasr.sauc.duration`，并绑定当前源视频、原始 ASR、标准化逐字稿和 preflight；Whisper、mlx-whisper 或其他替代 ASR 一律失败；非空词不得被静默丢弃，逐词时间必须有效、有序且位于媒体范围内。
- `corrected-transcript.json` 必须绑定当前标准化 ASR 和当前 `asr-corrections.json`；所有下游阶段统一使用纠正后的逐字稿。
- `editorial-review.md/json` 必须在用户介入前同时完成删除、ASR 纠错、说话者原话辨别、完整句和最终字幕断句；每条 cue 必须通过真实字体宽度、自然起止词和自适应节奏预计时长门禁。`3.8s` 是优选，预计处理后 `5.5s` 是上限，不允许把决定或校验拆成多轮审批。
- `rhythm-plan.json` 与 `rhythm-manifest.json` 必须绑定当前安全裁切、节奏前时间轴和最终节奏基底；先压缩长停顿，只有证据充分的慢语速单元才允许局部加速，最高 `1.15×`，英文、数字和样本过短单元不得自动加速语音。
- 自适应节奏完成后必须重映射全部词、字幕和动画触发点；最终 cue 不得超过 `5.5s`，不得因节奏处理吞字、截尾音或造成字幕与画面错位。
- `locked-editorial-master.json` 必须声明 `single-human-confirmed-editorial-master`、`user_confirmed=true` 和 `review_count=1`。
- `asr-corrections.json`、`corrected-transcript.json`、`cut-plan.json`、`caption-units.json`、`semantic-map.json` 必须全部绑定当前 `locked_text_master_sha256`；锁定前或哈希不一致时禁止进入剪辑。
- ASR 纠错只能是已批准的高置信词级机器误听修正；不得用于改写说话者真实口误或整句表达。复核后仍不唯一的词必须原样保留并记录到 `preserved_uncertain`，不得卡死整条视频。
- 16:9 横屏成片最低为 `1920×1080`；输入高于 1080P 时保留输入分辨率。横竖方向和帧率与输入一致。
- 字幕字体和动画字体均来自 Skill 内嵌文件，无 fallback 日志。
- 透明动画使用 alpha 像素格式。
- HyperFrames `check` 无错误。
- 全片只允许一个 `skin_id` 和一个 `paint_tokens_sha256`；每个 overlay 必须与整片 `style-decision.json` 一致。
- 默认深色皮肤卡片必须使用 `#0A141B / 0.82`；其他底色或不透明度视为合同不匹配。
- 白墙融合皮肤使用透明舞台、带轻浅色轮廓的 `#17212B` 自由文字、`#0A141B / 0.82` 局部内容板和 `#F3F5F7` 板内主文字；轮廓用于跨过深色人物时保持可读，不形成底板。
- 动画中文主字体为 Bold（700），不得误用字幕的 Black（900）。
- 路径卡头只有 kicker 与标题；对比卡有语义 emoji；公式卡按主项/关系符/结论分色。
- 每个视觉 state 都声明 `fidelity_mode/relation_layout/layout_reason/card_size/content_structure/size_reason`；小/中两档宽度分别为 `373/427 px`，中卡为默认且是画面 `33.4%` 最大宽度。
- 2–4 个流程节点在一行中铺满中卡；3–4 个普通并列节点等宽；5–8 项按 `3+2 / 3+3 / 4+3 / 4+4` 换行；9–12 个同组短节点按 `4+4+1 / 4+4+2 / 4+4+3 / 4+4+4` 使用一个复合卡；13 项以上按语义拆章。
- 卡片高度由真实内容、字体行高、节点行数和内边距生成；短标题或一句短观点不得出现与信息量不匹配的大面积空底板。
- 卡片节点、人物、顺序和关系必须忠于真实口述；禁止为了形式逻辑整齐而合并、替换、重排或补写。
- 所有 overlay 画布为 `2560×1440`，布局为 `fixed-left` 或 `fullscreen`。
- 普通舞台 content bounds 固定在左上参考区域。
- 卡片底板必须使用当前皮肤的半透明内容面板；`panel_mode=none` 不得通过验收。
- `animation-plan` 只含 `semantic-stage`，字体与皮肤只有一套。
- overlay 必须声明 `information_model=persistent-layer-stack`。
- overlay 必须声明 `motion_model=anchored-opacity`。
- overlay 必须声明 `semantic_timing_model=exact-spoken-reveal`。
- overlay 必须声明 `component_skin=type-specific-reference`。
- 普通卡不得含 `x/y/scale` 入场；栏目竖线除外。
- `thesis/quote/comparison/formula/path/chat/relation` 必须保持各自版式，禁止万能黑框。
- 每章估算层高不得超过模板坐标 `690 px`；每个动画项目必须生成与当前 HTML 哈希绑定的 `layout-check.json`，HyperFrames 的 `container_overflow` 必须为 0。
- `container_overflow` 触发 AI 自动重排而不是继续渲染或请求用户审批；最多三轮不同计划，禁止使用 `data-layout-allow-occlusion/data-layout-allow-overflow` 掩盖截断。
- `semantic-reveal-timeline.json` 必须完整覆盖每个 state、item 和 formula part。
- 每条揭示事件必须绑定连续精确原话、实际渲染触发词、完整显示词和章节保留终点。
- 触发点必须位于原话证据范围内，且不得早于 `earliest_allowed_word_id`。
- `spoiler_check.passed` 必须为真；公式 parts 必须有独立触发词并按口述顺序出现。
- 完整显示后至少保留可读时间：state `1.0s`、item `0.75s`、formula part `0.60s`。
- `cut-plan.audit.json` 与 `caption-units.audit.json` 的保留硬填充词数量都必须为 0。
- `acoustic-boundaries.json` 必须使用 `asr-plus-silero-vad-plus-energy`，记录音轨到媒体时间轴的偏移；每个入口必须声明 `entry_context/entry_strategy/speech_onset_seconds/headroom_seconds`，不得使用统一 `80ms`。填充词与下一字无静音时允许 `continuous-speech-zero-cross-splice`，但只能在 token 交界前 `4ms` 至后 `2ms` 的窗口内微切，并使用不超过 `4ms` 的淡入。
- 整片开篇不得在首个有效语音前留下可闻静音、吸气或准备音；删除填充词后的入口不得带回填充词尾巴；首字起音必须完整。
- `caption-units.json` 必须按原顺序恰好覆盖每个剪后保留词一次；不得漏词、重叠、倒序或未批准。每个 cue 必须携带稳定 `sentence_id/full_sentence_text`，同句 cue 拼接必须还原完整句。
- 唯一确认稿中的 cue 必须用最终内嵌字体、实际字号和交付分辨率进行像素测宽，同时通过全角单位上限；不能只靠 ASR 停顿或固定字数拆分。
- 每条字幕必须且只能绑定一个完整语义单元；相邻语义单元即使停顿小于 `0.42s` 也不得合并。

## 无上下文 AI 镜头看样

执行代理必须启动一个不继承当前任务上下文的独立审查实例，连续观看当前成片并检查两张证据表。独立审查实例把结果写入 `review/ai-acceptance.json`，用户不参与常规审批。

每项填写 `passed/failed/not_applicable` 和具体证据；任一适用项 `failed` 即不通过。默认深色皮肤的白墙专项必须为 `not_applicable`，白墙融合皮肤则必须为 `passed`：

1. `opening-complete`：片头是否从清晰完整的第一句话紧凑进入，首个有效语音前没有可闻静音、吸气、准备音或填充词？
2. `asr-word-corrections`：ASR 是否确认为豆包 Agent Plan 并绑定当前源视频；明确误听的词是否已按音频和上下文纠正，且说话者真实口误没有被改写？
3. `speech-fillers-zero`：全片是否听不到已识别的“嗯、啊、呃、额、哦、噢、诶、唉”？
4. `segment-entry-clean`：每个剪后句首是否直接进入有效表达，没有上一段尾音、被删除的填充词尾巴或多余气口，同时首字没有被削头？
5. `speech-tail-complete`：每句句尾是否有完整尾音，没有提前截字？
6. `caption-semantic-boundaries`：每条字幕是否语义完整，上一句话的尾字没有进入下一条字幕？
7. `stage-fixed-left`：左上舞台是否始终在同一位置，没有为人物自动换边？
8. `chapter-build-sequence`：栏目是否按“竖线→英文→中文”出现，并在本章持续可见？
9. `first-layer-after-header`：首层内容是否在栏目建立后才出现？
10. `anchored-fade-motion`：普通容器是否固定坐标短渐显，而不是上浮、左滑或弹跳？
11. `persistent-layer-stack`：新信息是否追加在旧信息下方，旧信息没有被整卡替换？
12. `progressive-item-timing`：并列项是否在说到对应概念时逐项补入？
13. `type-specific-components`：不同语义类型是否使用参考片对应版式，而不是同一种黑框？
14. `animation-not-caption-duplicate`：动画是否提炼结构，而不是重复字幕整句？
15. `caption-readability-font`：字幕是否清楚、无字体回退、无卡片动画遮挡？
16. `fullscreen-transition-restraint`：是否只在真正升级处使用全屏转场？
17. `framing-adjustability`：最终画面是否能让拍摄者据此调整人物站位？
18. `semantic-card-meaning`：每张卡片表达的含义是否精准对应出现当下的原话，而非只与整章相关？
19. `semantic-trigger-timing`：触发点是否自然，没有讲完才补画面或尚未开讲就提前出现？
20. `semantic-no-spoiler`：是否没有提前展示未来才讲出的结论、对比另一面或后续列表项？
21. `semantic-hold-relevance`：旧信息在持续保留期间是否仍与当前口述相关？
22. `white-wall-fusion-readability`：白墙版是否与背景融合但仍清晰可读，且动画结构和深色版完全一致？
23. `white-wall-transparent-stage`：白墙版是否呈现为透明舞台＋深色自由文字＋局部深色透明内容板？
24. `card-size-semantic-fit`：小、中卡是否与信息结构匹配，且所有普通卡片都没有超过画面宽度 `33.4%`？
25. `card-content-height-fit`：短内容卡片是否按内容自然收口，没有与信息量不匹配的大面积空底板？
26. `spoken-expression-fidelity`：信息节点、人物、顺序和箭头关系是否忠于真实口述，没有为了形式整齐而改写、合并或补充；每条箭头是否只在它所引出的后一个节点触发时同步出现，没有提前成为固定背景？
27. `card-layout-grammar`：2–4 项关系是否充分使用中卡内容区，3–4 项并列是否等宽，5–12 项是否按合同等尺寸均衡换行，且右侧没有大块无意义空白？
28. `stage-overflow-zero`：所有逐层增加后的卡片是否完整可见，没有截断、越界或用遮挡豁免隐藏问题？
29. `speech-rhythm-natural`：全片口播是否紧凑但仍自然，长停顿已收紧，局部加速没有机械感、音高异常、吞字、截尾音，字幕与动画仍精准同步？

`ai-acceptance.json` 必须声明 `policy=fresh-ai-lens-acceptance`、`reviewer.type=ai-agent`、`reviewer.context_mode=fresh`，并逐项原样复制 `artifacts/agent-review-brief.json` 中的当前证据指纹。`verify` 会重新计算指纹，不接受旧成片或旧运行的验收。

## 证据

每次完成实际素材运行并准备交付时，必须保留以下证据：

- `review/contact-sheet.jpg`
- `review/editorial-review.md`
- `review/editorial-review.json`
- `review/locked-editorial-master.json`
- `review/semantic-reveal-sheet.jpg`
- `review/semantic-reveal-timeline.json`
- `review/semantic-reveal.audit.json`
- `review/caption-units.json`
- `review/caption-units.audit.json`
- `review/rhythm-plan.json`
- `review/layout-fit-report.json`
- `work/rhythm/rhythm-manifest.json`
- `review/ai-acceptance.json`
- `artifacts/agent-review-brief.json`
- `logs/animations-*-check.log`
- `logs/animations-*-render.log`
- `deliverable/final.mp4`

用户只看成片时，至少提供成片与联系表；工程审查再附 JSON 和日志。
