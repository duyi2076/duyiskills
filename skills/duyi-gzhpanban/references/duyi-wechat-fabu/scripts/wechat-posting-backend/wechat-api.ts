import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  loadWechatExtendConfig,
  resolveAccount,
  loadCredentials,
  type ResolvedAccount,
} from "./wechat-extend-config.ts";
import {
  type WechatUploadAsset,
  prepareWechatBodyImageUpload,
  needsWechatBodyImageProcessing,
  detectImageFormatFromBuffer,
} from "./wechat-image-processor.ts";

interface AccessTokenResponse {
  access_token?: string;
  errcode?: number;
  errmsg?: string;
}

interface UploadResponse {
  media_id: string;
  url: string;
  errcode?: number;
  errmsg?: string;
}

interface PublishResponse {
  media_id?: string;
  errcode?: number;
  errmsg?: string;
}

interface ImageInfo {
  placeholder: string;
  localPath: string;
  originalPath: string;
}

interface MarkdownRenderResult {
  title: string;
  author: string;
  summary: string;
  htmlPath: string;
  contentImages: ImageInfo[];
}

type ArticleType = "news" | "newspic";

interface ArticleOptions {
  title: string;
  author?: string;
  digest?: string;
  content: string;
  thumbMediaId: string;
  articleType: ArticleType;
  imageMediaIds?: string[];
  needOpenComment?: number;
  onlyFansCanComment?: number;
}

const TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token";
const UPLOAD_BODY_IMG_URL = "https://api.weixin.qq.com/cgi-bin/media/uploadimg";
const UPLOAD_MATERIAL_URL = "https://api.weixin.qq.com/cgi-bin/material/add_material";
const DRAFT_URL = "https://api.weixin.qq.com/cgi-bin/draft/add";
const EGRESS_CHECK_URLS = ["https://api.ipify.org", "https://ifconfig.me/ip"];

let wechatApiProxy = "";

type BunFetchInit = RequestInit & { proxy?: string };

async function fetchWechatApi(url: string, init: RequestInit = {}): Promise<Response> {
  if (!wechatApiProxy) {
    throw new Error("WeChat API proxy is not configured. Refusing to fall back to a dynamic direct IP.");
  }
  return fetch(url, { ...init, proxy: wechatApiProxy } as BunFetchInit);
}

function normalizeIpv4(value: string): string {
  const match = value.trim().match(/\b(?:\d{1,3}\.){3}\d{1,3}\b/);
  const candidate = match?.[0] || "";
  const octets = candidate.split(".");
  if (octets.length !== 4 || octets.some((part) => !/^\d{1,3}$/.test(part) || Number(part) > 255)) {
    return "";
  }
  return candidate;
}

async function verifyFixedEgress(proxy: string, expectedIp: string): Promise<void> {
  const normalizedExpected = normalizeIpv4(expectedIp);
  if (!normalizedExpected || normalizedExpected !== expectedIp.trim()) {
    throw new Error(`Invalid api_expected_egress_ip: ${expectedIp}`);
  }

  const observed: string[] = [];
  for (const url of EGRESS_CHECK_URLS) {
    const response = await fetch(url, {
      proxy,
      signal: AbortSignal.timeout(8_000),
      headers: { "Cache-Control": "no-cache" },
    } as BunFetchInit);
    if (!response.ok) {
      throw new Error(`Fixed-egress check failed at ${url}: HTTP ${response.status}`);
    }
    const ip = normalizeIpv4(await response.text());
    if (!ip) throw new Error(`Fixed-egress check returned no IPv4 address at ${url}`);
    observed.push(ip);
  }

  const mismatch = observed.find((ip) => ip !== normalizedExpected);
  if (mismatch) {
    throw new Error(
      `Fixed-egress mismatch: expected ${normalizedExpected}, observed ${observed.join(", ")}. Refusing WeChat API submission.`
    );
  }
  console.error(`[wechat-api] Fixed egress verified by ${observed.length} providers: ${normalizedExpected}`);
}

async function configureFixedEgress(account: ResolvedAccount): Promise<string> {
  const apiProxy = account.api_proxy?.trim();
  const expectedEgressIp = account.api_expected_egress_ip?.trim();
  if (!apiProxy || !expectedEgressIp) {
    throw new Error(
      "Missing api_proxy or api_expected_egress_ip in wechat-fabu/EXTEND.md. Refusing to use a dynamic direct IP."
    );
  }
  await verifyFixedEgress(apiProxy, expectedEgressIp);
  wechatApiProxy = apiProxy;
  return expectedEgressIp;
}

