#!/usr/bin/env node
import { execFile } from "node:child_process";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const args = parseArgs(process.argv.slice(2));
const session = `douyin-video-breakdown-${Date.now()}`;

main().finally(async () => {
  await closeSessionQuietly(session);
});

async function main() {
  if (args.url && !isPublicDouyinUrl(args.url)) {
    throw new Error("Credential-free public Douyin URL required.");
  }
  const outPath = resolve(args.out || "metadata.json");
  const rawOutPath = args["raw-out"] ? resolve(args["raw-out"]) : "";
  const screenshotOutPath = args["screenshot-out"] ? resolve(args["screenshot-out"]) : "";
  await mkdir(dirname(outPath), { recursive: true });
  if (rawOutPath) await mkdir(dirname(rawOutPath), { recursive: true });
  if (screenshotOutPath) await mkdir(dirname(screenshotOutPath), { recursive: true });

  const identity = await verifyIdentity(args);
  const startedAt = new Date().toISOString();
  let metadata;

  if (args.url) {
    metadata = await collectUrl(args.url, { rawOutPath, screenshotOutPath });
  } else if (args.search) {
    metadata = await collectSearch(args.search);
  } else if (args.config) {
    metadata = await collectFromConfig(resolve(args.config), { rawOutPath, screenshotOutPath });
  } else {
    throw new Error("Provide --url, --search, or --config.");
  }

  metadata = {
    ...metadata,
    sourceType: args.url ? "url" : args.search ? "search" : "config",
    collectedAt: startedAt,
    identity: {
      logged_in: Boolean(identity.logged_in),
    },
    dataBoundary: [
      "Public Douyin page extraction only.",
      "Visible metrics and comments are demand clues, not backend data or paid validation.",
    ],
  };

  await writeFile(outPath, JSON.stringify(metadata, null, 2), "utf8");
  console.log(`Wrote ${outPath}`);
  if (metadata.url) console.log(`Selected ${metadata.url}`);
}

function isPublicDouyinUrl(value) {
  try {
    const url = new URL(String(value || "").trim());
    if (!new Set(["http:", "https:"]).has(url.protocol) || url.username || url.password) return false;
    const hostname = url.hostname.toLowerCase().replace(/\.+$/, "");
    return ["douyin.com", "iesdouyin.com"].some(
      (suffix) => hostname === suffix || hostname.endsWith(`.${suffix}`),
    );
  } catch {
    return false;
  }
}

async function verifyIdentity(options) {
  if (options.search || options["skip-whoami"]) {
    return { logged_in: null, username: "" };
  }
  const identity = normalizeObject(await runOpenCli(["douyin", "whoami", "--site-session", "persistent"]));
  if (!identity.logged_in) {
    throw new Error("Douyin is not logged in in the OpenCLI persistent session.");
  }
  if (options["expected-username"]) {
    const currentName = String(identity.username || identity.name || "");
    if (currentName && currentName !== options["expected-username"] && !options["allow-current-account"]) {
      throw new Error(`Current Douyin session is ${currentName}; expected ${options["expected-username"]}.`);
    }
  }
  return identity;
}

async function collectSearch(query) {
  const results = await runOpenCli(["douyin", "search", query, "--site-session", "persistent"]);
  const items = Array.isArray(results) ? results : [];
  const authorNeedle = args.author || args["author-keyword"] || "";
  const candidates = items
    .filter((item) => item && item.url)
    .filter((item) => !authorNeedle || containsLoose(item.author, authorNeedle))
    .sort((a, b) => numberValue(b.likes) - numberValue(a.likes));
  const selected = candidates[0] || items.find((item) => item && item.url) || {};
  return {
    input: query,
    query,
    candidates: candidates.slice(0, numberArg("max-candidates", 10)),
    url: selected.url || "",
    title: selected.desc || "",
    author: selected.author || "",
    publishedAt: "",
    metrics: {
      likes: numberValue(selected.likes),
      comments: numberValue(selected.comments),
      collects: 0,
      shares: numberValue(selected.shares),
    },
    comments: [],
    errors: selected.url ? [] : ["No URL returned by opencli douyin search."],
  };
}

