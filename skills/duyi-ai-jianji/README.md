# 杜一 AI 剪辑

`duyi-ai-jianji` 把中文横屏一镜到底口播整理成带字幕和语义动画的成片。逐词审校、删改、完整句和字幕断句先集中在一份确认稿里；确认后锁定文字母版，再完成精剪、声学切点、局部节奏、响度和画面合成。

## 解决什么问题

- 清理口播中的填充词、重复重说和未完成起句，同时保护有效词的起音和尾音。
- 按真实音频修正 ASR（自动语音识别）误听，保留说话者原话和表达顺序。
- 用固定左上信息舞台逐层展示概念、关系、对照和列表，动画在对应词说出时出现。
- 把字幕、剪辑和动画绑定到同一份文字决定，支持中断后恢复和证据复查。

## 适用范围

适合中文、16:9 横屏、一镜到底口播的 MP4/MOV。最低交付分辨率为 1920×1080；更高分辨率素材保留原分辨率，输出帧率与输入一致。

默认使用固定深色皮肤 `dark-reference-fixed`。用户明确指定白墙融合时使用 `white-wall-fusion-fixed`。两种皮肤共享构图、字体和动画结构。

竖屏剪辑使用独立流程。多人、多机位或任意比例素材需要另行处理。

## 运行条件

| 条件 | 要求 |
|---|---|
| 系统 | macOS；动画中的彩色 emoji 使用系统 Apple Color Emoji，其他平台的同等外观尚未验证 |
| Python | 3.10 及以上，安装 `requirements.txt` 中的 Pillow、NumPy、ONNX Runtime |
| 视频工具 | PATH 中有 FFmpeg 和 ffprobe；FFmpeg 支持 `subtitles`、`loudnorm`、`libx264` 和 AAC |
| 动画运行时 | Node.js 22 及以上、npx；流水线固定使用 `hyperframes@0.7.69` |
| 浏览器 | HyperFrames 可启动 Chromium；首次使用可能下载运行时或浏览器 |
| 逐词转写 | 豆包 Agent Plan ASR，固定 `agent_plan / volc.seedasr.sauc.duration`，包含逐词时间及当前源视频指纹 |
| 执行代理 | 能听音频、看成片，制作文字与视觉计划，并启动不继承当前上下文的独立审查实例 |

字体、GSAP 文件和 Silero VAD（语音活动检测）模型随包提供。`fc-scan` 可用于检查字体名称；缺少时环境检查给出提示。动画浏览器的实际可用性在 HyperFrames `check` 时验证。

## 安装

先获取仓库，在仓库根目录执行。目标目录已有安装时，先保留自己的修改和包外配置，再更新。

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
mkdir -p ~/.agents/skills
cp -R skills/duyi-ai-jianji ~/.agents/skills/
```

按使用的客户端建立入口。以下命令适用于入口尚不存在的首次安装：

```bash
mkdir -p ~/.claude/skills ~/.codex/skills ~/.hermes/skills
ln -s ../../.agents/skills/duyi-ai-jianji ~/.claude/skills/duyi-ai-jianji
ln -s ../../.agents/skills/duyi-ai-jianji ~/.codex/skills/duyi-ai-jianji
ln -s ../../.agents/skills/duyi-ai-jianji ~/.hermes/skills/duyi-ai-jianji
```

只运行实际使用的客户端对应的命令。然后安装 Python 依赖并检查环境：

```bash
cd ~/.agents/skills/duyi-ai-jianji
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 scripts/duyi_edit.py doctor
```

让执行代理使用这个虚拟环境的 Python。`doctor` 检查编解码能力、内嵌字体和模型指纹、Python 依赖与 Node 版本；通过后仍需完成实际素材门禁。

## 配置逐词转写

可以提供已生成的、符合合同的豆包逐词 JSON。它必须绑定当前视频的 SHA-256 和字节数，来源或指纹不匹配时流水线停止。

仅提供视频时，需要自己配置可用的豆包 ASR 适配器和服务凭据。适配器与账号凭据不包含在这个包里，服务费用按使用者的服务账户计算。不得替换为其他 ASR 服务来绕过合同。

适配器由 Python 执行，调用形式为：

```text
python3 <tool> <source-video> --env <credentials-file> --json --raw
```

标准输出必须是单个 JSON 对象，包含 `ok=true`、`provider=agent_plan`、`resource_id=volc.seedasr.sauc.duration` 和 `raw.result.utterances[].words[]`。每个词包含 `text/start_time/end_time`，时间单位是毫秒。兼容结构见 [ASR 生成脚本](scripts/generate_doubao_asr.py) 和 [离线适配器测试](tests/test_runtime_inputs.py)。

显式传入工具和配置文件：

```bash
python3 scripts/generate_doubao_asr.py \
  --input /path/to/source.mp4 \
  --tool /path/to/agent_plan_asr.py \
  --env /path/to/asr-config.env \
  --output /path/to/run/incoming/doubao-asr.json
