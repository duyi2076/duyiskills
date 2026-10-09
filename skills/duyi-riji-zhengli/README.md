# 杜一日记整理

把日记、语音转写或日常记录梳理成能回看的复盘，保留完整原文。整理实际发生的事、原文已有判断、任务状态与下一步，不替你补经历或把计划写成成果。

Skill 名称：`duyi-riji-zhengli`。

## 适用场景

- 口述日记很散，想按主题整理。
- 有“今日任务”和复盘，希望看清完成情况与下一步。
- 已有整理稿，只想修订特定部分或补充新原话。

## 运行条件

支持读取本地 Skills 的 AI 客户端即可。聊天交付不需要资料库、外部 Skill、登录账号或 API 密钥；保存文件时需要对应目录权限。

输入可以是你贴出的文字、附件或指定文件。Skill 整理现成记录，不自动转录音频，也不默认读取其他账号里的笔记。

## 安装

获取仓库后，安装整个文件夹，保留 `references/`：

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
mkdir -p ~/.agents/skills
cp -R skills/duyi-riji-zhengli ~/.agents/skills/
```

以上适用于首次安装。目标已有同名目录时，先保留自己的修改再更新。支持导入的客户端也可直接导入完整文件夹。

按所用客户端选择一个入口：

```bash
# Codex
mkdir -p ~/.codex/skills
ln -s ../../.agents/skills/duyi-riji-zhengli ~/.codex/skills/duyi-riji-zhengli
```

```bash
# Claude Code
mkdir -p ~/.claude/skills
ln -s ../../.agents/skills/duyi-riji-zhengli ~/.claude/skills/duyi-riji-zhengli
```

```bash
# Hermes
mkdir -p ~/.hermes/skills
ln -s ../../.agents/skills/duyi-riji-zhengli ~/.hermes/skills/duyi-riji-zhengli
```

入口已有同名文件或链接时先检查，不强制覆盖。安装后让客户端重新扫描，必要时重启会话；以能识别 `$duyi-riji-zhengli` 为准。

## 调用示例

聊天交付：

```text
使用 $duyi-riji-zhengli，整理下面这段日记。
保留完整原文，只根据原文判断任务状态，先在聊天里交付。
```

保存新整理稿：

```text
使用 $duyi-riji-zhengli，整理我指定的日记文件。
把整理稿另存到我指定的输出位置，保留原始文件。
```

局部修改：

```text
使用 $duyi-riji-zhengli，只修改这份已整理日记里的待办状态。
保留其他段落和原文附录，完成后给我看改动。
```

## 交付内容

| 部分 | 内容 |
|---|---|
| 开头总结 | 当日主线与实际进展 |
| 主题事项 | 动作、细节、判断和结果 |
| 想清楚的事 | 原文明确表达的认识 |
| 待办完成情况 | 已完成、未完成与尚未确认 |
| 下一步行动 | 原文已经提出的行动 |
| 记录边界 | 来源范围、必要疑点与状态 |
| 原始记录附录 | 分隔线后完整保留输入原文 |

无相应内容时不凑章节。附录保留口误、标点、空行和背景讲话；整理部分不把他人的话当作你的经历。

默认交付可复制的 Markdown。保存和重命名按你指定的范围执行，重要覆盖先展示待写内容；不直接发布或同步外部服务。

## 文件结构

```text
duyi-riji-zhengli/
├── SKILL.md
├── README.md
├── LICENSE
├── agents/openai.yaml
└── references/file-handling.md
```

## 许可

本 Skill 文档采用 [MIT License](LICENSE)。
