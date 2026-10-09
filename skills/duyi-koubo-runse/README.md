# 杜一口播润色（duyi-koubo-runse）

把已有中文口播稿改得更容易听懂、更顺着说下去，保留作者的事实、观点和口吻。

## 解决什么问题

检查段落接不上、同一信息反复说、指代含糊、语序难说清，以及口播指向与必要画面不同步。五项标准逐项给出判断和原文依据；发现问题后提供具体改法。

适合完整稿件或明确指定的片段。只有选题时先列缺少的正文，不凭空诊断。它不预测播放量、完播率或传播效果。

## 安装

下载 [duyiskills](https://github.com/duyi2076/duyiskills)，或在终端获取：

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
mkdir -p ~/.agents/skills
cp -Rn skills/duyi-koubo-runse ~/.agents/skills/
```

以上适用于首次安装，复制命令保留已有文件。更新时先备份自己的修改，再对照新版本替换，避免把两个版本混在一起。

随后为实际使用的工具配置入口。例如 Codex：

```bash
mkdir -p ~/.codex/skills
ln -s ../../.agents/skills/duyi-koubo-runse ~/.codex/skills/duyi-koubo-runse
```

Claude Code 的入口是 `~/.claude/skills/`，Hermes 的入口是 `~/.hermes/skills/`，软链接同样指向 `~/.agents/skills/duyi-koubo-runse`。已有同名入口时先检查目标，安装后在新会话中确认工具能读取 Skill。

也可直接把完整文件夹放入所用工具的 Skill 目录。运行只需要能读取 Markdown 附件的 AI 工具，无需 API 密钥、浏览器登录或额外运行软件。

## 怎么调用

```text
帮我润色下面这份口播稿，保留我的观点、事实和口吻：

【粘贴稿件】
```

也可明确说「用 duyi-koubo-runse」。只想找问题时说「只诊断，先不改稿」；需要录制版本时说「按已采纳的修改给净稿」。

## 输入与交付

输入已有稿件，可附需要保留的表达、目标观众和画面说明；这些信息只有会改变建议时才补充。

默认润色交付五项检查、完整原位标记稿和改动清单。替换、删除、合并都保留原文，方便逐处核对。只要求检查时给诊断和局部建议；明确要求净稿时按用户要求提供。

## 与内容诊断配套

本 Skill 可独立完成五项口播检查。判断观点、承诺和论据是否成立，可配套安装 [杜一内容诊断](../duyi-neirong-zhenduan/README.md)。未安装时将相关内容问题列为待处理，继续完成口播检查。

争议性、尖锐表达和强烈立场本身不是删改理由，保留作者观点和锋芒。为了顺口而新增事实、改变因果或结论强弱，需要作为内容建议单独说明；用户采纳后再改，不混入表达润色。

## 文件与许可

- [SKILL.md](SKILL.md)：五项检查、标记式改稿与净稿要求。
- [agents/openai.yaml](agents/openai.yaml)：工具显示名称与默认调用。
- [LICENSE](LICENSE)：MIT License，覆盖本 Skill 原创文档与演示说明。
