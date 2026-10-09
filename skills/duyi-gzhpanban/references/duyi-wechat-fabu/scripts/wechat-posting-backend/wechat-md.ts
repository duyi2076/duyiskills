import fs from "node:fs";
import path from "node:path";

import { marked } from "marked";

export interface FrontmatterResult {
  frontmatter: Record<string, string>;
  body: string;
}

interface MarkdownImage {
  placeholder: string;
  originalPath: string;
  alt: string;
}

interface ResolvedImage {
  placeholder: string;
  localPath: string;
  originalPath: string;
}

interface RenderOptions {
  citeStatus?: boolean;
  defaultTitle?: string;
  keepTitle?: boolean;
  primaryColor?: string;
  theme?: string;
}

const COLOR_TOKENS: Record<string, string> = {
  blue: "#2f6fed",
  cyan: "#147a8c",
  green: "#3f8b6d",
  jade: "#3f8b6d",
  ink: "#222222",
  orange: "#d4742f",
  purple: "#6955a6",
  red: "#c64b44",
  vermilion: "#c94f2d",
  yellow: "#b9872b",
};

const THEME_TEXT_COLORS: Record<string, string> = {
  default: "#242424",
  grace: "#2b2a28",
  modern: "#20242a",
  simple: "#222222",
};

export function parseFrontmatter(content: string): FrontmatterResult {
  const normalized = content.replace(/^\uFEFF/, "");
  const match = normalized.match(/^---\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)([\s\S]*)$/);
  if (!match) return { frontmatter: {}, body: normalized };

  const frontmatter: Record<string, string> = {};
  const lines = match[1]!.split(/\r?\n/);
  let currentKey = "";

  for (const line of lines) {
    if (!line.trim() || line.trimStart().startsWith("#")) continue;

    const continuationMatch = line.match(/^\s+(.+)$/);
    if (continuationMatch && currentKey) {
      frontmatter[currentKey] = `${frontmatter[currentKey]}\n${stripWrappingQuotes(continuationMatch[1]!.trim())}`.trim();
      continue;
    }

    const keyValue = line.match(/^([A-Za-z0-9_-]+)\s*:\s*(.*)$/);
    if (!keyValue) continue;

    currentKey = keyValue[1]!;
    frontmatter[currentKey] = stripWrappingQuotes(keyValue[2]!.trim());
  }

  return { frontmatter, body: match[2]! };
}

export function serializeFrontmatter(frontmatter: Record<string, string>): string {
  const entries = Object.entries(frontmatter)
    .filter(([key, value]) => key.trim() && String(value ?? "").trim())
    .map(([key, value]) => `${key}: ${quoteYamlValue(String(value))}`);

  if (entries.length === 0) return "";
  return `---\n${entries.join("\n")}\n---\n\n`;
}

export function stripWrappingQuotes(value: string | undefined): string {
  if (!value) return "";
  const trimmed = value.trim();
  if (trimmed.length < 2) return trimmed;

  const first = trimmed[0];
  const last = trimmed[trimmed.length - 1];
  if ((first === `"` && last === `"`) || (first === `'` && last === `'`)) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

export function extractTitleFromMarkdown(markdown: string): string {
  const body = parseFrontmatter(markdown).body;
  const heading = body.match(/^\s*#\s+(.+?)\s*#*\s*$/m);
  if (heading) return cleanInlineMarkdown(heading[1]!);

  const firstLine = body
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith("!") && !line.startsWith(">"));
  return cleanInlineMarkdown(firstLine ?? "");
}

export function cleanSummaryText(summary: string | undefined): string {
  if (!summary) return "";
  return cleanInlineMarkdown(summary)
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function extractSummaryFromBody(markdown: string, maxLength = 120): string {
  const body = parseFrontmatter(markdown).body;
  const withoutImages = body.replace(/!\[[^\]]*]\([^)]+\)/g, "");
  const paragraphs = withoutImages.split(/\n{2,}/);

  for (const paragraph of paragraphs) {
    const text = paragraph
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line && !line.startsWith("#") && !line.startsWith("|") && !line.startsWith("```"))
      .join(" ");
    const cleaned = cleanSummaryText(text);
    if (cleaned) return truncateText(cleaned, maxLength);
  }
  return "";
}

