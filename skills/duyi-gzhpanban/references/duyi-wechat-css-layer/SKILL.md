---
name: duyi-wechat-css-layer
description: 杜一公众号固定风格层。读取唯一权威 styles.md，选择或批量生成 15 套固定 style id，并交给排版 renderer 输出双模式 HTML。
---

# duyi-wechat-css-layer

只负责读取主题 CSS、选择固定风格和编排批量输出，不改写正文。排版、重点、Markdown 解析、内联、微信后处理和 QA 由 `duyi-wechat-paipan` 负责。

## 输出模式

`copy` 为默认模式，生成正文编号图片占位的复制稿，并另附原图、配图清单、配图复制页和复制说明。配图复制页只含原图、编号及前后文定位，用户可右键复制图片后粘到微信后台；copy 不自动操作剪贴板、进入微信后台或保存草稿。`api` 生成保留唯一 `#output` 和原图 `src` 的 API 草稿 HTML，只有 API 创建草稿时才自动上传图片。模式只选输出格式，不代表网络提交授权。批量命令示例：

API 发布不能直接提交 copy 版占位 HTML。已有 copy HTML 必须从同一份排版 Markdown 重新生成 api 版，只切换交付格式，不重新选重点或改正文；缺 Markdown 时依据原文和配图清单恢复真实图片引用并核验。带 `wechat-delivery-mode=copy` 标记的文件由发布后端拒绝。

```bash
"$SKILL_ROOT/references/duyi-wechat-css-layer/scripts/render_style_set.sh" input.md output_dir --mode copy --all
"$SKILL_ROOT/references/duyi-wechat-css-layer/scripts/render_style_set.sh" input.md output_dir --mode api --all
```

`--mode` 与 `--all/--preview/--style` 独立；批量未指定 style 集合时仍生成全部 15 套。复制交付须打开专用 `copy.html` 和配图复制页；含图预览只用于核对，实际微信粘贴仍需验收。

## 唯一权威与路径

唯一 CSS 权威：

```text
templates/styles.md
```

运行时使用相对 Skill 路径：

```bash
SKILL_ROOT="${SKILL_ROOT:-$HOME/.agents/skills/duyi-gzhpanban}"
STYLE_SOURCE="$SKILL_ROOT/references/duyi-wechat-css-layer/templates/styles.md"
```

每次生成前实际读取 `STYLE_SOURCE`。`theme-index.json` 仅提供主题名称、分组和适用场景，不能覆盖 `styles.md` 的字号、颜色、行高、间距和组件规则。

## 固定 style id

```text
minimal / medium / wired / verge / stripe / apple / ft / linear / github / notion / magazine / editorial / newspaper / course / event
```

没有指定风格时使用 `minimal`。全量模式生成全部 15 套；预览模式生成：

```text
minimal / medium / stripe / wired / ft / course
```

显式 style id 只生成该风格。不得混用多套主风格。

## 重点协作规则

排版前必须通读原文并主动选重点，不能只保留已有加粗。长文逐个真实论证阶段评估，重点数量由内容决定。

- 行内重点：`**关键短语**`。
- 块级重点：独占行 `::: emphasis`、下一行原文完整句或段、独占行 `:::`。
- 强调块继承所选主题 blockquote 样式。
- 不增写、不复制原句、不改变论证顺序；真实引用仍使用 `>`。
- 不只框数字或成绩，不去掉限制条件，不使观点更绝对。
- 选择理由和原文定位只放排版分析稿。

## 批量命令

```bash
"$SKILL_ROOT/references/duyi-wechat-css-layer/scripts/render_style_set.sh" input.md output_dir --mode copy --all
"$SKILL_ROOT/references/duyi-wechat-css-layer/scripts/render_style_set.sh" input.md output_dir --preview
"$SKILL_ROOT/references/duyi-wechat-css-layer/scripts/render_style_set.sh" input.md output_dir --style minimal
```

未传模式时按总控默认生成全部 15 套。每套输出都必须经同一 renderer、CSS 内联和 QA gate。

## 输出契约

- API 微信片段保留唯一 `id="output"`，作为发布后端入口；copy 版移除发布入口属性并用编号图片占位。
- 每个可见元素保留 `style` 属性。
- 清理其他 class、data 属性和 `<style>` 标签。
- 不使用外部 CSS、外部字体、脚本、JavaScript、伪元素、动画、hover 或 fixed。
- API 保留真实图片引用、列表、表格、公式和段落语义；copy 图片只保留编号定位，可见链接文字保留。
- 首个文章标题不重复进入正文。

## 交付前验收

检查实际输出的 style id、主题 CSS 关键属性、重点块可见差异、正文完整性和 390px 手机全篇通读。任何 QA gate 或视觉检查失败都要修输入或 renderer 后重跑，不绕过失败。
