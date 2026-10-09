---
name: duyi-wechat-fabu
description: "Receive an existing WeChat-ready API HTML file, validate it, upload cover and body images, and create a WeChat draft when the user explicitly asks to upload it. This skill does not typeset or mass-send."
---

# Du Yi WeChat Fabu

Send an existing finished WeChat API HTML file into the Official Account draft box through the local publishing backend. This skill is the final mile after:

`duyi-wechat-peitu` -> cover/body images  
`duyi-wechat-paipan` -> final Markdown -> WeChat-ready inline HTML  
`duyi-wechat-fabu` -> channel selection, local checks, draft creation, mobile preview checklist

The backend path is resolved from the current `duyi-gzhpanban` Skill root. Do not use a separately installed absolute path.

Publishing backend: use `scripts/wechat-posting-backend/`. Markdown rendering uses local `wechat-md.ts`; browser control uses local `wechat-chrome-cdp.ts`.

## Non-Negotiables

- Author defaults to `杜一`.
- The workflow ends at the WeChat draft box.
- Prefer API publishing for normal articles.
- Use local Chrome CDP publishing for 贴图 and browser fallback.
- Cover is required only for API `news` articles and must be checked before draft creation.
- Run dry-run or browser preview before draft creation. Use `--submit` only when the current request context targets draft creation.
- Do not reformat the article here. If HTML is not ready, route back to `duyi-wechat-paipan`.
- Only an explicit draft-box request authorizes creation. Local QA and dry-run are the draft-box gate; otherwise stop before submission.
- Copy mode does not operate the user's clipboard, enter the WeChat backend, or save a draft automatically. When the user explicitly asks for assisted pasting, use the existing browser paste capability. API mode uploads images automatically only during API draft creation.
- Do not describe copying the whole article with images in one operation as guaranteed to succeed. Verify the actual pasted result in the WeChat backend.
- Never submit copy HTML with numbered image placeholders to the API. Regenerate the api version from the same typeset Markdown, changing only delivery mode; do not reselect emphasis or rewrite content. If Markdown is unavailable, restore and verify real image references from the source article and image manifest. Reject any file marked `wechat-delivery-mode=copy`.
- `--mode api --standalone` is browser preview only and must never be submitted as the API delivery file. Mark standalone, image preview, and overview outputs with `wechat-delivery-mode=preview`; reject both `copy` and `preview` markers. Submit only the api fragment generated without `--standalone`.
- Do not add custom no-image 贴图 behavior unless the user explicitly asks for an extension.

## Channel Selection

| User intent | Backend | Script |
| --- | --- | --- |
| 普通公众号文章 / 草稿箱 | WeChat API | `wechat-api.ts` |
| 贴图 / 图文 / 有图短内容 | Chrome CDP | `wechat-browser.ts` |
| 普通文章但 API 不适合 | Chrome CDP | `wechat-article.ts` |
| 环境检查 | Local checks | `check-permissions.ts` |

## API Article Workflow

1. For an authorized draft upload, verify the dedicated fixed egress and WeChat whitelist before submitting. Skip this network check for a local-only dry-run:
   ```bash
   cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
   bun wechat-api.ts --check-network
   ```
   This must report the configured fixed egress and an available access token. It never creates a draft. Do not continue on `40164`, an egress mismatch, or a tunnel failure.
2. Check that the input is a WeChat-ready HTML file from `duyi-wechat-paipan`, ideally containing `#output`. Render Markdown with `render_wechat_html.py` before this step.
3. Resolve metadata:
   - title: CLI/user value -> `<title>` -> first `<h1>`.
   - author: CLI/user value -> `杜一`.
   - digest: CLI/user value -> first meaningful paragraph, trimmed.
4. Require a cover path. Check existence, image dimensions, file size, and rough Official Account suitability before `--submit`.
5. Run dry-run:
   ```bash
   cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
   bun wechat-api.ts /absolute/path/article.html --cover /absolute/path/cover.png --author "杜一"
   ```
6. Review the dry-run report as an automatic gate: title, author, digest, content length, placeholder image count, cover path/existence, and account. Dry-run is the default and does not fetch tokens or call WeChat APIs.
   - `literalBackslashNCount` should be `0`.
   - `removedLiteralBackslashNCharsAtEdges` should be `0` after `duyi-wechat-paipan` rendering. If this is non-zero, the API guard removed a boundary artifact before it reached the draft.
   - If `literalBackslashNCount` remains non-zero, inspect the HTML manually before submitting, unless the article intentionally discusses escape characters such as `\n`.
7. If the current request context targets draft creation and the dry-run gate is clean, run:
   ```bash
   cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
   bun wechat-api.ts /absolute/path/article.html --cover /absolute/path/cover.png --author "杜一" --submit
   ```
8. Report the resulting draft `media_id` and ask the user to check the phone preview in the WeChat Official Account app/backend.
9. After the user confirms the article was actually published, commit the public-record counter if it was used:
   ```bash
   python3 "$SKILL_ROOT/references/duyi-wechat-paipan/scripts/record_counter.py" commit public_record
   ```

## Browser 贴图 Workflow

Use the local Chrome CDP path for image-text/贴图:

```bash
cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
bun wechat-browser.ts --markdown /absolute/path/article.md --images /absolute/path/images
```

Explicit title/content mode:

```bash
cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
bun wechat-browser.ts \
  --title "短标题" \
  --content "短内容" \
  --image /absolute/path/image.png
```

Actual draft creation:

```bash
cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
bun wechat-browser.ts \
  --title "短标题" \
  --content "短内容" \
  --image /absolute/path/image.png \
  --submit
```

Browser mode opens or reuses an isolated Chrome profile and may require QR login. Without `--submit`, it composes in preview mode only.

## Browser Article Fallback

Use only when API publishing is unsuitable:

```bash
cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
bun wechat-article.ts --html /absolute/path/article.html
```

Actual draft creation:

```bash
cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
bun wechat-article.ts --html /absolute/path/article.html --submit
```

## API Article Commands

Use explicit metadata when the title or digest matters:

```bash
cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
bun wechat-api.ts /absolute/path/article.html \
  --cover /absolute/path/cover.png \
  --title "文章标题" \
  --summary "一句话摘要" \
  --author "杜一"
```

Actual draft creation:

```bash
cd "$SKILL_ROOT/references/duyi-wechat-fabu/scripts/wechat-posting-backend"
bun wechat-api.ts /absolute/path/article.html \
  --cover /absolute/path/cover.png \
  --title "文章标题" \
  --summary "一句话摘要" \
  --author "杜一" \
  --submit
```

## Credentials

The backend reads API credentials and browser/account preferences from environment variables or Du Yi's local config files:

- `WECHAT_APP_ID`
- `WECHAT_APP_SECRET`

Config file search order:

1. Environment variables
2. account config in `.wechat-article-suite/wechat-fabu/EXTEND.md`
3. `<cwd>/.wechat-article-suite/.env`
4. `~/.wechat-article-suite/.env`

Chrome CDP publishing uses the selected account's isolated Chrome profile from `EXTEND.md`, or an auto-generated `~/.wechat-article-suite/chrome-profile` profile when no explicit profile is set.

## Output

In preview-only or dry-run-only mode, report whether the draft is ready to create and what still needs checking.

After `--submit`, report:

- draft saved or failed
- `media_id`
- title
- author
- cover path
- local images uploaded
- phone preview status or next check