export function replaceMarkdownImagesWithPlaceholders(
  markdown: string,
  prefix = "WECHATIMGPH_",
): { images: MarkdownImage[]; markdown: string } {
  const images: MarkdownImage[] = [];
  let rewritten = "";
  let cursor = 0;

  while (cursor < markdown.length) {
    const start = markdown.indexOf("![", cursor);
    if (start === -1) {
      rewritten += markdown.slice(cursor);
      break;
    }

    if (start > 0 && markdown[start - 1] === "\\") {
      rewritten += markdown.slice(cursor, start + 2);
      cursor = start + 2;
      continue;
    }

    const altEnd = findUnescaped(markdown, "]", start + 2);
    if (altEnd === -1 || markdown[altEnd + 1] !== "(") {
      rewritten += markdown.slice(cursor, start + 2);
      cursor = start + 2;
      continue;
    }

    const destStart = altEnd + 2;
    const destEnd = findClosingParen(markdown, destStart);
    if (destEnd === -1) {
      rewritten += markdown.slice(cursor, start + 2);
      cursor = start + 2;
      continue;
    }

    const alt = markdown.slice(start + 2, altEnd);
    const destination = parseImageDestination(markdown.slice(destStart, destEnd));
    if (!destination) {
      rewritten += markdown.slice(cursor, destEnd + 1);
      cursor = destEnd + 1;
      continue;
    }

    const placeholder = `${prefix}${images.length + 1}`;
    images.push({ placeholder, originalPath: destination, alt });
    rewritten += markdown.slice(cursor, start);
    rewritten += placeholder;
    cursor = destEnd + 1;
  }

  return { images, markdown: rewritten };
}

export function resolveColorToken(color?: string): string | undefined {
  if (!color) return undefined;
  const value = color.trim();
  if (/^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(value)) return value;
  return COLOR_TOKENS[value.toLowerCase()];
}

export async function resolveContentImages(
  images: MarkdownImage[],
  baseDir: string,
  tempDir: string,
  sourceLabel = "wechat-md",
): Promise<ResolvedImage[]> {
  const resolved: ResolvedImage[] = [];

  for (const image of images) {
    const originalPath = decodeMarkdownDestination(image.originalPath);
    let localPath = originalPath;

    if (/^https?:\/\//i.test(originalPath)) {
      localPath = await downloadRemoteImage(originalPath, tempDir, image.placeholder, sourceLabel);
    } else if (/^data:/i.test(originalPath)) {
      throw new Error(`[${sourceLabel}] Data URI images are not supported: ${image.placeholder}`);
    } else {
      localPath = path.isAbsolute(originalPath)
        ? originalPath
        : path.resolve(baseDir, originalPath);
      if (!fs.existsSync(localPath)) {
        throw new Error(`[${sourceLabel}] Image not found: ${localPath}`);
      }
    }

    resolved.push({
      placeholder: image.placeholder,
      localPath,
      originalPath,
    });
  }

  return resolved;
}

export async function renderMarkdownDocument(
  markdown: string,
  options: RenderOptions = {},
): Promise<{ html: string }> {
  const { frontmatter, body } = parseFrontmatter(markdown);
  const title = stripWrappingQuotes(frontmatter.title)
    || stripWrappingQuotes(options.defaultTitle)
    || extractTitleFromMarkdown(body);
  const author = stripWrappingQuotes(frontmatter.author);
  const summary = cleanSummaryText(frontmatter.description || frontmatter.summary)
    || extractSummaryFromBody(body, 120);

  const markdownBody = options.keepTitle === false ? removeLeadingH1(body) : body;
  const rawHtml = marked.parse(markdownBody, {
    async: false,
    breaks: false,
    gfm: true,
  }) as string;
  const primaryColor = options.primaryColor || "#3f8b6d";
  const themeName = options.theme && THEME_TEXT_COLORS[options.theme] ? options.theme : "default";
  const bodyColor = THEME_TEXT_COLORS[themeName]!;
  const contentHtml = applyWechatInlineStyles(rawHtml, primaryColor, bodyColor);
  const citations = options.citeStatus === false ? "" : renderCitations(rawHtml, primaryColor);

  return {
    html: [
      "<!doctype html>",
      '<html lang="zh-CN">',
      "<head>",
      '<meta charset="utf-8">',
      '<meta name="viewport" content="width=device-width, initial-scale=1">',
      `<title>${escapeHtml(title)}</title>`,
      author ? `<meta name="author" content="${escapeHtml(author)}">` : "",
      summary ? `<meta name="description" content="${escapeHtml(summary)}">` : "",
      "</head>",
      `<body style="margin:0;padding:0;background:#ffffff;color:${bodyColor};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">`,
      '<section id="output" style="max-width:680px;margin:0 auto;padding:24px 18px 40px;box-sizing:border-box;">',
      contentHtml,
      citations,
      "</section>",
      "</body>",
      "</html>",
    ].filter(Boolean).join("\n"),
  };
}

