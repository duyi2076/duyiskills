---
name: duyi-ai-jianji
description: 将中文横屏一镜到底口播剪成可发布成片，包含逐词审校、唯一一次文字确认、口播精剪、字幕、响度处理和固定左上舞台的语义动画。适用于横屏 AI 剪辑、逐层信息揭示、深色或白墙融合皮肤；不处理竖屏轻量剪辑。
---

# 杜一 AI 剪辑

剪辑、字幕、响度和运行恢复由同一条确定性流水线完成。视觉导演层在固定左上舞台中按语义逐层增加信息，每章先建立栏目，再追加观点、关系和列表项。

## 不可变合同

开始前阅读 [文字母版锁定合同](references/editorial-lock-contract.md)、[自适应口播节奏合同](references/adaptive-rhythm-contract.md)、[固定构图合同](references/composition-contract.md)、[卡片视觉语法](references/card-visual-grammar.md)、[卡片内容高度与舞台自动重排合同](references/adaptive-card-layout-contract.md)、[状态计划格式](references/state-plan-schema.md) 和 [验收标准](references/acceptance.md)。

- 画布按 `1280×720` 参考坐标等比缩放；卡片只保留小/中两档参考宽度 `373/427 px`，中卡 `427 px` 即画面宽度约 `33.4%`，是不可突破的最大宽度；横屏 16:9 成片最低交付 `1920×1080`，输入高于 1080P 时保留输入分辨率，帧率与横屏比例保持不变。
- 左上舞台固定，不因人物位置自动换边、缩小或避让。人物与舞台冲突要报告，不能静默改版。
- 动画卡片固定使用 Noto Sans CJK SC Bold（700），语音字幕才使用 Black（900）；字体和动效结构不随皮肤变化，禁止系统字体回退。
- 一条视频只能锁定一种视觉皮肤：默认 `dark-reference-fixed`；用户明确要求白墙融合时使用 `white-wall-fusion-fixed`。禁止章节内混皮、随机换皮或由 AI 自动选择白墙版。
- 白墙融合使用透明舞台：自由文字使用带轻浅色轮廓的深色字，保证跨过人物深色头发时仍可读；类型组件使用局部深色半透明内容板与浅色板内文字。
- 全片永久删除已识别的非语义填充词 `嗯/啊/呃/额/哦/噢/诶/唉`。此规则适用于全部视觉皮肤。
- 逐词转写强制使用豆包 ASR：`provider=agent_plan`、`resource_id=volc.seedasr.sauc.duration`。禁止使用 Whisper、mlx-whisper、FunASR 或任何其他本机/云端模型替代；即使替代结果包含逐词时间也必须阻断。豆包结果必须绑定当前源视频的 SHA-256 与字节数，禁止复用无法证明对应当前素材的旧转写。
- 所有剪后入口必须经过离线声学检测，禁止统一预留 `80ms`：先把 ASR 的音轨时间换算到媒体时间轴，再用 Silero VAD（语音活动检测）定位真实人声起点，并以能量低谷补足连续口语边界。整片开篇目标保护约 `32ms`，删除填充词后的入口约 `30ms`，普通干净入口约 `55ms`；听得到吸气、准备音或上一段尾巴即不通过。若填充词与下一有效字连续且不存在可用静音，必须在两 token 交界附近做采样级零交叉微切并使用最多 `4ms` 淡入，不能因没有 `20ms` 静音而保留填充词或阻断整条视频。
- ASR 标准化后先通过当前源视频绑定与逐词完整性门禁，再由 AI 一次性完成删除建议、词级纠错、说话者原话辨别、完整句和最终字幕断句。只修正音频与上下文能够明确证明的机器误听；保留说话者真实的口误和不完整表达，禁止句子级润色。
- AI 完成全部文字决定后生成一份完整标注确认稿；用户只审核这一次。用户确认或提出修改后，AI 把修改写回同一决定并立即生成 `locked-editorial-master.json`，不再发第二轮审批。
- 锁定前禁止剪辑、字幕和动画；锁定后下游只读。切点、字幕和动画均必须绑定文字母版 SHA-256，任何下游不得重新改字、删词、合句或断句。
- 每条字幕必须对应锁定母版中的完整句与 cue；禁止按字符数、停顿或物理剪辑段自动跨句拼接。确认稿生成前必须用最终真实字体、字号和安全宽度测量每一条字幕，并以删词压缩后的逐词时间轴校验自然起止词。`3.8s` 是优选时长；保守压缩长停顿、必要时局部加速后可进入 `3.8–5.5s` 自适应区间，预计仍超过 `5.5s` 才阻断。宽度、时长或断句任一失败都不得把确认稿交给用户。
- 节奏层必须先判断停顿比例与真实发声语速：先压缩长内部停顿，只有语音确实偏慢且证据充分时才局部加速；最高 `1.15×`，含英文、数字或样本过短的字幕单元禁止语音加速。禁止整片统一加速。
- 栏目按“竖线→英文→中文”建立并常驻；首层内容随后出现。
- 普通容器固定坐标渐显 `0.22s`，列表项渐显 `0.15s`；禁止普通卡平移、缩放、弹跳、呼吸、漂浮和循环。
- `update` 必须追加下一层，不能让旧整卡退出、新整卡替换。
- `thesis/quote/comparison/formula/progressive-list/path/chat/relation` 使用锁定的不同参考组件，禁止重新合并成万能黑框。
- 卡片首先服务真实口述。不得为了形式逻辑整齐而替换、合并、重排或补写说话者表达的节点；不同词性的叙事节点可以共存，箭头可表示推进、交接、执行或结果演进，只有原话明确表达因果时才使用因果关系。
- 箭头不是卡片的固定背景。叙事推进或明确因果中的每条箭头必须独立绑定它所引出的后一个节点，并在该节点的真实语音触发词到达时同步生长；禁止一个 state 共用全局箭头字段，也禁止后续节点尚未成立时提前露出空箭头。
- 每个视觉 state 必须由 AI 显式填写 `fidelity_mode=spoken-first`、`relation_layout/layout_reason` 和 `card_size/content_structure/size_reason`。中卡默认；小卡用于短单点。文字或节点超出预算时拆层，不得放宽到 33.4% 以外。
- 卡片高度必须由真实字体、行数、节点行数和内边距决定；禁止使用与信息量无关的固定大底板。浏览器 DOM 实测是最终权威，任何 `container_overflow` 都必须由 AI 自动重排后重试，不能裁切、豁免或交给用户审批。
- 字幕轨与动画轨分离。字幕写原话，动画只写概念、关系和结构。
- 每个视觉单元都必须有逐词证据和独立的语义揭示事件；章节相关不等于当下相关。禁止提前展示尚未说出的结论。
- 已有运行目录和既有输出只读；更换本 Skill 或视觉合同后必须创建新运行目录。

