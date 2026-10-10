/* 杜一社交媒体卡片：本地多平台卡片工具 */

// 后台标签页里 rAF 被冻结，会卡死 html-to-image 导出和卡片测量；隐藏时退化为 setTimeout
const _raf = window.requestAnimationFrame.bind(window);
window.requestAnimationFrame = (cb) =>
  document.hidden ? setTimeout(() => cb(performance.now()), 32) : _raf(cb);

const $ = (id) => document.getElementById(id);

const DEFAULT_PROFILE = { name: "你的名字", handle: "yourname", avatar: "avatar-placeholder.svg", verified: false };

/* 抖音安全区：全站唯一真源，画布 px（1080 宽）。虚线参考线和卡片布局都读这份，预览 = 画布 × PREVIEW */
const SAFE = {
  poster: { w: 1080, h: 1440, top: 150, right: 140, bottom: 300, left: 60 },
  tall:   { w: 1080, h: 1920, top: 176, right: 140, bottom: 300, left: 60 },
};
const PREVIEW = 0.5;
/* 抖音右侧互动栏模拟：栏宽（画布 px），用来在右侧留白带里居中 */
const RAIL_W = 96;

/* 正文字号（画布 px，成品 1080 宽下的真实像素）。自动模式从 FONT_BASE 往下调，不往上放大 */
const FONT_BASE = 34, FONT_MIN = 20, FONT_MAX = 48;
/* 字号到底仍超高时允许的整卡微缩下限，再往下就成细长条了，不如放行 */
const RESIDUAL_MIN = 0.75;
/* 纯卡片模式没有画框，宽度固定（画布 px）。908 × PREVIEW × 导出 pixelRatio 3 = 1362，
   与加安全区约束之前的成品尺寸保持一致 */
const CARD_ONLY_W = 908;

const state = {
  profile: { ...DEFAULT_PROFILE },
  customText: "",
  platform: "x",
  question: "",
  momentsAt: "",
  momentsAvatars: [],
  momentsShowPeople: false,
  mode: "poster",        // poster | card
  theme: "light",        // light | dark
  metricsOn: false,
  platformMetrics: { x: false, moments: false, weibo: false, zhihu: false },
  // 以下几何量统一用画布 px（预览按 PREVIEW 折算），默认锚点是安全区中心
  cardWidth: 100,        // 卡片宽度占安全区宽度的百分比，50–100
  fontSize: FONT_BASE,   // 手动字号（画布 px）
  fontAuto: true,        // 自动缩字号直到内容进安全区
  fitFont: FONT_BASE,    // 实际生效的字号
  fitScale: 1,           // 字号已到底仍超高时的兜底整卡缩放
  cardX: 0,              // 拖动偏移（画布 px，相对安全区中心）
  cardY: 0,
  cardOpacity: 100,
  guidesOn: true,        // 抖音安全区参考线（仅预览，不进导出）
  bg: null,              // 当前背景的 URL / dataURL
  fakeMetrics: null,     // 卡片上显示的随机互动数据
  metricsProvided: false,
  dateOverride: "",      // URL 参数指定的日期
  backgrounds: [],       // manifest 内容，供 bg 参数解析
};

const MOMENTS_AVATARS_KEY = "duyi-social-card-moments-avatars";
const PLATFORMS = { x: "推特", moments: "朋友圈", weibo: "微博", zhihu: "知乎" };

/* ---------- 工具 ---------- */

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function fmtNum(n) {
  if (n == null) return "0";
  if (n >= 10000) return (n / 10000).toFixed(n >= 100000 ? 0 : 1).replace(/\.0$/, "") + "万";
  if (n >= 1000) return n.toLocaleString("en-US");
  return String(n);
}

function fmtDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  const now = new Date();
  return (y === now.getFullYear() ? "" : `${y}年`) + `${m}月${d}日`;
}

