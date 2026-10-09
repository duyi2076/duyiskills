---
name: duyi-douyin-chaijie
description: 公开核心版抖音视频拆解工作流。接收公开抖音链接，保存可核验证据，生成结构化深度拆解和 HTML 报告。适用于分析视频为什么有效、如何迁移结构、如何形成填空模板与评论选题。不包含个人知识库或远端工作台同步。
---

# 杜一抖音拆解

## 目标

把一条公开抖音视频整理成一份可复核、可迁移的拆解报告：

1. 保留来源、可见数据、视频、转写和关键帧等证据。
2. 分开“表面在做什么”和“实际完成了什么传播或营销动作”。
3. 判断创作者层级、开篇机制、论证结构、留存机制和 CTA。
4. 把结构抽成可迁移的填空模板，但不生成对原作者的逐句仿写。
5. 把评论整理成需求信号和后续选题，而不是把评论当成付费需求证明。
6. 输出 Markdown 最终报告和一个可直接打开的自包含 HTML 页面。

## 触发条件

- 用户提供抖音链接，要求拆解、分析、找爆点、提炼结构或生成报告。
- 用户要求把视频变成可迁移的结构、填空题、CTA 或评论选题。

如果用户只要剪辑、封面或发布，不调用本 Skill。

## 核心边界

- 只读取公开页面、公开可见互动数据和用户明确提供的本地素材。
- 不访问创作者后台，不调用发布、编辑、删除、私信或账户设置能力。
- 不绕过隐私、付费或权限控制。
- 不把公开点赞、收藏、评论推断成后台真实数据或付费意愿。
- 报告中的原话必须来自本地转写或用户提供的原稿；分析判断必须挂证据，缺证据写“素材不足”或“待核验”。
- 迁移只复用功能关系和结构槽位，不照搬作者的句壳、口头禅、比喻、节奏和人设承诺。
- 公开包不保存凭证、Cookie、Bearer Token、环境文件或个人绝对路径。

## 运行前准备与依赖自举

将 `{SKILL_ROOT}` 替换成本 Skill 的实际目录，将 `{OUT_ROOT}` 替换成你自己的输出目录：

```bash
python3 "{SKILL_ROOT}/scripts/transcribe_with_doubao.py" --preflight
```

执行任务时，AI 先做依赖预检。缺少可安装的公开依赖时，AI 应使用当前操作系统已有的可信包管理器自动安装，再重新预检；不要把安装步骤甩给用户。具体平台路由见 `references/runtime-dependencies.md`。

- Apple Silicon macOS：优先安装并使用 `mlx_whisper`。
- Windows、Linux 或不支持 MLX 的 macOS：安装并使用普通 `openai-whisper`，运行流水线时加 `--allow-slow-whisper`。
- `mlx_whisper` 不是 Windows 的必需依赖，也不要在 Windows 上反复尝试安装它。
- `ffmpeg`、`ffprobe`、Python 的 `markdown` 包、Node.js 和 `yt-dlp` 缺少时，先自动安装再运行。
- 抖音链接采集还需要 `opencli` CLI 和 Chrome Browser Bridge。缺少 `opencli` 时，AI 应通过可信 npm 安装 `@jackwener/opencli`，然后运行 `opencli --version` 和 `opencli doctor` 验证。具体流程见 [`references/opencli-setup.md`](references/opencli-setup.md)。
- `opencli` 的 Chrome 扩展、OpenCLIApp 安装和抖音登录需要用户在本机确认，AI 不复制浏览器 Profile、不导出 Cookie，也不把 `opencli` 二进制或扩展打包进本 Skill。
- 只有 CLI 没有 Browser Bridge 时，AI 必须自己执行安装、浏览器打开、扩展检查、Profile 选择和 `doctor` 验证；连续两次 `doctor` 失败时，若具备浏览器控制和截图能力，优先用截图操作和标注安装步骤。用户只在浏览器窗口完成登录或权限确认，不得被要求回到终端。不要假装页面采集成功；仍未连接时，明确报告链接采集被浏览器连接阻塞。

安装后必须用版本命令、`--preflight` 或一次真实小流程验证，不以“安装命令返回 0”作为成功证据。需要管理员权限、登录、凭证或不明来源安装包时，停止并向用户说明具体阻塞点。

如果使用私有 Agent Plan ASR，必须显式传入适配器和凭证环境文件：

```bash
python3 "{SKILL_ROOT}/scripts/transcribe_with_doubao.py" \
  --video "{VIDEO_PATH}" \
  --out-dir "{RUN_DIR}" \
  --use-doubao \
  --asr-script "{PRIVATE_ASR_SCRIPT}" \
  --env "{PRIVATE_ENV_FILE}"
```

私有适配器和凭证不属于公开包，也不能复制进 run 目录或提交到 Git。

## 标准流程

### 1. 建立或复用证据目录

链接入口：

