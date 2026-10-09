# 杜一账号定位

把“我可以讲什么、该讲给谁、主页怎么写”整理成可修改的账号方案。通过逐轮访谈，完成个人定位、赛道推导、账号定位、内容定位和主页包装。

Skill 名称：`duyi-zhanghao-dingwei`。

## 解决什么问题

- 有经历或正在探索新方向，但还没找到可持续的内容主线。
- 已经有账号，需要重新明确目标读者、账号价值和业务边界。
- 定位大致清楚，希望让昵称、简介、头像与内容方向一致。

适用于不同领域，不预设必须做 AI 内容。可以从已有经验出发，也可以从正在发生的真实探索出发。

## 如何使用

一次只问一个问题，收到回答就更新草案，让你直接修改。四阶段共覆盖 13 个核心项，前文已经回答的不用重复问；答不出可以跳过，结果会保留待确认状态。

```text
个人定位与候选赛道 → 账号定位 → 内容定位 → 账号包装
```

业务目标、主平台、公开边界和每周可投入时间都会问到。事实、偏好、建议和默认值分别记录，不把推荐方向写成已经发生的成绩。

## 运行条件

- 支持读取本地 Skills 的 AI 客户端。
- 聊天交付无需资料库、外部 Skill、API 密钥或额外运行依赖。
- 附带字符计数工具使用 Python 3 标准库；没有 Python 时可使用客户端已有的可靠计数工具，或明确标记尚未实际统计。
- 需要保存文件时，客户端须有对应目录的写入权限。

## 安装

先获取仓库：

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
```

把整个 `skills/duyi-zhanghao-dingwei/` 文件夹安装到客户端实际读取的 Skills 目录，保留 `references/` 与 `templates/`。支持导入的客户端也可以直接导入整个文件夹。

使用共享目录时，以下命令适用于首次安装。目标位置已有同名目录或入口时，先保留自己的修改，再按需要更新。

```bash
mkdir -p ~/.agents/skills
cp -R skills/duyi-zhanghao-dingwei ~/.agents/skills/
```

按使用的客户端选择对应入口：

```bash
# Codex
mkdir -p ~/.codex/skills
ln -s ../../.agents/skills/duyi-zhanghao-dingwei ~/.codex/skills/duyi-zhanghao-dingwei
```

```bash
# Claude Code
mkdir -p ~/.claude/skills
ln -s ../../.agents/skills/duyi-zhanghao-dingwei ~/.claude/skills/duyi-zhanghao-dingwei
```

```bash
# Hermes
mkdir -p ~/.hermes/skills
ln -s ../../.agents/skills/duyi-zhanghao-dingwei ~/.hermes/skills/duyi-zhanghao-dingwei
```

安装后让客户端重新扫描 Skills，必要时重启会话。明确调用 `$duyi-zhanghao-dingwei`，以客户端能识别此名称为准。

## 调用示例

从零开始，默认在聊天里拿结果：

```text
使用 $duyi-zhanghao-dingwei，帮我从零完成个人账号定位。
先在聊天里交付定位总览和账号包装，一次只问一个问题。
```

继续已有定位：

```text
使用 $duyi-zhanghao-dingwei，根据下面这份已有定位继续调整。
只使用我提供的材料，保留已确认事实和公开边界。
```

保存结果：

```text
使用 $duyi-zhanghao-dingwei，从零完成定位，最后把两份结果保存到我指定的输出目录。
写入前先给我看完整内容，等我确认后保存。
```

也可以指定现有的两份文件。继续定位时只局部修改本轮确认的字段，保留其他手工内容。

## 交付内容

| 结果 | 内容 |
|---|---|
| 定位总览 | 真实基础、候选赛道、目标读者、账号价值、业务约束、内容支柱、形式和前 5 条起步方向 |
| 账号包装 | 2 到 3 套昵称、简介与头像方案，主平台其他主页字段、内容主线、推荐方案和公开边界 |

默认交付可复制的 Markdown。保存时可参考附带的两份空白模板，文件名和保存位置由你指定。

具备可靠计数工具时，昵称与简介分别实际计数；无法统计时标记“未实际统计”。平台字段上限未知时会标明，不凭记忆承诺编辑器一定接受。

## 完成与边界

“访谈已完成”表示四阶段草案和核心项都已覆盖；“定位已最终确认”需要你看过两份完整结果并明确确认。你可以接受暂时保留待确认项，Skill 会保留这些项目的状态。

结果属于待实践检验的账号方案，不代表已有市场成绩。它不搜索对标账号，不生成整篇文章，不直接修改平台主页或发布内容。

## 文件结构

```text
duyi-zhanghao-dingwei/
├── SKILL.md
├── README.md
├── LICENSE
├── agents/openai.yaml
├── scripts/count_chars.py
├── references/
│   ├── interview-guide.md
│   ├── niche-guide.md
│   ├── content-form-guide.md
│   ├── profile-bio-guide.md
│   └── output-templates.md
└── templates/
    ├── 定位总览.md
    └── 账号包装.md
```

## 许可

本 Skill 文档与模板采用 [MIT License](LICENSE)。
