# duyi-wechat-paipan

公众号排版与双模式 HTML。这是 `duyi-gzhpanban` 的内部模块。

## 解决什么问题

把已有文章整理为手机可读的 Markdown 和 HTML；选择重点并保留原文事实、句子与图片顺序。

## 安装

随主 Skill 一起安装，按 [主包 README](../../README.md#安装) 安装对应依赖。模块不需要单独安装或建立客户端入口。

```bash
SKILL_ROOT="${SKILL_ROOT:-$HOME/.agents/skills/duyi-gzhpanban}"
```

## 使用

普通排版使用 `copy`；需要提交 API 时使用 `api`。

```bash
python "$SKILL_ROOT/references/duyi-wechat-paipan/scripts/render_wechat_html.py" \
  article.md --mode copy --style minimal --output article-copy.html
```

复制版包含正文 HTML、原图、编号位置、配图复制页和说明。API 版保留真实图片引用；standalone 产物只用于预览。

完整执行规则见 [SKILL.md](SKILL.md)。
