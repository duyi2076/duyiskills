# 运行参数

入口为 `assets/app/index.html`。参数通过 URL query string 传入，值需要 URL 编码。

## 内容与身份

- `text`：卡片正文，必填。支持换行，工具按输入原文渲染。
- `name`：显示名称，默认读取包内占位 profile。
- `handle`：用户名，不含 `@`。
- `avatar`：用户明确提供且有权使用的图片 URL；需允许跨域读取，失败时回退占位头像。
- `verified=1` 或 `verified=0`：是否显示认证标识，默认关闭。
- `date`：X 卡片日期，格式 `YYYY-MM-DD`。
- `question`：知乎问题标题，可选，最多 180 字。
- `momentsAt`：朋友圈时间，格式 `YYYY-MM-DDTHH:MM`。

## 平台、尺寸和样式

- `platform`：`x`、`moments`、`weibo` 或 `zhihu`，默认 `x`。
- `mode`：`poster` 为 1080×1440，`tall` 为 1080×1920，`card` 为不带竖图背景的纯卡片，宽度为 1362 像素，高度随文字变化。
- `theme`：`light` 或 `dark`。
- `bg`：包内 SVG 背景文件名，不含扩展名；也可传入用户有权使用的图片 URL。
- `width`：卡片宽度百分比。
- `font=<number>`：手动字号，范围 20 至 48；保留指定字号，超出安全区时提示。`font=auto` 恢复自动适配。
- `opacity`：卡片透明度百分比。
- `x`、`y`：相对安全区中心的画布偏移。

## 互动和调用

- `metrics=on` 或 `metrics=off`：显示或隐藏互动区域，默认隐藏。
- `momentsPeople=1`：仅使用当前普通页面已上传的点赞头像；embed 模式始终忽略本机 localStorage。
- `likes`、`reposts`、`replies`、`bookmarks`、`views`：用户明确给出的互动数字。没有明确来源时不要填入事实数字。
- 显示互动区且未传入数字时，工具生成的数字会带有“示例互动数据”标识。传入数字后，只显示已提供的项目，其余项目不补数字。
- `embed=1`：隐藏编辑界面，完成后将 PNG data URL 放到 `window.__cardDataUrl`，并设置 `document.documentElement.dataset.ready`。

示例：

```text
http://127.0.0.1:8798/assets/app/?embed=1&text=%E8%BF%99%E6%98%AF%E7%94%A8%E6%88%B7%E5%B7%B2%E5%86%99%E5%A5%BD%E7%9A%84%E6%96%87%E5%AD%97&platform=x&mode=poster&theme=light&metrics=off
```

参数只控制本地渲染。工具不读取浏览器凭据，也不会把输入上传到服务端；用户明确提供外部图片 URL 时，会读取该图片。
