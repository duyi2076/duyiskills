# 抖音抓取边界

## Allowed

- Read public Douyin search pages, public video detail pages, visible metrics, and visible public comments.
- Use OpenCLI browser extraction with the user's existing logged-in read-only session.
- Attempt public video download with `yt-dlp` when the URL is publicly accessible.
- Save extracted metadata, comments, transcripts, frames, and reports under the configured output root.

## Not Allowed

- Do not call creator-center, backend analytics, publish, delete, edit, private message, or account-setting APIs.
- Do not bypass privacy, paid access, or permission controls.
- Do not treat visible comments as paid validation.
- Do not expose API keys, cookies, bearer tokens, `.env` files, or full local credential paths in shareable reports.

## Degradation

If public video download fails:

1. Keep `source/metadata.json` and `source/douyin-extract.md`.
2. Build a weak report from public title, metrics, and comments.
3. Mark audio and visual evidence as missing.
4. Keep audio and visual evidence marked as missing until the public media can be downloaded.
