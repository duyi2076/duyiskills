# Editorial Illustration Style

这套风格用于杜一公众号封面、首图和正文插图。目标是商业编辑插画，不是 AI 卡片、PPT 信息图、金句海报或可爱角色图。

## 适用场景

- 公众号封面、文章首图。
- 正文里的认知锚点、商业隐喻、状态图。
- 抽象概念需要被转成一个“一眼能感到”的画面时。

不适用：

- 需要严谨数值图、真实截图、流程图、表格、对比图。
- 用户明确要“小黑”荒诞产品草图。
- 用户明确要金句海报。

## 视觉 DNA

- 低饱和深青绿、墨黑、米白为主，少量朱红点睛。
- 背景有暗部层次和空间感，但不要科技蓝光、霓虹、玻璃拟态。
- 人物低细节、无脸或弱表情，动作清楚，情绪克制。
- 常见构图：群体等待、接力奔跑、被路径牵引、围观、搬运、排队、横穿四层系统。
- 红色线条只表示路径、判断、变化、风险、连接，不做普通装饰。
- 标题字体偏衬线/宋体，放在左下或底部暗区；正文插图尽量少字或无字。
- 留白要大。画面先像文章插画，再像封面。

## 内容转译流程

先把文章压成一句话：

```text
这篇文章讲的是：谁在什么场景下，经历了什么变化。
```

再提炼一个场景隐喻：

```text
抽象概念：一人公司 AI Native 内容系统
场景隐喻：一个人站在四层工作台之间，红色路径把用户问题、文档、内容、产品连接起来。
```

最后才决定图型：

| 图型 | 画面重点 | 字 |
|---|---|---|
| 21:9 首图 | 完整场景 + 标题 | 短标题 + 可选英文副标题 |
| 1:1 封面/分享图 | 强主体 + 强判断 | 短标题 |
| 正文 16:9/3:4 | 一个段落隐喻 | 少字或无字 |

## 常见隐喻库

优先从动作和关系里找画面，不从框架名里找画面。

| 抽象概念 | 可用场景隐喻 |
|---|---|
| 内容变产品 | 纸页、用户反馈、文档被一条红色市场动线牵起来 |
| AI 横向赋能 | 一条红色电流/路径横穿多层暗色地形 |
| 定位筛选 | 一个基础闸门堵住或放行后面的系统 |
| 规划排期 | 多个远处塔楼被一条路径串联，不画排期表 |
| 创作流水线 | 人物搬运纸页、打开暗门、点亮路径，不画流程节点 |
| 运营反馈 | 红线回流，人物在远处接住信号，不画仪表盘 |

正文插图只抓一个动作隐喻。不要把“定位 / 规划 / 创作 / 运营”四个词都摆成模块；如果需要出现文字，控制在 0-4 个短词。

## Prompt 骨架

用于 image backend 的内部 prompt 可以按这个骨架写：

```text
Generate a commercial editorial illustration for a Chinese WeChat article.

Core idea:
{一句话主题}

Scene metaphor:
{场景隐喻}

Composition:
{21:9 / 1:1 / 16:9 / 3:4} editorial illustration, large negative space, low-detail faceless people, clear action, a single red path line showing {路径/判断/变化}.

Style:
dark teal and ink-black atmosphere, muted cream highlights, restrained cinnabar red accent, flat vector-like editorial illustration, business magazine illustration mood, subtle depth, not cute, not infographic, not PPT, not UI dashboard, not cyberpunk, no tables, no charts, no decorative cards.

Text:
{封面可指定短标题；正文插图尽量 no text}
```

## 杜一渲染器约束

封面/首图推荐使用杜一自有 Editorial Illustration brief：

- `format`: `wide` for 21:9, `square` for 1:1
- `role`: `hero` / `cover` / `inline`
- `image.src`: 由 image backend 生成的无标题、无编号、无工作标签的原始场景图
- 左上角不放“公众号首图 / 分享封面 / 正文配图”等工作标签
- 右上角编号默认不放；只有系列专栏、封面合集或明确需要“第几张/第几期”时，才设置 `issue`
- 右下角印记默认不放；只有明确需要杜一视觉落款时，才设置 `seal`

不要把已经渲染过的封面成品、带标题的样张或风格锚点图再次放进 `image.src`。标题、英文副标题、编号、印章只能由杜一自有渲染器加一次；否则会出现标题重叠、编号重叠和工作标签残留。

模板：

```text
$SKILL_ROOT/references/duyi-wechat-peitu/templates/duyi-editorial-illustration-brief.json
```

渲染：

```bash
node "$SKILL_ROOT/references/duyi-wechat-peitu/scripts/render_duyi_editorial_illustration.mjs" brief.json --out output/editorial
```

## 失败信号

- 第一眼像课程 PPT、流程图、卡片组、信息图。
- 画面只有“漂亮背景 + 大标题”，没有场景隐喻。
- 红色线条变成随手装饰。
- 正文插图也像封面，抢文章节奏。
- 正文插图出现等距模块、层级标题栏、完整框架说明，读起来像一页课件。
- 直接模仿某个商业媒体的品牌版式、logo、栏目视觉。
- 人物过于真实、可爱、表情化或网感插画。
