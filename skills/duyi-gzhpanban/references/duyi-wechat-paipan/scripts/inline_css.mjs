#!/usr/bin/env node
import { createRequire } from "module";

const requireFromHere = createRequire(import.meta.url);

function loadJuice() {
  try {
    return requireFromHere("juice");
  } catch {
    const vendorRequire = createRequire(new URL("./vendor/package.json", import.meta.url));
    return vendorRequire("juice");
  }
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", chunk => {
      data += chunk;
    });
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

const payload = JSON.parse(await readStdin());
const loadedJuice = loadJuice();
const juice = loadedJuice.default || loadedJuice;
const html = payload.html || "";
const css = payload.css || "";

const inlineContent = juice.inlineContent || loadedJuice.inlineContent;
if (typeof inlineContent !== "function") {
  throw new Error("juice.inlineContent is unavailable");
}

const output = inlineContent(html, css, {
  inlinePseudoElements: true,
  preserveImportant: true,
  resolveCSSVariables: false,
});

process.stdout.write(output);