async function readWechatJson<T>(res: Response, stage: string): Promise<T> {
  const raw = await res.text();
  const responsePreview = raw.trim().slice(0, 800) || "<empty body>";

  if (!res.ok) {
    throw new Error(`${stage} HTTP ${res.status}: ${responsePreview}`);
  }

  let data: unknown;
  try {
    data = raw ? JSON.parse(raw) : null;
  } catch {
    throw new Error(`${stage} returned non-JSON: ${responsePreview}`);
  }

  if (!data || typeof data !== "object") {
    throw new Error(`${stage} returned an empty or invalid JSON body: ${responsePreview}`);
  }

  return data as T;
}

function countLiteralBackslashNewlines(content: string): number {
  return content.match(/\\n/g)?.length || 0;
}

function stripLiteralBackslashNewlineEdges(content: string): { content: string; removedChars: number } {
  const cleaned = content
    .replace(/^(?:\s*\\n\s*)+/, "")
    .replace(/(?:\s*\\n\s*)+$/, "");
  return { content: cleaned, removedChars: content.length - cleaned.length };
}

async function fetchAccessToken(appId: string, appSecret: string): Promise<string> {
  const url = `${TOKEN_URL}?grant_type=client_credential&appid=${appId}&secret=${appSecret}`;
  const res = await fetchWechatApi(url);
  const data = await readWechatJson<AccessTokenResponse>(res, "Access token API");
  if (data.errcode) {
    throw new Error(`Access token error ${data.errcode}: ${data.errmsg}`);
  }
  if (!data.access_token) {
    throw new Error("No access_token in response");
  }
  return data.access_token;
}

