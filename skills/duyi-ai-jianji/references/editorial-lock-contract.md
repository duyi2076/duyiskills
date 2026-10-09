# 文字母版锁定合同

## 目标

用户只审核一次。AI 必须在这次审核前完成全部文字判断；审核后只允许执行用户明确提出的修改，然后立即锁定。剪辑、字幕和动画只能读取锁定母版。

## 唯一权威顺序

1. 豆包逐词 ASR 与源视频指纹校验。
2. AI 对照音频和全文生成 `editorial-review-plan.json`。
3. 机器验证删词、纠错、完整句、字幕 cue、真实字体宽度、删词压缩后的 cue 时长、自然起止词和全词覆盖。
4. 生成 `editorial-review.md/json`。
5. 用户唯一一次审核。
6. AI 写回用户提出的修改并运行 `lock-review`。
7. 生成 `locked-editorial-master.json` 与所有确定性派生文件。
8. 后续自动剪辑、字幕、视觉导演、渲染和 QA 只读母版。

## `editorial-review-plan.json`

```json
{
  "schema_version": 1,
  "policy": "one-human-review-before-lock",
  "ai_review_complete": true,
  "inputs": {
    "normalized_transcript_sha256": "...",
    "source_media_sha256": "...",
    "asr_integrity_sha256": "..."
  },
  "subtitle_font_preset": "reference-caption",
  "term_hints": ["Claude", "Agent", "ClawBot"],
  "corrections": [],
  "preserved_uncertain": [],
  "unresolved": [],
  "speaker_issues": [
    {
      "start_word_id": "word-000100",
      "end_word_id": "word-000101",
      "decision": "preserve_original",
      "reason": "这是说话者实际说出的口误，不是 ASR 误听"
    }
  ],
  "deletions": [
    {
      "id": "deletion-001",
      "start_word_id": "word-000001",
      "end_word_id": "word-000001",
      "kind": "filler",
      "reason": "开篇非语义填充音"
    }
  ],
  "sentences": [
    {
      "id": "sentence-001",
      "start_word_id": "word-000002",
      "end_word_id": "word-000040",
      "cues": [
        {
          "id": "sentence-001-cue-01",
          "start_word_id": "word-000002",
          "end_word_id": "word-000020",
          "boundary_reason": "clause"
        },
        {
          "id": "sentence-001-cue-02",
          "start_word_id": "word-000021",
          "end_word_id": "word-000040",
          "boundary_reason": "sentence"
        }
      ]
    }
  ],
  "semantic_map": {
    "schema_version": 1,
    "policy": "spoken-semantic-map",
    "propositions": []
  }
}
```

## 硬规则

- `ai_review_complete=true` 代表 AI 已完成所有文字决定，不代表用户已确认。
- `corrections` 只允许明确 ASR 误听，沿用 `word-level-asr-errors-only` 合同。
- 说话者实际说错、读错、事实错或没说完，写入 `speaker_issues` 并固定保留原话；不得静默改字。
- `deletions.kind` 只允许 `filler/repeated_retake/incomplete_start/explicit_user_removal`。
- 所有保留词必须被 `sentences` 按原顺序恰好覆盖一次；每个句子内又必须被 `cues` 恰好覆盖一次。
- cue 的文字从纠错后的逐词稿确定性生成，计划不得另写润色文本。
- cue 必须在用户审核前同时通过真实字体像素宽度、最大全角单位、自适应节奏预计时长和自然起止词合同；`3.8s` 是优选时长，经保守停顿压缩与局部节奏处理后允许进入 `3.8–5.5s` 区间，预计仍超过 `5.5s` 才视为超限。任一失败都不得生成可供确认的审核包；超限时只在完整分句或自然短语边界拆分。
- 同一 `sentence_id` 的全部 cue 拼接后必须等于 `full_sentence_text`。
- 删除词用下划线展示；纠正词直接显示并附原转写和原因；最终 cue 换行按成片原样展示。
- 用户修改后不创建第二轮审批。`lock-review` 会重建机器包用于校验，但不再次请求用户确认。
- `locked-editorial-master.json` 的 `confirmation.review_count` 必须恒为 `1`。
- `asr-corrections.json`、`corrected-transcript.json`、`cut-plan.json`、`caption-units.json`、`semantic-map.json` 必须携带当前 `locked_text_master_sha256`。
- 自动 QA 可以阻断，但不得改写母版；若必须改变已锁定文字，重新回到用户，不得暗改。
