#!/usr/bin/env node
import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

const FORMATS = {
  wide: { width: 4200, height: 1800 },
  square: { width: 2400, height: 2400 },
  inline: { width: 1600, height: 900 },
  xhs: { width: 2160, height: 2880 },
};

function usage() {
  console.log(`render_duyi_editorial_illustration.mjs

Usage:
  node render_duyi_editorial_illustration.mjs <brief.json> --out <task-dir>

Reads a Du Yi editorial-illustration brief and renders PNG files for WeChat
covers, hero images, and inline article illustrations.
`);
}

function argAfter(args, flag) {
  const i = args.indexOf(flag);
  return i >= 0 ? args[i + 1] : null;
}

function esc(value = "") {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function attr(value = "") {
  return esc(value).replace(/\n/g, " ");
}

function mimeFor(file) {
  const ext = path.extname(file).toLowerCase();
  if (ext === ".svg") return "image/svg+xml";
  if (ext === ".jpg" || ext === ".jpeg") return "image/jpeg";
  if (ext === ".webp") return "image/webp";
  return "image/png";
}

function resolveImageSrc(src, briefDir) {
  if (!src) return "";
  if (/^data:|^https?:|^file:/i.test(src)) return src;
  const abs = path.isAbsolute(src) ? src : path.resolve(briefDir, src);
  if (!fs.existsSync(abs)) return "";
  const data = fs.readFileSync(abs);
  return `data:${mimeFor(abs)};base64,${data.toString("base64")}`;
}

function wrapText(text, maxChars) {
  const explicit = String(text || "").split(/\n+/).filter(Boolean);
  if (explicit.length > 1) return explicit;
  const raw = explicit[0] || "";
  if (raw.length <= maxChars) return raw ? [raw] : [];
  const lines = [];
  let rest = raw;
  while (rest.length > maxChars && lines.length < 3) {
    lines.push(rest.slice(0, maxChars));
    rest = rest.slice(maxChars);
  }
  if (rest) lines.push(rest);
  return lines;
}

function textBlock(lines, x, y, size, lineGap, options = {}) {
  const weight = options.weight || 700;
  const fill = options.fill || "#f2ecd9";
  const opacity = options.opacity ?? 1;
  const family = options.family || `"Songti SC", "STSong", "Noto Serif CJK SC", serif`;
  return `<text x="${x}" y="${y}" fill="${fill}" opacity="${opacity}" font-size="${size}" font-weight="${weight}" font-family='${family}'>${lines.map((line, i) => `<tspan x="${x}" dy="${i === 0 ? 0 : lineGap}">${esc(line)}</tspan>`).join("")}</text>`;
}

function defaultScene({ w, h, card }) {
  const y = h * 0.58;
  const red = `M ${w * 0.10} ${h * 0.62} C ${w * 0.30} ${h * 0.46}, ${w * 0.50} ${h * 0.50}, ${w * 0.65} ${h * 0.60} S ${w * 0.86} ${h * 0.60}, ${w * 0.92} ${h * 0.50}`;
  const person = (x, scale = 1, opacity = 1) => `
    <g transform="translate(${x} ${y}) scale(${scale})" opacity="${opacity}">
      <path d="M-110 80 C-80 0 -10 -40 80 -10 C145 12 175 74 160 150 L130 310 L-105 265 Z" fill="#817467"/>
      <path d="M-118 80 C-78 -4 -12 -45 70 -38 C122 -34 158 -12 188 22 C130 14 80 28 35 70 C-6 108 -58 118 -118 80 Z" fill="#050707"/>
      <path d="M-155 190 L-350 145 L-342 350 L-198 280 Z" fill="#020707"/>
      <path d="M130 190 L380 330 L372 405 L104 254 Z" fill="#030707"/>
      <path d="M-62 338 L-180 608 L-74 616 L42 388 Z" fill="#020707"/>
      <path d="M70 342 L210 620 L328 616 L158 342 Z" fill="#020707"/>
      <path d="M-2 150 C82 143 165 158 240 202" fill="none" stroke="#6b211d" stroke-width="38" stroke-linecap="round" opacity="0.9"/>
      <path d="M6 144 C90 138 172 151 246 194" fill="none" stroke="#9d3c31" stroke-width="26" stroke-linecap="round"/>
    </g>`;
  const labels = (card.labels || []).slice(0, 4);
  return `
    <path d="M0 ${h * 0.54} C ${w * 0.16} ${h * 0.42}, ${w * 0.29} ${h * 0.56}, ${w * 0.45} ${h * 0.45} C ${w * 0.62} ${h * 0.34}, ${w * 0.72} ${h * 0.51}, ${w} ${h * 0.45} L ${w} ${h} L 0 ${h} Z" fill="#0b2926" opacity="0.56"/>
    <path d="M0 ${h * 0.68} C ${w * 0.28} ${h * 0.61}, ${w * 0.45} ${h * 0.69}, ${w * 0.75} ${h * 0.61} C ${w * 0.88} ${h * 0.57}, ${w * 0.96} ${h * 0.59}, ${w} ${h * 0.61} L ${w} ${h} L 0 ${h} Z" fill="url(#floor)"/>
    <g opacity="0.44">
      <path d="M${w * 0.40} ${h * 0.36} C${w * 0.47} ${h * 0.30} ${w * 0.56} ${h * 0.31} ${w * 0.64} ${h * 0.36} L${w * 0.61} ${h * 0.43} C${w * 0.52} ${h * 0.39} ${w * 0.46} ${h * 0.40} ${w * 0.37} ${h * 0.45}Z" fill="#123e39"/>
      <path d="M${w * 0.44} ${h * 0.48} C${w * 0.51} ${h * 0.44} ${w * 0.58} ${h * 0.44} ${w * 0.64} ${h * 0.48} L${w * 0.61} ${h * 0.56} C${w * 0.53} ${h * 0.53} ${w * 0.48} ${h * 0.53} ${w * 0.41} ${h * 0.58}Z" fill="#16554e"/>
      ${labels.map((label, i) => `<text x="${w * (0.43 + i * 0.055)}" y="${h * (0.41 + i * 0.095)}" fill="#d9e4d8" opacity="0.50" font-size="${Math.max(22, w * 0.018)}" letter-spacing="4" font-family="Avenir Next Condensed, DIN Condensed, Arial Narrow, sans-serif">${esc(label)}</text>`).join("")}
    </g>
    <path d="${red}" fill="none" stroke="#5d201b" stroke-width="${Math.max(20, w * 0.012)}" stroke-linecap="round" opacity="0.55"/>
    <path d="${red}" fill="none" stroke="#a64636" stroke-width="${Math.max(14, w * 0.008)}" stroke-linecap="round" opacity="0.9"/>
    ${person(w * 0.36, w / 4200, 0.96)}
    ${w > 1800 ? person(w * 0.68, w / 5200, 0.82) + person(w * 0.86, w / 5600, 0.70) : ""}
  `;
}

function cardSvg(card, briefDir) {
  const dims = FORMATS[card.format] || FORMATS.wide;
  const { width: w, height: h } = dims;
  const imageHref = resolveImageSrc(card.image?.src, briefDir);
  const titleLines = wrapText(card.title || "", card.format === "wide" ? 16 : 10);
  const subtitle = card.subtitle || card.lead || "";
  const showTitle = titleLines.length > 0 && card.role !== "inline-no-title";
  const titleSize = card.format === "wide" ? 128 : card.format === "square" ? 116 : 70;
  const titleX = card.format === "square" ? 170 : card.format === "inline" ? 90 : 190;
  const titleY = card.format === "inline" ? h - 210 : h - (card.format === "square" ? 580 : 540);
  const maxSub = card.format === "inline" ? 46 : 54;
  const subText = subtitle ? esc(subtitle).slice(0, 88) : "";
  const issue = card.issue || "";
  const issueHtml = issue ? `<g opacity=".68"><text x="${w - 510}" y="${card.format === "square" ? 210 : 214}" font-size="${card.format === "square" ? 28 : 28}" fill="#dce7db" letter-spacing="7" font-family="Avenir Next Condensed, DIN Condensed, Arial Narrow, sans-serif">${esc(issue)}</text><rect x="${w - 575}" y="${card.format === "square" ? 165 : 168}" width="146" height="72" fill="none" stroke="#dce7db" opacity="0.5" stroke-width="3"/></g>` : "";
  const sealText = typeof card.seal === "string" ? card.seal.trim() : "";
  const sealHtml = sealText ? `<rect x="${w - titleX - 96}" y="${h - 210}" width="66" height="96" fill="#6b2d24" stroke="#e9dcc9" stroke-width="4" opacity=".86"/><text x="${w - titleX - 76}" y="${h - 147}" fill="#f3e6d0" font-size="38" font-weight="700" font-family='"Songti SC", serif'>${esc(sealText)}</text>` : "";
  const scene = imageHref
    ? `<image href="${attr(imageHref)}" x="0" y="0" width="${w}" height="${h}" preserveAspectRatio="xMidYMid slice"/><rect width="${w}" height="${h}" fill="url(#imageShade)"/>`
    : defaultScene({ w, h, card });

  return `<section class="poster" data-name="${attr(card.name || "card")}" style="width:${w}px;height:${h}px">
  <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" role="img" aria-label="${attr(card.title || card.name || "editorial illustration")}">
    <defs>
      <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#071918"/>
        <stop offset=".48" stop-color="#1f6b63"/>
        <stop offset="1" stop-color="#08201e"/>
      </linearGradient>
      <linearGradient id="floor" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#102d2a" stop-opacity="0"/>
        <stop offset=".55" stop-color="#081716" stop-opacity=".86"/>
        <stop offset="1" stop-color="#020606"/>
      </linearGradient>
      <linearGradient id="imageShade" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#061615" stop-opacity=".04"/>
        <stop offset=".60" stop-color="#061615" stop-opacity=".24"/>
        <stop offset="1" stop-color="#010505" stop-opacity=".88"/>
      </linearGradient>
      <radialGradient id="halo" cx=".68" cy=".18" r=".52">
        <stop offset="0" stop-color="#4aa79a" stop-opacity=".34"/>
        <stop offset="1" stop-color="#11322f" stop-opacity="0"/>
      </radialGradient>
      <filter id="paperNoise" x="-20%" y="-20%" width="140%" height="140%">
        <feTurbulence type="fractalNoise" baseFrequency=".78" numOctaves="3" seed="29"/>
        <feColorMatrix type="saturate" values="0"/>
        <feComponentTransfer><feFuncA type="table" tableValues="0 .07"/></feComponentTransfer>
      </filter>
    </defs>
    <rect width="${w}" height="${h}" fill="url(#bg)"/>
    <rect width="${w}" height="${h}" filter="url(#paperNoise)" opacity=".9"/>
    <circle cx="${w * 0.78}" cy="${h * 0.18}" r="${Math.min(w, h) * 0.26}" fill="url(#halo)" opacity=".75"/>
    ${scene}
    <line x1="${titleX}" y1="${card.format === "square" ? 316 : 316}" x2="${w - titleX}" y2="${card.format === "square" ? 316 : 316}" stroke="#d9e4d8" stroke-width="2.5" opacity=".28"/>
    <line x1="${titleX}" y1="${h - 280}" x2="${w - titleX}" y2="${h - 280}" stroke="#e8eadf" stroke-width="2" opacity=".30"/>
    ${issueHtml}
    ${showTitle ? textBlock(titleLines, titleX, titleY, titleSize, titleSize * 1.18) : ""}
    ${subText ? `<text x="${titleX}" y="${titleY + titleLines.length * titleSize * 1.16 + 52}" fill="#efe8d8" opacity=".82" font-size="${maxSub}" font-style="italic" font-weight="700" font-family="Georgia, serif">${subText}</text>` : ""}
    <text x="${titleX}" y="${h - 160}" fill="#efe8d8" opacity=".76" font-size="${card.format === "inline" ? 22 : 30}" font-weight="700" letter-spacing="8" font-family="Avenir Next Condensed, DIN Condensed, Arial Narrow, sans-serif">${esc(card.footerYear || "2026")}</text>
    ${sealHtml}
  </svg>
</section>`;
}

async function loadPlaywright() {
  try {
    return require("playwright");
  } catch (err) {
    throw new Error("Playwright is required to render Du Yi editorial illustrations. Install it in the local Node runtime or run from an environment that already provides playwright.", { cause: err });
  }
}

async function render(indexPath, outDir) {
  const { chromium } = await loadPlaywright();
  const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const page = await browser.newPage({ viewport: { width: 4400, height: 3000 }, deviceScaleFactor: 1 });
  await page.goto(`file://${indexPath}`, { waitUntil: "networkidle" });
  await page.evaluate(async () => {
    if (document.fonts?.ready) await document.fonts.ready;
  });
  const posters = await page.$$("section.poster");
  for (let i = 0; i < posters.length; i++) {
    const el = posters[i];
    const name = (await el.getAttribute("data-name")) || String(i + 1).padStart(2, "0");
    await el.screenshot({ path: path.join(outDir, `${name}.png`), type: "png" });
    console.log(path.join(outDir, `${name}.png`));
  }
  await browser.close();
}

async function main() {
  const args = process.argv.slice(2);
  if (!args[0] || args.includes("-h") || args.includes("--help")) {
    usage();
    process.exit(args[0] ? 0 : 2);
  }
  const briefPath = path.resolve(args[0]);
  const outDir = path.resolve(argAfter(args, "--out") || "duyi-editorial-illustration-output");
  const briefDir = path.dirname(briefPath);
  const brief = JSON.parse(await fsp.readFile(briefPath, "utf8"));
  const cards = brief.cards || [];
  await fsp.mkdir(path.join(outDir, "output"), { recursive: true });
  const html = `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;background:#050d0d}.sheet{display:flex;flex-direction:column;gap:48px;align-items:flex-start}.poster{display:block;overflow:hidden;background:#061615}</style></head><body><main class="sheet">${cards.map(card => cardSvg(card, briefDir)).join("\n")}</main></body></html>`;
  const indexPath = path.join(outDir, "index.html");
  await fsp.writeFile(indexPath, html, "utf8");
  await fsp.writeFile(path.join(outDir, "brief.resolved.json"), JSON.stringify(brief, null, 2), "utf8");
  await render(indexPath, path.join(outDir, "output"));
  console.log(outDir);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