## 工作流

### 1. 创建独立运行目录

运行目录由调用方传入，必须是新建且独立的目录。原视频、ASR、已有成片和旧运行目录只读。运行数据保存在 Skill 目录之外。

先阅读 [安装与 ASR 配置](README.md)。用户只提供视频时，必须先配置可用的外部豆包 ASR 适配器和凭据文件，再在运行目录的 `incoming/` 中生成逐词 ASR：

```bash
python3 scripts/generate_doubao_asr.py \
  --input /path/to/source.mp4 \
  --tool /path/to/agent_plan_asr.py \
  --env /path/to/asr-config.env \
  --output /path/to/run/incoming/doubao-asr.json
```

该脚本固定调用豆包 Agent Plan ASR，并写入 provider、resource ID 和当前源视频指纹。调用失败时停止；禁止自动降级到本机 ASR。若用户已经提供 ASR，也必须包含同样的豆包来源合同和当前素材绑定，否则 `asr-integrity` 门禁会拒绝。

```bash
python3 scripts/duyi_edit.py doctor
python3 scripts/duyi_edit.py init \
  --input /path/to/source.mp4 \
  --asr /path/to/run/incoming/doubao-asr.json \
  --run-dir /path/to/run
```

`init` 会完整验证源视频、标准化逐词稿并生成 `artifacts/asr-integrity.json`。门禁通过后以阻塞码结束，运行本 Skill 的 AI 继续完成整份文字审校方案；此时不得提前剪辑。

### 2. AI 一次性完成文字审校

运行本 Skill 的 AI 对照真实音频、`artifacts/asr-integrity.json` 和完整上下文逐词检查 `artifacts/normalized-transcript.json`，只写一份 `review/editorial-review-plan.json`。它必须在交给用户前同时完成：