async function collectUrl(url, { rawOutPath, screenshotOutPath }) {
  const detail = await extractDetail(url, {
    maxComments: numberArg("max-comments", 80),
    commentTarget: numberArg("comment-target", 80),
    minCommentLikes: numberArg("min-comment-likes", 1),
    includeInteractionFallback: args["no-interaction-fallback"] !== true,
    rawOutPath,
    screenshotOutPath,
  });
  return { input: url, url, ...detail };
}

async function collectFromConfig(configPath, { rawOutPath, screenshotOutPath }) {
  const config = JSON.parse(await readFile(configPath, "utf8"));
  const maxVideos = Number(config.maxVideosPerAccount || 3);
  const lookbackDays = Number(config.lookbackDays || 7);
  const maxComments = Number(config.maxCommentsPerVideo || 8);
  const minCommentLikes = Number(config.minCommentLikes ?? 1);
  const includeInteractionFallback = config.includeInteractionFallback !== false;
  const errors = [];

  for (const account of config.accounts || []) {
    const candidates = [];
    const seen = new Set();
    const queries = [...(account.searchQueries || []), account.searchQuery || account.name]
      .filter(Boolean)
      .filter((query, index, list) => list.indexOf(query) === index);

    for (const [index, query] of queries.entries()) {
      if (index > 0) await sleep(2200);
      const searchUrl = `https://www.douyin.com/search/${encodeURIComponent(query)}?type=video`;
      try {
        const content = await extractUrl(searchUrl, 20000);
        for (const item of parseSearchResults(content, query)) {
          if (seen.has(item.url)) continue;
          seen.add(item.url);
          candidates.push(item);
        }
      } catch (error) {
        errors.push(`Search failed for ${query}: ${compactError(error)}`);
      }
    }

    const filtered = [];
    for (const item of candidates) {
      if (filtered.length >= maxVideos) break;
      if (!matchesAccountAuthor(item.author, account)) continue;
      const age = ageInDays(item.relativeTime || item.publishedAt);
      item.ageDays = age;
      if (age == null && !config.includeUnknownDates) continue;
      if (age != null && age > lookbackDays) continue;
      filtered.push(item);
    }

    const selected = filtered[0] || candidates.find((item) => matchesAccountAuthor(item.author, account)) || candidates[0];
    if (!selected) continue;

    try {
      await sleep(2200);
      const detail = await extractDetail(selected.url, {
        maxComments,
        minCommentLikes,
        includeInteractionFallback,
        rawOutPath,
        screenshotOutPath,
      });
      return {
        input: configPath,
        account: account.name,
        queries,
        candidates: filtered.slice(0, maxVideos),
        url: selected.url,
        ...selected,
        ...detail,
        errors,
      };
    } catch (error) {
      errors.push(`Detail failed for ${selected.url}: ${compactError(error)}`);
    }
  }

  return {
    input: configPath,
    title: config.title || "抖音视频候选",
    url: "",
    errors: errors.length ? errors : ["No matching public video candidate was found."],
  };
}

async function extractUrl(url, chunkSize = 12000) {
  await runBrowser(["open", url]);
  const extracted = normalizeObject(await runBrowser(["extract", "--chunk-size", String(chunkSize)]));
  return String(extracted.content || "");
}