function quoteYamlValue(value: string): string {
  if (!value) return '""';
  if (/[:#\n\r]|^\s|\s$/.test(value)) return JSON.stringify(value);
  return value;
}

function cleanInlineMarkdown(value: string): string {
  return value
    .replace(/!\[([^\]]*)]\([^)]+\)/g, "$1")
    .replace(/\[([^\]]+)]\([^)]+\)/g, "$1")
    .replace(/[`*_~>#-]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function truncateText(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 1)).trim()}...`;
}

function findUnescaped(input: string, target: string, start: number): number {
  for (let i = start; i < input.length; i++) {
    if (input[i] === target && input[i - 1] !== "\\") return i;
  }
  return -1;
}

function findClosingParen(input: string, start: number): number {
  let depth = 0;
  for (let i = start; i < input.length; i++) {
    const char = input[i];
    if (char === "\\" && i + 1 < input.length) {
      i++;
      continue;
    }
    if (char === "(") {
      depth++;
      continue;
    }
    if (char === ")") {
      if (depth === 0) return i;
      depth--;
    }
  }
  return -1;
}

function parseImageDestination(raw: string): string {
  const value = raw.trim();
  if (!value) return "";

  if (value.startsWith("<")) {
    const end = value.indexOf(">");
    return end > 1 ? value.slice(1, end).trim() : "";
  }

  let destination = "";
  let depth = 0;
  for (const char of value) {
    if (/\s/.test(char) && depth === 0) break;
    if (char === "(") depth++;
    if (char === ")" && depth > 0) depth--;
    destination += char;
  }
  return stripWrappingQuotes(destination);
}

function decodeMarkdownDestination(value: string): string {
  try {
    return decodeURI(value);
  } catch {
    return value;
  }
}

async function downloadRemoteImage(
  url: string,
  tempDir: string,
  placeholder: string,
  sourceLabel: string,
): Promise<string> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`[${sourceLabel}] Failed to download image ${url}: ${response.status}`);
  }

  const buffer = Buffer.from(await response.arrayBuffer());
  if (buffer.length === 0) {
    throw new Error(`[${sourceLabel}] Remote image is empty: ${url}`);
  }

  const contentType = response.headers.get("content-type") || "";
  const extension = extensionFromContentType(contentType) || path.extname(new URL(url).pathname) || ".jpg";
  const filePath = path.join(tempDir, `${placeholder}${extension}`);
  fs.writeFileSync(filePath, buffer);
  return filePath;
}

function extensionFromContentType(contentType: string): string {
  if (contentType.includes("png")) return ".png";
  if (contentType.includes("gif")) return ".gif";
  if (contentType.includes("webp")) return ".webp";
  if (contentType.includes("jpeg") || contentType.includes("jpg")) return ".jpg";
  return "";
}

