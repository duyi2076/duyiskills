# duyiskills

杜一个人 Skills 合集。每个 Skill 放在独立目录，README 说明解决什么问题、如何安装和使用，以及交付内容。

## 当前可用

| Skill | 解决什么问题 | 安装与使用 |
|---|---|---|
| [duyi-gzhpanban](skills/duyi-gzhpanban/SKILL.md) | 将已写好的公众号文章排成手机可读的 HTML，提供 15 套样式、重点与配图；默认交付复制稿，明确要求时上传草稿箱 | [README](skills/duyi-gzhpanban/README.md) |

## 获取与安装

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
```

按需要选择 Skill，进入该 Skill 的 README 完成安装。运行依赖因 Skill 而异，只安装所选 Skill 需要的依赖。

建议将实体目录安装到 `~/.agents/skills/<skill-name>/`，再按使用的客户端建立入口：

- Claude Code：`~/.claude/skills/`
- Codex：`~/.codex/skills/`
- Hermes：`~/.hermes/skills/`

## 目录

```text
skills/
  duyi-gzhpanban/
    README.md
    SKILL.md
    references/
    THIRD_PARTY_NOTICES.md
```

## 收录与更新

每个新增 Skill 的 README 应写清楚：解决的问题、适用场景、运行条件、安装步骤、调用示例、交付内容和许可。

公开版本按 Skill 独立维护。账号密钥、浏览器登录数据、本机路径、私人案例和运行缓存保存在使用者本地。更新已有安装时，先保留自己的修改和包外配置。

## 许可

各 Skill 和第三方组件按自己的许可执行。查看对应目录的许可文件和第三方说明；本仓库没有统一的 MIT 声明。公众号 Skill 的 15 套样式包含 CC BY-NC 4.0 的非商业用途限制，范围见[许可说明](skills/duyi-gzhpanban/THIRD_PARTY_NOTICES.md)。
