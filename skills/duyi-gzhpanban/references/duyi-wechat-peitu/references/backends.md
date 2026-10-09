# Backend 配置

## 可用 Backend

| Backend | 适用环境 | 要求 | 推荐度 |
|---------|---------|------|--------|
| **codex-cli** | Claude Code、Hermes、任何有 `codex` CLI 的 Agent 环境 | 安装 `codex` CLI 且有订阅 | ★★★★★ |
| **native** | Codex、Hermes 等原生暴露 `image_gen` 的环境 | 当前 runtime 支持 | ★★★★☆ |
| **api** | 任何环境 | 配置外部 API key（Google/OpenAI 等） | ★★★☆☆ |

## 选择优先级

```
1. 用户显式指定 --backend → 使用指定
2. 未指定，且 codex CLI 可用 → codex-cli
3. 未指定，当前 runtime 有 native image_gen → native
4. 未指定，配置了外部 API key → api
5. 都不行 → 报错，提示安装 codex CLI 或配置 API key
```

codex-cli 可用性检查：

```bash
command -v codex &>/dev/null && echo "available" || echo "not found"
```

## codex-cli 特性

- 通过 `codex exec --json --sandbox danger-full-access --skip-git-repo-check` 调用。
- 每次调用 spawn 一个新 Codex agent 进程。
- 图片逐张生成，使用文件锁避免并发冲突。
- 默认超时 5 分钟。
- 支持参考图（`--ref`）。
- 支持失败重试，默认重试 2 次。
- 支持幂等缓存：同 prompt + aspect + refs 命中后直接复制缓存图。
- 支持 JSONL 诊断日志。
- 输出会做 PNG magic-byte 校验，不只检查文件是否存在。

## 环境变量

| 变量 | 说明 |
|------|------|
| `DUYI_CODEX_IMAGEGEN_TIMEOUT_MS` | codex exec 单次超时，默认 300000；兼容通用变量 `CODEX_CLI_TIMEOUT_MS` |
| `DUYI_CODEX_IMAGEGEN_RETRIES` | wrapper 重试次数，默认 2 |
| `DUYI_CODEX_IMAGEGEN_CACHE_DIR` | 启用缓存目录；为空则不开启缓存 |
| `DUYI_CODEX_IMAGEGEN_LOG_FILE` | 追加 JSONL 诊断日志 |

## 批量生成

一篇文章配多张图时，按图串行调用 `codex-cli`，逐张核验输出文件；单张失败时，根据对应日志处理。