async function extractDetail(url, options) {
  await runBrowser(["open", url]);
  const first = normalizeObject(await runBrowser(["extract", "--chunk-size", "14000"]));
  let content = String(first.content || "");
  if (first.next_start_char) {
    const second = normalizeObject(
      await runBrowser(["extract", "--chunk-size", "14000", "--start", String(first.next_start_char)])
    );
    content += `\n${String(second.content || "")}`;
  }
  if (options.rawOutPath) await writeFile(options.rawOutPath, content, "utf8");
  await sleep(1000);
  const detail = parseDetailContent(content, options);
  const pageState = await inspectAndResetDetailPage();
  const detailEvidence = validateDetailEvidence(url, content, detail, pageState);
  if (!detailEvidence.ok) {
    throw new Error(`Detail-page evidence check failed: ${detailEvidence.errors.join("; ")}`);
  }
  let screenshot = {};
  if (options.screenshotOutPath) {
    await sleep(800);
    screenshot = await captureDetailScreenshot(options.screenshotOutPath);
  }
  const media = await extractMediaUrls();
  // 页面文本里只解析得到首屏那几条评论，滚动采集能拿到几十条真实用户原话
  const scrolled = await scrollAndCollectComments(options.commentTarget || 80);
  if (scrolled.comments?.length > (detail.comments?.length || 0)) {
    detail.comments = scrolled.comments;
    detail.commentCollection = { method: "scroll", loadedNodes: scrolled.loaded };
  }
  return { ...detail, ...media, detailEvidence, ...screenshot };
}

async function inspectAndResetDetailPage() {
  const js = `(() => {
    const box = document.querySelector(".route-scroll-container");
    if (box) box.scrollTop = 0;
    window.scrollTo(0, 0);
    const text = document.body?.innerText || "";
    return {
      currentUrl: location.href,
      title: document.title,
      hasPublishTime: text.includes("发布时间："),
      hasReportMarker: text.includes("举报"),
      scrollTop: box ? box.scrollTop : window.scrollY,
    };
  })()`;
  return normalizeObject(await runBrowser(["eval", js]));
}

function validateDetailEvidence(inputUrl, content, detail, pageState) {
  const errors = [];
  const currentUrl = String(pageState.currentUrl || "");
  const inputId = String(inputUrl).match(/\/video\/(\d+)/)?.[1] || "";
  const currentId = currentUrl.match(/\/video\/(\d+)/)?.[1] || "";
  const publishMatch = content.match(/发布时间：([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2})/);
  const beforePublish = publishMatch
    ? content.slice(Math.max(0, publishMatch.index - 900), publishMatch.index)
    : "";
  const metricLines = cleanLines(beforePublish).filter((line) => /^(\d+(?:\.\d+)?万?|\d+)$/.test(line));

  if (!currentId) errors.push("当前页面不是具体视频详情页");
  if (inputId && currentId && inputId !== currentId) errors.push("打开的视频 ID 与输入链接不一致");
  if (!detail.title) errors.push("未识别到视频标题");
  if (!detail.publishedAt || !pageState.hasPublishTime) errors.push("未识别到发布时间");
  if (metricLines.length < 4 || !pageState.hasReportMarker) errors.push("点赞/评论/收藏/分享数据尚未稳定出现");

  return {
    ok: errors.length === 0,
    errors,
    currentUrl,
    videoId: currentId,
    visibleMetricCount: metricLines.length,
    capturedAt: new Date().toISOString(),
  };
}

async function captureDetailScreenshot(path) {
  await execFileAsync(
    "opencli",
    ["browser", session, "screenshot", "--width", "1440", "--height", "1000", path],
    { maxBuffer: 10 * 1024 * 1024, timeout: 120000 }
  );
  const info = await stat(path);
  if (!info.isFile() || info.size < 10000) {
    throw new Error(`Detail-page screenshot was not created correctly: ${path}`);
  }
  return {
    sourceScreenshot: path,
    sourceScreenshotBytes: info.size,
  };
}

