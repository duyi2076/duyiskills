# 失败恢复

恢复目标不是“让某条命令返回 0”，而是保住同一个证据目录并完成缺失阶段。

## 唯一入口

先读：

```text
<run_dir>/manifest.json
```

使用其中的 `failed_stages`、`resume_command` 和各阶段落盘文件，不从聊天文字猜测。

## 阶段诊断表

| 阶段 | 主要证据 | 失败时先查 | 正确恢复 |
|---|---|---|---|
| `collect_douyin` | `source/metadata.json`、详情页截图 | 详情页、浏览器会话、采集返回 | 原目录续跑；需要刷新时显式 `--refresh-collection` |
| `prepare_video` | `source/download.json`、`source/video.mp4` | 媒体 URL、浏览器 cookies、ffmpeg | 原目录续跑；无法下载时保留证据并标记媒体缺失 |
| `transcribe` | `transcript/asr.json` | provider、executable、Profile HOME、真实 HOME、timeout | 先跑 ASR preflight，再用 `--run-dir` 续跑 |
| `extract_frames` | `frames/frames.json` | ffmpeg 返回、视频可读性 | 原目录续跑 |
| `build_report` | `breakdown.json`、自动报告 | 上游证据是否缺失 | 修复上游后原目录续跑 |
| `finalize` | Markdown 报告渲染为 HTML | final report、run-dir、`report-web.json`（可选） | 按原 run-dir 重跑 finalizer |

## 禁止的恢复方式

- 不修改 `--out-root`。
- 不加 `--new-run`。
- 不在 `/tmp` 重抓、重下或手工拼证据。
- 不把完整 runner 拆成若干临时命令。
- 不用 `execute_code` 包裹长任务。
- 不因为 `python3 import` 失败就宣称软件未安装。
- 不手工移动证据文件，也不修改 `manifest.json` 伪造阶段成功；先修复失败阶段，再从同一 run-dir 续跑。
- 不在同一阶段连续失败后继续改参数碰运气。

## 两次失败规则

同一阶段第二次失败后立即停止：

1. 保留正式 `run_dir`。
2. 记录两次命令、错误和阶段产物。
3. 区分环境、输入、权限、网络和代码错误。
4. 给出一个根因判断和一个待验证假设。
5. 修复脚本或配置后，仍从原 `run_dir` 续跑。

## 完成验证

成功必须接到真实产物：

- `manifest.json`: `ok: true`、`evidence_complete: true`
- `transcript/asr.json`: `ok: true`
- `frames/frames.json`: `ok: true` 且存在实际图片
- 自动报告仅作为初稿
- `完整拆解报告.md` 存在且来自人工复核后的最终报告
- `拆解报告.html` 存在且能在浏览器打开
- 同一链接再次执行时复用原证据目录
