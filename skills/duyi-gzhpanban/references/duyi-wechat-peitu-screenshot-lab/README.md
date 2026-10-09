# duyi-wechat-peitu-screenshot-lab

截图证据图包装。这是 `duyi-gzhpanban` 的内部模块。

## 解决什么问题

将已有截图放入统一画布，保留原有信息关系，避免裁切关键内容；也可生成金句封面和正文小黑插图。

## 安装

随主 Skill 一起安装，按 [主包 README](../../README.md#安装) 安装对应依赖。模块不需要单独安装或建立客户端入口。

```bash
SKILL_ROOT="${SKILL_ROOT:-$HOME/.agents/skills/duyi-gzhpanban}"
```

## 使用

本地截图包装需要主包的 Pillow 依赖。

```bash
python "$SKILL_ROOT/references/duyi-wechat-peitu-screenshot-lab/scripts/render_screenshot_card.py" \
  input.png --output output.png --size 1080x1080 --shell light
```

金句封面和 AI 插图的依赖见主包 README。

完整执行规则见 [SKILL.md](SKILL.md)。