function toHttpsUrl(url: string | undefined): string {
  if (!url) return "";
  return url.startsWith("http://") ? url.replace(/^http:\/\//i, "https://") : url;
}

function isRemoteUrl(value: string): boolean {
  return value.startsWith("http://") || value.startsWith("https://");
}

async function loadUploadAsset(
  imagePath: string,
  baseDir?: string,
): Promise<WechatUploadAsset> {
  let fileBuffer: Buffer;
  let filename: string;
  let contentType: string;
  let fileSize = 0;
  let fileExt = "";

  if (imagePath.startsWith("http://") || imagePath.startsWith("https://")) {
    const response = await fetch(imagePath);
    if (!response.ok) {
      throw new Error(`Failed to download image: ${imagePath}`);
    }
    const buffer = await response.arrayBuffer();
    if (buffer.byteLength === 0) {
      throw new Error(`Remote image is empty: ${imagePath}`);
    }
    fileBuffer = Buffer.from(buffer);
    fileSize = buffer.byteLength;
    const urlPath = imagePath.split("?")[0];
    filename = path.basename(urlPath) || "image.jpg";
    fileExt = path.extname(filename).toLowerCase();
    contentType = response.headers.get("content-type") || "image/jpeg";
  } else {
    const resolvedPath = path.isAbsolute(imagePath)
      ? imagePath
      : path.resolve(baseDir || process.cwd(), imagePath);

    if (!fs.existsSync(resolvedPath)) {
      throw new Error(`Image not found: ${resolvedPath}`);
    }
    const stats = fs.statSync(resolvedPath);
    if (stats.size === 0) {
      throw new Error(`Local image is empty: ${resolvedPath}`);
    }
    fileSize = stats.size;
    fileBuffer = fs.readFileSync(resolvedPath);
    filename = path.basename(resolvedPath);
    fileExt = path.extname(filename).toLowerCase();
    const mimeTypes: Record<string, string> = {
      ".jpg": "image/jpeg",
      ".jpeg": "image/jpeg",
      ".png": "image/png",
      ".gif": "image/gif",
      ".webp": "image/webp",
      ".bmp": "image/bmp",
      ".tiff": "image/tiff",
      ".tif": "image/tiff",
      ".svg": "image/svg+xml",
      ".ico": "image/x-icon",
    };
    contentType = mimeTypes[fileExt] || "image/jpeg";
  }

  // Detect actual format from magic bytes to fix extension/content-type mismatches
  // (e.g. CDNs serving WebP for URLs with .png extension)
  const detected = detectImageFormatFromBuffer(fileBuffer);
  if (detected && detected.contentType !== contentType) {
    console.error(`[wechat-api] Format mismatch: ${filename} declared as ${contentType}, actual ${detected.contentType}`);
    contentType = detected.contentType;
    fileExt = detected.fileExt;
    filename = `${path.basename(filename, path.extname(filename))}${detected.fileExt}`;
  }

  return {
    buffer: fileBuffer,
    filename,
    contentType,
    fileExt,
    fileSize,
  };
}

async function uploadImage(
  imagePath: string,
  accessToken: string,
  baseDir?: string,
  uploadType: "body" | "material" = "body"
): Promise<UploadResponse> {
  const asset = await loadUploadAsset(imagePath, baseDir);
  let uploadAsset = asset;

  if (uploadType === "body" && needsWechatBodyImageProcessing(asset)) {
    const prepared = await prepareWechatBodyImageUpload(asset);
    uploadAsset = {
      ...asset,
      buffer: prepared.buffer,
      filename: prepared.filename,
      contentType: prepared.contentType,
      fileExt: path.extname(prepared.filename).toLowerCase(),
      fileSize: prepared.buffer.length,
    };
    const note = prepared.processingNotes.join(", ");
    console.error(`[wechat-api] Processed ${asset.filename} for body upload: ${note}`);
  }

  const result = await uploadToWechat(
    uploadAsset.buffer,
    uploadAsset.filename,
    uploadAsset.contentType,
    accessToken,
    uploadType,
  );

  // media/uploadimg 接口只返回 URL，material/add_material 返回 media_id
  if (uploadType === "body") {
    return {
      url: toHttpsUrl(result.url),
      media_id: "",
    } as UploadResponse;
  } else {
    result.url = toHttpsUrl(result.url);
    return result;
  }
}

// 实际的微信上传函数
async function uploadToWechat(
  fileBuffer: Buffer,
  filename: string,
  contentType: string,
  accessToken: string,
  uploadType: "body" | "material"
): Promise<UploadResponse> {
  const boundary = `----WebKitFormBoundary${Date.now().toString(16)}`;
  const header = [
    `--${boundary}`,
    `Content-Disposition: form-data; name="media"; filename="${filename}"`,
    `Content-Type: ${contentType}`,
    "",
    "",
  ].join("\r\n");
  const footer = `\r\n--${boundary}--\r\n`;

  const headerBuffer = Buffer.from(header, "utf-8");
  const footerBuffer = Buffer.from(footer, "utf-8");
  const body = Buffer.concat([headerBuffer, fileBuffer, footerBuffer]);

  const uploadUrl = uploadType === "body" ? UPLOAD_BODY_IMG_URL : UPLOAD_MATERIAL_URL;
  const url = `${uploadUrl}?type=image&access_token=${accessToken}`;
  const res = await fetchWechatApi(url, {
    method: "POST",
    headers: {
      "Content-Type": `multipart/form-data; boundary=${boundary}`,
    },
    body,
  });

  const data = await readWechatJson<UploadResponse>(res, `${uploadType} image upload API`);
  if (data.errcode && data.errcode !== 0) {
    throw new Error(`Upload failed ${data.errcode}: ${data.errmsg}`);
  }

  return data;
}

async function uploadImagesInHtml(
  html: string,
  accessToken: string,
  baseDir: string,
  contentImages: ImageInfo[] = [],
  articleType: ArticleType = "news",
  collectNewsCoverFallback: boolean = false,
): Promise<{ html: string; firstCoverMediaId: string; imageMediaIds: string[] }> {
  const imgRegex = /<img[^>]*\ssrc=["']([^"']+)["'][^>]*>/gi;
  const matches = [...html.matchAll(imgRegex)];

  if (matches.length === 0 && contentImages.length === 0) {
    return { html, firstCoverMediaId: "", imageMediaIds: [] };
  }

  let firstCoverMediaId = "";
  let updatedHtml = html;
  const imageMediaIds: string[] = [];
  const uploadedBySource = new Map<string, UploadResponse>();

  for (const match of matches) {
    const [fullTag, src] = match;
    if (!src) continue;

    if (src.startsWith("https://mmbiz.qpic.cn")) {
      if (collectNewsCoverFallback && !firstCoverMediaId) {
        try {
          const coverResp = await uploadImage(src, accessToken, baseDir, "material");
          firstCoverMediaId = coverResp.media_id;
        } catch (err) {
          console.error(`[wechat-api] Failed to reuse existing WeChat image as cover: ${src}`, err);
        }
      }
      continue;
    }

    const localPathMatch = fullTag.match(/data-local-path=["']([^"']+)["']/);
    const imagePath = localPathMatch ? localPathMatch[1]! : src;

    console.error(`[wechat-api] Uploading body image: ${imagePath}`);
    try {
      let resp = uploadedBySource.get(imagePath);
      if (!resp) {
        // 正文图片使用 media/uploadimg 接口获取 URL
        resp = await uploadImage(imagePath, accessToken, baseDir, "body");
        uploadedBySource.set(imagePath, resp);
      }
      const newTag = fullTag
        .replace(/\ssrc=["'][^"']+["']/, ` src="${resp.url}"`)
        .replace(/\sdata-local-path=["'][^"']+["']/, "");
      updatedHtml = updatedHtml.replace(fullTag, newTag);
      const shouldUploadMaterial = articleType === "newspic" || (collectNewsCoverFallback && !firstCoverMediaId);
      if (shouldUploadMaterial) {
        let materialResp = uploadedBySource.get(`${imagePath}:material`);
        if (!materialResp) {
          materialResp = await uploadImage(imagePath, accessToken, baseDir, "material");
          uploadedBySource.set(`${imagePath}:material`, materialResp);
        }
        if (articleType === "newspic" && materialResp.media_id) {
          imageMediaIds.push(materialResp.media_id);
        }
        if (collectNewsCoverFallback && !firstCoverMediaId && materialResp.media_id) {
          firstCoverMediaId = materialResp.media_id;
        }
      }
    } catch (err) {
      console.error(`[wechat-api] Failed to upload ${imagePath}:`, err);
    }
  }

  for (const image of contentImages) {
    if (!updatedHtml.includes(image.placeholder)) continue;

    const imagePath = image.localPath || image.originalPath;
    console.error(`[wechat-api] Uploading body image: ${imagePath}`);

    try {
      let resp = uploadedBySource.get(imagePath);
      if (!resp) {
        // 正文图片使用 media/uploadimg 接口获取 URL
        resp = await uploadImage(imagePath, accessToken, baseDir, "body");
        uploadedBySource.set(imagePath, resp);
      }

      const replacementTag = `<img src="${resp.url}" style="display: block; width: 100%; margin: 1.5em auto;">`;
      updatedHtml = replaceAllPlaceholders(updatedHtml, image.placeholder, replacementTag);
      const shouldUploadMaterial = articleType === "newspic" || (collectNewsCoverFallback && !firstCoverMediaId);
      if (shouldUploadMaterial) {
        let materialResp = uploadedBySource.get(`${imagePath}:material`);
        if (!materialResp) {
          materialResp = await uploadImage(imagePath, accessToken, baseDir, "material");
          uploadedBySource.set(`${imagePath}:material`, materialResp);
        }
        if (articleType === "newspic" && materialResp.media_id) {
          imageMediaIds.push(materialResp.media_id);
        }
        if (collectNewsCoverFallback && !firstCoverMediaId && materialResp.media_id) {
          firstCoverMediaId = materialResp.media_id;
        }
      }
    } catch (err) {
      console.error(`[wechat-api] Failed to upload placeholder ${image.placeholder}:`, err);
    }
  }

  return { html: updatedHtml, firstCoverMediaId, imageMediaIds };
}

async function publishToDraft(
  options: ArticleOptions,
  accessToken: string
): Promise<PublishResponse> {
  const url = `${DRAFT_URL}?access_token=${accessToken}`;

  let article: Record<string, unknown>;

  const noc = options.needOpenComment ?? 1;
  const ofcc = options.onlyFansCanComment ?? 0;

  if (options.articleType === "newspic") {
    if (!options.imageMediaIds || options.imageMediaIds.length === 0) {
      throw new Error("newspic requires at least one image");
    }
    article = {
      article_type: "newspic",
      title: options.title,
      content: options.content,
      need_open_comment: noc,
      only_fans_can_comment: ofcc,
      image_info: {
        image_list: options.imageMediaIds.map(id => ({ image_media_id: id })),
      },
    };
    if (options.author) article.author = options.author;
  } else {
    article = {
      article_type: "news",
      title: options.title,
      content: options.content,
      thumb_media_id: options.thumbMediaId,
      need_open_comment: noc,
      only_fans_can_comment: ofcc,
    };
    if (options.author) article.author = options.author;
    if (options.digest) article.digest = options.digest;
  }

  const res = await fetchWechatApi(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ articles: [article] }),
  });

  const data = await readWechatJson<PublishResponse>(res, "Draft creation API");
  if (data.errcode && data.errcode !== 0) {
    throw new Error(`Publish failed ${data.errcode}: ${data.errmsg}`);
  }

  return data;
}

