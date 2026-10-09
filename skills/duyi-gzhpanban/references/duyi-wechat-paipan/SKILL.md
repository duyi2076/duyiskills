---
name: duyi-wechat-paipan
description: 杜一公众号排版。用于把原文整理为手机可读的 Markdown 和双模式 HTML，主动选择重点并使用 15 套固定 style id。默认保留正文、标点、论证顺序、图片、列表、表格和公式。
---

# duyi-wechat-paipan

把原文转成手机端可读的排版稿。排版层可以调整段落、标题层级、重点、引用、图片槽位和样式，但不能改写内容。

## 双模式输出

- `copy` 为默认模式，适用于普通“帮我排版”。正文交付纯 HTML，正文不含 `id`、`class`、`<style>`、script、按钮或使用说明；图片替换为编号占位，并另附原图、配图清单、配图复制页和复制使用说明。配图复制页只含原图、编号及前后文定位，用户可右键复制图片后粘到微信后台。
- copy 不自动操作用户剪贴板、不自动进入微信后台或保存草稿；只有用户明确要求代为粘贴时，才交给已有发布模块的浏览器粘贴能力。含图预览或模拟剪贴板不能代替实际微信粘贴验收。
- `api` 只生成 API 草稿格式 HTML，保留唯一 `id="output"` 和原图 `src`。它只是输出格式，不是网络提交授权；API 创建草稿时才自动上传图片。
- API 发布不能直接提交 copy 版占位 HTML。已有 copy HTML 必须从同一份排版 Markdown 重新生成 `--mode api`，只切换交付格式，不重新选重点或改正文；缺 Markdown 时，依据原文和配图清单恢复真实图片引用并核验。带 `wechat-delivery-mode=copy` 标记的文件由发布后端拒绝。
- 单套示例：`renderer input.md --mode copy --style minimal --output article-copy.html`；`renderer input.md --mode api --style minimal --output article-api.html`。
- 批量示例：`render_style_set.sh input.md output_dir --mode copy --all`，API 模式同理。`--all/--preview/--style` 与 `--mode` 独立，未指定 style 集合时批量仍生成全部 15 套。
- 含图预览只用于核对；复制交付必须打开专用 `copy.html`。不得把浏览器预览或模拟剪贴板当作已完成微信后台粘贴验收。

## 输入和边界

- 先通读全文，再决定分节、重点和视觉停顿。
- 保留句子、标点、事实、数字、图片、列表、表格、公式和论证顺序；默认不删句末句号。
- 用户只说排版、配图、发布或预览时，正文锁定。改稿、润色、重写和精修需要明确授权。
- 开篇一级标题只作为标题元信息，不进入正文；其余正文一级标题降为二级。代码内的 `#` 不参与标题识别；没有开篇标题时可从 frontmatter（文件头元信息）读取 title。
- CSS 唯一权威是 `../duyi-wechat-css-layer/templates/styles.md`。使用 `SKILL_ROOT` 解析相对路径，不能依赖旧绝对路径。

## 固定风格

只接受以下 15 个 style id：

```text
minimal / medium / wired / verge / stripe / apple / ft / linear / github / notion / magazine / editorial / newspaper / course / event
```

没有指定风格时使用 `minimal`。需要全量比较时生成全部 15 套；不得混用多套主风格。排版前读取：

```bash
SKILL_ROOT="${SKILL_ROOT:-$HOME/.agents/skills/duyi-gzhpanban}"
sed -n '1,260p' "$SKILL_ROOT/references/duyi-wechat-css-layer/templates/styles.md"
```

## 重点规则

通读原文后主动选重点，不能只复制已有加粗。长文逐个真实论证阶段评估，重点数量由内容决定。

- `**关键短语**`：行内短语，保留原文措辞。
- `::: emphasis` 独占行，下一行放原文完整句或完整段，再以 `:::` 收束。
- 强调块复用所选主题的 blockquote 样式；不增写、不复制原句、不改变顺序。
- `>` 只表示真实引用、原话或引用语境。
- 不只框数字或成绩，不删除限制条件，不把观点变得更绝对。
- 选择理由、原文定位和未采用候选只写排版分析稿，不进入正文。

## 排版分析稿

完整文章必须先生成 `{filename}-paipan-analysis.md`，再生成排版 Markdown。分析稿至少包含主线、自然分节、长段落阅读问题、独立成行候选、重点候选、图片/停顿点、style id 和不改写检查。

## Markdown 到 HTML

推荐批量入口：

```bash
"$SKILL_ROOT/references/duyi-wechat-css-layer/scripts/render_style_set.sh" input.md output_dir --mode copy --all
```

单套调试入口：

```bash
python3 "$SKILL_ROOT/references/duyi-wechat-paipan/scripts/render_wechat_html.py" input.md --style minimal --output article-wechat.html
```

预览入口：

```bash
python3 "$SKILL_ROOT/references/duyi-wechat-paipan/scripts/render_preview.py" input.md --style minimal --output article-preview.html
```

渲染链路必须是 Markdown 解析、语义 HTML、读取主题 CSS、CSS 内联、微信兼容后处理和 QA gate。API 发布片段保留唯一 `id="output"`，清理其他 class、data 属性和 `<style>` 标签；元素 `style` 属性必须保留。copy 版按双模式契约移除发布入口属性，并把图片转成编号占位。

API 的已有图片、列表、表格、嵌套列表、分割线和公式按原有功能渲染；copy 图片只呈现编号定位，可见链接文字保留。不能用简化文本替代这些语义。

## 交付前检查

- 正文逐字核对，重点只是原文的行内或块级展示变化。
- 重点块在视觉上确实不同于普通正文，且使用所选主题的 blockquote 样式。
- 首个标题未重复进入正文。
- 所有可见元素有内联样式；无 `<style>`、class、data 属性、script、外部样式资源。
- 390px 视口完整通读首屏、中段和结尾，确认无密集、溢出、重叠、裁切或图片缺失。
- QA gate 通过后才交给发布模块；不使用 `--no-gate` 绕过失败。
- HTML gate 检查结构、内联样式、资源路径和兼容性。正文保真、重点选择和读者体验必须另与原文比较及通读，不能凭 gate 通过代替。
- 代码中的标记和转义按原样保留；公式支持稳定文本表达，未知命令停止并报告，不丢命令或猜测语义。复杂公式可保留原式并使用用户提供的公式图。
