# 抖音爆款视频结构拆解：最终报告模板

最终报告有两份产出，写完后再跑 finalize：

1. `完整拆解报告.md`：给人阅读和复核的完整论证。
2. `report-web.json`：写在 run 目录下，渲染 HTML 金字塔版的结构化内容源。HTML 页面按「结论先行、三个带走点」组织，所有模块内容来自这份 JSON。JSON 缺失时 HTML 降级为基础版（Hero + 正文 + 证据面板），所以缺了它流程不会断，但页面没有骨架。

两份内容必须一致：JSON 是报告的提炼，不允许出现报告里没有的判断。

理论基础单独见 `references/theory-basis/理论基础.md`。Markdown 的八个主要模块各追加一行 `理论视角：...`；`report-web.json` 不写理论字段，HTML 不显示理论标注。

## 报告结构（Markdown）

```markdown
# 《视频主题》完整拆解

## 一句话判断
这条视频表面在做什么，实际完成了什么，最强的是什么。允许点出「仍待验证」的部分。

## 证据边界
来源、视频规格、账号、发布时间、可见数据、数据限制、文案证据口径。

## 创作者层级定位
按四层价值阶梯模型归类：L1 实操教程 / L2 分析情报 / L3 同频旅程 / L4 哲学立旗。
只评这条视频呈现的层级，不给作者整个人定性。写明主体层级、带有的其他层元素、判断依据。

## 营销点：表面与底层
表面在做的：一句话。
底层在传递的：逐条列出，每条必须挂原话证据。不许主观猜测。

## 带走点 1：开篇怎么开
开篇结构标签（如 强比喻命名 + 双结果承诺）、开篇原话（逐字稿原文）、为什么有效。

## 带走点 2：一种表达结构
结构公式（一行，带原作者示范）；按论证转折切出的时间线；逐段拆解（每段：功能标签、时间段、原话、为什么有效）；机制分析（观众为什么停留/继续/相信/行动，各挂原话与出处）。

## 复用填空模板
把整条视频的结构变成可填空的骨架。每段：句子骨架 + 空位编号 + 每个空位的填写要求与原作者示范。示范只供理解，不照搬原作者的比喻、语气、句子壳。

## 带走点 3：一种 CTA
CTA 原话、CTA 结构拆解（免费资产/私域入口/连载悬念这类功能分层）、流量去向。

## 评论区在问什么
信号归类（名称、数量、评论样本），每条信号延伸一个可做的选题。评论只作需求线索。

## 不能照搬与待验证
逐条列出：结构可迁移但内容/承诺/技术点里哪些不能信、哪些缺证据。

## 证据文件
run 目录相对路径清单。
```

## report-web.json 结构

放在 run 目录根下，与 `完整拆解报告.md` 同级。顶层字段：

| 字段 | 内容 | 缺失时 |
|---|---|---|
| `verdict` | 一句话判断 | 页面降级基础版 |
| `verdict_emphasis` | 判断里要高亮的词组列表 | 不高亮 |
| `data_verdict` | 数据判断章（如 收藏是点赞的 1.2 倍） | 无徽章旁红章 |
| `creator_level.primary` | 主体层级编号（L1-L4） | 层级卡隐藏 |
| `creator_level.tinges` | 其他层元素，如 `{"L4": "造金句露出苗头"}` | 无苗头标注 |
| `creator_level.verdict` | 层级判断段落 | 无 |
| `marketing_points.surface` | 表面在做的一句话 | 营销卡隐藏 |
| `marketing_points.points[]` | `{title, tag, desc, quote}` 底层动作，quote 必须是原话 | 同上 |
| `hook` | `{tags[], quote, why, frame}` 开篇结构与首帧文件名 | 带走点 1 隐藏 |
| `structure.formula[]` | `{step, demo}` 结构公式步骤 | 公式带隐藏 |
| `structure.timeline[]` | `{range, fn, kind, seconds}`，kind ∈ hook/setup/method/turn/cta | 色带隐藏 |
| `structure.nodes[]` | `{fn, kind, range, frame, stamp, quote, why}` 逐段卡 | 段卡隐藏 |
| `structure.mechanisms[]` | `{title, quote, attribution, desc}` 机制卡 | 机制区隐藏 |
| `fill_blank[]` | `{label, script, notes}`，script 里用 ①②③ 标空位 | 填空区隐藏 |
| `cta` | `{quote, pieces[{label,desc}], flow[], flow_hot_index, flow_note}` | 带走点 3 隐藏 |
| `comment_signals[]` | `{name, count, sample, topic}` 信号与延伸选题 | 信号区隐藏 |
| `critiques[]` | `{title, desc}` 批判清单 | 批判区隐藏 |

模块整体缺失时对应区块自动隐藏，不留空壳。`frame` 字段填 `frames/` 目录下的文件名（如 `0000-00-00-00.jpg`）。

## 写作硬约束

- 原话必须来自逐字稿，按时间段取；改写过的句子不许加引号。
- 层级、营销点、机制、批判都是分析判断，由 agent 产出，脚本不编造。
- 填空模板只给骨架和填写要求，不生成成稿；没有原话支撑的判断写「素材不足」。
- 每个主要模块结论区块追加一行理论视角。理论只用于解释和命名，不作为证据，也不展开理论史。
- 理论视角必须使用类比式表达，不写成“源自”“继承了”或“该理论证明了”这类师承或证明关系。
- 理论出处存在争议时保留限定语，尤其是 AIDA 的起源归属和评论需求的四类工作映射。
- 其余口径沿用 `references/breakdown-quality-standard.md` 与 `references/layered-breakdown-v2.md`。