```bash
python3 "{SKILL_ROOT}/scripts/run_breakdown.py" \
  --source "{DOUYIN_URL}" \
  --out-root "{OUT_ROOT}"
```

Runner 会按同一个 run directory（证据目录）落盘并记录 `manifest.json`，阶段包括：

`collect_douyin` → `prepare_video` → `transcribe` → `extract_frames` → `build_report`

同一个来源再次运行时优先复用已有证据。某阶段失败后，先读 `manifest.json`，修复根因，再使用其中的 `--run-dir` 续跑。不要用新目录掩盖失败，也不要在临时目录重新拼证据。

### 2. 读取证据

至少检查：

- `source/metadata.json`
- `source/douyin-extract.md`
- `source/对标数据截图.png`（若公开页面采集成功）
- `source/video.*`
- `transcript/asr.json` 和 `transcript/transcript.md`
- `frames/frames.json` 与实际关键帧
- `breakdown.json` 和自动报告

自动报告只是机器生成的分析起点。最终分析必须回到转写、时间戳、关键帧和公开页面证据，不得只改写自动摘要。用户明确要求“完整跑完”且不需要人工复核时，AI 直接基于这些证据生成最终 Markdown、`report-web.json` 并渲染 HTML，不要停在初稿阶段等待用户。

### 3. 写最终报告

在 run directory 外或用户指定位置写入最终 `完整拆解报告.md`。同时在 run directory 根目录写入 `report-web.json`，让 HTML 使用金字塔版模块。若用户要求自动完成，不要把“人工复核”当成前置门槛，但要在报告里标注 ASR 错词、证据不足和待核验项。

报告结构和 JSON 字段见：

- `references/report-template.md`
- `references/theory-basis/理论基础.md`
- `references/breakdown-quality-standard.md`
- `references/layered-breakdown-v2.md`
- `references/structure-taxonomy.md`
- `references/douyin-boundaries.md`

### 4. 生成 HTML

```bash
python3 "{SKILL_ROOT}/scripts/finalize_breakdown.py" \
  --run-dir "{RUN_DIR}" \
  --final-report "{FINAL_REPORT_MD}"
```

默认生成 `{RUN_DIR}/拆解报告.html`。也可以指定 `--output`。HTML 是阅读呈现层，不替代 Markdown 和原始证据。

### 理论视角层

理论基础单独存放在 `references/theory-basis/理论基础.md`。生成最终 Markdown 报告时，创作者层级、营销点、Hook、时间线、CTA、填空模板、评论选题和证据边界这八个主要模块，各自追加一行 `理论视角：...`。

理论视角只负责命名和解释已经有证据支持的机制，不是证据、不是作者意图的证明，也不能替代原话、时间戳、画面、页面数据或评论样本。不得把类比写成师承关系；出处存在争议时，必须保留限定语。

`report-web.json` 不写理论字段。HTML 不显示“理论视角”“理论依据”或“解释视角”行，保证理论不抢占证据和结论的阅读位置。

## 报告最低交付线

一份合格报告至少回答：

1. 观众为什么停下来？
2. 为什么继续看？
3. 为什么相信？
4. 为什么评论、收藏或分享？
5. 哪些结构能迁移，哪些内容和承诺不能照搬？

全文拆解时，每个主要论证段都要有：原话或转写时间段、结构功能、有效机制、迁移方向。关键开篇、转折、反驳、边界和 CTA 要进一步转成结构槽位或填空题。

## 脚本职责

- `scripts/collect_douyin_video.mjs`：采集公开页面可见信息、评论和页面截图。
- `scripts/prepare_video.py`：下载公开抖音视频或处理页面提取出的公开媒体 URL。
- `scripts/transcribe_with_doubao.py`：统一本地 ASR 与显式私有 ASR 适配器入口。
- `scripts/extract_frames.py`：按视频时间轴提取关键帧。
- `scripts/build_report.py`：基于证据生成自动初稿和证据摘要。
- `scripts/run_breakdown.py`：按阶段编排、复用和记录证据目录。
- `scripts/render_report_html.py`：把最终报告和本地证据渲染成自包含 HTML。
- `scripts/finalize_breakdown.py`：校验最终报告并调用 HTML 渲染器。

## 验收

```bash
python3 -m unittest discover -s "{SKILL_ROOT}/tests" -p 'test_*.py'
python3 -m compileall -q "{SKILL_ROOT}/scripts" "{SKILL_ROOT}/tests"
node --check "{SKILL_ROOT}/scripts/collect_douyin_video.mjs"
```

完成前还要确认：

- 公开包中没有个人绝对路径、凭证、Cookie、环境文件或私有同步适配器。
- `manifest.json`、最终 Markdown、`report-web.json`（若有）和 HTML 位于同一个证据目录链路内。
- HTML 能打开，缺失素材会显示“素材不足”，不会被编造成确定事实。
- 测试失败时报告具体失败项，不把“脚本能运行”当成“分析已完成”。
