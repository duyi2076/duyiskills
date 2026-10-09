# duyi-wechat-peitu

公众号封面和正文配图。这是 `duyi-gzhpanban` 的内部模块。

## 解决什么问题

将文章中的具体段落转成封面、商业编辑插画、人物分镜或小黑插图，交付实际图片和建议插入位置。

## 安装

随主 Skill 一起安装，按 [主包 README](../../README.md#安装) 安装对应依赖。模块不需要单独安装或建立客户端入口。

```bash
SKILL_ROOT="${SKILL_ROOT:-$HOME/.agents/skills/duyi-gzhpanban}"
```

## 使用

读取 [SKILL.md](SKILL.md)，按文章选择风格。AI 配图需要可用的 Codex CLI 图像后端或当前环境的原生图像生成工具；本地封面渲染需要主包的 Playwright 依赖。

```text
使用 duyi-gzhpanban 为这篇文章生成封面和正文配图。
```

视觉规格、模板和脚本均包含在本模块中，参考图由使用者按需提供。

完整执行规则见 [SKILL.md](SKILL.md)。
