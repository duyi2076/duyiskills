# OpenCLI 与 Chrome Browser Bridge

抖音链接采集需要 OpenCLI 的浏览器入口。OpenCLI 本体是公开的第三方 npm
工具，浏览器连接还需要 Chrome/Chromium 中安装 Browser Bridge 扩展，并且用户
已经在目标网站登录。

## 自动安装范围

AI 可以在当前环境缺少 `opencli` 时，用可信的 Node.js/npm 安装：

```bash
npm install -g @jackwener/opencli
opencli --version
```

如果当前环境没有 Node.js 或 npm，只使用系统已有的可信包管理器补齐，不要下载
来路不明的安装器。Node.js 的最低版本以 OpenCLI 官方安装文档为准。

## 浏览器一次性设置

CLI 安装成功后检查：

```bash
opencli doctor
opencli profile list
```

如果提示 Browser Bridge 未连接，Agent 应自己完成可自动化的浏览器设置：

1. 用浏览器控制能力打开 OpenCLI 官方 Chrome Web Store 安装页或 OpenCLIApp 下载页。
2. 自动点击安装、打开 Chrome 扩展管理页，并确认 Browser Bridge 已启用。
3. 自动打开抖音页面。
4. 如果出现登录、系统权限或扩展安装确认，只让用户在浏览器窗口中完成这一项确认。
5. Agent 自己运行 `opencli doctor`，确认连接后继续任务。

AI 应把浏览器操作进度和截图展示给用户，而不是让用户回到终端：

```text
我正在打开 Chrome 并安装 Browser Bridge。
如果浏览器弹出登录或权限确认，请直接在浏览器窗口完成；终端命令由我自动执行。
```

如果用户有多个 Chrome Profile，Agent 自动执行 `opencli profile list`，选择或询问用户
确认正确的 Profile，随后自动执行 `opencli profile use <别名>` 和 `opencli doctor`。

如果是本地 Daemon 未运行，Agent 自动执行 `opencli daemon restart` 和 `opencli doctor`，
不要求用户打开终端。

连续两次 `doctor` 仍然失败时，停止重装和重试，把 `doctor` 的具体输出作为阻塞信息
交给用户；但仍然不要让用户回到终端。Agent 应展示失败截图和下一步浏览器操作，
不要复制 Cookie 或浏览器 Profile，也不要绕过扩展权限。

如果当前 Agent 具备浏览器截图能力，AI 还应把安装过程改成截图引导：

1. 打开 OpenCLI 官方安装页或 Browser Bridge 安装页。
2. 截图标出扩展安装入口或 OpenCLIApp 下载入口。
3. 截图标出 Chrome 中扩展已启用的位置。
4. 截图标出抖音页面已打开、等待用户登录的位置。
5. 用户完成操作后，再截图或展示 `opencli doctor` 的连接结果。

截图只能展示公开安装页面和必要的操作区域。必须遮挡账号名、Cookie、Profile
标识、私聊内容、其他标签页和本地路径。浏览器截图能力不可用时，才退回到文字说明
和官方链接；不能编造截图或把终端报错截图当成安装指引。若浏览器控制能力也不可用，
必须明确说明需要用户在浏览器中完成一次安装或登录确认，而不是把终端命令甩给用户。

AI 不应静默修改 Chrome 扩展、复制浏览器 Profile 或导出 Cookie 文件。浏览器
扩展安装和登录属于用户确认边界。

官方资料：

- https://github.com/jackwener/opencli
- https://github.com/jackwener/opencli/blob/main/docs/guide/installation.md
- https://github.com/jackwener/opencli/blob/main/docs/guide/browser-bridge.md

## 运行分支

- `opencli` 与 Browser Bridge 都正常：运行完整页面证据采集。
- 只有 `opencli` CLI、Browser Bridge 未连接：停止链接采集，报告具体阻塞点。
- Browser Bridge 未连接：不能进入链接采集或后续拆解，先完成连接或报告阻塞。

OpenCLI 不是本 Skill 的源码依赖，也不随本仓库重新分发；它按自己的许可证和
更新节奏维护。
