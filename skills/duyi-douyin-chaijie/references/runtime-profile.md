# 隔离 Profile 运行时

某些 Agent 宿主会给终端子进程设置独立 `HOME`。这是正常的隔离机制，但 Python user-site、模型缓存、git、ssh、npm 和部分 CLI 可能因此看到 Profile 目录，而不是操作系统账号的真实 HOME。

`yt-dlp --cookies-from-browser chrome` 也会受到这个隔离影响。`prepare_video.py` 会把浏览器名解析成操作系统账号下的浏览器根目录，只修正 Cookie 读取位置，不改变整个 Profile 的 `HOME`。

## ASR 规则

`mlx_whisper` 的子进程需要使用操作系统账号的真实 HOME。脚本只对 MLX 子进程做这个适配，不修改调用方的整个 Profile。

运行前检查：

```bash
python3 "{SKILL_ROOT}/scripts/transcribe_with_doubao.py" --preflight
```

成功结果必须同时满足：

- `ok: true`
- `provider: mlx_whisper`
- `executable` 指向真实的 `mlx_whisper`

不支持 MLX 的平台应走普通 `openai-whisper` 路径，不要反复尝试安装 MLX。

不要用以下方式绕过：

- 不要把整个 Profile 的 HOME 改成另一个账号的路径。
- 不要把 user-site 写死进临时生成的 `sys.path`。
- 不要调用 `python -m mlx_whisper`；这个包没有 `__main__` 入口。
- 不要改成手写 `mlx_whisper.transcribe(...)` 的一次性代码。

## 工具与超时

- 长流水线、ASR 和 finalizer 通过宿主提供的长时限终端工具运行。
- 短时限代码执行器可能在内部 subprocess 超时前提前杀死任务。
- Runner 会先输出当前 stage，并在每个 stage 后写 `manifest.json`。

## 路径与恢复

Profile 中的 `~` 不一定等于操作系统账号的 HOME。传给脚本的证据目录使用绝对路径；失败续跑只使用 `manifest.json` 记录的 `run_dir`。
