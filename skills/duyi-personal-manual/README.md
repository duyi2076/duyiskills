# 个人使用说明指南

`duyi-personal-manual` 帮你把真实经历和可分享的资料整理成一份给新读者的介绍：让对方认识你、取到一份有用的小礼物，并知道怎样开始使用和继续了解你。

分享物可以是模板、清单、工具、方法、教程或案例。你没有整理好资料时，可以从短访谈开始，一次回答一个问题。

## 适用场景

- 刚从公开内容认识你的读者，想知道你是谁、做过什么、现在在做什么。
- 你有自己常用的资料或做法，想整理成一份见面礼。
- 你已经有个人介绍，希望补上资源清单、取用方法和真实案例。
- 你只想写个人介绍，可以按这个范围使用。

## 提供什么

说明这份介绍想给谁看，附上已有笔记、作品、文档、资料目录或一段口述。有现成资源时说明本人怎样使用，以及哪些内容可以分享。

没有资料时可以直接说“我没准备资料，先采访我”。有真实做法但没有文件时，会先整理最小清单或短指南供你审阅，再确认分享范围和取用方式。

## 运行条件

需要能读取本地 Skill 目录的 AI 客户端。仅整理文案不需要平台账号或 API 密钥。

生成本地 HTML 时，内附脚本需要 Python 3 和 `markdown-it-py`。创建飞书文档、读取外部材料或编辑图片时，使用客户端已有的对应能力与权限；这些连接能力由使用者配置。

## 安装

首次安装时复制完整目录，包括参考文件和渲染脚本。同名目录已经存在时，先保留自己的修改，再合并更新。

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
mkdir -p ~/.agents/skills
cp -R skills/duyi-personal-manual ~/.agents/skills/
```

按实际使用的客户端建立入口，已有同名入口时先检查其去向：

```bash
mkdir -p ~/.claude/skills ~/.codex/skills ~/.hermes/skills
ln -s ../../.agents/skills/duyi-personal-manual ~/.claude/skills/duyi-personal-manual
ln -s ../../.agents/skills/duyi-personal-manual ~/.codex/skills/duyi-personal-manual
ln -s ../../.agents/skills/duyi-personal-manual ~/.hermes/skills/duyi-personal-manual
```

其它客户端按其本地 Skill 目录规则接入。安装后刷新技能列表或重启客户端，在新会话确认能识别 `$duyi-personal-manual`。

## 怎么调用

有资料时：

> 用个人使用说明指南，根据我提供的资料，给刚认识我的读者做一份个人介绍与自用资料指南。挑选能帮到他们的小礼物，写清楚在哪里取得、第一次怎么用，以及怎样继续了解我。

没有准备资料时：

> 用个人使用说明指南。我想给新读者一份介绍和小礼物，但还没准备资料。先采访我，一次只问一个问题。

也可以显式使用 `$duyi-personal-manual`，附上读者、用途、资料入口和已选呈现形式。

## 结构与交付

默认阅读顺序：简短认识本人 → 小礼物与取用方法 → 经验来源 → 现在帮助推进的事 → 真实案例 → 适合谁 → 怎么连接。

默认交付一份合篇可编辑 Markdown、大字单栏 HTML、可分享的实际资源或真实入口、对应配图和阅读入口。简介版按快速转发需要或明确要求另做。指定飞书时交付对应飞书文档及本地正文与配图。

资源条目写清适用场景、准备材料、第一步、可得到的东西与必要限制。没有案例或付费服务时，按现有材料合并或省去相应章节。

素材依据、试读意见和未验证项保存在独立内部记录；对外正文只放使用者可以确认并公开的内容。

## 单独生成 HTML

在本 Skill 目录创建专用 Python 环境并安装渲染依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install markdown-it-py
.venv/bin/python scripts/render_article.py --input guide.md --output guide.html
```

以上环境路径适用于 macOS 和 Linux；Windows 使用该虚拟环境中的 Python 执行相同脚本。

脚本支持 Markdown 图片和 Obsidian 图片嵌入。图片放在输入文档目录内，或通过 `--asset-root` 指定获准的图片目录。正文基准字号为 20px，保留浏览器缩放，图片支持点按放大。默认拒绝覆盖已有输出。

图片内嵌到 HTML，模板等资源链接仍需对应文件或可用外部入口。转发时一并提供所需资源文件。

## 资源与许可

资源是否本人自用、允许分享、实际可取得，以及使用后的结果，分别按材料核对。新整理的草稿需经本人审阅，不能写成已经验证或已可领取的资源。

本目录当前未附独立 LICENSE 文件。HTML 渲染的外部依赖 [markdown-it-py](https://github.com/executablebooks/markdown-it-py) 采用 MIT 许可；使用者提供的素材和分享物按其原有许可处理。