1. 标出应删除的填充词、重复重说和未完成起句；
2. 只修正音频与上下文明确证明的 ASR 误听；
3. 把说话者真实口误、事实说错和未完成表达列入 `speaker_issues`，固定 `decision=preserve_original`，不得伪装成 ASR 错误；
4. 给全部保留词建立稳定 `sentence_id`；
5. 在完整句内部给出最终 subtitle cue，每条 cue 必须语义自然；
6. 所有保留词必须被句子和 cue 按原顺序恰好覆盖一次。

单 token 纠错绑定一个原始 `word_id`。若一个词被 ASR 拆成连续 2–8 个 token，可绑定 `word_ids` 并提供等长 `corrected_parts`；全部原 ID 和时间保持不变，字幕把整个范围显示成一个词。典型例子包括 `cloud → Claude`、`a+镜+头 → A+gen+t → Agent`、`发会 → 花费`。所有机器误听修正仍须满足 `kind=asr_error`、`evidence=audio-and-context`、`confidence=high`、`approved=true`。证据不足时保留原词并写入 `preserved_uncertain`；`unresolved` 必须为空。

完整格式见 [文字母版锁定合同](references/editorial-lock-contract.md) 和 [状态计划格式](references/state-plan-schema.md)。

### 3. 生成唯一确认稿并锁定

```bash
python3 scripts/duyi_edit.py prepare-review /path/to/run
```

该命令会生成：

- `review/editorial-review.md`：给用户看的唯一一次确认稿；
- `review/editorial-review.json`：同一决定的机器可读版本。

确认稿必须完整呈现：普通文字表示保留、`<u>` 下划线表示建议删除、纠正词直接写在正文并紧跟原转写与原因、说话者真实口误单独标注为保留、最终句子与最终字幕换行原样展示。每条字幕同时显示用内嵌 Noto Sans CJK SC Black 字体、实际字号和交付分辨率测得的像素宽度，以及原始时长、预计节奏处理后时长和节奏分类。超宽、预计超过 `5.5s`、停在不自然虚词、残句、漏词、重叠或仍含硬填充词时，命令阻断，不能把半成品给用户。

执行代理必须在唯一一次人工确认前完成全部文字判断。若用户提出修改，AI 直接修改 `editorial-review-plan.json`；不得再生成第二份确认稿要求用户复审。随后执行：

```bash
python3 scripts/duyi_edit.py lock-review /path/to/run \
  --confirmation-note "用户已完成唯一一次文字确认"
```

`lock-review` 会静默重跑机器校验，并生成 `review/locked-editorial-master.json`。同时从锁定母版确定性派生 `asr-corrections.json`、`corrected-transcript.json`、`cut-plan.json`、`caption-units.json` 和 `semantic-map.json`；这些文件全部写入同一个母版 SHA-256。任何源稿、计划或字体合同在确认稿生成后发生未授权变化，锁定失败。

### 4. 自动处理口播与声学边界

锁定后才能执行 `resume`。片头不能从填充词、吸气或准备音进入；全片任何保留区间都不能含已识别的 `嗯/啊/呃/额/哦/噢/诶/唉`。`然后/所以/就是/那个` 可能有语义，不能机械删除。段内填充词必须通过拆分保留区间从音频中移除，不能只在字幕中隐藏。

边界脚本必须读取音轨的 `start_time`，把 ASR 音轨时钟换算为视频媒体时钟；禁止直接拿从零开始的解码 WAV 时间与视频裁切时间比较。每个入口优先使用 Skill 内嵌的离线 Silero ONNX 模型识别新的人声起点；填充词和下一句话连续但仍有可用间隙时，在 ASR 首词附近寻找最后一个能量低谷；两词首尾相接或轻微重叠时使用 `continuous-speech-zero-cross-splice`，在交界前最多 `4ms`、交界后最多 `2ms` 内选择最近零交叉点，并给音频最多 `4ms` 微淡入。任何入口都不能再套用统一 `80ms`。

若 ASR 出现 `嗯对/呃我觉得` 这类粘连 token，必须在唯一确认稿生成前补更细时间；若只是 `金额/额度/额外` 等正常词被字符规则命中，在 `editorial-review-plan.json` 中逐 word ID 明确为语义词，不能做全局词表豁免。

若使用白墙融合皮肤，在首次 `resume` 前写：

```json
{"user_style":"white-wall-fusion-fixed","user_confirmed":true,"user_reason":"拍摄背景为白墙，用户明确选择融合皮肤"}
```

