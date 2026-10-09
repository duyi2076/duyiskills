---
name: duyi-gzhpanban
description: 杜一公众号生产总控。用于把已写好的文章完成排版、配图、15 套固定风格 HTML、截图质检，以及按请求交接微信公众号草稿。普通排版默认输出复制版；明确要求上传草稿箱时才交给发布模块。
---

# duyi-gzhpanban：公众号生产总控

统领配图、固定风格、排版和发布模块，把一篇已写好的文章交付为可复制的排版稿或可检查的微信公众号草稿。

```text
配图 -> 固定风格 -> 排版 -> copy/api HTML -> 手机质检 -> （明确上传时）API dry-run -> 草稿箱
```

总控只负责编排、质量闸门和返工决策，具体实现交给下游 Skill。下游发布只能创建草稿，不能群发。

## 双模式与交接

- `copy` 是默认模式。普通“帮我排版”使用它，输出纯 HTML 复制稿、编号图片占位、原图、配图清单、配图复制页和复制使用说明。配图复制页只含原图、编号及前后文定位，用户可右键复制图片后粘到微信后台；不自动操作剪贴板、不自动进入微信后台或保存草稿。
- `api` 只生成 API 草稿格式的 HTML，不代表网络提交授权。它保留唯一 `#output` 和原图 `src`；只有交给发布模块创建草稿时才自动上传图片。
- `--mode api --standalone` 只生成含图浏览器预览，不能作为 API 交付稿提交。所有 standalone、含图预览和总览产物写入 `wechat-delivery-mode=preview`；发布后端拒绝 `copy` 和 `preview` 标记。实际提交必须使用不带 `--standalone` 的 api 片段。
- API 发布不能直接提交 copy 版占位 HTML。已有 copy HTML 必须从同一份排版 Markdown 重新生成 `--mode api`，只切换交付格式，不重新选重点或改正文；缺 Markdown 时，依据原文和配图清单恢复真实图片引用并核验。带 `wechat-delivery-mode=copy` 标记的文件由发布后端拒绝。
- 用户明确要求代为粘贴时，才调用已有发布模块的浏览器粘贴能力，不增加第三种主模式。
- 明确“帮我排版并上传到草稿箱”时，先排版并质检，再把 `api` 输出交给发布模块，通过 API 创建一套选定风格的草稿。
- “把已有排版稿上传”只交给发布模块，不重复排版。
- 用户明确只预览、不要上传或只 dry-run 时，不创建草稿。

## 固定风格契约

全量风格池只有以下 15 个 style id：

```text
minimal / medium / wired / verge / stripe / apple / ft / linear / github / notion / magazine / editorial / newspaper / course / event
```

风格 CSS 的唯一权威是 `references/duyi-wechat-css-layer/templates/styles.md`。运行时必须通过 `SKILL_ROOT` 定位并实际读取该文件：

```bash
SKILL_ROOT="${SKILL_ROOT:-$HOME/.agents/skills/duyi-gzhpanban}"
export PATH="$SKILL_ROOT/.venv/bin:$SKILL_ROOT/node_modules/.bin:$PATH"
```

首次使用按 `README.md` 安装依赖；每次执行脚本前设置上面的运行路径，使 Python 使用本包虚拟环境，截图工具使用本包依赖。

没有指定风格时使用 `minimal`。用户要求全部样式时生成 15 套；单篇完整排版只渲染选定的一套，只有明确上传时才创建一个草稿。

## 模块入口

按当前请求读取相应模块：

- 配图：`references/duyi-wechat-peitu/SKILL.md`，补齐封面和必要的正文图。
- 固定风格：`references/duyi-wechat-css-layer/SKILL.md`，选择或批量生成主题。
- 排版：`references/duyi-wechat-paipan/SKILL.md`，选重点、标记和渲染。
- 发布：`references/duyi-wechat-fabu/SKILL.md`，API dry-run 和创建草稿。
- 截图配图任务读取 `references/duyi-wechat-peitu-screenshot-lab/SKILL.md`。

## 排版和重点契约

排版前必须通读原文，理解文章主线后主动选择重点。不能只保留原有加粗，也不能为了视觉平均分配重点数量。长文要逐个真实论证阶段评估，重点数量由内容决定。

- 行内重点使用 `**关键短语**`，短而完整，不框选孤立数字。
- 块级重点使用独占行的 `::: emphasis`、完整原文句或段、`:::`。
- 强调块重用所选主题的 blockquote 样式；不增写、不复制原句、不改变论证顺序。
- 真实引用仍使用 `>`，不能把引用伪装成强调块。
- 强调不能去掉限制条件，也不能把原文判断改得更绝对；选块理由和原文定位只写进分析稿。
- 正文保护优先：保留句子、标点、事实、数字、图片、列表、表格和公式。默认不删句末句号。

## 生产流程

1. 读取原文并识别标题、正文、已有图片、列表、表格和公式。
2. 通读原文，建立排版分析稿，记录主线、真实分节、重点候选、图片停顿点和风格选择。
3. 读取 `$SKILL_ROOT/references/duyi-wechat-css-layer/templates/styles.md`，选择固定 style id；完整生产时调用配图模块补齐封面和正文插图。
4. 调用 `duyi-wechat-paipan` 完成结构化 Markdown、重点标记和 HTML。
5. 按模式使用 CSS 层的批量脚本：

```bash
"$SKILL_ROOT/references/duyi-wechat-css-layer/scripts/render_style_set.sh" input.md output_dir --mode copy --all
```

`--mode copy|api` 与 `--all/--preview/--style` 独立。批量未指定 style 集合时仍生成全部 15 套；`--preview` 只生成预览集合；不要把多个风格当作多个文章发布。单套示例：`renderer input.md --mode copy --style minimal --output article-copy.html`；API 示例：`renderer input.md --mode api --style minimal --output article-api.html`。

6. 用 390px 手机视口完整通读首屏、中段和结尾，检查密度、重点、图片、列表、表格、公式、溢出、重叠和裁切。
7. 通过 HTML QA gate 后，只有明确要求上传草稿箱才把 `api` 输出交给发布模块做 API dry-run 并创建一套草稿；其余请求停在相应中间产物。

## HTML 交付契约

- `api` 微信片段保留唯一 `id="output"` 作为发布后端入口；`copy` 正文交付不保留 `id`、`class`、`<style>`、script、按钮或使用说明。配图复制页和复制说明是独立文件。
- 可见元素的样式必须写在元素 `style` 属性中；清理其他 `class`、`data-*` 和 `<style>` 标签。
- 不保留外部 CSS、外部字体、脚本、JavaScript、伪元素、动画、hover 或 fixed；API 保留真实图片引用，copy 只保留编号定位；可见链接文字保留。
- 首个文章标题只进入文档标题元信息，不重复进入正文；用户明确要求正文保留时才例外。
- HTML QA gate 失败时修输入、路径、参数或 renderer，不绕过 gate。

## 授权边界

用户明确“只排版”“只预览”“先 dry-run”“不要进草稿箱”时，在对应中间产物停止。只有明确上传草稿箱时才创建草稿；任何对外发布、群发或不可逆动作仍遵守上层授权规则。

## 交付汇报

只汇报使用的 style id、分析稿、HTML/预览路径、QA 结果和是否进入草稿流程。交付物正文不写提示词、执行过程、规则解释或 AI 痕迹。
