# 本地内容预览

仅在用户明确要求 Obsidian 预览或 Markdown 阅读时使用。完整公众号生产以正式 HTML、390px 截图和微信草稿手机预览为验收依据。

1. 保存原文，完成排版分析和排版 Markdown。
2. 使用正式 renderer 生成 HTML，默认 QA gate 通过后检查手机阅读效果。
3. 用户指定 Obsidian 时，通过本模块 `scripts/open_obsidian_preview.py` 打开 Markdown。
4. Obsidian 用于核对文字、段落和图片位置。其原生渲染可能直接显示 `::: emphasis` 标记，不能据此判断强调块或 15 套主题效果；主题与强调块必须看正式 HTML。
5. 用户要求只预览时停在本地产物；完整生产按总控授权继续 dry-run 和草稿步骤。

不自动安装 CSS snippet、不修改 vault 配置，不把本地 Markdown 预览当作微信视觉通过。