到 `review/style-selection-input.json`。不写时固定使用默认深色参考皮肤。已经锁定皮肤后若要更换，必须新建运行目录，不能覆盖原决定。

白墙版的生成样式固定为：透明舞台、带轻浅色轮廓的自由文字 `#17212B`、局部内容板 `#0A141B / 0.82`、板内主文字 `#F3F5F7`。浅色轮廓只服务于自由文字跨过深色人物或物体时的可读性，不形成底板。

### 5. 以章节为单位导演视觉

阅读 `artifacts/visual-director-brief.json`（首次 `resume` 后生成）以及最终映射时间轴。写：

- `review/visual-direction.json`
- `review/animation-plan.json`
- `review/semantic-reveal-timeline.json`

每个 `segment` 是一个章节视觉状态，不是一个短促动画。典型视频使用 3–6 个章节、总计约 8–16 次状态更新；同一章节最多 4 个视觉层。第一个视觉状态用 `enter`，后续用 `update` 追加；同一层的并列项按口述逐项出现。

只有口述明确否定上一层时，才使用 `previous_treatment=dim` 或 `cross-out`；其他情况保持 `hold`。

优先把同一关系的并列信息放进一个类型层的 `items`。不要先做一张 thesis，再为同一组信息叠一张完整 list；固定舞台高度预算为模板坐标 `690 px`。计划阶段先按 [卡片内容高度与舞台自动重排合同](references/adaptive-card-layout-contract.md) 计算最终完全展开高度，超出时由 AI 自动归并和重排，不要求用户审批。

必须遵守组件字段：`path/progressive-list` 不写 body；`comparison` 必须给语义 emoji 且不写 body；`formula` 必须拆成带 `primary/muted/accent` 的 parts；`quote` 使用独立来源字段。不要为了方便退回“title + body 万能卡”。

逐个视觉 state 按 [卡片视觉语法](references/card-visual-grammar.md) 做两次判断：

1. 先忠实提取原话中的节点、顺序、人物和关系，不为追求词性一致或形式因果而重写。
2. 再选择 `relation_layout`：叙事推进用 `narrative-path`，明确因果用 `spoken-cause`，同级并列用 `parallel`，两面对照用 `comparison`，上下级用 `hierarchy`，5–12 个同组短节点用 `multi-item`。
3. `medium` 是完整观点和关系布局的默认尺寸；`small` 只用于短单点。任何卡片不得超过画面宽度 `33.4%`。
4. 流程的 2–4 个节点在一行内按文字自然宽度排列，剩余空间平均给动态箭头通道；每个后续节点用 `incoming_connector` 声明它与前一节点的连接，连接线与目标节点共用触发词并同步出现。普通 3 项各占 `1/3`，4 项各占 `1/4`，不得在右侧留下大块空白。
5. 5–8 项按 `3+2 / 3+3 / 4+3 / 4+4` 换行；9–12 个属于同一语义组的短节点使用一个复合卡外壳，按 `4+4+1 / 4+4+2 / 4+4+3 / 4+4+4` 换行并让末行居中；13 项以上按真实语义边界拆章。
6. `layout_reason` 必须引用口述关系线索；`size_reason` 必须解释小卡或中卡选择，不能只写“更好看”或“AI 判断”。

必须让每个章节覆盖真实口述区间，并用 `trigger_word_ids` 把状态变化锚定到让画面文字首次完全成立的那个词。卡片只写主题时可在主题词出现后建立；卡片若包含动作结果、数字、结论或完整短语，必须等说到足以确认该结果、数字、结论或完整短语的词再出现，不能只因前面出现了相关关键词就提前揭示。章节栏要使用不剧透的中性主题，结论留给后续 state/item。每个 state、item 和 formula part 都要有稳定 `id`；公式分段必须各自给触发词，按口述次序逐段出现。

随后为每个视觉单元写一条语义揭示事件，逐项记录精确原话范围、最早允许出现词、实际触发词、完整显示词、保留终点和防剧透判断。`spoken_excerpt` 必须由连续逐词记录原样拼成，不能用概括句代替。计划格式严格按 [状态计划格式](references/state-plan-schema.md)。

### 6. 恢复并自动构建动画

```bash
python3 scripts/duyi_edit.py resume /path/to/run
```

编排器会：