```

也可通过 `DUYI_ASR_TOOL` 和 `DUYI_ASR_ENV` 指定这两个路径。脚本核对来源与逐词结果、写入视频指纹，并拒绝覆盖已有 ASR 文件。

## 如何使用

在代理中明确调用：

```text
用 duyi-ai-jianji 剪辑这个横屏口播视频。先给我完整文字确认稿，确认后完成成片。
```

白墙融合示例：

```text
用 duyi-ai-jianji 剪辑这个横屏视频，使用白墙融合皮肤。
```

执行代理按 [SKILL.md](SKILL.md) 完成文字和视觉判断；脚本负责时间轴、指纹、布局门禁及渲染。用户在文字确认稿中统一确认删除、纠错、完整句和最终字幕换行。

```text
视频与豆包逐词稿
    → 文字审校与唯一一次人工确认
    → 锁定文字母版
    → 声学精剪、节奏、字幕
    → 语义动画、浏览器布局检查
    → 成片与独立审查
```

运行目录应在 Skill 包外；已存在的运行和成片保持只读。调用示例：

```bash
python3 scripts/duyi_edit.py init \
  --input /path/to/source.mp4 \
  --asr /path/to/run/incoming/doubao-asr.json \
  --run-dir /path/to/run
python3 scripts/duyi_edit.py status /path/to/run
```

`init` 在等待文字审校时会按门禁返回阻塞状态；执行代理需继续生成审校计划。文字锁定和视觉计划齐备后，使用 `resume` 继续，最终通过 `verify` 才交付。

## 交付内容

- `deliverable/final.mp4`：成片。
- `review/contact-sheet.jpg`：章节与状态联系表。
- `review/semantic-reveal-sheet.jpg`：语义揭示前、中、后三帧证据。
- `review/editorial-review.md`：文字确认稿。
- `review/locked-editorial-master.json`：锁定文字母版。
- `review/ai-acceptance.json`：独立审查结果。
- `artifacts/`、`work/`、`logs/`：本地恢复和复查证据。

运行证据会包含素材路径、原话与时间轴。分享时只选择需要的成片和证据，公开仓库中不放原视频、账号配置、运行目录或真实案例。

## 验证

在所选 Python 环境中运行离线回归：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

测试覆盖文字锁定、逐词来源绑定、字幕、声学边界、节奏、组件布局和恢复门禁。部分测试执行 FFmpeg；假 ASR 适配器测试不会请求服务。每次实际成片还须完成浏览器布局检查、透明动画渲染及独立审查。

## 许可与来源

作者：杜一，GitHub [@duyi2076](https://github.com/duyi2076)。原项目：[duyi-scripted-video-edit](https://github.com/duyi2076/duyi-scripted-video-edit)。

原创代码采用 PolyForm Noncommercial 1.0.0；Skill 文档和原创设计材料采用 CC BY-NC 4.0。商业使用需要另行取得书面授权。字体、GSAP 和 Silero 模型按各自许可执行。

分发与使用前请阅读 [LICENSE](LICENSE)、[NOTICE.md](NOTICE.md) 和 [第三方说明](THIRD_PARTY_NOTICES.md)。
