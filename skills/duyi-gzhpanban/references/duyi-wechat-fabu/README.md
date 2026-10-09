# duyi-wechat-fabu

公众号草稿箱交接。这是 `duyi-gzhpanban` 的内部模块。

## 解决什么问题

接收已有 API 排版稿，校验账号与固定出口、上传封面和正文图片，再创建一个微信公众号草稿。

## 安装

随主 Skill 一起安装，按 [主包 README](../../README.md#安装) 安装对应依赖。模块不需要单独安装或建立客户端入口。

```bash
SKILL_ROOT="${SKILL_ROOT:-$HOME/.agents/skills/duyi-gzhpanban}"
```

## 使用

先完成主包的 Bun 依赖安装，填写包外的账号密钥与固定出口配置，参见 [配置示例](config/EXTEND.example.md)。

本地检查默认不创建草稿：

```bash
cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
bun wechat-api.ts /absolute/path/article-api.html --cover /absolute/path/cover.png --author "作者名" --dry-run
```

明确要求上传草稿时，检查通过后使用 `--submit`。复制版与预览版 HTML 会被拒绝；本模块不负责重排正文和群发。

完整执行规则见 [SKILL.md](SKILL.md)。
