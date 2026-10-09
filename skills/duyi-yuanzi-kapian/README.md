# 杜一原子卡片

杜一原子卡片（`duyi-yuanzi-kapian`）把用户明确指定的访谈、答疑、课程逐字稿或对话记录，整理成可独立理解、可回查来源的原子卡片。它保留实际问题、回答、追问补充、判断变化、角色归属、判断力度、限制条件和未回答部分，默认不补充外部理论、方案或执行要求。

## 适用场景

- 整理一段或多段已明确指定范围的访谈、答疑或对话材料。
- 将同一问题的分散补充合并到一张卡，并保留各段来源位置。
- 区分提问者、主要回答者、受访者与其他参与者，保留每个人的回答与经历归属。
- 在用户明确要求后，先交付原始卡片，再另列编辑分析或编辑建议。

不适用于替用户补写答案、把假设写成案例、把建议写成结果、无授权读取私人资料库，或代替用户发布、同步和推送内容。

## 运行条件

- 可读取的原始材料，以及用户明确指定的文件、时间段或问题范围。
- 能够回查来源位置时使用实际行号、时间戳、标题或原文短句；无法定位时如实标明限制。
- 支持 Markdown 和 YAML frontmatter 的技能运行环境。无需额外依赖、脚本或联网服务。

## 首次安装

安装时保留完整文件夹结构，不要只复制 `SKILL.md`：

```text
duyi-yuanzi-kapian/
├── SKILL.md
├── README.md
├── LICENSE
├── agents/
│   └── openai.yaml
└── references/
    └── extension-analysis.md
```

以下命令适用于首次安装。在准备存放仓库的目录执行：

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
mkdir -p ~/.agents/skills
cp -R skills/duyi-yuanzi-kapian ~/.agents/skills/duyi-yuanzi-kapian
```

按实际使用的客户端建立入口：

```bash
mkdir -p ~/.claude/skills ~/.codex/skills ~/.hermes/skills
ln -s ../../.agents/skills/duyi-yuanzi-kapian ~/.claude/skills/duyi-yuanzi-kapian
ln -s ../../.agents/skills/duyi-yuanzi-kapian ~/.codex/skills/duyi-yuanzi-kapian
ln -s ../../.agents/skills/duyi-yuanzi-kapian ~/.hermes/skills/duyi-yuanzi-kapian
```

如果目标目录或入口已存在，先保留自己的修改，再决定更新方式，不直接覆盖。重启客户端或刷新技能列表后，调用 `duyi-yuanzi-kapian`。其他支持本地 Skill 的工具也可以安装完整目录。

## 调用示例

显式调用：

```text
使用 $duyi-yuanzi-kapian，整理我指定的访谈逐字稿，按具体问题拆成原子卡片，保留实际回答者、判断变化和来源位置，不加入延伸分析。
```

自然语言调用：

```text
请把这段答疑整理成杜一原子卡片。完整阅读我指定的材料，区分每位参与者，保留原回答和未回答的问题。
```

## 交付方式

默认在当前聊天中交付 Markdown，不自动保存到本地，不自动读取其他资料，不自动发布或同步。只有用户明确授权并指定保存位置时，才保存整理结果；保存前应遵守目标位置的规则并保留原始材料。

## 核心边界

- 先完整阅读本次指定范围，再决定拆卡边界；一张卡围绕一个可以独立理解和回应的具体问题。
- 同一问题的追问、补充、理由、必要例子、纠正和后续建议原则上放在同卡；不同人的独立问题另立卡。
- 用户指定的主要回答者明确确认身份后可使用第一人称；其他人沿用实际角色或原说话人标记。
- 保留原回答和判断变化，不把编辑归纳写成回答者观点，不把自述、假设、意愿、付款或建议写成独立核验的结果。
- 未实质回答的问题只列出问题和来源，不代为回答；延伸分析只能在用户明确要求后另列，不能回填原回答。
- 只处理用户提供或明确指定的材料；保存、延伸分析与对外发布各自需要相应授权。

## 文件结构

- `SKILL.md`：核心工作流、拆卡边界、忠实整理规则、输出结构和验收要求。
- `agents/openai.yaml`：客户端显示名称、短描述和默认调用提示。
- `references/extension-analysis.md`：用户明确要求延伸分析时使用的归属、证据和适用条件规则。
- `LICENSE`：MIT 许可证。

## 许可

本项目按 MIT License 发布，详见 [LICENSE](LICENSE)。
