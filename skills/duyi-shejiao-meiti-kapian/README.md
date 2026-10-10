# 杜一社交媒体卡片

这是一个本地静态 Skill 和卡片工具包。它把用户已经写好的文字渲染成 X、朋友圈、微博或知乎风格的 PNG 卡片，支持 3:4、9:16 和不带竖图背景的纯卡片，卡片底色透明度可调；也可在浏览器支持 WebCodecs 时导出 MP4 动效素材。

## 首次安装

把完整目录安装到共享 Skill 目录，不要只复制 `SKILL.md`，卡片工具与本地素材也需要保留：

```bash
git clone https://github.com/duyi2076/duyiskills.git
cd duyiskills
mkdir -p ~/.agents/skills
cp -R skills/duyi-shejiao-meiti-kapian ~/.agents/skills/
```

按实际使用的客户端建立入口：

```bash
mkdir -p ~/.claude/skills ~/.codex/skills ~/.hermes/skills
ln -s ../../.agents/skills/duyi-shejiao-meiti-kapian ~/.claude/skills/duyi-shejiao-meiti-kapian
ln -s ../../.agents/skills/duyi-shejiao-meiti-kapian ~/.codex/skills/duyi-shejiao-meiti-kapian
ln -s ../../.agents/skills/duyi-shejiao-meiti-kapian ~/.hermes/skills/duyi-shejiao-meiti-kapian
```

同名目录或入口已存在时先保留自己的修改，再决定更新方式。安装后刷新技能列表或重启客户端，在新会话中确认可识别 `$duyi-shejiao-meiti-kapian`。

## 启动静态网页

在 Skill 根目录执行：

```bash
python3 -m http.server 8798 --bind 127.0.0.1
```

打开 `http://127.0.0.1:8798/assets/app/`。工具无构建步骤、无包管理依赖、无后端。仅绑定 `127.0.0.1`，不对公网提供服务。

## 调用示例

人工制卡：输入已有文字，确认显示身份、平台和尺寸，预览后导出 PNG。

也可以直接对 AI 说：

> 用杜一社交媒体卡片把下面的原文做成朋友圈风格的 3:4 PNG，保持文字，使用占位头像，不显示互动数字。交付实际图片文件。

浏览器自动制卡：

```js
await page.goto('http://127.0.0.1:8798/assets/app/?embed=1&text=' + encodeURIComponent('这里放用户已经写好的文字') + '&platform=x&mode=poster');
await page.waitForFunction(() => document.documentElement.dataset.ready === '1');
const dataUrl = await page.evaluate(() => window.__cardDataUrl);
```

完整参数见 [references/runtime-parameters.md](references/runtime-parameters.md)。

## 交付检查

交付前读取实际 PNG，核对像素尺寸、文字、显示身份和平台样式。互动数字只有在用户明确提供时才作为事实显示，否则保持关闭或标注为示例。MP4 只在浏览器实际支持 WebCodecs 并成功生成文件时交付。

## 局限

系统字体会造成跨设备排版差异。纯卡片的默认底色不透明，调低卡片透明度可导出带半透明底色的 PNG。MP4 依赖浏览器的编码能力。内置背景只包含本地自生成 SVG；用户明确提供图片 URL 时会请求对应图片，上传头像和图片只在本地处理，不随 Skill 分发。

## 许可

代码和上游来源见 [LICENSE](LICENSE) 与 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。用户输入素材的权利归原权利人，不因使用本工具而转移。
