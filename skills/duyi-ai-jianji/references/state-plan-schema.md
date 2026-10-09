# 杜一 AI 剪辑 状态计划格式

## 权威入口：`editorial-review-plan.json`

杜一 AI 剪辑.15 起，AI 不再分别把 `asr-corrections.json`、`cut-plan.json` 和
`caption-units.json` 当作三个独立审批对象。AI 必须先按
[文字母版锁定合同](editorial-lock-contract.md) 完成一份
`editorial-review-plan.json`，生成唯一一次人工确认稿并锁定。

锁定后，下方的 `asr-corrections.json`、`caption-units.json` 以及
`semantic-map.json/cut-plan.json` 均由 `lock-review` 确定性派生；Agent
不得手工绕过 `locked-editorial-master.json` 直接创建或改写这些文件。

## `asr-corrections.json`

它只纠正机器误听的词汇，不改写说话者真实表达。若同一个词被 ASR 拆成多个连续 token，可绑定一个短 token span：

```json
{
  "schema_version": 1,
  "policy": "word-level-asr-errors-only",
  "reviewed": true,
  "transcript_sha256": "normalized-transcript.json 的 SHA-256",
  "source_media_sha256": "当前源视频的 SHA-256",
  "asr_integrity_sha256": "当前 asr-integrity.json 的 SHA-256",
  "term_hints": ["Claude", "Agent", "ClawBot"],
  "corrections": [
    {
      "word_id": "word-000120",
      "original": "cloud",
      "corrected": "Claude",
      "kind": "asr_error",
      "evidence": "audio-and-context",
      "confidence": "high",
      "approved": true
    },
    {
      "word_ids": ["word-000175", "word-000176", "word-000177"],
      "original": "a镜头",
      "corrected": "Agent",
      "corrected_parts": ["A", "gen", "t"],
      "kind": "asr_error",
      "evidence": "audio-and-context",
      "confidence": "high",
      "approved": true
    }
  ],
  "preserved_uncertain": [
    {
      "word_id": "word-000210",
      "original": "key",
      "decision": "preserve_asr",
      "confidence": "not-high",
      "reason": "音频转写与局部上下文都不足以唯一确定目标词，保留豆包原词"
    }
  ],
  "unresolved": []
}
```

字段规则：

- 术语提示只是辅助，不是允许修正的封闭清单。
- 每条纠错对应一个 `word_id`，或同一 utterance 内连续的 2–8 个 `word_ids`；保留全部原时间与 ID。
- 多 token 纠错必须提供等长且都非空的 `corrected_parts`，拼接结果必须等于 `corrected`；下游字幕把这个连续纠错范围作为一个完整词显示，不在 parts 之间插入空格，也不能把一个纠错范围拆到两个字幕单元。
- 纠错文件必须同时绑定当前标准化逐字稿、源视频和 ASR 完整性报告，不能跨运行复用。
- 只有源视频绑定的豆包音频证据和上下文共同明确时才修正；同音字可以由唯一成立的固定搭配或局部语法确定。
- 说话者真实口误、事实错误和不完整表达保持原样。
- 禁止增加、删除、重排 token 或润色整句。
- 已完成复核但证据仍不足的词保持原样，逐项写入 `preserved_uncertain`：必须绑定原 `word_id/original`，固定 `decision=preserve_asr`、`confidence=not-high` 并解释原因；这些项目只留审计记录，不阻断。
- `unresolved` 只表示 AI 尚未作出“纠正或保留”的决定；确认前流水线阻塞，自动流程交付前必须为空。
- 即使没有纠错，也必须提交 `reviewed=true`、空 `corrections` 和空 `unresolved`。

## `caption-units.json`

字幕边界由 Agent 阅读逐词稿后明确给出，机器只做覆盖与边界审计，不再按字数或短停顿猜句子。

```json
{
  "schema_version": 1,
  "policy": "semantic-complete",
  "units": [
    {
      "id": "caption-unit-001",
      "start_word_id": "word-000001",
      "end_word_id": "word-000024",
      "boundary_reason": "sentence",
      "approved": true
    },
    {
      "id": "caption-unit-002",
      "start_word_id": "word-000026",
      "end_word_id": "word-000043",
      "boundary_reason": "clause",
      "approved": true
    }
  ]
}
```

字段规则：

- `boundary_reason` 只允许 `sentence/clause/breath-group`。
- `start_word_id/end_word_id` 必须是剪后实际保留的词。
- 所有保留词必须按原顺序恰好覆盖一次，不得漏词、重叠或倒序。
- 为删除段内填充词，一个语义单元可以跨多个物理剪辑片段。
- 单元开头不得是上一句遗留的助词或连接残片；结尾不得停在介词、连词或未完成修饰语上。
- 单元过长时按完整从句拆分，不能只为满足字数从词组中间切开。
- `approved` 必须为 `true`；机器不会替 Agent 猜测语义完整性。
- `caption-corrections.json` 已停用；文字纠错只能在语义审查前通过 `asr-corrections.json` 完成，断句只能修改本文件并重新审计。

