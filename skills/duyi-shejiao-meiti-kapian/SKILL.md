---
name: duyi-shejiao-meiti-kapian
description: 将用户已经写好的文字制作成 X、朋友圈、微博或知乎风格的社交媒体卡片 PNG；需要本地静态预览、参数化导出或保留原文时使用。
---

# 杜一社交媒体卡片

这个 Skill 使用 `assets/app/` 中的本地静态工具，把现成文字渲染为社交媒体卡片。先确认可使用的显示身份、平台和输出尺寸，再制卡。原文默认保持原样，不擅自改写、补写或编造互动数据。

## 工作边界

- 只使用用户明确提供且有权使用的姓名、账号、头像和图片。未提供时使用 `assets/app/profile.json` 的占位身份与 `avatar-placeholder.svg`。
- 平台可选 X、朋友圈、微博、知乎；输出可选 3:4、9:16 或不带竖图背景的纯卡片 PNG。卡片底色透明度可调。互动数字默认关闭；打开时必须标明是示例或用户给定数据。
- 本地运行和本地导出是默认方式。不得自行公网部署、上传、同步或接入第三方 API。用户明确提供图片 URL 时，只读取该图片。
- 需要读取详细 URL 参数时，先读 [references/runtime-parameters.md](references/runtime-parameters.md)。
- 使用前确认 `assets/app` 的静态文件完整。需要 PNG 时可用浏览器人工操作或 `embed=1` 调用；MP4 仅在浏览器支持 WebCodecs 时作为可选输出。

## 运行与交付

1. 在包根目录启动 `python3 -m http.server 8798 --bind 127.0.0.1`。
2. 打开 `http://127.0.0.1:8798/assets/app/`，输入文字、确认身份、选择平台和尺寸，查看预览后导出。
3. 自动调用时访问 `assets/app/?embed=1&text=...`，等待 `document.documentElement.dataset.ready === "1"`，再读取 `window.__cardDataUrl` 并解码为 PNG。
4. 交付前独立核对输出文件可读取、尺寸符合选择、文字与原文一致、身份归属正确，并记录任何浏览器或字体差异。

不要把浏览器 localStorage 中的头像、个人资料或测试输出复制进 Skill。embed 模式忽略本机身份覆盖和朋友圈点赞头像，保证链接不会偷带本机个人数据。
