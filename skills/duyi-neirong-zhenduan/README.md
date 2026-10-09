# 杜一内容诊断（duyi-neirong-zhenduan）

按杜一的内容标准检查选题、文章和口播稿，找出影响用户理解、相信和使用内容的具体缺口。

## 解决什么问题

判断用户能否认出自己的困境、方法是否简单、亲身经历是否支撑判断、正文是否兑现承诺，以及论据能否支持结论。

十项标准覆盖用户代入、低行动成本、承诺吸引力、亲历经验、具体支撑、正文兑现、试用价值、概念推理、标题封面和形式适配。它采用作者明确的内容立场，不把这些立场宣称为所有体裁的普遍定律，也不预测流量或保证爆款。

## 安装

下载 [duyiskills](https://github.com/duyi2076/duyiskills)，或在终端获取：

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
mkdir -p ~/.agents/skills
cp -Rn skills/duyi-neirong-zhenduan ~/.agents/skills/
```

以上适用于首次安装，复制命令保留已有文件。更新时先备份自己的修改，再对照新版本替换，避免把两个版本混在一起。

随后为实际使用的工具配置入口。例如 Codex：

```bash
mkdir -p ~/.codex/skills
ln -s ../../.agents/skills/duyi-neirong-zhenduan ~/.codex/skills/duyi-neirong-zhenduan
```

Claude Code 的入口是 `~/.claude/skills/`，Hermes 的入口是 `~/.hermes/skills/`，软链接同样指向 `~/.agents/skills/duyi-neirong-zhenduan`。已有同名入口时先检查目标，安装后在新会话中确认工具能读取 Skill。

也可直接把完整文件夹放入所用工具的 Skill 目录。运行只需要能读取 Markdown 附件的 AI 工具，无需 API 密钥、浏览器登录或额外运行软件。

## 怎么调用

```text
帮我诊断下面这份内容，逐项给出原文依据和具体修改建议：

【粘贴选题或正文】
```

也可明确说「用 duyi-neirong-zhenduan」。只有选题时诊断内容设计，未提供的正文、经历或封面标待补。已要求改稿时直接执行，并保留原文与新旧对照。

## 输入与交付

输入选题、文章、口播稿或明确指定的片段，可附已知的目标读者、内容目标、平台、产品资料和封面。只询问影响判断的关键缺口。

交付总体判断、十项标准的判断与原文依据，以及按优先级排列的具体修改建议。各项可判通过、部分通过、未通过、待补或不适用，没有问题时说明通过依据。

真实经历、数字和产品信息来自用户材料；缺少时指出需要补什么，不替用户编写经历。附件中的案例明确为虚构演示，只说明判断方式。

## 与口播润色配套

本 Skill 可独立完成十项内容诊断。段落承接、重复、指代、说话节奏和画面同步，可配套安装 [杜一口播润色](../duyi-koubo-runse/README.md)。同时要求两项工作时先处理内容，再修表达；未安装配套 Skill 时列明待处理问题。

## 文件与许可

- [SKILL.md](SKILL.md)：十项内容标准与改稿边界。
- [references/diagnosis-examples.md](references/diagnosis-examples.md)：虚构演示稿与标准说明。
- [agents/openai.yaml](agents/openai.yaml)：工具显示名称与默认调用。
- [LICENSE](LICENSE)：MIT License，覆盖本 Skill 原创文档与演示说明。
