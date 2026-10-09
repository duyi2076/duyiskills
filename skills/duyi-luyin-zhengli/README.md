# 杜一录音整理

`duyi-luyin-zhengli` 把用户指定的现成转写稿、访谈记录、多人答疑或聊天原文，整理成可回查来源的完整主题整理稿和候选清单。

它解决的是长对话整理时容易出现的几个问题：把账号所有者误当成发言或经历主体，把建议写成执行结果，把举例写成真实数据，把后续修正漏掉，或只给出结论却无法回查原文。它保留角色、原判断强度、条件、动作顺序、来源 ID、时间或行号、未回答部分和“归属待核”状态。

输入必须是用户已经取得的文字转写或对话原文。本 Skill 不自动转录、不下载录音、不回听音频，也不声称完成事实核验。

## 安装

支持读取本地 Skills 的客户端即可使用，无需外部 Skill、登录账号或 API 密钥。聊天交付只需可读的指定文字材料；保存文件需要对应目录权限。

保留完整目录结构，首次安装可在准备存放仓库的目录执行：

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
mkdir -p ~/.agents/skills
cp -R skills/duyi-luyin-zhengli ~/.agents/skills/duyi-luyin-zhengli
```

按实际使用的客户端建立入口：

```bash
mkdir -p ~/.claude/skills ~/.codex/skills ~/.hermes/skills
ln -s ../../.agents/skills/duyi-luyin-zhengli ~/.claude/skills/duyi-luyin-zhengli
ln -s ../../.agents/skills/duyi-luyin-zhengli ~/.codex/skills/duyi-luyin-zhengli
ln -s ../../.agents/skills/duyi-luyin-zhengli ~/.hermes/skills/duyi-luyin-zhengli
```

目标目录或入口已存在时，先保留自己的修改再决定更新方式，不直接覆盖。重启客户端或刷新技能列表后，调用 `duyi-luyin-zhengli`。后续只维护共享目录中的权威原件；支持导入的客户端也可以导入完整文件夹。

## 调用示例

```text
使用 $duyi-luyin-zhengli，完整阅读我指定的转写稿，整理出主题主线、来源定位和候选清单。区分账号所有者、参与者和具体经历主体；保留原回答、后续修正、未回答问题和归属待核状态。默认在聊天中交付，不写入任何目录。
```

如果用户明确指定保存目录，应先读取该目录的真实规则，再按授权写入并读回核验。没有私人知识库也可以直接在聊天中使用。

## 完整输出

默认输出包括来源范围、实际阅读范围、转写覆盖和是否回听、角色边界、整体主线、主题或问答索引、分主题整理、候选清单、未回应问题、转写疑点、隐私边界和未交付范围。原始资料、整理结果、候选区和已采纳目标职责保持清楚区分。候选记录资产类型、具体内容、真实来源位置、证据性质、拟归属、待确认状态和公开范围。

候选不是采纳结果。建议、举例、付款、交付结果、实践验证和公开许可分别记录，不能互相推断。账号所有者不等于录音参与者，参与者也不等于具体经历或发言主体；归属不明时仍可整理，但标为“归属待核”。

## 保存边界

默认只在聊天中交付，不自动归档、分流、移动、改名、更新索引或写入知识库。用户明确指定目录和动作后，才按其真实规则保存；原件保持不可变，来源 ID、时间或行号和链接必须可回查。未经授权的第三方资料默认保持原隐私范围。

## 文件结构

```text
duyi-luyin-zhengli/
├── SKILL.md
├── README.md
├── LICENSE
├── agents/
│   └── openai.yaml
└── references/
    ├── ingestion.md
    └── output-contract.md
```

## 许可

本项目按 MIT License 发布，详见 [LICENSE](LICENSE)。
