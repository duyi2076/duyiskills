# duyiskills

杜一个人 Skills 合集。每个 Skill 放在独立目录，README 说明解决什么问题、如何安装和使用，以及交付内容。

## 当前可用

| Skill | 解决什么问题 | 安装与使用 |
|---|---|---|
| [杜一公众号排版（duyi-gzhpanban）](skills/duyi-gzhpanban/SKILL.md) | 将已写好的公众号文章排成手机可读的 HTML，提供 15 套样式、重点与配图；默认交付复制稿，明确要求时上传草稿箱 | [README](skills/duyi-gzhpanban/README.md) |
| [杜一抖音拆解（duyi-douyin-chaijie）](skills/duyi-douyin-chaijie/SKILL.md) | 将公开抖音视频整理为可回查的页面、转写和关键帧证据，拆解开篇、论证、营销与评论，输出 Markdown 和 HTML 报告 | [README](skills/duyi-douyin-chaijie/README.md) |
| [杜一 AI 剪辑（duyi-ai-jianji）](skills/duyi-ai-jianji/SKILL.md) | 将中文横屏口播经一次文字确认后精剪，生成原话字幕、固定左上语义动画和可复查成片；默认深色，可明确选择白墙融合 | [README](skills/duyi-ai-jianji/README.md) |
| [杜一朋友圈（duyi-pyq）](skills/duyi-pyq/SKILL.md) | 把真实事项、口述或草稿整理成可复制的朋友圈，保留口吻与细节 | [README](skills/duyi-pyq/README.md) |
| [杜一口播润色（duyi-koubo-runse）](skills/duyi-koubo-runse/SKILL.md) | 检查口播衔接、重复、指代、节奏和画面同步，交付原位标记稿 | [README](skills/duyi-koubo-runse/README.md) |
| [杜一内容诊断（duyi-neirong-zhenduan）](skills/duyi-neirong-zhenduan/SKILL.md) | 按十项内容标准检查用户价值、亲历支撑、承诺和推理，给出具体改法 | [README](skills/duyi-neirong-zhenduan/README.md) |
| [杜一账号定位（duyi-zhanghao-dingwei）](skills/duyi-zhanghao-dingwei/SKILL.md) | 逐轮访谈确定个人账号方向，交付定位总览、内容主线与昵称简介；默认聊天交付，可按需保存 | [README](skills/duyi-zhanghao-dingwei/README.md) |
| [杜一录音整理（duyi-luyin-zhengli）](skills/duyi-luyin-zhengli/SKILL.md) | 将现成转写或对话原文整理成完整主题稿与候选清单，保留角色归属、追问修正和真实出处 | [README](skills/duyi-luyin-zhengli/README.md) |
| [杜一原子卡片（duyi-yuanzi-kapian）](skills/duyi-yuanzi-kapian/SKILL.md) | 将访谈、答疑和课程记录按独立问题拆卡，忠实保留原回答、判断过程与未回答部分 | [README](skills/duyi-yuanzi-kapian/README.md) |
| [杜一日记整理（duyi-riji-zhengli）](skills/duyi-riji-zhengli/SKILL.md) | 将日记或口述转写按主题整理，核对任务状态与已有下一步，并完整保留输入原文 | [README](skills/duyi-riji-zhengli/README.md) |
| [产品客户沟通分析（duyi-kehu-goutong-fenxi）](skills/duyi-kehu-goutong-fenxi/SKILL.md) | 根据客户原话、行为与场景分析角色、可能顾虑和证据缺口，帮助澄清需求、异议与合作预期 | [README](skills/duyi-kehu-goutong-fenxi/README.md) |
| [杜一社交媒体卡片（duyi-shejiao-meiti-kapian）](skills/duyi-shejiao-meiti-kapian/SKILL.md) | 将现成文字做成朋友圈、X、微博或知乎样式的本地图片卡片，支持竖图、纯卡片 PNG 和可选动效素材 | [README](skills/duyi-shejiao-meiti-kapian/README.md) |

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
  duyi-douyin-chaijie/
    README.md
    SKILL.md
    references/
    scripts/
    tests/
    LICENSE
    NOTICE.md
    SECURITY.md
    THIRD_PARTY_NOTICES.md
  duyi-ai-jianji/
    README.md
    SKILL.md
    requirements.txt
    scripts/
    references/
    assets/
    tests/
    LICENSES/
    LICENSE
    NOTICE.md
    THIRD_PARTY_NOTICES.md
  duyi-pyq/
    README.md
    SKILL.md
    prompt.md
    references/
    LICENSE
    THIRD_PARTY_NOTICES.md
  duyi-koubo-runse/
    README.md
    SKILL.md
    agents/
    LICENSE
  duyi-neirong-zhenduan/
    README.md
    SKILL.md
    agents/
    references/
    LICENSE
  duyi-zhanghao-dingwei/
    README.md
    SKILL.md
    agents/
    scripts/
    references/
    templates/
    LICENSE
  duyi-luyin-zhengli/
    README.md
    SKILL.md
    agents/
    references/
    LICENSE
  duyi-yuanzi-kapian/
    README.md
    SKILL.md
    agents/
    references/
    LICENSE
  duyi-riji-zhengli/
    README.md
    SKILL.md
    agents/
    references/
    LICENSE
  duyi-kehu-goutong-fenxi/
    README.md
    SKILL.md
    agents/
    references/
    LICENSE
    NOTICE
  duyi-shejiao-meiti-kapian/
    README.md
    SKILL.md
    agents/
    references/
    assets/app/
    LICENSE
    THIRD_PARTY_NOTICES.md
```

## 收录与更新

每个新增 Skill 的 README 应写清楚：解决的问题、适用场景、运行条件、安装步骤、调用示例、交付内容和许可。

公开版本按 Skill 独立维护。账号密钥、浏览器登录数据、本机路径、私人案例和运行缓存保存在使用者本地。更新已有安装时，先保留自己的修改和包外配置。

## 许可

各 Skill 和第三方组件按自己的许可执行。查看对应目录的许可文件和第三方说明；本仓库没有统一的 MIT 声明。公众号 Skill 的 15 套样式包含 CC BY-NC 4.0 的非商业用途限制，范围见[许可说明](skills/duyi-gzhpanban/THIRD_PARTY_NOTICES.md)。

杜一抖音拆解采用 CC BY-NC 4.0，署名、非商业用途和第三方依赖范围见[许可与来源说明](skills/duyi-douyin-chaijie/NOTICE.md)。

杜一 AI 剪辑的原创代码采用 PolyForm Noncommercial 1.0.0，文档和设计材料采用 CC BY-NC 4.0；字体、GSAP 与 Silero 模型保留各自许可，见[许可与第三方说明](skills/duyi-ai-jianji/THIRD_PARTY_NOTICES.md)。

杜一朋友圈、杜一口播润色、杜一内容诊断、杜一账号定位、杜一录音整理、杜一原子卡片与杜一日记整理的原创文档采用 MIT License，各目录保留独立许可。朋友圈参考方法的权利和上游声明见[第三方说明](skills/duyi-pyq/THIRD_PARTY_NOTICES.md)。

产品客户沟通分析采用 MIT License，理论与材料来源见[来源说明](skills/duyi-kehu-goutong-fenxi/NOTICE)。杜一社交媒体卡片的代码和自生成渐变素材采用 MIT License，上游及导出组件保留原版权声明；用户输入的头像、文字和图片保留各自权利，见[第三方说明](skills/duyi-shejiao-meiti-kapian/THIRD_PARTY_NOTICES.md)。