## `embedded-filler-review.json`（仅在 ASR 粘词时）

若 ASR 把填充音与正文粘成一个 token，例如 `嗯对`，流水线必须阻塞；不能凭字符时间猜切点。若 token 实际是 `金额/额度/额外/唉声叹气` 这类正常语义词，可由 AI 逐词审核：

```json
{
  "schema_version": 1,
  "transcript_sha256": "corrected-transcript.json 的 SHA-256",
  "decisions": {
    "word-000120": {
      "decision": "semantic_word",
      "approved": true,
      "reason": "这里说的是金额，额不是填充音"
    }
  }
}
```

只有 `semantic_word + approved=true + 非空原因` 可以放行。若确认 token 中确有填充音，必须取得更细词级时间或重新识别后再拆剪，不能用该文件隐藏音频。

## `review-decisions.json`（仅在 cut plan 有待审项时）

```json
{
  "schema_version": 1,
  "inputs": {
    "corrected_transcript_sha256": "当前 corrected-transcript.json 的 SHA-256",
    "cut_plan_sha256": "当前 cut-plan.refined.json 的 SHA-256",
    "boundary_report_sha256": "当前 acoustic-boundaries.json 的 SHA-256",
    "source_media_sha256": "当前源视频的 SHA-256"
  },
  "approved_ids": ["review-001"],
  "decisions": {
    "review-001": {
      "approved": true,
      "reason": "AI 对照当前音频确认该边界保留完整起音与尾音"
    }
  }
}
```

审批只能写入绑定当前对象的文件；命令行临时批准和跨运行复用都会被拒绝。

## `visual-direction.json`

```json
{
  "schema_version": 3,
  "system": "reference-1to1",
  "viewer_experience": "观众持续看到同一块信息舞台被逐步搭建",
  "rhythm": "章节常驻 状态短更新 长时间静止",
  "chapters": [
    {
      "id": "chapter-001",
      "purpose": "说明这一章帮助观众理解什么",
      "segment_id": "chapter-001"
    }
  ]
}
```

## `animation-plan.json`

```json
{
  "schema_version": 3,
  "segments": [
    {
      "id": "chapter-001",
      "template": "semantic-stage",
      "purpose": "把开篇命题持续保留并逐层补充",
      "source_word_ids": ["word-000010", "word-000180"],
      "render_approved": true,
      "config": {
        "chapter_en": "THE WORKFLOW",
        "chapter_zh": "从拍摄到发布",
        "accent": "blue",
        "layout": "fixed-left",
        "states": [
          {
            "id": "state-001",
            "action": "enter",
            "type": "thesis",
            "fidelity_mode": "spoken-first",
            "relation_layout": "single-point",
            "layout_reason": "原话在此建立一个核心命题",
            "card_size": "medium",
            "content_structure": "core-idea",
            "size_reason": "标题加解释构成完整核心观点，使用默认中卡",
            "trigger_word_ids": ["word-000010"],
            "title": "剪辑自动化",
            "body": "从原片到可发布成片"
          },
          {
            "id": "state-002",
            "action": "update",
            "type": "progressive-list",
            "fidelity_mode": "spoken-first",
            "relation_layout": "vertical-list",
            "layout_reason": "原话按三个步骤逐项展开",
            "card_size": "medium",
            "content_structure": "vertical-list",
            "size_reason": "三个步骤纵向逐项出现，使用默认中卡",
            "previous_treatment": "hold",
            "trigger_word_ids": ["word-000035"],
            "title": "完整流程",
            "items": [
              {"id": "item-001", "text": "识别口述", "trigger_word_ids": ["word-000035"]},
              {"id": "item-002", "text": "清理停顿", "trigger_word_ids": ["word-000060"]},
              {"id": "item-003", "text": "生成动画", "trigger_word_ids": ["word-000095"]}
            ]
          },
          {
            "id": "hold-001",
            "action": "hold",
            "trigger_word_ids": ["word-000120"],
            "reason": "让人物完成判断，不新增重复动画"
          },
          {
            "id": "clear-001",
            "action": "clear",
            "trigger_word_ids": ["word-000180"]
          }
        ]
      }
    }
  ]
}
```

## 字段规则

