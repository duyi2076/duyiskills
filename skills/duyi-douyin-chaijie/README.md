# 杜一抖音拆解

Skill 标识：`duyi-douyin-chaijie`。

把公开抖音视频链接整理为可回查的证据、深度拆解报告和一个可直接打开的 HTML 页面。

## 解决什么问题

看完一个对标视频，往往只能复述内容，难以说明它为什么让人停下、继续看、相信或行动。本 Skill 把转写、关键帧、公开页面与评论放在同一条证据链中，再由 AI 分析：

- 开篇如何吸引注意，论证如何推进，转折如何承接。
- 创作者展示了什么能力，完成了什么营销或信任动作。
- 哪些结构可以迁移为填空模板，哪些表达和承诺需要自己的材料。
- 评论暴露了哪些追问、争议和后续选题。

适合单条视频对标、结构学习、内容复盘和评论选题。报告包含缺证据与适用边界说明。

## 交付内容

| 交付 | 内容 |
|---|---|
| 页面证据 | 公开可见信息、互动数据、评论与详情页截图 |
| 视频与转写 | 下载的视频、带时间戳的转写和关键帧 |
| 深度拆解 | 开篇、论证单元、留存、营销、CTA、结构槽位与填空模板 |
| Markdown 报告 | 可编辑的完整拆解，主要模块附理论视角和证据位置 |
| HTML 报告 | 自包含的阅读页面，整合最终结论与本地证据，不展示理论标注 |

脚本生成的是证据和自动初稿。最终分析需要 Agent 读取实际转写、关键帧和页面证据后完成。

## 安装

### 使用安装器

需要 Node.js/npm。使用 [Skills 安装器](https://github.com/vercel-labs/skills)，从合集里只选择这个 Skill：

```bash
npx skills add duyi2076/duyiskills --skill duyi-douyin-chaijie -g
```

按提示选择实际使用的客户端。已有同名安装时，先备份自己的修改和包外配置。

### macOS / Linux 手动安装

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills

DOUYIN_SKILL_ROOT="$HOME/.agents/skills/duyi-douyin-chaijie"
mkdir -p "$HOME/.agents/skills"
test ! -e "$DOUYIN_SKILL_ROOT" && cp -R skills/duyi-douyin-chaijie "$DOUYIN_SKILL_ROOT"
```

为使用的客户端添加入口，例如 Codex：

```bash
mkdir -p "$HOME/.codex/skills"
ln -s ../../.agents/skills/duyi-douyin-chaijie "$HOME/.codex/skills/duyi-douyin-chaijie"
```

Claude Code 和 Hermes 的入口分别为 `~/.claude/skills/`、`~/.hermes/skills/`。只安装需要使用的客户端入口。Windows 可使用上面的安装器。

### 运行条件

- Python 3.10+。
- Node.js 20.18.1+，这是 OpenCLI 的 npm 安装要求。
- FFmpeg / FFprobe、curl、yt-dlp、Python 的 Markdown 包。
- Apple Silicon macOS 优先使用 `mlx-whisper`；Windows、Linux、Intel macOS 使用 `openai-whisper`。
- [OpenCLI](https://github.com/jackwener/opencli)、Chrome / Chromium 和 Browser Bridge，浏览器中已登录抖音。

Agent 会先检查依赖，并从可信的系统包管理器、PyPI 或 npm 安装缺少的项目。平台安装与验证命令见 [运行依赖](references/runtime-dependencies.md)。

OpenCLI 的 npm 安装不会代替浏览器连接设置。Browser Bridge 扩展、OpenCLIApp 安装和抖音登录，需要使用者在浏览器或系统界面完成确认。设置后以 `opencli doctor` 的实际结果为准，详见 [浏览器连接设置](references/opencli-setup.md)。

Windows / Linux 的普通 Whisper 路径要通过一次实际音频转写确认可用；MLX 的 `--preflight` 不能代替这项验证。

## 使用

把公开抖音链接交给 Agent：

```text
使用 duyi-douyin-chaijie 完整拆解这个抖音视频：<公开抖音链接>。
输出完整 Markdown 和 HTML 报告，并提炼结构槽位、填空模板与评论选题。
```

Agent 先读取 [SKILL.md](SKILL.md)，完成环境检查，再采集证据、分析和生成报告。

从已安装的 Skill 目录运行证据流水线：

```bash
python3 scripts/run_breakdown.py --source "https://v.douyin.com/example-share/"
```

Windows 使用 `py` 替换 `python3`。普通 Whisper 路径增加 `--allow-slow-whisper`。

默认输出到 `~/douyin-video-breakdowns/`。同一来源再次运行时优先复用已有证据；失败后读取 `manifest.json`，通过 `--run-dir` 续跑原目录。

最终分析写入 `完整拆解报告.md`，在证据目录中写入 `report-web.json`，然后生成 HTML：

```bash
python3 scripts/finalize_breakdown.py \
  --run-dir "/path/to/run" \
  --final-report "/path/to/完整拆解报告.md"
```

默认生成 `/path/to/run/拆解报告.html`。

## 使用边界

只读取公开页面及其媒体，不访问创作者后台、不执行发布或私信、不绕过隐私与付费控制。公开互动和评论只能作为内容线索，不能推断为后台真实数据或付费验证。

结构迁移使用功能关系和变量槽位，需要自己的经历、观点与证据来填写。报告中的原话能回查到转写或原稿，缺失证据标为“素材不足”或“待核验”。

登录用户名不写入采集元数据，浏览器 Cookie Profile 路径不写入下载记录。浏览器登录态只由本机工具使用，不导出 Cookie 文件。

原始证据目录可能含临时媒体地址、公开评论和本地运行路径。分享报告前检查分享范围，避免把整个证据目录或运行日志直接上传。API 密钥、环境文件、浏览器 Profile 和私有 ASR 适配器始终放在包外。

默认使用本地 ASR，不需要 API 凭证。可选的私有 ASR 通过 `--asr-script` 与 `--asr-env` 显式传入，配置见 [SKILL.md](SKILL.md)。

## 验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall -q scripts tests
node --check scripts/collect_douyin_video.mjs
```

离线测试覆盖下载记录隐私、输入边界、运行目录复用、ASR 运行条件和 HTML 渲染。浏览器连接、真实链接下载和实际转写仍需在使用者的运行环境验证。

## 理论与许可

理论用于解释已有证据支持的机制，不能替代原话、时间戳、画面或评论样本。理论说明与文献出处见 [理论基础](references/theory-basis/理论基础.md)。

本 Skill 使用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)，分享与改编需要保留署名和许可，不授予商业用途许可。见 [LICENSE](LICENSE)、[来源说明](NOTICE.md) 和 [第三方说明](THIRD_PARTY_NOTICES.md)。运行依赖不随本包分发，各自遵守原有许可。