async function extractMediaUrls() {
  const js = `(async () => {
    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const unique = (items) => [...new Set(items.filter(
      (url) => typeof url === "string" && /^https?:\\/\\//.test(url)
    ))];
    const diagnostics = {
      video_element_count: 0,
      playable_video_count: 0,
      current_src_count: 0,
      detail_resource_count: 0,
      detail_fetch_status: 0,
      detail_fetch_error: "",
      performance_media_count: 0,
    };
    let domVideoUrls = [];
    let domAudioUrls = [];

    // currentSrc is the strongest browser-grounded source. Performance entries can
    // be absent when the resource was cached or the buffer was read too early.
    for (let attempt = 0; attempt < 10; attempt += 1) {
      const videos = [...document.querySelectorAll("video")];
      const audios = [...document.querySelectorAll("audio")];
      diagnostics.video_element_count = videos.length;
      for (const video of videos) {
        try {
          video.muted = true;
          if (video.paused) await video.play();
        } catch {}
      }
      domVideoUrls = unique(videos.flatMap((video) => [
        video.currentSrc,
        video.src,
        ...[...video.querySelectorAll("source")].map((source) => source.src),
      ]));
      domAudioUrls = unique(audios.flatMap((audio) => [
        audio.currentSrc,
        audio.src,
        ...[...audio.querySelectorAll("source")].map((source) => source.src),
      ]));
      diagnostics.playable_video_count = videos.filter((video) => video.readyState >= 2).length;
      diagnostics.current_src_count = domVideoUrls.length;
      if (domVideoUrls.length) break;
      await sleep(800);
    }

    const resources = performance.getEntriesByType("resource").map((entry) => entry.name);
    const detailUrls = unique(resources.filter((url) => url.includes("/aweme/v1/web/aweme/detail/")));
    diagnostics.detail_resource_count = detailUrls.length;
    const mediaUrls = [];
    const audioUrls = [];
    for (const detailUrl of detailUrls.slice().reverse()) {
      try {
        const response = await fetch(detailUrl, { credentials: "include" });
        diagnostics.detail_fetch_status = response.status;
        const body = await response.text();
        if (!body) throw new Error("detail response body was empty");
        const data = JSON.parse(body);
        const video = data?.aweme_detail?.video || {};
        for (const key of ["play_addr_h264", "play_addr"]) {
          const urls = video?.[key]?.url_list;
          if (Array.isArray(urls)) mediaUrls.push(...urls);
        }
        for (const rate of video?.bit_rate || []) {
          if (rate?.format === "mp4" && Array.isArray(rate?.play_addr?.url_list)) {
            mediaUrls.push(...rate.play_addr.url_list);
          }
        }
        for (const rate of video?.bit_rate_audio || []) {
          const list = rate?.audio_meta?.url_list || {};
          audioUrls.push(...Object.values(list));
        }
        if (mediaUrls.length || audioUrls.length) break;
      } catch (error) {
        diagnostics.detail_fetch_error = String(error?.message || error || "detail fetch failed");
      }
    }
    const performanceMedia = unique(resources.filter(
      (url) => /mime_type=video_mp4|media-video|\\.mp4|m3u8/i.test(url)
    ));
    diagnostics.performance_media_count = performanceMedia.length;
    // 抖音的 DASH 播放会把纯音轨也标成 mime_type=video_mp4。
    // 不能只看 mime_type，必须优先按 media-audio / media-video 区分轨道。
    const performanceAudio = performanceMedia.filter((url) => /media-audio/i.test(url));
    const performanceVideo = performanceMedia.filter((url) => !/media-audio/i.test(url));
    return {
      media_urls: unique([...mediaUrls, ...domVideoUrls, ...performanceMedia]),
      audio_urls: unique([...audioUrls, ...domAudioUrls, ...performanceAudio]),
      video_only_urls: unique([...domVideoUrls, ...performanceVideo]),
      media_diagnostics: diagnostics,
    };
  })()`;
  try {
    const result = await runBrowser(["eval", js]);
    return normalizeObject(result);
  } catch (error) {
    return {
      media_urls: [],
      audio_urls: [],
      video_only_urls: [],
      media_diagnostics: { browser_eval_error: compactError(error) },
    };
  }
}