- `source_word_ids`：章节范围的首尾及关键覆盖词；必须映射到剪后时间。
- `template`：只允许 `semantic-stage`。
- `accent`：`blue/red/green/yellow`。
- `layout`：通常为 `fixed-left`；真正章节升级可用 `fullscreen`。
- `action`：`enter/update/hold/clear`。
- 每章第一个视觉状态必须是 `enter`；后续视觉状态必须是 `update`。
- `update` 表示在同一左上舞台继续增加下一层，不能替换或删除前一层。
- `type`：`thesis/quote/chat/comparison/formula/progressive-list/path/relation`。
- `fidelity_mode`：每个视觉 state 必填且固定为 `spoken-first`；卡片服务原话，不得为了形式逻辑整齐而改写节点。
- `relation_layout`：每个视觉 state 必填，只允许 `single-point/narrative-path/spoken-cause/parallel/comparison/hierarchy/formula/multi-item/vertical-list/quote/chat`。
- `layout_reason`：每个视觉 state 必填，引用口述中的顺序词、因果词、并列关系或上下级关系，说明为什么选择该布局。
- `card_size`：每个视觉 state 必填，只允许 `small/medium`；默认选择是 `medium`，但仍必须显式写出。
- `content_structure`：每个视觉 state 必填，只允许 `short-single/core-idea/horizontal-relation/parallel-row/comparison-row/hierarchy/balanced-grid/vertical-list/quote/chat`。
- `size_reason`：每个视觉 state 必填，说明尺寸与信息结构的对应关系；不能只写“好看”“文字多”或“AI判断”。
- 小卡宽 `373 px`，用于短单点；中卡宽 `427 px`，用于常规核心信息和关系布局，也是 `33.4%` 最大宽度。
- 超出文字预算时先拆层或压缩动画概念，不得扩大卡片。
- `previous_treatment`：`hold/dim/cross-out`，默认 `hold`；只有口述明确否定上一层时才能使用后两者。
- `trigger_word_ids`：至少一个让该视觉文字首次完全成立的实际词。主题卡可锚定主题词；包含动作结果、数字、结论或完整短语的视觉，必须锚定到足以确认这些信息的词，不能锚定更早的相关关键词。
- `chapter_zh`：只写本章已经建立的中性主题；如果“代价、结论、结果、数量”等信息尚未说出，放入后续 state/item，不在章节栏提前概括。
- 每个视觉 state、item 和 formula part 必须有本章内唯一、稳定的 `id`，供语义揭示时间轴交叉引用。
- `items`：普通组件最多 4 项；`relation` 最多 12 项。每项单独给触发词，按语义出现，禁止平均分配时间。
- `relation`：2–4 项流程/因果为单行；普通并列 3 项各占 `1/3`、4 项各占 `1/4`；5–8 项按 `3+2 / 3+3 / 4+3 / 4+4` 换行；9–12 个同组短节点使用 `multi-item`，按 `4+4+1 / 4+4+2 / 4+4+3 / 4+4+4` 换行；13 项以上按真实语义边界拆章。行数与列位由渲染器按 item 数量确定，不允许计划另写 `row_distribution/columns` 覆盖。
- `narrative-path` 保留原话中的节点和顺序；不得仅因节点词性不同就合并或替换。`spoken-cause` 只在原话明确表达因果时使用。
- `relation` 的 `label` 可选，缺省由类型提供；`title` 必填且必须是当下已经成立的中性主题，不能提前写入最后结果。
- 禁止 state 级 `connector`。`narrative-path/spoken-cause` 的第一个 item 不带连接线；后续每个 item 必须填写 `incoming_connector: "→"` 或 `"⇒"`，连接线自动绑定该 item 的 `trigger_word_ids`，与目标节点同步出现。并列、对比、层级和多项网格不得填写 `incoming_connector`。
- `path/progressive-list`：只允许 `label + title + items`，禁止 `body`，否则标题卡高度会偏离参考片。
- `comparison`：必须填写 `icon`（1 个语义 emoji）；可填写 `marker`，默认 `⚠`；禁止 `body`。
- `formula`：必须填写 `parts`，每项为 `{"text":"…","tone":"primary|muted|accent"}`，共 2–7 项。
- `formula.parts`：每项还必须填写 `id` 和 `trigger_word_ids`；关系符可与它所引出的下一项共用触发词。
- `thesis/quote`：可用 `accent_text` 指定标题中唯一的强调色片段。
- `quote`：填写 `source_name`，可选 `source_note`、`source_initial`；不要把来源层级塞进普通 `body`。
- `hold` 不产生新画面，只记录“为什么此处保持不变”。
- 禁止使用 `replace`、`replace_state` 或 `remove_previous` 一类字段。
- 每章最多 4 个视觉层；栏目栏不计入。
- 先把同一关系中的并列信息放进一个类型层的 `items`，不要为每组并列项再新建一张完整卡。
- 固定左上舞台的估算高度预算是模板坐标 `690 px`；卡片按内容自然高度计算。审计超出时，AI 按“内容高度收口→安全间距收紧→同组复合→摘要条→语义拆章”自动重排并重新审计，不要求用户确认，也不能依赖裁切。
- 章节间不能重叠；允许小于 0.35 秒的切换缝隙。
- 中文标题建议 2–8 个全角字符；正文不超过 2 行；列表项不超过 10 个全角字符。

