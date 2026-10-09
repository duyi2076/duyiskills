# Screenshot Card Renderer

Use this route when article images need to show evidence, comparison, workflow proof, product state, terminal output, or before/after results.

## Selection Rules

- Use screenshot-card for screenshots that already contain useful information.
- Do not turn screenshots into Xiaohei illustrations.
- Do not crop, enlarge, or restage comparison screenshots unless the user explicitly asks.
- Preserve the relationship that makes the screenshot useful: columns, before/after, process steps, table rows, or terminal output.
- Add no explanatory text to the final image. The screenshot must remain the first information layer.

## Template Modes

| Input | Canvas | Shell | Rule |
|---|---:|---|---|
| Horizontal multi-column comparison | `1280x720` | `light` | Preserve full screenshot. |
| Terminal table or proof screenshot | `1080x1080` | `light` | Prioritize readability over 16:9. |
| Product/UI screenshot for atmosphere | `1280x720` | `browser` | Browser shell is allowed. |
| Single long article screenshot | `1280x720` | `browser` + `cover` | Crop only to the important reading area. |

## Light Shell Rules

- No shadow. Do not add drop shadows, black bars, or bottom glow.
- Use only background, rounded corners, and a 1-2px border.
- Keep the screenshot large enough that mobile readers can read the key text.
- If a screenshot is near-square or vertical, prefer `1080x1080` over forcing 16:9.

## Commands

Horizontal comparison:

```bash
python3 scripts/render_screenshot_card.py input.png -o output.png --size 1280x720 --shell light
```

Terminal table:

```bash
python3 scripts/render_screenshot_card.py input.png -o output.png --size 1080x1080 --shell light
```

Browser-window screenshot:

```bash
python3 scripts/render_screenshot_card.py input.png -o output.png --size 1280x720 --shell browser --fit cover --focus 0.23
```

## QA

- The original screenshot relationship is intact.
- No meaningful content is cropped.
- No shadow or black bar appears in light shell mode.
- Text remains readable when viewed at article width.
- The final image contains no prompt notes, production notes, or process explanations.
