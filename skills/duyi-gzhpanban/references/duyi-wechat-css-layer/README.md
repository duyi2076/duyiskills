# duyi-wechat-css-layer

15 套固定排版样式。这是 `duyi-gzhpanban` 的内部模块。

## 解决什么问题

在同一份文章上选用固定样式，或生成全部样式供比较。样式定义统一保存在 `templates/styles.md`。

## 安装

随主 Skill 一起安装，按 [主包 README](../../README.md#安装) 安装对应依赖。模块不需要单独安装或建立客户端入口。

```bash
SKILL_ROOT="${SKILL_ROOT:-$HOME/.agents/skills/duyi-gzhpanban}"
```

## 使用

```bash
"$SKILL_ROOT/references/duyi-wechat-css-layer/scripts/render_style_set.sh" \
  article.md output --mode copy --all
```

使用 `--style minimal` 可生成单套。`--mode copy|api` 选择交付格式，和样式数量独立。

完整执行规则见 [SKILL.md](SKILL.md)。