function todayISO() {
  const t = new Date();
  return `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
}

/* ---------- 账号信息（profile.json 默认值 + localStorage 本机覆盖） ---------- */

const PROFILE_KEY = "duyi-social-card-profile";

async function loadProfile(useLocalOverride = true) {
  try {
    const base = await fetch("profile.json", { cache: "no-store" }).then((r) => (r.ok ? r.json() : {}));
    Object.assign(state.profile, base);
  } catch { /* 没有 profile.json 就用内置默认 */ }
  if (useLocalOverride) {
    try {
      Object.assign(state.profile, JSON.parse(localStorage.getItem(PROFILE_KEY) || "{}"));
    } catch { /* 本机覆盖损坏则忽略 */ }
  }
  applyProfile();
}

function saveProfileOverride(patch) {
  Object.assign(state.profile, patch);
  try {
    const saved = JSON.parse(localStorage.getItem(PROFILE_KEY) || "{}");
    localStorage.setItem(PROFILE_KEY, JSON.stringify(Object.assign(saved, patch)));
  } catch (e) {
    alert("保存到本机失败（可能是头像图片太大）：" + e.message);
  }
  applyProfile();
}

function applyProfile() {
  const p = state.profile;
  const avatarSrc = p.avatarData || p.avatar || "avatar-placeholder.svg";
  $("tc-avatar").src = avatarSrc;
  $("brand-avatar").src = avatarSrc;
  $("profile-avatar-preview").src = avatarSrc;
  $("tc-name-text").textContent = p.name;
  $("tc-handle-text").textContent = "@" + p.handle;
  $("tc-badge").style.display = p.verified && state.platform === "x" ? "" : "none";
  $("tc-weibo-badge").classList.toggle("hidden", !p.verified || state.platform !== "weibo");
  $("brand-eyebrow").textContent = `${p.name} · @${p.handle}`.toUpperCase();
  $("profile-name").value = p.name;
  $("profile-handle").value = p.handle;
  $("badge-on").classList.toggle("active", !!p.verified);
  $("badge-off").classList.toggle("active", !p.verified);
}

/* 随机但好看的互动数据：浏览量对数均匀分布，其余按真实比例区间派生 */
function rollMetrics() {
  state.metricsProvided = false;
  const r = (min, max) => min + Math.random() * (max - min);
  const views = Math.round(30000 * Math.pow(25, Math.random()) / 100) * 100; // 3万 ~ 75万
  const likes = Math.round(views * r(0.022, 0.045));
  state.fakeMetrics = {
    views,
    likes,
    bookmarks: Math.round(likes * r(0.55, 1.05)),
    reposts: Math.round(likes * r(0.15, 0.32)),
    replies: Math.round(likes * r(0.05, 0.12)),
  };
}

/* ---------- 卡片渲染 ---------- */

const METRIC_ICONS = {
  replies: '<svg viewBox="0 0 24 24"><path d="M1.751 10c0-4.42 3.584-8 8.005-8h4.366c4.49 0 8.129 3.64 8.129 8.13 0 2.96-1.607 5.68-4.196 7.11l-8.054 4.46v-3.69h-.067c-4.49.1-8.183-3.51-8.183-8.01z"/></svg>',
  reposts: '<svg viewBox="0 0 24 24"><path d="M4.5 3.88l4.432 4.14-1.364 1.46L5.5 7.55V16c0 1.1.896 2 2 2H13v2H7.5c-2.209 0-4-1.79-4-4V7.55L1.432 9.48.068 8.02 4.5 3.88zM16.5 6H11V4h5.5c2.209 0 4 1.79 4 4v8.45l2.068-1.93 1.364 1.46-4.432 4.14-4.432-4.14 1.364-1.46 2.068 1.93V8c0-1.1-.896-2-2-2z"/></svg>',
  likes: '<svg viewBox="0 0 24 24"><path d="M16.697 5.5c-1.222-.06-2.679.51-3.89 2.16l-.805 1.09-.806-1.09C9.984 6.01 8.526 5.44 7.304 5.5c-1.243.07-2.349.78-2.91 1.91-.552 1.12-.633 2.78.479 4.82 1.074 1.97 3.257 4.27 7.129 6.61 3.87-2.34 6.052-4.64 7.126-6.61 1.111-2.04 1.03-3.7.477-4.82-.561-1.13-1.666-1.84-2.908-1.91z"/></svg>',
  bookmarks: '<svg viewBox="0 0 24 24"><path d="M4 4.5C4 3.12 5.119 2 6.5 2h11C18.881 2 20 3.12 20 4.5v18.44l-8-5.71-8 5.71V4.5z"/></svg>',
  views: '<svg viewBox="0 0 24 24"><path d="M8.75 21V3h2v18h-2zM18 21V8.5h2V21h-2zM4 21l.004-10h2L6 21H4zm9.248 0v-7h2v7h-2z"/></svg>',
};

/* 正文渲染：链接 / @提及 / #话题 显示为 X 蓝，与真实推文一致 */
function renderBody(text) {
  const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc
    .replace(/(?:https?:\/\/)?(?:[\w-]+\.)+[a-z]{2,}(?:\/[^\s]*)?/gi, (m) => `<span class="tc-link">${m}</span>`)
    .replace(/(^|[^\w@/])@([A-Za-z0-9_]{2,15})/g, '$1<span class="tc-link">@$2</span>')
    .replace(/(^|[^&\w])#([\p{L}\p{N}_]+)/gu, '$1<span class="tc-link">#$2</span>');
}

function momentsTimestamp(date) {
  if (state.momentsAt) return state.momentsAt;
  const now = new Date();
  state.momentsAt = date + "T" + String(now.getHours()).padStart(2,"0") + ":" + String(now.getMinutes()).padStart(2,"0");
  return state.momentsAt;
}

function renderMomentsLikes(container) {
  container.replaceChildren();
  container.classList.toggle("hidden", !state.metricsOn);
  if (!state.metricsOn) return;
  container.innerHTML = '<svg class="moments-heart" viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 20.2 3.2 11.5C-2 6.2 5.4-.3 12 6.2c6.6-6.5 14 0 8.8 5.3Z" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linejoin="round"/></svg>';
  if (!state.momentsShowPeople) return;
  const avatars = document.createElement("div");
  avatars.className = "moments-likers";
  for (const src of state.momentsAvatars) {
    const img = document.createElement("img");
    img.src = src;
    img.alt = "点赞头像";
    avatars.append(img);
  }
  container.append(avatars);
}

function renderPlatform(date) {
  const platform = state.platform;
  $("tweet-card").dataset.platform = platform;
  $("tc-handle-text").textContent = platform === "x" ? "@" + state.profile.handle : "";
  $("tc-handle-separator").hidden = platform !== "x";
  $("tc-badge").style.display = state.profile.verified && platform === "x" ? "" : "none";
  $("tc-weibo-badge").classList.toggle("hidden", !state.profile.verified || platform !== "weibo");
  $("tc-platform-brand").textContent = ["weibo", "zhihu"].includes(platform) ? PLATFORMS[platform] : "";
  const question = $("tc-question");
  question.textContent = state.question;
  question.classList.toggle("hidden", platform !== "zhihu" || !state.question.trim());
  $("zhihu-fields").classList.toggle("hidden", platform !== "zhihu");
  $("moments-fields").classList.toggle("hidden", platform !== "moments");
  $("metrics-label").textContent = platform === "moments" ? "点赞区" : state.metricsProvided ? "互动数据（用户提供）" : "互动数据（随机示例）";
  $("shuffle-metrics").classList.toggle("hidden", platform === "moments");
  $("moments-likes-status").textContent = state.momentsAvatars.length ? `已添加 ${state.momentsAvatars.length} 张头像` : "暂未添加点赞人头像";
  $("moments-likes-clear").disabled = !state.momentsAvatars.length;
  $("moments-show-people").checked = state.momentsShowPeople;
  const meta = $("tc-platform-meta");
  meta.replaceChildren();
  meta.classList.toggle("hidden", !["moments", "zhihu"].includes(platform));
  const time = document.createElement("span");
  time.className = "tc-moments-date";
  if (platform === "moments") {
    const stamp = momentsTimestamp(date);
    $("moments-datetime").value = stamp;
    const [day, clock] = stamp.split("T");
    const [y, mo, d] = day.split("-");
    time.textContent = `${y}年${Number(mo)}月${Number(d)}日 ${clock}`;
  } else time.textContent = "发布于 " + date;
  meta.append(time);
  if (platform === "moments") {
    const trash = document.createElement("span");
    trash.className = "tc-moments-delete";
    trash.innerHTML = '<svg viewBox="0 0 20 24" aria-hidden="true"><path fill="currentColor" d="M7 1h6v2h5v2H2V3h5zm-3 6h12l-1 16H5z"/><path stroke="white" stroke-width="1.2" d="M8 10v9m4-9v9"/></svg>';
    meta.append(trash);
    const more = document.createElement("span");
    more.className = "tc-moments-more";
    more.textContent = "••";
    meta.append(more);
  }
  for (const key of Object.keys(PLATFORMS)) {
    $("platform-" + key).classList.toggle("active", key === platform);
    $("platform-" + key).setAttribute("aria-pressed", String(key === platform));
  }
}

function renderPlatformMetrics(m) {
  const item = (key, label, metric = key) => m[metric] == null ? "" : `<span class="metric-${key}">${METRIC_ICONS[metric] || ""}<b>${fmtNum(m[metric])}</b>${label ? `<span>${label}</span>` : ""}</span>`;
  if (state.platform === "weibo") return item("reposts", "转发") + item("replies", "评论") + item("likes", "赞");

  if (state.platform === "zhihu") return (m.likes == null ? "" : `<span class="metric-vote">▲ 赞同 ${fmtNum(m.likes)}</span>`) + item("replies", "评论") + item("bookmarks", "收藏") + '<span class="metric-share">分享</span>';
  return ["replies", "reposts", "likes", "bookmarks", "views"].map((key) => item(key, "")).join("");
}

function renderCard() {
  const text = state.customText || "写点什么……";
  const date = state.dateOverride || todayISO();

  const body = $("tc-body");
  body.innerHTML = renderBody(text);

  $("tc-date").textContent = fmtDate(date);
  renderPlatform(date);

  const card = $("tweet-card");
  card.classList.toggle("dark", state.theme === "dark");
  $("width-val").textContent = state.cardWidth + "%";

  // 背景半透明（只透卡片底色，文字不透）
  const alpha = state.cardOpacity / 100;
  card.style.backgroundColor = state.theme === "dark"
    ? `rgba(0, 0, 0, ${alpha})` : `rgba(255, 255, 255, ${alpha})`;
  $("opacity-val").textContent = state.cardOpacity + "%";

  const metricsEl = $("tc-metrics");
  const m = state.fakeMetrics;
  metricsEl.dataset.sample = String(state.platform !== "moments" && state.metricsOn && !state.metricsProvided);
  if (state.platform === "moments") {
    renderMomentsLikes(metricsEl);
  } else if (state.metricsOn && m) {
    metricsEl.classList.remove("hidden");
    metricsEl.innerHTML = renderPlatformMetrics(m);
  } else {
    metricsEl.classList.add("hidden");
  }

  const stage = $("stage");
  const isFrame = state.mode !== "card"; // poster(3:4) 或 tall(9:16)
  stage.classList.toggle("card-only", !isFrame);
  stage.classList.toggle("tall", state.mode === "tall");
  $("preview-label").textContent = state.mode === "card" ? "纯卡片 · PNG"
    : state.mode === "tall" ? "9:16 竖图 · 1080×1920" : "3:4 竖图 · 1080×1440";
  $("drag-hint").style.display = isFrame ? "" : "none";

  // 安全区参考线只在竖图模式且开关打开时显示
  $("safe-guides").classList.toggle("hidden", !isFrame || !state.guidesOn);
  renderRail();
  $("guides-toggle").style.display = isFrame ? "" : "none";
  $("live-btn").style.display = isFrame ? "" : "none";


  // 竖图模式：卡片浮动在安全区里（可拖动）；纯卡片模式贴着画布流式排版
  card.classList.toggle("floating", isFrame);
  layoutCard();
}

/* 安全区几何（预览 px，相对 stage 左上角）。纯卡片模式没有画框，借用 3:4 的宽度当基准 */
function safeBox() {
  const s = SAFE[state.mode === "tall" ? "tall" : "poster"];
  const k = PREVIEW;
  const x0 = s.left * k, x1 = (s.w - s.right) * k;
  const y0 = s.top * k, y1 = (s.h - s.bottom) * k;
  return {
    x0, y0, x1, y1, w: x1 - x0, h: y1 - y0,
    cx: (x0 + x1) / 2, cy: (y0 + y1) / 2,
    stageW: s.w * k, stageH: s.h * k,
  };
}

/* 参考线位置由 SAFE 直接生成，避免 CSS 里再抄一遍数字 */
function syncGuides() {
  const s = SAFE[state.mode === "tall" ? "tall" : "poster"];
  const k = PREVIEW;
  const set = (sel, prop, v) => { const el = document.querySelector(sel); if (el) el.style[prop] = v * k + "px"; };
  set(".sg-top", "top", s.top);
  set(".sg-right", "right", s.right);
  set(".sg-bottom", "bottom", s.bottom);
  set(".sg-left", "left", s.left);
  set(".sg-label-top", "top", s.top + 8);
  set(".sg-label-right", "right", s.right + 8);
  set(".sg-label-bottom", "bottom", s.bottom + 8);
  const lab = document.querySelector(".sg-label-top"), lab2 = document.querySelector(".sg-label-bottom");
  [lab, lab2].forEach((el) => { if (el) el.style.left = (s.left + 8) * k + "px"; });

  // 互动栏在右侧留白带里居中，底边压着底部虚线，正好落在文案区上方
  const rail = $("tt-rail");
  if (rail) {
    rail.style.right = ((s.right - RAIL_W) / 2) * k + "px";
    rail.style.bottom = (s.bottom + 16) * k + "px";
  }
}

/* 互动栏内容：头像和数字都跟卡片走，换一组数据时一起变 */
function renderRail() {
  const rail = $("tt-rail");
  if (!rail) return;
  // 只在 9:16 且开着参考线时出现——它和虚线是同一件事：告诉你抖音会盖住哪里
  const on = state.mode === "tall" && state.guidesOn;
  rail.classList.toggle("hidden", !on);
  // 图标本身就说明了这条带子是干什么的，旁边那个竖排标签就多余了
  const label = document.querySelector(".sg-label-right");
  if (label) label.style.display = on ? "none" : "";
  if (!on) return;

  $("ttr-avatar-img").src = state.profile.avatarData || state.profile.avatar;
  const m = state.fakeMetrics;
  if (m) {
    $("ttr-likes").textContent = fmtNum(m.likes);
    $("ttr-replies").textContent = fmtNum(m.replies);
    $("ttr-bookmarks").textContent = fmtNum(m.bookmarks);
    $("ttr-reposts").textContent = fmtNum(m.reposts);
  }
}

function applyFont(canvasPx) {
  const body = $("tc-body");
  body.style.fontSize = canvasPx * PREVIEW + "px";
  // 字号越小行距越紧，沿用原来 34/30/26/23 四档的手感
  body.style.lineHeight = state.platform === "moments" ? "1.5" : (1.5 + (canvasPx - 22) * 0.01).toFixed(3);
}

/* 自动模式缩小字号和卡片以适配画框；手动模式保留用户字号，超出时提示。 */
function layoutCard() {
  const card = $("tweet-card");
  const box = safeBox();
  const isFrame = state.mode !== "card";

  card.style.width = (isFrame ? (box.w * state.cardWidth) / 100 : CARD_ONLY_W * PREVIEW) + "px";
  $("card-width").disabled = !isFrame; // 纯卡片宽度固定，滑杆在这个模式下不参与

  const base = state.fontAuto ? FONT_BASE : state.fontSize;
  let fs = base;
  applyFont(fs);

  // 在 [FONT_MIN, base] 里二分找装得下的最大字号（步长 1 画布 px）
  if (isFrame && state.fontAuto && card.offsetHeight > box.h) {
    let lo = FONT_MIN, hi = base, best = FONT_MIN;
    for (let i = 0; i < 8 && hi - lo > 1; i++) {
      const mid = Math.round((lo + hi) / 2);
      applyFont(mid);
      if (card.offsetHeight <= box.h) { best = mid; lo = mid; } else hi = mid;
    }
    fs = best;
    applyFont(fs);
  }
  state.fitFont = fs;

  // 字号到下限还超高：整卡微缩兜底。但缩到 RESIDUAL_MIN 以下就成细长条了，
  // 那时改成只保证不被画布裁掉（等于放弃安全区），并把超出量明说
  const need = isFrame ? Math.min(1, box.h / card.offsetHeight) : 1;
  state.fitScale = !state.fontAuto ? 1 : (need >= RESIDUAL_MIN ? need : Math.min(1, (box.stageH * 0.94) / card.offsetHeight));
  const overflowPx = Math.round((card.offsetHeight * state.fitScale - box.h) / PREVIEW);

  const hint = $("fit-hint");
  if (hint) {
    let msg = "";
    if (isFrame && !state.fontAuto && overflowPx > 1) {
      msg = card.offsetHeight > box.stageH
        ? `已按 ${fs}px 显示，内容超出画布，导出会裁切。可减小字号、切换自动，或改用纯卡片保留全文。`
        : `已按 ${fs}px 显示，内容超出安全区。可减小字号、切换自动，或改用 9:16。`;
    } else if (isFrame && overflowPx > 1) {
      msg = `文字太多：字号已到下限 ${FONT_MIN}px，仍超出安全区 ${overflowPx}px，底部可能被抖音文案栏挡住——建议精简文字，或改用 9:16`;
    } else if (isFrame && state.fitScale < 0.999) {
      msg = `内容偏多，卡片整体缩到 ${Math.round(state.fitScale * 100)}% 才装进安全区`;
    } else if (isFrame && fs < base) {
      msg = state.fontAuto
        ? `内容较长，字号已自动降到 ${fs}px`
        : `${base}px 放不下，已按 ${fs}px 渲染——减少文字才能用上你选的字号`;
    }
    hint.textContent = msg;
    hint.classList.toggle("hidden", !msg);
  }

  $("font-val").textContent = state.fitFont + "px" + (state.fontAuto ? "（自动）" : "");
  $("card-font").value = state.fitFont;
  $("card-width").value = state.cardWidth;
  syncFontButtons();

  applyCardTransform();
}

/* 卡片摆位：以安全区中心为锚点，拖动偏移被夹在安全区内，短内容自然垂直居中，
   长内容缩到刚好等于安全区高度时，居中即等于顶边贴住虚线框左上角 */
function cardPlacement() {
  const card = $("tweet-card");
  const box = safeBox();
  const s = state.fitScale;
  const rw = card.offsetWidth * s, rh = card.offsetHeight * s;
  // 拖动不受安全区约束（出框裁切是有意为之的构图手段），只按画框大小兜底防止拖飞
  const maxDX = box.stageW * 0.55, maxDY = box.stageH * 0.55;
  const dx = clamp(state.cardX * PREVIEW, -maxDX, maxDX);
  const dy = clamp(state.cardY * PREVIEW, -maxDY, maxDY);
  // 锚点：装得进安全区就以安全区中心为准；装不进的极端长文改成对画布居中，
  // 让上下溢出对称，不至于一头被画布裁掉
  const anchorY = rh > box.h ? box.stageH / 2 : box.cy;
  return { s, cx: box.cx + dx, cy: anchorY + dy, rw, rh, maxDX, maxDY };
}

/* 偏移收在画框范围内（画布 px），避免拖出去之后还在累加、往回拖要先补一段空程 */
function clampCardOffset() {
  const { maxDX, maxDY } = cardPlacement();
  state.cardX = clamp(state.cardX, -maxDX / PREVIEW, maxDX / PREVIEW);
  state.cardY = clamp(state.cardY, -maxDY / PREVIEW, maxDY / PREVIEW);
}

function applyCardTransform() {
  const card = $("tweet-card");
  if (state.mode === "card") { card.style.transform = ""; card.style.left = ""; card.style.top = ""; return; }
  const { s, cx, cy } = cardPlacement();
  card.style.left = cx + "px";
  card.style.top = cy + "px";
  card.style.transform = `translate(-50%, -50%) scale(${s.toFixed(4)})`;
}

/* 拖动卡片（仅竖图模式），双击回中 */
function initDrag() {
  const card = $("tweet-card");
  const stage = $("stage");
  let drag = null;
  card.addEventListener("pointerdown", (e) => {
    if (state.mode === "card") return;
    e.preventDefault();
    drag = { x0: e.clientX, y0: e.clientY, baseX: state.cardX, baseY: state.cardY };
    card.classList.add("dragging");
    card.setPointerCapture(e.pointerId);
  });
  card.addEventListener("pointermove", (e) => {
    if (!drag) return;
    // 指针位移 → 预览 px（抵消移动端 zoom）→ 画布 px；越界由 cardPlacement 统一夹在安全区内
    const z = Number(stage.style.zoom || 1) || 1;
    const k = z * PREVIEW;
    state.cardX = drag.baseX + (e.clientX - drag.x0) / k;
    state.cardY = drag.baseY + (e.clientY - drag.y0) / k;
    clampCardOffset();
    applyCardTransform();
  });
  const end = () => { drag = null; card.classList.remove("dragging"); };
  card.addEventListener("pointerup", end);
  card.addEventListener("pointercancel", end);
  card.addEventListener("dblclick", () => { state.cardX = 0; state.cardY = 0; applyCardTransform(); });
}

/* ---------- 背景 ---------- */

function renderBackgroundGrid() {
  const grid = $("bg-grid");
  state.backgrounds.forEach((item, i) => {
    const btn = document.createElement("button");
    btn.className = "bg-thumb";
    btn.title = item.name;
    btn.innerHTML = `<img src="backgrounds/${item.file}" alt="${item.name}" />`;
    btn.onclick = () => setBg("backgrounds/" + item.file, btn);
    grid.appendChild(btn);
    // 已由 URL 参数指定背景时不要覆盖
    if (state.bg === "backgrounds/" + item.file) btn.classList.add("active");
    else if (i === 0 && !state.bg) setBg("backgrounds/" + item.file, btn);
  });
}

function setBg(src, thumbEl) {
  state.bg = src;
  $("stage-bg").src = src;
  document.querySelectorAll(".bg-thumb").forEach((b) => b.classList.remove("active"));
  if (thumbEl) thumbEl.classList.add("active");
}

function addCustomThumb(dataUrl) {
  const grid = $("bg-grid");
  const btn = document.createElement("button");
  btn.className = "bg-thumb";
  btn.innerHTML = `<img src="${dataUrl}" alt="自定义背景" />`;
  btn.onclick = () => setBg(dataUrl, btn);
  grid.appendChild(btn);
  setBg(dataUrl, btn);
}

/* ---------- 移动端适配与成品交付 ---------- */

/* stage 用 zoom 等比缩放适配窄屏：zoom 改变布局尺寸（不像 transform 会残留 540px 布局导致溢出错位）。导出前会临时还原。 */
function fitStageScale() {
  const wrap = document.querySelector(".stage-wrap");
  const stage = $("stage");
  stage.style.zoom = Math.min(1, (wrap.clientWidth - 24) / 540);
}

function isMobileLike() {
  return /iPad|iPhone|iPod|Android/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

/* 桌面直接下载；移动端弹预览面板走系统分享（按钮点击是新的用户手势，不会像异步 a.click 那样被 iOS 拦截） */
function deliverFile(blob, filename, hint) {
  if (isMobileLike()) { showExportSheet(blob, filename, hint); return; }
  const a = document.createElement("a");
  a.download = filename;
  a.href = URL.createObjectURL(blob);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}

function showExportSheet(blob, filename, hint) {
  const url = URL.createObjectURL(blob);
  const isVideo = blob.type.startsWith("video/");
  const sheet = document.createElement("div");
  sheet.className = "export-sheet";
  sheet.innerHTML = `
    <div class="es-panel">
      <div class="es-preview">${isVideo ? `<video src="${url}" autoplay muted loop playsinline></video>` : `<img src="${url}" alt="导出结果" />`}</div>
      <p class="es-hint">${hint}</p>
      <div class="es-actions">
        <button class="primary-btn es-share">保存 / 分享</button>
        <button class="ghost-btn es-close">关闭</button>
      </div>
    </div>`;
  document.body.appendChild(sheet);
  sheet.querySelector(".es-share").onclick = async () => {
    const file = new File([blob], filename, { type: blob.type });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      try { await navigator.share({ files: [file] }); } catch { /* 用户取消 */ }
    } else {
      const a = document.createElement("a");
      a.download = filename; a.href = url; a.click();
    }
  };
  sheet.querySelector(".es-close").onclick = () => { sheet.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
}

/* ---------- 导出 ---------- */

/* 卡片单独光栅化：临时摘掉浮动定位与 transform（作为根节点捕获时这些样式会被克隆进画布导致位移裁切） */
async function captureCardCanvas(pixelRatio) {
  const card = $("tweet-card");
  const hadFloating = card.classList.contains("floating");
  const prev = { transform: card.style.transform, left: card.style.left, top: card.style.top };
  card.classList.remove("floating");
  // 摘掉 floating 后 position 回到 relative，残留的 left/top 会把卡片推偏，一并清掉
  card.style.transform = "none";
  card.style.left = "";
  card.style.top = "";
  try {
    return await htmlToImage.toCanvas(card, { pixelRatio });
  } finally {
    if (hadFloating) card.classList.add("floating");
    Object.assign(card.style, prev);
  }
}

/* 竖图成品：canvas 手动合成——背景直接 drawImage，不经 foreignObject
   （iOS Safari 对 foreignObject 里的 <img> 渲染不可靠，会导致背景整片变黑）。与 Live 视频同一条管线。 */
async function composePoster() {
  const stage = $("stage");
  const prevZoom = stage.style.zoom;
  stage.style.zoom = "1"; // 还原 1:1 布局再测量与捕获，避免移动端缩放影响尺寸计算
  try {
    const SP = SAFE[state.mode === "tall" ? "tall" : "poster"];
    const W = SP.w, H = SP.h;
    const cardCanvas = await captureCardCanvas(2);
    // 预览 px → 画布 px：全部走 cardPlacement，保证预览所见即导出所得
    const { rw, rh, cx: pcx, cy: pcy } = cardPlacement();
    const cw = rw / PREVIEW, ch = rh / PREVIEW;
    const cx = pcx / PREVIEW, cy = pcy / PREVIEW;
    const bg = new Image();
    await new Promise((res, rej) => { bg.onload = res; bg.onerror = rej; bg.src = state.bg; });
    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    const ctx = cv.getContext("2d");
    drawCover(ctx, bg, W, H, 1);
    ctx.save();
    ctx.shadowColor = "rgba(0,0,0,0.35)";
    ctx.shadowBlur = 40;
    ctx.shadowOffsetY = 10;
    ctx.drawImage(cardCanvas, cx - cw / 2, cy - ch / 2, cw, ch);
    ctx.restore();
    return cv;
  } finally {
    stage.style.zoom = prevZoom;
  }
}

async function exportPng() {
  const btn = $("export-btn");
  btn.disabled = true;
  btn.textContent = "生成中…";
  try {
    let blob;
    if (state.mode === "card") {
      // 纯卡片：不带竖图背景，单独光栅化卡片
      const cardCanvas = await captureCardCanvas(3);
      blob = await new Promise((res) => cardCanvas.toBlob(res, "image/png"));
    } else {
      const cv = await composePoster();
      blob = await new Promise((res) => cv.toBlob(res, "image/png"));
    }
    const tag = "custom";
    const name = `${state.profile.handle}-${state.platform}-card-${todayISO().replaceAll("-", "")}-${tag}.png`;
    deliverFile(blob, name, "点「保存 / 分享」存到相册，或长按图片保存");
  } catch (err) {
    alert("导出失败：" + err.message + "\n如果用了网络图片背景，可能是跨域限制，请下载后用「上传图片」。");
  } finally {
    btn.disabled = false;
    btn.textContent = "下载 PNG";
  }
}

/* ---------- 导出 Live 图（3 秒动效 MP4，WebCodecs 编码） ----------
   卡片完全静止，只有背景缓慢推近（Ken Burns）。
   手机端用 intoLive / 快捷指令把 MP4 转成实况照片后即可按 Live 图发布。 */

function drawCover(ctx, img, W, H, zoom) {
  const iw = img.naturalWidth || img.width, ih = img.naturalHeight || img.height;
  const ir = iw / ih, r = W / H;
  let dw, dh;
  if (ir > r) { dh = H * zoom; dw = dh * ir; } else { dw = W * zoom; dh = dw / ir; }
  ctx.drawImage(img, (W - dw) / 2, (H - dh) / 2, dw, dh);
}

async function exportLive() {
  if (state.mode === "card") return;
  if (!("VideoEncoder" in window)) {
    alert("当前浏览器不支持视频编码（WebCodecs）。请使用新版 Chrome / Edge / Safari。");
    return;
  }
  const btn = $("live-btn");
  btn.disabled = true;
  try {
    const SP = SAFE[state.mode === "tall" ? "tall" : "poster"];
    const W = SP.w, H = SP.h;
    const FPS = 30, DUR = 3, TOTAL = FPS * DUR;

    const codec = { codec: "avc1.640028", width: W, height: H, bitrate: 8_000_000, framerate: FPS };
    const support = await VideoEncoder.isConfigSupported(codec);
    if (!support.supported) throw new Error("此设备不支持 H.264 1080p 编码");

    // 卡片只光栅化一次，逐帧只做画布合成
    btn.textContent = "准备卡片…";
    const cardCanvas = await captureCardCanvas(2);
    const { rw, rh, cx: pcx, cy: pcy } = cardPlacement();
    const cw = rw / PREVIEW, ch = rh / PREVIEW;
    const cx = pcx / PREVIEW, cy = pcy / PREVIEW;

    const bg = new Image();
    await new Promise((res, rej) => { bg.onload = res; bg.onerror = rej; bg.src = state.bg; });

    const muxer = new Mp4Muxer.Muxer({
      target: new Mp4Muxer.ArrayBufferTarget(),
      video: { codec: "avc", width: W, height: H },
      fastStart: "in-memory",
    });
    const encoder = new VideoEncoder({
      output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
      error: (e) => console.error(e),
    });
    encoder.configure(codec);

    const cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    const ctx = cv.getContext("2d");

    for (let f = 0; f < TOTAL; f++) {
      const t = f / (TOTAL - 1);
      drawCover(ctx, bg, W, H, 1 + 0.07 * t); // 只动背景：缓慢推近
      ctx.save();
      ctx.shadowColor = "rgba(0,0,0,0.35)";
      ctx.shadowBlur = 40;
      ctx.shadowOffsetY = 10;
      ctx.drawImage(cardCanvas, cx - cw / 2, cy - ch / 2, cw, ch); // 卡片完全静止
      ctx.restore();
      const frame = new VideoFrame(cv, { timestamp: (f * 1e6) / FPS, duration: 1e6 / FPS });
      encoder.encode(frame, { keyFrame: f % FPS === 0 });
      frame.close();
      if (f % 6 === 0) {
        btn.textContent = `渲染 ${Math.round((f / TOTAL) * 100)}%`;
        await new Promise((r) => setTimeout(r));
      }
    }
    btn.textContent = "编码中…";
    await encoder.flush();
    muxer.finalize();

    const blob = new Blob([muxer.target.buffer], { type: "video/mp4" });
    const tag = "custom";
    const name = `${state.profile.handle}-live-${todayISO().replaceAll("-", "")}-${tag}.mp4`;
    deliverFile(blob, name, "保存到相册后，用 intoLive / 快捷指令转成实况照片再发布");

    if (!isMobileLike() && !localStorage.getItem("duyi-social-card-live-hint")) {
      localStorage.setItem("duyi-social-card-live-hint", "1");
      alert("已导出 3 秒动效 MP4。\n\n如需实况照片，请使用支持视频转实况照片的工具，并核对目标平台的上传要求。");
    }
  } catch (err) {
    alert("Live 图导出失败：" + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "导出 Live 图";
  }
}

/* ---------- 事件绑定 ---------- */

/* URL 参数改了 state 之后，左侧那几组按钮得跟着亮，否则会出现
   预览是 9:16、按钮却停在 3:4 这种对不上的状态 */
function syncControls() {
  const pick = (pairs) => pairs.forEach(([id, on]) => $(id).classList.toggle("active", on));
  pick([["mode-poster", state.mode === "poster"], ["mode-tall", state.mode === "tall"], ["mode-card", state.mode === "card"]]);
  pick([["theme-light", state.theme === "light"], ["theme-dark", state.theme === "dark"]]);
  pick([["metrics-on", state.metricsOn], ["metrics-off", !state.metricsOn]]);
  $("guides-toggle").textContent = state.guidesOn ? "安全区 ✓" : "安全区";
  $("guides-toggle").classList.toggle("active", state.guidesOn);
  $("card-opacity").value = state.cardOpacity;
}

/* 拖字号滑杆等于切到手动，按钮状态跟着走 */
function syncFontButtons() {
  $("font-auto").classList.toggle("active", state.fontAuto);
  $("font-manual").classList.toggle("active", !state.fontAuto);
  $("card-font").disabled = false;
}

function bindSegmented(pairs, onChange) {
  // pairs: [[element, value], ...]
  pairs.forEach(([el, value]) => {
    el.onclick = () => {
      pairs.forEach(([e]) => e.classList.remove("active"));
      el.classList.add("active");
      onChange(value);
    };
  });
}

function bind() {
  bindSegmented([[$("mode-poster"), "poster"], [$("mode-tall"), "tall"], [$("mode-card"), "card"]], (v) => { state.mode = v; syncGuides(); renderCard(); });
  bindSegmented([[$("font-auto"), true], [$("font-manual"), false]], (v) => {
    state.fontAuto = v;
    if (!v) state.fontSize = state.fitFont; // 切手动时从当前自动值接上，不跳变
    layoutCard();
  });
  bindSegmented([[$("theme-light"), "light"], [$("theme-dark"), "dark"]], (v) => { state.theme = v; renderCard(); });
  bindSegmented([[$("metrics-on"), true], [$("metrics-off"), false]], (v) => { state.metricsOn = v; renderCard(); });

  $("moments-show-people").onchange = (e) => { state.momentsShowPeople = e.target.checked; renderCard(); };
  $("moments-datetime").oninput = (e) => {
    if (e.target.validity.valid && e.target.value) { state.momentsAt = e.target.value; renderCard(); }
  };
  $("moments-likes-clear").onclick = () => {
    state.momentsAvatars = [];
    try { localStorage.removeItem(MOMENTS_AVATARS_KEY); } catch { /* 本次会话仍可使用 */ }
    $("moments-likes-upload").value = "";
    renderCard();
  };
  $("moments-likes-upload").onchange = async (e) => {
    const input = e.target;
    const files = Array.from(input.files || []);
    if (!files.length) return;
    input.disabled = true;
    try {
      if (files.length > 24) throw new Error("最多选择 24 张头像");
      const avatars = [];
      for (const file of files) {
        if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type) || file.size > 10 * 1024 * 1024) throw new Error("请选择 10 MB 以内的 PNG、JPG、WebP 或 GIF 图片");
        const img = new Image();
        img.src = await blobToDataUrl(file);
        await img.decode();
        const cv = document.createElement("canvas");
        cv.width = cv.height = 120;
        const edge = Math.min(img.naturalWidth, img.naturalHeight);
        cv.getContext("2d").drawImage(img, (img.naturalWidth-edge)/2, (img.naturalHeight-edge)/2, edge, edge, 0, 0, 120, 120);
        avatars.push(cv.toDataURL("image/png"));
      }
      localStorage.setItem(MOMENTS_AVATARS_KEY, JSON.stringify(avatars));
      state.momentsAvatars = avatars;
      state.momentsShowPeople = true;
      state.metricsOn = true;
      syncControls();
      renderCard();
    } catch (err) { alert("头像添加失败：" + err.message); }
    finally { input.disabled = false; input.value = ""; }
  };
  $("zhihu-question").oninput = (e) => { state.question = e.target.value; renderCard(); };
  bindSegmented(Object.keys(PLATFORMS).map((key) => [$("platform-" + key), key]), (value) => {
    state.platformMetrics[state.platform] = state.metricsOn;
    state.platform = value;
    state.metricsOn = state.platformMetrics[value];
    syncControls();
    renderCard();
  });
  $("custom-text").oninput = (e) => { state.customText = e.target.value; renderCard(); };
  $("card-width").oninput = (e) => {
    state.cardWidth = Number(e.target.value);
    $("width-val").textContent = state.cardWidth + "%";
    layoutCard();
  };
  $("card-font").oninput = (e) => {
    state.fontAuto = false;
    state.fontSize = Number(e.target.value);
    syncFontButtons();
    layoutCard();
  };
  $("card-opacity").oninput = (e) => { state.cardOpacity = Number(e.target.value); renderCard(); };

  $("bg-upload").onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => addCustomThumb(reader.result);
    reader.readAsDataURL(file);
  };

  $("bg-url").onkeydown = async (e) => {
    if (e.key !== "Enter") return;
    const url = e.target.value.trim();
    if (!url) return;
    try {
      const blob = await fetch(url).then((r) => { if (!r.ok) throw new Error(r.status); return r.blob(); });
      const reader = new FileReader();
      reader.onload = () => addCustomThumb(reader.result);
      reader.readAsDataURL(blob);
    } catch {
      alert("拉取失败（多半是跨域限制）。请把图片下载到本地后用「上传图片」。");
    }
  };

  $("copy-text").onclick = async () => {
    const text = state.customText;
    await navigator.clipboard.writeText(text);
    $("copy-text").textContent = "已复制 ✓";
    setTimeout(() => ($("copy-text").textContent = "复制文案"), 1200);
  };

  $("shuffle-metrics").onclick = () => { rollMetrics(); renderCard(); };

  $("copy-link").onclick = async () => {
    await navigator.clipboard.writeText(buildShareUrl(false));
    $("copy-link").textContent = "已复制 ✓";
    setTimeout(() => ($("copy-link").textContent = "复制链接"), 1200);
  };



  $("guides-toggle").onclick = () => {
    state.guidesOn = !state.guidesOn;
    syncControls();
    renderCard();
  };

  $("export-btn").onclick = exportPng;
  $("live-btn").onclick = exportLive;

  /* ---- 账号信息 ---- */
  $("profile-name").oninput = (e) => { saveProfileOverride({ name: e.target.value || DEFAULT_PROFILE.name }); renderCard(); };
  $("profile-handle").oninput = (e) => { saveProfileOverride({ handle: e.target.value.replace(/^@+/, "") || DEFAULT_PROFILE.handle }); renderCard(); };
  $("badge-on").onclick = () => saveProfileOverride({ verified: true });
  $("badge-off").onclick = () => saveProfileOverride({ verified: false });

  $("avatar-upload").onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => saveProfileOverride({ avatarData: reader.result });
    reader.readAsDataURL(file);
  };

  $("profile-reset").onclick = () => {
    localStorage.removeItem(PROFILE_KEY);
    location.reload();
  };


}

/* ---------- 启动 ---------- */

/* ---------- URL 参数 / Agent 接口 ----------
   任何带浏览器能力的 Agent 都可以：打开 ?embed=1&text=...，等待
   document.documentElement.dataset.ready === "1"，再读 window.__cardDataUrl。 */

const clampNum = (v, lo, hi, dflt) => {
  const n = Number(v);
  return Number.isFinite(n) ? Math.max(lo, Math.min(hi, n)) : dflt;
};

function blobToDataUrl(blob) {
  return new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result); fr.readAsDataURL(blob); });
}

/* 外部图片先取回转 dataURL，避免 canvas 被跨域污染导致导出失败 */
async function fetchAsDataUrl(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    return await blobToDataUrl(await r.blob());
  } catch { return null; }
}

async function resolveBgParam(v) {
  if (!v) return null;
  if (/^https?:\/\//i.test(v)) return await fetchAsDataUrl(v);
  const hit = state.backgrounds.find((b) => b.file === v || b.file.replace(/\.(jpg|jpeg|png|svg)$/, "") === v || b.name === v);
  return hit ? "backgrounds/" + hit.file : null;
}

async function applyUrlParams() {
  const q = new URLSearchParams(location.search);
  if (![...q.keys()].length) return false;

  if (q.get("name")) state.profile.name = q.get("name");
  if (q.get("handle")) state.profile.handle = q.get("handle").replace(/^@+/, "");
  if (q.has("verified")) state.profile.verified = q.get("verified") !== "0";
  if (q.get("avatar")) {
    const data = await fetchAsDataUrl(q.get("avatar"));
    if (data) state.profile.avatarData = data;
  }
  applyProfile();

  if (q.get("text")) { state.customText = q.get("text"); }
  if (q.get("date")) state.dateOverride = q.get("date");

  if (Object.hasOwn(PLATFORMS, q.get("platform"))) state.platform = q.get("platform");
  state.momentsShowPeople = q.get("momentsPeople") === "1";
  const momentsAt = q.get("momentsAt");
  if (momentsAt && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(momentsAt) && Number.isFinite(new Date(momentsAt).getTime())) state.momentsAt = momentsAt;
  state.question = (q.get("question") || "").slice(0, 180);
  $("zhihu-question").value = state.question;

  const mode = q.get("mode");
  if (["poster", "tall", "card"].includes(mode)) state.mode = mode;
  if (q.get("theme") === "dark") state.theme = "dark";
  // width：卡片宽度占安全区宽度的百分比。scale 是旧参数名（原义是占画布的缩放），
  // 语义已变，这里只当别名收下并按新范围夹紧，老链接不至于失效
  if (q.has("width")) state.cardWidth = clampNum(q.get("width"), 50, 100, state.cardWidth);
  else if (q.has("scale")) state.cardWidth = clampNum(q.get("scale"), 50, 100, state.cardWidth);
  if (q.has("font")) {
    const v = q.get("font");
    if (v === "auto") state.fontAuto = true;
    else { state.fontAuto = false; state.fontSize = clampNum(v, FONT_MIN, FONT_MAX, FONT_BASE); }
  }
  if (q.has("opacity")) state.cardOpacity = clampNum(q.get("opacity"), 30, 100, state.cardOpacity);
  if (q.has("x")) state.cardX = clampNum(q.get("x"), -600, 600, 0);
  if (q.has("y")) state.cardY = clampNum(q.get("y"), -900, 900, 0);
  if (q.get("guides") === "0") state.guidesOn = false;

  state.metricsOn = q.get("metrics") === "on" ? true : q.get("metrics") === "off" ? false : state.platformMetrics[state.platform];
  const MET = ["likes", "reposts", "replies", "bookmarks", "views"];
  if (MET.some((k) => q.has(k))) {
    state.metricsProvided = true;
    state.fakeMetrics = Object.fromEntries(MET.map((k) => [k, q.has(k) ? clampNum(q.get(k), 0, 1e9, null) : null]));
  }

  const bg = await resolveBgParam(q.get("bg"));
  if (bg) { state.bg = bg; $("stage-bg").src = bg; }

  return q.get("embed") === "1";
}

/* embed 模式：隐藏界面，只输出成品，把 base64 PNG 挂到 window.__cardDataUrl */
async function runEmbed() {
  document.body.style.opacity = "0"; // 保留布局（卡片才有尺寸可捕获）
  try {
    await document.fonts.ready.catch(() => {});
    renderCard();
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    const cv = state.mode === "card" ? await captureCardCanvas(3) : await composePoster();
    const dataUrl = cv.toDataURL("image/png");
    window.__cardDataUrl = dataUrl;
    window.__cardSize = { width: cv.width, height: cv.height };

    document.body.classList.add("embed");
    document.body.style.opacity = "";
    const view = document.createElement("div");
    view.id = "embed-view";
    view.innerHTML = '<img id="embed-img" alt="social media card" />';
    document.body.appendChild(view);
    $("embed-img").src = dataUrl;
    document.documentElement.dataset.ready = "1";
  } catch (err) {
    document.body.style.opacity = "";
    window.__cardError = String(err && err.message ? err.message : err);
    document.documentElement.dataset.ready = "error";
  }
}

function buildShareUrl(embed) {
  const q = new URLSearchParams();
  const text = state.customText;
  if (text) q.set("text", text);
  if (state.platform !== "x") q.set("platform", state.platform);
  if (state.platform === "moments" && state.momentsAt) q.set("momentsAt", state.momentsAt);
  if (state.platform === "moments" && state.momentsShowPeople) q.set("momentsPeople", "1");
  if (state.platform === "zhihu" && state.question) q.set("question", state.question);
  if (state.profile.name !== DEFAULT_PROFILE.name) q.set("name", state.profile.name);
  if (state.profile.handle !== DEFAULT_PROFILE.handle) q.set("handle", state.profile.handle);
  q.set("verified", state.profile.verified ? "1" : "0");
  if (state.mode !== "poster") q.set("mode", state.mode);
  if (state.theme !== "light") q.set("theme", state.theme);
  // 与初始默认值一致的项不写进链接，保持简短（省略时页面会用同样的默认值）
  if (state.cardWidth !== 100) q.set("width", state.cardWidth);
  if (!state.fontAuto) q.set("font", state.fontSize);
  if (state.cardOpacity !== 100) q.set("opacity", state.cardOpacity);
  if (Math.round(state.cardX) !== 0) q.set("x", Math.round(state.cardX));
  if (Math.round(state.cardY) !== 0) q.set("y", Math.round(state.cardY));
  if (!state.metricsOn) q.set("metrics", "off");
  else q.set("metrics", "on");
  if (state.metricsProvided) {
    for (const [key, value] of Object.entries(state.fakeMetrics)) {
      if (value != null) q.set(key, value);
    }
  }
  if (state.bg && state.bg.startsWith("backgrounds/")) q.set("bg", state.bg.replace("backgrounds/", "").replace(/\.(jpg|jpeg|png|svg)$/, ""));
  if (embed) q.set("embed", "1");
  return location.origin + location.pathname + "?" + q.toString();
}

async function init() {
  const q = new URLSearchParams(location.search);
  // embed 模式忽略本机 localStorage（保留 profile.json 默认身份），
  // 保证同一条链接在任何设备上结果一致
  await loadProfile(q.get("embed") !== "1");

  if (q.get("embed") !== "1") {
    try {
      const avatars = JSON.parse(localStorage.getItem(MOMENTS_AVATARS_KEY) || "[]");
      if (Array.isArray(avatars)) state.momentsAvatars = avatars.filter(s => typeof s === "string" && /^data:image\/png;base64,/.test(s)).slice(0,24);
    } catch { /* 忽略损坏的本机头像数据 */ }
  }
  try { state.backgrounds = await fetch("backgrounds/manifest.json").then((r) => r.json()); } catch { state.backgrounds = []; }
  rollMetrics();

  const embed = await applyUrlParams();

  bind();
  initDrag();
  syncGuides();
  syncControls();
  renderBackgroundGrid();
  fitStageScale();
  window.addEventListener("resize", fitStageScale);
  $("custom-text").value = state.customText;
  renderCard();

  if (embed) runEmbed();
}

init();