async function scrollAndCollectComments(targetCount) {
  // 抖音评论区没有可复用的翻页接口，评论也不是随首屏一次给全的。
  // 真正的滚动容器是 .route-scroll-container（body 和评论区祖先都不带滚动条），
  // 滚它才会继续加载。取够就停——用不着把几百条全捞下来。
  const js = `(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const nodes = () => [...document.querySelectorAll("[data-e2e=comment-item]")];
    const box = document.querySelector(".route-scroll-container");
    let stall = 0;
    if (box) {
      for (let i = 0; i < 20 && nodes().length < ${targetCount} && stall < 4; i++) {
        const before = nodes().length;
        box.scrollTop = box.scrollHeight;
        await sleep(1800);
        stall = nodes().length === before ? stall + 1 : 0;
      }
    }
    const timePattern = /(刚刚|\\d+分钟前|\\d+小时前|昨天|前天|\\d+天前|\\d+周前|\\d+月前|\\d+年前)/;
    const parsed = nodes().map((el) => {
      const lines = el.innerText.split("\\n").map((s) => s.trim()).filter(Boolean);
      const timeIdx = lines.findIndex((l) => timePattern.test(l));
      if (timeIdx < 1) return null;
      const body = lines.slice(1, timeIdx).filter((l) => l !== "...").join(" ").trim();
      if (!body) return null;
      const likesRaw = lines[timeIdx + 1] || "0";
      const likes = /^\\d+(\\.\\d+)?万?$/.test(likesRaw)
        ? Math.round(parseFloat(likesRaw) * (likesRaw.includes("万") ? 10000 : 1))
        : 0;
      return { author: lines[0], text: body, time: lines[timeIdx], likes };
    }).filter(Boolean);
    // 同一条评论可能被相邻节点重复包含，按正文去重
    const seen = new Set();
    const unique = parsed.filter((c) => (seen.has(c.text) ? false : seen.add(c.text)));
    return { comments: unique, loaded: nodes().length };
  })()`;
  try {
    return normalizeObject(await runBrowser(["eval", js]));
  } catch {
    return { comments: [], loaded: 0 };
  }
}

function parseSearchResults(content, query) {
  const results = [];
  const linkPattern = /\]\((?:https:)?\/\/www\.douyin\.com\/video\/(\d+)\)/g;
  let match;
  while ((match = linkPattern.exec(content))) {
    const id = match[1];
    const start = Math.max(0, content.lastIndexOf("-   [", match.index));
    const block = content.slice(start, match.index);
    const lines = cleanLines(block);
    const authorIndex = findLastIndex(lines, (line) =>
      /^@.+?(刚刚|\d+分钟前|\d+小时前|昨天|前天|\d+天前|\d+周前|\d+月前|\d+年前)$/.test(line)
    );
    const authorLine = authorIndex >= 0 ? lines[authorIndex] : "";
    const relativeTime = authorLine.match(/(刚刚|\d+分钟前|\d+小时前|昨天|前天|\d+天前|\d+周前|\d+月前|\d+年前)$/)?.[1] || "";
    const author = authorLine ? authorLine.replace(/^@/, "").replace(relativeTime, "").trim() : "";
    const title = cleanMarkdownInline(authorIndex > 0 ? lines[authorIndex - 1] : findLikelyTitle(lines));
    const searchMetric = Number.parseInt((authorIndex > 1 ? lines[authorIndex - 2] : "").replace(/[^\d]/g, ""), 10) || 0;
    if (!title) continue;
    results.push({
      id,
      url: `https://www.douyin.com/video/${id}`,
      title,
      author,
      relativeTime,
      searchMetric,
      query,
    });
  }
  return results;
}