### 精确组件示例

```json
{
  "type": "comparison",
  "fidelity_mode": "spoken-first",
  "relation_layout": "comparison",
  "layout_reason": "原话明确对照两种发布节奏",
  "card_size": "medium",
  "content_structure": "comparison-row",
  "size_reason": "单行对比观点需要完整层级，使用默认中卡",
  "label": "SHIPPING DAILY",
  "icon": "🚀",
  "title": "每天都在发新的版本",
  "marker": "⚠"
}
```

```json
{
  "type": "formula",
  "fidelity_mode": "spoken-first",
  "relation_layout": "formula",
  "layout_reason": "原话按主项、等号和结果依次建立公式关系",
  "card_size": "medium",
  "content_structure": "horizontal-relation",
  "size_reason": "公式关系使用最大宽度中卡，不突破画面33.4%",
  "parts": [
    {"id": "part-001", "text": "学了前置知识", "tone": "primary", "trigger_word_ids": ["word-000120"]},
    {"id": "part-002", "text": "=", "tone": "muted", "trigger_word_ids": ["word-000128"]},
    {"id": "part-003", "text": "不需要人教", "tone": "accent", "trigger_word_ids": ["word-000128"]},
    {"id": "part-004", "text": "→", "tone": "muted", "trigger_word_ids": ["word-000146"]},
    {"id": "part-005", "text": "自己探索一切场景", "tone": "accent", "trigger_word_ids": ["word-000146"]}
  ]
}
```

```json
{
  "type": "relation",
  "fidelity_mode": "spoken-first",
  "relation_layout": "narrative-path",
  "layout_reason": "原话使用“然后、交给、然后发布”表达叙事推进，并非形式因果",
  "card_size": "medium",
  "content_structure": "horizontal-relation",
  "size_reason": "四个节点加三个箭头需要在33.4%中卡内铺满一行",
  "label": "WORKFLOW",
  "title": "素材工作流",
  "items": [
    {"id": "node-001", "text": "录完素材", "trigger_word_ids": ["word-000120"]},
    {"id": "node-002", "text": "Agent", "incoming_connector": "→", "trigger_word_ids": ["word-000126"]},
    {"id": "node-003", "text": "剪辑", "incoming_connector": "→", "trigger_word_ids": ["word-000132"]},
    {"id": "node-004", "text": "发布", "incoming_connector": "→", "trigger_word_ids": ["word-000138"]}
  ]
}
```

## `semantic-reveal-timeline.json`

```json
{
  "schema_version": 1,
  "policy": "exact-spoken-reveal",
  "events": [
    {
      "id": "reveal-item-001",
      "segment_id": "chapter-001",
      "visual_id": "item-001",
      "unit": "item",
      "role": "instruction",
      "spoken_excerpt": "先识别完整的口述内容",
      "evidence_start_word_id": "word-000032",
      "evidence_end_word_id": "word-000043",
      "earliest_allowed_word_id": "word-000032",
      "trigger_word_id": "word-000035",
      "fully_visible_by_word_id": "word-000038",
      "hold_until_word_id": "word-000180",
      "timing_reason": "说到识别动作时增加第一项，观众不会提前得知后续步骤",
      "spoiler_check": {
        "passed": true,
        "reason": "画面只显示已经开始讲述的识别步骤，没有出现后续清理和动画结论"
      }
    }
  ]
}
```

字段规则：

- 每个 visual state、item、formula part 必须且只能对应一条 event。
- `spoken_excerpt` 必须等于 `evidence_start_word_id` 到 `evidence_end_word_id` 之间连续逐词文本，不能写概括。
- `trigger_word_id` 必须等于渲染计划中最早的有效 `trigger_word_ids`。
- 时间顺序必须满足：`earliest_allowed ≤ trigger ≤ fully_visible_by ≤ hold_until`。
- `trigger_word_id` 必须位于原话证据范围内。
- `hold_until_word_id` 必须覆盖章节末尾；若信息更早失效，应缩短章节或显式结束，不允许审计与实际持久层矛盾。
- 完整显示后必须留下最低阅读时间：state `1.0s`、item `0.75s`、formula part `0.60s`。
- `role`：`setup/explain/compare/conclude/recap/instruction/example`。
- 防剧透不能只写“已检查”，必须说明当前画面为什么没有提前透露后续信息。