function parseFrontmatter(content: string): { frontmatter: Record<string, string>; body: string } {
  const match = content.match(/^\s*---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
  if (!match) return { frontmatter: {}, body: content };

  const frontmatter: Record<string, string> = {};
  const lines = match[1]!.split("\n");
  for (const line of lines) {
    const colonIdx = line.indexOf(":");
    if (colonIdx > 0) {
      const key = line.slice(0, colonIdx).trim();
      let value = line.slice(colonIdx + 1).trim();
      if ((value.startsWith('"') && value.endsWith('"')) ||
          (value.startsWith("'") && value.endsWith("'"))) {
        value = value.slice(1, -1);
      }
      frontmatter[key] = value;
    }
  }

  return { frontmatter, body: match[2]! };
}

function renderMarkdownWithPlaceholders(
  markdownPath: string,
  theme: string = "default",
  color?: string,
  citeStatus: boolean = true,
  title?: string,
): MarkdownRenderResult {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = path.dirname(__filename);
  const mdToWechatScript = path.join(__dirname, "md-to-wechat.ts");
  const baseDir = path.dirname(markdownPath);

  const args = ["-y", "bun", mdToWechatScript, markdownPath];
  if (title) args.push("--title", title);
  if (theme) args.push("--theme", theme);
  if (color) args.push("--color", color);
  if (!citeStatus) args.push("--no-cite");

  console.error(`[wechat-api] Rendering markdown with placeholders via md-to-wechat: ${theme}${color ? `, color: ${color}` : ""}, citeStatus: ${citeStatus}`);
  const result = spawnSync("npx", args, {
    stdio: ["inherit", "pipe", "pipe"],
    cwd: baseDir,
  });

  if (result.status !== 0) {
    const stderr = result.stderr?.toString() || "";
    throw new Error(`Markdown placeholder render failed: ${stderr}`);
  }

  const stdout = result.stdout?.toString() || "";
  return JSON.parse(stdout) as MarkdownRenderResult;
}

function replaceAllPlaceholders(html: string, placeholder: string, replacement: string): string {
  const escapedPlaceholder = placeholder.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return html.replace(new RegExp(escapedPlaceholder + "(?!\\d)", "g"), replacement);
}

function extractHtmlContent(htmlPath: string): string {
  const html = fs.readFileSync(htmlPath, "utf-8");
  const isNonApiDelivery = (html.match(/<meta\b[^>]*>/gi) ?? []).some((meta) =>
    /\bname\s*=\s*["']wechat-delivery-mode["']/i.test(meta) &&
    /\bcontent\s*=\s*["'](?:copy|preview)["']/i.test(meta),
  );
  if (isNonApiDelivery) {
    throw new Error("Copy/preview HTML cannot be submitted through API. Render the same Markdown with --mode api and without --standalone first.");
  }
  const outputStart = html.match(/<(section|div)\b[^>]*\bid=["']output["'][^>]*>/i);
  if (outputStart && outputStart.index !== undefined) {
    const tag = outputStart[1]!.toLowerCase();
    const start = outputStart.index + outputStart[0].length;
    const remainder = html.slice(start);
    const lowerRemainder = remainder.toLowerCase();
    const closeIndex = lowerRemainder.lastIndexOf(`</${tag}>`);
    return (closeIndex >= 0 ? remainder.slice(0, closeIndex) : remainder).trim();
  }
  const bodyMatch = html.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  return bodyMatch ? bodyMatch[1]!.trim() : html;
}

function printUsage(): never {
  console.log(`Publish article to WeChat Official Account draft using API.
Local WeChat publishing backend for duyi-wechat-fabu. Chrome CDP fallback uses the local wechat-chrome-cdp adapter.
Safe default: dry-run. Add --submit to create a real draft.

Usage:
  bun wechat-api.ts <file> [options]

Arguments:
  file                Markdown (.md) or HTML (.html) file

Options:
  --type <type>       Article type: news (文章, default) or newspic (图文)
  --title <title>     Override title
  --author <name>     Author name (max 16 chars)
  --summary <text>    Article summary/digest (max 128 chars)
  --theme <name>      Theme name for markdown (default, grace, simple, modern). Default: default
  --color <name|hex>  Primary color (blue, green, vermilion, etc. or hex)
  --cover <path>      Cover image path (local or URL)
  --account <alias>   Select account by alias (for multi-account setups)
  --no-cite           Disable bottom citations for ordinary external links in markdown mode
  --check-network     Verify fixed egress and access-token availability; create no draft
  --dry-run           Parse and render only, don't publish (default)
  --submit            Actually upload images and create a WeChat draft
  --help              Show this help

Frontmatter Fields (markdown):
  title               Article title
  author              Author name
  digest/summary      Article summary
  coverImage/featureImage/cover/image   Cover image path

Comments:
  Comments are enabled by default, open to all users.

Environment Variables:
  WECHAT_APP_ID       WeChat App ID
  WECHAT_APP_SECRET   WeChat App Secret

Config File Locations (in priority order):
  1. Environment variables
  2. <cwd>/.wechat-article-suite/.env
  3. ~/.wechat-article-suite/.env

Example:
  bun wechat-api.ts article.html --title "My Article" --cover cover.png
  bun wechat-api.ts article.md --theme grace --cover cover.png
  bun wechat-api.ts article.md --author "Author Name" --summary "Brief intro"
  bun wechat-api.ts --check-network
  bun wechat-api.ts article.md --submit
  bun wechat-api.ts article.md --no-cite
`);
  process.exit(0);
}

interface CliArgs {
  filePath: string;
  isHtml: boolean;
  articleType: ArticleType;
  title?: string;
  author?: string;
  summary?: string;
  theme: string;
  color?: string;
  cover?: string;
  account?: string;
  citeStatus: boolean;
  dryRun: boolean;
  checkNetwork: boolean;
}

function parseArgs(argv: string[]): CliArgs {
  if (argv.length === 0 || argv.includes("--help") || argv.includes("-h")) {
    printUsage();
  }

  const args: CliArgs = {
    filePath: "",
    isHtml: false,
    articleType: "news",
    theme: "default",
    citeStatus: true,
    dryRun: true,
    checkNetwork: false,
  };

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!;
    if (arg === "--type" && argv[i + 1]) {
      const t = argv[++i]!.toLowerCase();
      if (t === "news" || t === "newspic") {
        args.articleType = t;
      }
    } else if (arg === "--title" && argv[i + 1]) {
      args.title = argv[++i];
    } else if (arg === "--author" && argv[i + 1]) {
      args.author = argv[++i];
    } else if (arg === "--summary" && argv[i + 1]) {
      args.summary = argv[++i];
    } else if (arg === "--theme" && argv[i + 1]) {
      args.theme = argv[++i]!;
    } else if (arg === "--color" && argv[i + 1]) {
      args.color = argv[++i];
    } else if (arg === "--cover" && argv[i + 1]) {
      args.cover = argv[++i];
    } else if (arg === "--account" && argv[i + 1]) {
      args.account = argv[++i];
    } else if (arg === "--cite") {
      args.citeStatus = true;
    } else if (arg === "--no-cite") {
      args.citeStatus = false;
    } else if (arg === "--check-network") {
      args.checkNetwork = true;
    } else if (arg === "--dry-run") {
      args.dryRun = true;
    } else if (arg === "--submit") {
      args.dryRun = false;
    } else if (arg.startsWith("--") && argv[i + 1] && !argv[i + 1]!.startsWith("-")) {
      i++;
    } else if (!arg.startsWith("-")) {
      args.filePath = arg;
    }
  }

  if (!args.filePath && !args.checkNetwork) {
    console.error("Error: File path required");
    process.exit(1);
  }

  args.isHtml = args.filePath.toLowerCase().endsWith(".html");

  return args;
}

function extractHtmlTitle(html: string): string {
  const titleMatch = html.match(/<title>([^<]+)<\/title>/i);
  if (titleMatch) return titleMatch[1]!;
  const h1Match = html.match(/<h1[^>]*>([^<]+)<\/h1>/i);
  if (h1Match) return h1Match[1]!.replace(/<[^>]+>/g, "").trim();
  return "";
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));

  const extConfig = loadWechatExtendConfig();
  const resolved = resolveAccount(extConfig, args.account);
  if (resolved.name) console.error(`[wechat-api] Account: ${resolved.name} (${resolved.alias})`);

  if (args.checkNetwork) {
    const expectedEgressIp = await configureFixedEgress(resolved);
    const creds = loadCredentials(resolved);
    const accessToken = await fetchAccessToken(creds.appId, creds.appSecret);
    console.log(JSON.stringify({
      success: true,
      fixedEgressIp: expectedEgressIp,
      accessTokenAvailable: Boolean(accessToken),
      draftCreated: false,
    }, null, 2));
    return;
  }

  const filePath = path.resolve(args.filePath);
  if (!fs.existsSync(filePath)) {
    console.error(`Error: File not found: ${filePath}`);
    process.exit(1);
  }

  const baseDir = path.dirname(filePath);
  let title = args.title || "";
  let author = args.author || "";
  let digest = args.summary || "";
  let htmlPath: string;
  let htmlContent: string;
  let frontmatter: Record<string, string> = {};
  let contentImages: ImageInfo[] = [];

  if (args.isHtml) {
    htmlPath = filePath;
    htmlContent = extractHtmlContent(htmlPath);
    const mdPath = filePath.replace(/\.html$/i, ".md");
    if (fs.existsSync(mdPath)) {
      const mdContent = fs.readFileSync(mdPath, "utf-8");
      const parsed = parseFrontmatter(mdContent);
      frontmatter = parsed.frontmatter;
      if (!title && frontmatter.title) title = frontmatter.title;
      if (!author) author = frontmatter.author || "";
      if (!digest) digest = frontmatter.digest || frontmatter.summary || frontmatter.description || "";
    }
    if (!title) {
      title = extractHtmlTitle(fs.readFileSync(htmlPath, "utf-8"));
    }
    console.error(`[wechat-api] Using HTML file: ${htmlPath}`);
  } else {
    const content = fs.readFileSync(filePath, "utf-8");
    const parsed = parseFrontmatter(content);
    frontmatter = parsed.frontmatter;
    const body = parsed.body;

    title = title || frontmatter.title || "";
    if (!title) {
      const h1Match = body.match(/^#\s+(.+)$/m);
      if (h1Match) title = h1Match[1]!;
    }
    if (!author) author = frontmatter.author || "";
    if (!digest) digest = frontmatter.digest || frontmatter.summary || frontmatter.description || "";

    console.error(`[wechat-api] Theme: ${args.theme}${args.color ? `, color: ${args.color}` : ""}, citeStatus: ${args.citeStatus}`);
    const rendered = renderMarkdownWithPlaceholders(filePath, args.theme, args.color, args.citeStatus, args.title);
    htmlPath = rendered.htmlPath;
    contentImages = rendered.contentImages;
    if (!title) title = rendered.title;
    if (!author) author = rendered.author;
    if (!digest) digest = rendered.summary;
    console.error(`[wechat-api] HTML generated: ${htmlPath}`);
    console.error(`[wechat-api] Placeholder images: ${contentImages.length}`);
    htmlContent = extractHtmlContent(htmlPath);
  }

  const newlineGuard = stripLiteralBackslashNewlineEdges(htmlContent);
  htmlContent = newlineGuard.content;
  const literalBackslashNCount = countLiteralBackslashNewlines(htmlContent);
  if (newlineGuard.removedChars > 0) {
    console.error(`[wechat-api] Removed literal \\n marker(s) from HTML edges, chars=${newlineGuard.removedChars}`);
  }
  if (literalBackslashNCount > 0) {
    console.error(`[wechat-api] Warning: HTML still contains literal \\n text, count=${literalBackslashNCount}`);
  }

  if (!title) {
    console.error("Error: No title found. Provide via --title, frontmatter, or <title> tag.");
    process.exit(1);
  }

  if (digest && digest.length > 120) {
    const truncated = digest.slice(0, 117);
    const lastPunct = Math.max(truncated.lastIndexOf("。"), truncated.lastIndexOf("，"), truncated.lastIndexOf("；"), truncated.lastIndexOf("、"));
    digest = lastPunct > 80 ? truncated.slice(0, lastPunct + 1) : truncated + "...";
    console.error(`[wechat-api] Digest truncated to ${digest.length} chars`);
  }

  console.error(`[wechat-api] Title: ${title}`);
  if (author) console.error(`[wechat-api] Author: ${author}`);
  if (digest) console.error(`[wechat-api] Digest: ${digest.slice(0, 50)}...`);
  console.error(`[wechat-api] Type: ${args.articleType}`);

  if (!author && resolved.default_author) author = resolved.default_author;

  const rawCoverPath = args.cover ||
    frontmatter.coverImage ||
    frontmatter.featureImage ||
    frontmatter.cover ||
    frontmatter.image;
  const coverBaseDir = args.cover ? process.cwd() : baseDir;
  const coverPath = rawCoverPath && !path.isAbsolute(rawCoverPath) && !isRemoteUrl(rawCoverPath)
    ? path.resolve(coverBaseDir, rawCoverPath)
    : rawCoverPath;
  const coverIsRemote = coverPath ? isRemoteUrl(coverPath) : false;
  const coverExists = coverPath ? (coverIsRemote ? undefined : fs.existsSync(coverPath)) : undefined;
  const hasBodyImage = /<img[^>]*\ssrc=["'][^"']+["'][^>]*>/i.test(htmlContent) || contentImages.length > 0;

  if (args.dryRun) {
    console.log(JSON.stringify({
      articleType: args.articleType,
      title,
      author: author || undefined,
      digest: digest || undefined,
      htmlPath,
      contentLength: htmlContent.length,
      literalBackslashNCount,
      removedLiteralBackslashNCharsAtEdges: newlineGuard.removedChars,
      placeholderImageCount: contentImages.length || undefined,
      coverPath: coverPath || undefined,
      coverExists,
      coverIsRemote: coverPath ? coverIsRemote : undefined,
      coverFallbackAvailable: !coverPath && hasBodyImage ? true : undefined,
      account: resolved.alias || undefined,
    }, null, 2));
    return;
  }

  if (args.articleType === "news") {
    if (coverPath && coverExists === false) {
      console.error(`Error: Cover image not found: ${coverPath}`);
      process.exit(1);
    }
    if (!coverPath && !hasBodyImage) {
      console.error("Error: No cover image. Provide via --cover, frontmatter.coverImage, or include an image in content.");
      process.exit(1);
    }
  }

  await configureFixedEgress(resolved);

  const creds = loadCredentials(resolved);
  for (const skippedSource of creds.skippedSources) {
    console.error(`[wechat-api] Skipped incomplete credential source: ${skippedSource}`);
  }
  console.error(`[wechat-api] Credentials source: ${creds.source}`);
  console.error("[wechat-api] Fetching access token...");
  const accessToken = await fetchAccessToken(creds.appId, creds.appSecret);

  const needNewsCoverFallback = args.articleType === "news" && !coverPath;

  console.error("[wechat-api] Uploading body images...");
  const { html: processedHtml, firstCoverMediaId, imageMediaIds } = await uploadImagesInHtml(
    htmlContent,
    accessToken,
    baseDir,
    contentImages,
    args.articleType,
    needNewsCoverFallback,
  );
  htmlContent = processedHtml;

  let thumbMediaId = "";

  if (coverPath) {
    console.error(`[wechat-api] Uploading cover: ${coverPath}`);
    // 封面图片使用 material/add_material 接口
    const coverResp = await uploadImage(coverPath, accessToken, baseDir, "material");
    thumbMediaId = coverResp.media_id;
    console.error(`[wechat-api] Cover uploaded successfully, media_id: ${thumbMediaId}`);
  } else if (firstCoverMediaId && args.articleType === "news") {
    // news 类型没有封面时，使用第一张正文图的 media_id 作为备用封面。
    thumbMediaId = firstCoverMediaId;
    console.error(`[wechat-api] Using first body image as cover (fallback), media_id: ${thumbMediaId}`);
  }

  if (args.articleType === "news" && !thumbMediaId) {
    console.error("Error: No cover image. Provide via --cover, frontmatter.coverImage, or include an image in content.");
    process.exit(1);
  }

  if (args.articleType === "newspic" && imageMediaIds.length === 0) {
    console.error("Error: newspic requires at least one image in content.");
    process.exit(1);
  }

  console.error("[wechat-api] Publishing to draft...");
  const result = await publishToDraft({
    title,
    author: author || undefined,
    digest: digest || undefined,
    content: htmlContent,
    thumbMediaId,
    articleType: args.articleType,
    imageMediaIds: args.articleType === "newspic" ? imageMediaIds : undefined,
    needOpenComment: resolved.need_open_comment,
    onlyFansCanComment: resolved.only_fans_can_comment,
  }, accessToken);

  console.log(JSON.stringify({
    success: true,
    media_id: result.media_id,
    title,
    articleType: args.articleType,
  }, null, 2));

  console.error(`[wechat-api] Published successfully! media_id: ${result.media_id}`);
}

await main().catch((err) => {
  console.error(`Error: ${err instanceof Error ? err.message : String(err)}`);
  process.exit(1);
});