function parseDetailContent(content, options) {
  const publishMatch = content.match(/发布时间：([0-9]{4}-[0-9]{2}-[0-9]{2}\s+[0-9]{2}:[0-9]{2})/);
  const publishedAt = publishMatch?.[1] || "";
  const beforePublish = publishMatch ? content.slice(Math.max(0, publishMatch.index - 900), publishMatch.index) : content.slice(0, 1800);
  const metricLines = cleanLines(beforePublish).filter((line) => /^(\d+(?:\.\d+)?万?|\d+)$/.test(line));
  const metrics = metricLines.slice(-4).map(numberValue);
  const title =
    cleanMarkdownInline(content.match(/#\s+(.+?)\n\n(?:\d+(?:\.\d+)?万?\n\n){1,4}举报\n\n发布时间：/s)?.[1]) ||
    cleanMarkdownInline(content.match(/#\s+([^\n]{4,120})/)?.[1]) ||
    "";
  const author =
    cleanMarkdownInline(content.match(/\n\n([^\n]{1,60})\n\n\]\(\/\/www\.douyin\.com\/user\//)?.[1]) ||
    cleanMarkdownInline(content.match(/@([^\n]{2,40})/)?.[1]) ||
    "";

  return {
    title,
    author,
    publishedAt,
    metrics: {
      likes: metrics[0] || 0,
      comments: metrics[1] || 0,
      collects: metrics[2] || 0,
      shares: metrics[3] || 0,
    },
    comments: parseComments(content, options.maxComments, options.minCommentLikes, options.includeInteractionFallback),
  };
}

function parseComments(content, maxComments, minCommentLikes, includeInteractionFallback) {
  const start = content.indexOf("全部评论");
  if (start < 0) return [];
  const lines = cleanLines(content.slice(start));
  const likedComments = [];
  const interactionFallback = [];
  for (let i = 0; i < lines.length; i += 1) {
    if (!/^(刚刚|\d+分钟前|\d+小时前|昨天|前天|\d+天前|\d+周前|\d+月前|\d+年前)(·.+)?$/.test(lines[i])) continue;
    const text = findPreviousCommentText(lines, i);
    if (!text || text.length < 2 || /^0+$/.test(text)) continue;
    const author = findPreviousAuthor(lines, i);
    const likes = numberValue(lines.slice(i + 1).find((line) => /^(\d+(?:\.\d+)?万?|\d+)$/.test(line)) || "0");
    if (likes >= minCommentLikes) {
      likedComments.push({ author, text, time: lines[i], likes, signal: "有赞" });
      if (likedComments.length >= maxComments) break;
      continue;
    }
    if (includeInteractionFallback && isInteractionComment(text)) {
      interactionFallback.push({ author, text, time: lines[i], likes, signal: "互动" });
    }
  }
  if (likedComments.length) return likedComments;
  return interactionFallback.slice(0, maxComments);
}

function findPreviousCommentText(lines, dateIndex) {
  for (let i = dateIndex - 1; i >= 0; i -= 1) {
    const line = lines[i];
    if (isNoise(line)) continue;
    if (/^(\d+(?:\.\d+)?万?|\d+)$/.test(line)) continue;
    if (/^\[.+\]\(\/\/www\.douyin\.com\/user\//.test(line)) continue;
    const cleaned = cleanMarkdownInline(line);
    const namedComment = cleaned.match(/^[^:：]{1,32}[:：](.+)$/);
    return (namedComment ? namedComment[1] : cleaned).trim();
  }
  return "";
}

function findPreviousAuthor(lines, dateIndex) {
  for (let i = dateIndex - 1; i >= 0; i -= 1) {
    const match = lines[i].match(/^\[([^\]]+)\]\(\/\/www\.douyin\.com\/user\//);
    if (match) return match[1];
  }
  return "";
}

function cleanLines(text) {
  return String(text)
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .filter((line) => !line.startsWith("![]("));
}

function isNoise(line) {
  return (
    line === "..." ||
    line === "分享" ||
    line === "回复" ||
    line === "作者赞过" ||
    line === "加载中" ||
    line === "留下你的精彩评论吧" ||
    line.startsWith("大家都在搜") ||
    line.startsWith("[![")
  );
}

function findLikelyTitle(lines) {
  const title = [...lines]
    .reverse()
    .find((line) => line.length > 6 && !line.startsWith("@") && !/^\d/.test(line) && !line.includes("http"));
  return title ? cleanMarkdownInline(title) : "";
}

function isInteractionComment(text) {
  return /(@|回复|请问|求问|想问|怎么|如何|有没有|能不能|可以吗|吗|？|\?|博主|主播|老师|求|指路|讲讲|展开说|我也|我现在|我就是|有人)/.test(
    text
  );
}

function cleanMarkdownInline(value) {
  return String(value || "")
    .replace(/!\[[\s\S]*?\]\([^)]+\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

function matchesAccountAuthor(author, account) {
  const candidates = [account.name, ...(account.authorKeywords || [])].filter(Boolean);
  return candidates.some((candidate) => containsLoose(author, candidate));
}

function containsLoose(source, target) {
  const clean = (value) => String(value || "").replace(/\s+/g, "").toLowerCase();
  return clean(source).includes(clean(target));
}

function ageInDays(value) {
  const text = String(value || "").trim();
  if (!text) return null;
  if (/刚刚|分钟前|小时前/.test(text)) return 0;
  if (/昨天/.test(text)) return 1;
  if (/前天/.test(text)) return 2;
  const days = text.match(/(\d+)\s*天前/);
  if (days) return Number(days[1]);
  const weeks = text.match(/(\d+)\s*周前/);
  if (weeks) return Number(weeks[1]) * 7;
  const months = text.match(/(\d+)\s*月前/);
  if (months) return Number(months[1]) * 30;
  const parsed = new Date(text.replace(/\./g, "-").replace(/\//g, "-"));
  if (Number.isNaN(parsed.getTime())) return null;
  return Math.floor((startOfDay(new Date()) - startOfDay(parsed)) / 86400000);
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function numberValue(value) {
  if (value == null || value === "") return 0;
  if (typeof value === "number") return value;
  const text = String(value).replace(/,/g, "").trim();
  const match = text.match(/([\d.]+)/);
  if (!match) return 0;
  const n = Number(match[1]);
  if (text.includes("万")) return Math.round(n * 10000);
  if (text.toLowerCase().includes("k")) return Math.round(n * 1000);
  return Math.round(n);
}

async function runOpenCli(params) {
  const { stdout, stderr } = await execFileAsync("opencli", [...params, "-f", "json"], {
    maxBuffer: 30 * 1024 * 1024,
    timeout: 120000,
  });
  const parsed = parseJson(stdout);
  if (parsed == null) throw new Error((stderr || stdout || "OpenCLI returned no JSON.").trim());
  return parsed;
}

async function runBrowser(params) {
  const { stdout, stderr } = await execFileAsync("opencli", ["browser", session, ...params], {
    maxBuffer: 60 * 1024 * 1024,
    timeout: 120000,
  });
  const parsed = parseJson(stdout);
  if (parsed == null) throw new Error((stderr || stdout || "OpenCLI browser returned no JSON.").trim());
  return parsed;
}

async function closeSessionQuietly(name) {
  try {
    await execFileAsync("opencli", ["browser", name, "close"], { timeout: 15000 });
  } catch {
    // Session may not have opened.
  }
}

function parseJson(output) {
  const text = String(output || "").trim();
  if (!text) return null;
  const firstObject = text.indexOf("{");
  const firstArray = text.indexOf("[");
  const start = firstObject === -1 ? firstArray : firstArray === -1 ? firstObject : Math.min(firstObject, firstArray);
  if (start === -1) return null;
  const json = text.slice(start);
  try {
    return JSON.parse(json);
  } catch {
    const end = Math.max(json.lastIndexOf("}"), json.lastIndexOf("]"));
    if (end === -1) return null;
    return JSON.parse(json.slice(0, end + 1));
  }
}

function normalizeObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function compactError(error) {
  const message = String(error?.message || error || "");
  return (
    message
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find((line) => line && !line.startsWith("Command failed:") && !line.startsWith("(node:")) || "OpenCLI read failed"
  );
}

function numberArg(name, fallback) {
  return args[name] == null ? fallback : Number(args[name]);
}

function parseArgs(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) continue;
    const key = token.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith("--")) result[key] = true;
    else {
      result[key] = next;
      i += 1;
    }
  }
  return result;
}

function findLastIndex(items, predicate) {
  for (let i = items.length - 1; i >= 0; i -= 1) {
    if (predicate(items[i], i)) return i;
  }
  return -1;
}

function sleep(ms) {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}
