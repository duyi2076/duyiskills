# 产品客户沟通分析

“产品客户沟通分析”（`duyi-kehu-goutong-fenxi`）是一个以欧文·戈夫曼（Erving Goffman）拟剧分析为理论来源的公开 Skill。它把一段沟通拆成事实材料、角色与情境、前台与后台、信息边界、多种解释和沟通建议。

## 用途与场景

- 分析客户咨询、询价、异议、需求澄清与交付反馈。
- 区分客户实际说了什么、可能顾虑什么以及尚未确认的需求。
- 检查承诺、样稿、能力和交付流程是否支撑对客户的表达。
- 在说法与行为不一致时列出相容解释，准备有依据的追问与回复。

## 运行条件

需要支持 Markdown Skill 的 Codex、Claude Code 或 WorkBuddy 环境。Skill 本身不需要网络、账号、第三方 API 或额外依赖；分析所需的原始材料由调用者提供。

## 安装

首次安装时，把整个 `duyi-kehu-goutong-fenxi/` 目录放入 `~/.agents/skills/`。如果客户端支持 Skill 目录发现，安装后即可自动发现；三客户端之间是否建立软链由使用者按本机管理方式决定，并非运行条件。不要只复制 `SKILL.md`，否则支持资料的引用会失效。

首次安装命令：

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
mkdir -p ~/.agents/skills
cp -R skills/duyi-kehu-goutong-fenxi ~/.agents/skills/
```

按实际使用的客户端建立入口：

```bash
mkdir -p ~/.claude/skills ~/.codex/skills ~/.hermes/skills
ln -s ../../.agents/skills/duyi-kehu-goutong-fenxi ~/.claude/skills/duyi-kehu-goutong-fenxi
ln -s ../../.agents/skills/duyi-kehu-goutong-fenxi ~/.codex/skills/duyi-kehu-goutong-fenxi
ln -s ../../.agents/skills/duyi-kehu-goutong-fenxi ~/.hermes/skills/duyi-kehu-goutong-fenxi
```

同名目录或入口已存在时先保留自己的修改，再决定更新方式。安装后刷新技能列表或重启客户端，新会话中确认可识别 `$duyi-kehu-goutong-fenxi`。

## 调用例

直接描述任务即可，例如：

> 请用产品客户沟通分析拆解下面这段对话。先列事实材料和证据缺口，再分析角色、情境、前台后台，给出至少两种解释和三条沟通建议。不要猜测任何人的真实动机。

也可以显式使用 `$duyi-kehu-goutong-fenxi`，然后附上对话、场景和希望解决的问题。

## 交付与局限

默认交付包含事实材料表、角色与情境、前台与后台、多种解释及其依据和缺口、沟通建议。它不提供读心、人格诊断或事实调查；“流露”“后台”“不协调角色”都是分析线索，不是已证实动机。拟剧理论也不能单独解释制度、资源、技术或宏观权力。分析结论的可靠度取决于材料完整度，重大决定应再做独立核验。

## 来源与许可

理论来源为欧文·戈夫曼《日常生活中的自我呈现》（*The Presentation of Self in Everyday Life*）。支持资料沿用公开仓库 [duyi2076/goffman-dramaturgy](https://github.com/duyi2076/goffman-dramaturgy) 中的拟剧分析材料，并在本包中保留其章节、术语、模式与速查资料。许可文本见 [LICENSE](LICENSE)，来源说明见 [NOTICE](NOTICE)。
