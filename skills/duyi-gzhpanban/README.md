# duyi-gzhpanban

把已写好的公众号文章排成适合手机阅读的 HTML，提供 15 套固定样式、重点标记和配图流程。

## 解决什么问题

文章写好后，还需要整理段落、选择重点、统一标题与正文样式、安排图片，再交给微信编辑器或草稿接口。这些环节可以通过一次调用完成：

- 保留原文句子、事实、标点和论证顺序，用标题层级、行内加粗和重点块改善阅读。
- 使用固定样式，既可选一套，也可用同一份内容查看全部 15 套。
- 按需求交付复制稿或 API 草稿格式，普通排版默认停在复制稿。
- 让封面、正文配图和截图证据图接入同一排版流程。

| 请求 | 交付 |
|---|---|
| 帮我排版 | 复制版正文 HTML、编号图片位置、原图、配图复制页和使用说明 |
| 帮我排版并上传到草稿箱 | API 版 HTML，检查通过后创建一个公众号草稿 |
| 用每个样式排一版 | 15 套排版预览 |

普通排版默认使用复制版。公众号账号与 API 密钥只在上传草稿时需要。

## 安装

需要 Python 3.10+、Node.js 和 npm。API 草稿与配图脚本另外需要 Bun；使用 AI 配图时，还需可用的图像生成工具。浏览器预览可直接打开 HTML，浏览器自动化备用通道需要 Chrome。

先获取仓库：

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
```

从仓库根目录执行以下命令。已有同名 Skill 时，先备份并合并本机修改。

```bash
SKILL_ROOT="$HOME/.agents/skills/duyi-gzhpanban"
mkdir -p "$HOME/.agents/skills"
test ! -e "$SKILL_ROOT" && cp -R skills/duyi-gzhpanban "$SKILL_ROOT"
```

为实际使用的客户端添加入口，例如 Codex：

```bash
mkdir -p "$HOME/.codex/skills"
ln -s ../../.agents/skills/duyi-gzhpanban "$HOME/.codex/skills/duyi-gzhpanban"
```

Claude 和 Hermes 分别使用 `~/.claude/skills/`、`~/.hermes/skills/`。只需安装 `duyi-gzhpanban` 一个入口，下游模块已包含在 `references/` 中。

安装排版依赖：

```bash
python3 -m venv "$SKILL_ROOT/.venv"
source "$SKILL_ROOT/.venv/bin/activate"
python -m pip install -r "$SKILL_ROOT/requirements.txt"
npm ci --prefix "$SKILL_ROOT/references/duyi-wechat-paipan/scripts/vendor"
```

每次运行 Python 脚本时，先激活上面的虚拟环境。Agent 调用脚本前会按主 Skill 设置本包运行路径。

本地封面渲染和自动截图另需：

```bash
npm ci --prefix "$SKILL_ROOT"
npm exec --prefix "$SKILL_ROOT" -- playwright install chromium
export PATH="$SKILL_ROOT/node_modules/.bin:$PATH"
```

API 草稿依赖：

```bash
cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
bun install --frozen-lockfile
```

## 调用

把文章交给 Agent：

```text
使用 duyi-gzhpanban 帮我排版。
```

明确上传草稿：

```text
使用 duyi-gzhpanban 帮我排版并上传到草稿箱。
```

直接调用渲染器：

```bash
python "$SKILL_ROOT/references/duyi-wechat-paipan/scripts/render_wechat_html.py" \
  article.md --mode copy --style minimal --output article-copy.html
```

正文图片会保留为编号位置，同时导出原图、配图清单和独立配图复制页。在浏览器中复制正文，粘到微信编辑器后，通过配图复制页逐张复制图片并插入对应位置，检查实际粘贴结果。

API 格式：

```bash
python "$SKILL_ROOT/references/duyi-wechat-paipan/scripts/render_wechat_html.py" \
  article.md --mode api --style minimal --output article-api.html
```

全部样式：

```bash
"$SKILL_ROOT/references/duyi-wechat-css-layer/scripts/render_style_set.sh" \
  article.md output --mode copy --all
```

样式：`minimal`、`medium`、`wired`、`verge`、`stripe`、`apple`、`ft`、`linear`、`github`、`notion`、`magazine`、`editorial`、`newspaper`、`course`、`event`。未指定时使用 `minimal`。

## API 配置

填写 [EXTEND 示例](references/duyi-wechat-fabu/config/EXTEND.example.md) 中自己的固定出口、代理和作者，保存到包外的 `~/.wechat-article-suite/wechat-fabu/EXTEND.md`。在包外的 `~/.wechat-article-suite/.env` 设置 `WECHAT_APP_ID` 和 `WECHAT_APP_SECRET`。示例 IP 必须替换为自己的白名单公网地址。密钥、EXTEND.md 和 Chrome 登录 profile 保存在包外，不提交到仓库。

默认 dry-run 只做本地检查；明确要求上传时才检查网络、上传图片并创建草稿。发布后端会拒绝复制版和预览版 HTML。`--mode api --standalone` 用于浏览器预览，实际提交须使用不带 `--standalone` 的 API 片段。群发不属于本包的自动流程。

## 模块

| 模块 | 用途 |
|---|---|
| `duyi-wechat-paipan` | 结构整理、重点标记、复制/API HTML |
| `duyi-wechat-css-layer` | 固定样式与批量渲染 |
| `duyi-wechat-peitu` | 封面和正文插图 |
| `duyi-wechat-peitu-screenshot-lab` | 原始截图的证据图包装 |
| `duyi-wechat-fabu` | 账号校验、上传图片、创建草稿 |

## 验证

安装排版和 API 依赖后：

```bash
python -m unittest discover \
  -s "$SKILL_ROOT/references/duyi-wechat-paipan/tests" -p 'test_*.py'
bun test "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend/wechat-extend-config.test.ts"
```

测试覆盖 15 套样式、正文和重点保留、原图导出、交付格式、发布拦截与账号配置；复制后的微信编辑器显示仍需实际检查。

## 许可

15 套样式包含 CC BY-NC 4.0 的非商业用途限制，发布后端的第三方代码采用 MIT。完整范围、署名和许可见 [第三方许可说明](THIRD_PARTY_NOTICES.md)。本包未声明统一 MIT 或其他统一开源许可证。
