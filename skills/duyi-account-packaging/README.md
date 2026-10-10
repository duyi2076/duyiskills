# 杜一账号包装

`duyi-account-packaging` 基于已有事实和方向制作账号昵称与主页简介，核对读者关注理由、个人辨识度、可信线索和字符容量，交付可直接复制的文案。

## 解决的问题

- 已有个人经历与定位，希望把它们表达为昵称和简介。
- 简介写得笼统、缺少关注理由，或压缩后丢了个人特点。
- 昵称已经确定，只想修改简介或适配不同平台。
- 希望检查读者是否误解内容方向或服务范围。

本 Skill 处理昵称和文字简介，不包含头像、封面制作或完整定位访谈。若方向尚未明确，先指出关键缺口；材料足够时直接起稿。

## 运行条件

需要支持 Markdown Skill 的 AI 客户端，以及用于实际计数的 Python 3。计数脚本只用标准库，不需要安装 Python 包。常规任务不需要平台账号、API 密钥或登录状态。

原始材料由使用者提供或明确授权读取。只确认文案不代表授权修改平台资料。

## 安装

首次安装时复制完整目录，包括参考文件和计数脚本：

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
mkdir -p ~/.agents/skills
cp -R skills/duyi-account-packaging ~/.agents/skills/
```

按实际使用的客户端建立入口：

```bash
mkdir -p ~/.claude/skills ~/.codex/skills ~/.hermes/skills
ln -s ../../.agents/skills/duyi-account-packaging ~/.claude/skills/duyi-account-packaging
ln -s ../../.agents/skills/duyi-account-packaging ~/.codex/skills/duyi-account-packaging
ln -s ../../.agents/skills/duyi-account-packaging ~/.hermes/skills/duyi-account-packaging
```

同名目录或入口已存在时先保留自己的修改，再决定更新方式。安装后刷新技能列表或重启客户端，在新会话中确认可识别 `$duyi-account-packaging`。

## 怎么调用

> 用杜一账号包装，根据下面的真实资料制作昵称和简介。给我三种昵称候选、一个推荐，以及抖音／小红书共用长版和 B 站短版。事实不够时先问我一个关键问题。

已有昵称时可以说：

> 昵称已经定为「我的账号名」。只调整简介，用我提供的材料，保留已采纳的表达，适配本轮要求的字符范围。

也可显式使用 `$duyi-account-packaging`，附上现有昵称、个人材料、内容方向和平台要求。

## 交付内容

- 昵称未定时默认给三个不同候选与一个推荐；已定昵称沿用。
- 默认简介为抖音／小红书共享长版 100 至 160 字符，B 站短版不超过 80 字符。用户只要一个平台或给定其他容量时采用本轮条件。
- 每版分别给实际字符核对，以及个人辨识度、关注理由、可信程度、记忆点与整体性、阅读与代入感五项审核依据。
- 材料不足时逐项补问；关键材料仍缺时说明缺口，不编造身份、成绩或承诺。
- 独立读者试读按需进行，并明确是模拟反馈。

默认字符范围是本包的交付配置，不能当作实时平台官方限制。最终能否填入，以实际编辑器接受结果为准。

计数工具可以单独使用。在 Skill 目录执行：

```bash
python3 scripts/count_chars.py --file /path/to/final-bio.txt --min 100 --limit 160
```

原文中的标点、空格、字母与换行都计入。工具默认统计 Unicode 码点，并同时报告 UTF-16 单元数；支持 `--unit utf16`。没有下限或上限时省略对应参数。

## 局限与许可

不保证昵称可用、涨粉或转化效果，也不自动更新账号资料。来源、计数和审核说明位于正文之外；实际对外简介只包含使用者可确认的内容。

[简介示例](references/bio-examples.md) 使用杜一本人的账号包装，保留昵称、长版与短版的确认状态。其他使用者只参考写法，不借用示例中的个人事实。文档和计数工具采用 [MIT License](LICENSE)。