function removeLeadingH1(markdown: string): string {
  return markdown.replace(/^\s*#\s+.+?(?:\r?\n{1,2}|$)/, "");
}

function applyWechatInlineStyles(html: string, primaryColor: string, bodyColor: string): string {
  let output = html;
  output = addStyle(output, "h1", `margin:0 0 24px;font-size:24px;line-height:1.35;font-weight:700;color:${bodyColor};text-align:left;`);
  output = addStyle(output, "h2", `margin:34px 0 14px;font-size:20px;line-height:1.45;font-weight:700;color:${bodyColor};border-left:4px solid ${primaryColor};padding-left:12px;`);
  output = addStyle(output, "h3", `margin:26px 0 12px;font-size:17px;line-height:1.5;font-weight:700;color:${bodyColor};`);
  output = addStyle(output, "p", `margin:0 0 18px;font-size:16px;line-height:1.85;color:${bodyColor};letter-spacing:0.02em;`);
  output = addStyle(output, "blockquote", `margin:22px 0;padding:14px 18px;border-left:4px solid ${primaryColor};background:#f5f8f6;color:#3b4a42;`);
  output = addStyle(output, "ul", "margin:0 0 18px;padding-left:1.4em;");
  output = addStyle(output, "ol", "margin:0 0 18px;padding-left:1.4em;");
  output = addStyle(output, "li", `margin:0 0 8px;font-size:16px;line-height:1.8;color:${bodyColor};`);
  output = addStyle(output, "strong", `font-weight:700;color:${primaryColor};`);
  output = addStyle(output, "em", "font-style:normal;color:#5d6470;");
  output = addStyle(output, "code", "font-family:Menlo,Consolas,monospace;font-size:0.9em;background:#f4f4f4;border-radius:4px;padding:0.12em 0.35em;color:#b24a3b;");
  output = addStyle(output, "pre", "margin:20px 0;padding:14px 16px;overflow:auto;background:#f6f7f8;border-radius:6px;line-height:1.6;");
  output = addStyle(output, "a", `color:${primaryColor};text-decoration:none;border-bottom:1px solid ${primaryColor};`);
  output = addStyle(output, "hr", "border:0;border-top:1px solid #e8e8e8;margin:28px 0;");
  output = addStyle(output, "img", "display:block;width:100%;height:auto;margin:18px auto;");
  output = addStyle(output, "table", "width:100%;border-collapse:collapse;margin:20px 0;font-size:14px;line-height:1.7;");
  output = addStyle(output, "th", "border:1px solid #e5e5e5;padding:8px;background:#f7f8f8;text-align:left;font-weight:700;");
  output = addStyle(output, "td", "border:1px solid #e5e5e5;padding:8px;vertical-align:top;");
  return output;
}

function addStyle(html: string, tag: string, style: string): string {
  const pattern = new RegExp(`<${tag}(\\s[^>]*)?>`, "gi");
  return html.replace(pattern, (match, attrs = "") => {
    const existing = String(attrs).match(/\sstyle=(["'])(.*?)\1/i);
    if (existing) {
      const quote = existing[1]!;
      const merged = `${existing[2]!.trim().replace(/;?$/, ";")}${style}`;
      return match.replace(existing[0], ` style=${quote}${escapeAttribute(merged)}${quote}`);
    }
    return `<${tag}${attrs} style="${escapeAttribute(style)}">`;
  });
}

function renderCitations(html: string, primaryColor: string): string {
  const links: { text: string; href: string }[] = [];
  const seen = new Set<string>();
  const linkPattern = /<a\b[^>]*\shref=(["'])(https?:\/\/[^"']+)\1[^>]*>([\s\S]*?)<\/a>/gi;

  for (const match of html.matchAll(linkPattern)) {
    const href = match[2]!;
    if (seen.has(href)) continue;
    seen.add(href);
    links.push({
      href,
      text: cleanSummaryText(match[3]!.replace(/<[^>]+>/g, "")) || href,
    });
  }

  if (links.length === 0) return "";
  const items = links.map((link, index) => (
    `<p style="margin:0 0 8px;font-size:13px;line-height:1.55;color:#72777f;">[${index + 1}] <a href="${escapeAttribute(link.href)}" style="color:${primaryColor};text-decoration:none;">${escapeHtml(link.text)}</a></p>`
  ));
  return [
    '<section style="margin-top:30px;padding-top:16px;border-top:1px solid #ececec;">',
    '<p style="margin:0 0 10px;font-size:13px;line-height:1.5;color:#72777f;">References</p>',
    ...items,
    "</section>",
  ].join("\n");
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttribute(value: string): string {
  return escapeHtml(value).replace(/'/g, "&#39;");
}