1. 映射安全裁切后的逐字时间；
2. 阻断任何仍被保留的非语义填充词；
3. 审计字幕语义单元的完整覆盖，并把单位 ID 写入每个映射词；
4. 执行自适应节奏层：先压缩长停顿，再对证据充分的慢语速单元做最高 `1.15×` 局部加速；
5. 生成 `rhythm-plan.json` 和 `rhythm-manifest.json`，重新映射每个词、字幕单元和动画触发点；
6. 把嵌套状态的 `trigger_word_ids` 解析为章节内时间；
7. 审计每个视觉单元的原话证据、出现顺序、完整显示点、保留终点和防剧透声明；
8. 调用 `assets/composition/semantic-stage/build.py`；
9. 运行 HyperFrames `check`，把当前 HTML 哈希和实际 DOM 布局写入 `layout-check.json`；
10. 若出现 `container_overflow`，生成 `review/layout-fit-report.json`，执行代理按固定策略修改动画计划和语义揭示计划后重新 `resume`，最多三轮；布局重排由代理自动修复，不得把溢出问题交给人工审批；
11. 只有浏览器实测零溢出才渲染透明 MOV；
12. 最后烧录语音字幕并验证字体、分辨率、响度、语义断句、节奏和视觉合同；
13. 生成 `review/semantic-reveal-sheet.jpg`，逐事件展示出现前、触发中、出现后三帧。

不手工改 `output_start/output_end/reveal_at`，除非审计报告明确指出映射错误。

### 7. 独立审查后交付

```bash
python3 scripts/duyi_edit.py status /path/to/run
```

机械 QA 通过后，编排器会自动生成 `review/contact-sheet.jpg`、`review/semantic-reveal-sheet.jpg` 和 `artifacts/agent-review-brief.json`。执行代理必须启动一个不继承当前任务上下文的独立审查实例，让它连续观看当前成片并逐项检查 brief 中的 29 项合同，写入 `review/ai-acceptance.json`。用户不参与常规审批。

AI 验收通过后执行：

```bash
python3 scripts/duyi_edit.py verify /path/to/run
```

`verify` 会重算当前成片、QA、联系表、语义揭示表和导演计划的哈希；任何旧运行的验收文件或验收后被替换的成片都会被拒绝。工具检查通过不等于语义时机或视觉 1:1 已通过，必须完成无上下文 AI 连续观看。

## 停止条件

- 没有逐字级 ASR：停止，先补 ASR。
- ASR 不是豆包 `agent_plan / volc.seedasr.sauc.duration`、缺少豆包来源合同、缺少当前源视频指纹绑定，或使用任何本机 ASR：停止；不得自动降级或继续剪辑。
- `asr-integrity.json` 未通过，或 `asr-corrections.json` 未完成 AI 逐词复核、仍有真正未决的 `unresolved`、或试图改写说话者真实表达：停止，不进入语义审查。已经明确决定保留原词的低置信项写入 `preserved_uncertain`，不阻断。
- `editorial-review-plan.json` 尚未同时完成删除、纠错、说话者原话辨别、完整句和最终字幕断句：停止，不生成给用户看的确认稿。
- 用户尚未完成唯一一次确认，或 `locked-editorial-master.json` 缺失、失效、出现第二次审批记录，或任一下游文件未绑定当前母版 SHA-256：停止，不剪辑、不渲染。
- 语义计划无法给出章节起止或触发词：停止，不凭时间均分。
- 任一 state、item 或 formula part 没有精确原话证据、稳定 ID、触发词或防剧透结论：停止，不渲染。
- 任一保留区间仍含已识别的硬填充词，或字幕语义单元缺失、重叠、漏词、跨句、未批准：停止，不剪辑、不渲染。
- 人物遮住固定舞台：继续生成测试证据，但标记为“拍摄站位冲突”，不得自动换边。
- 任一字体未嵌入、透明通道缺失，或 16:9 横屏最终成片低于 `1920×1080`：停止交付。
- HyperFrames 出现 `container_overflow`：停止当前渲染，由 AI 自动执行内容高度收口、间距收紧、同组复合、摘要条或语义拆章并重试；三份不同计划仍失败才报告技术阻塞，禁止使用布局豁免属性。
- 独立审查实例的 29 项验收任一适用项失败，或 `ai-acceptance.json` 不匹配当前证据哈希：停止交付，由 AI 修正后重新渲染与验收，不把审批责任转给用户。
- 若需要竖屏版本：新建独立 Skill，保持横屏与竖屏流程独立。
