#!/usr/bin/env bun
import { readFile, writeFile, mkdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const CODEX_WRAPPER = path.join(SCRIPT_DIR, "codex-imagegen", "main.ts");

const STYLE_PRESETS: Record<Args["style"], string> = {
  xiaohei: `Visual DNA: Pure white background. Minimalist black hand-drawn line art. Slightly wobbly pen lines. Lots of empty white space. Sparse red/orange/blue handwritten Chinese annotations. Clean absurd product-sketch feeling. No gradients, no shadows, no paper texture, no complex background, no commercial vector style, no PPT infographic look, no cute mascot poster, no children's illustration, no realistic UI.

Recurring IP character required: 小黑, a small solid-black absurd creature with exactly two white dot eyes, no mouth, no smile, no frown, tiny thin legs, blank serious expression, slightly uneven hand-drawn body shape. 小黑 must perform the core conceptual action, not decorate the scene. Make 小黑 serious, deadpan, and slightly bizarre, not cute.`,
};

type Args = {
  type: "illustration";
  content: string | null;
  promptFile: string | null;
  output: string;
  backend: "codex-cli" | "native" | "api";
  style: "xiaohei";
  aspect: string;
  refImages: string[];
  verbose: boolean;
};

function help() {
  console.log(`generate_image.ts — Du Yi 统一配图入口

Usage:
  bun generate_image.ts --type illustration --output <path> [options]

Required:
  --type illustration   图类型：正文小黑插图
  --output <path>       输出路径

Options:
  --content <file>      内容文件（用于自动构建 prompt）
  --prompt-file <file>  直接指定 prompt 文件（优先于 --content）
  --backend <name>      backend: codex-cli | native | api. Default: codex-cli
  --style xiaohei       风格：xiaohei. Default: xiaohei
  --aspect <ratio>      比例. Default: 16:9
  --ref <files...>      参考图（可多次指定）
  -v, --verbose         详细输出
  -h, --help            显示帮助
`);
}

function parseArgs(argv: string[]): Args {
  const args: Args = {
    type: "illustration",
    content: null,
    promptFile: null,
    output: "",
    backend: "codex-cli",
    style: "xiaohei",
    aspect: "16:9",
    refImages: [],
    verbose: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case "--type": {
        const type = argv[++i];
        if (type !== "illustration") {
          throw new Error(`Unsupported type: ${type}. Use --type illustration.`);
        }
        args.type = type as Args["type"];
        break;
      }
      case "--content": args.content = argv[++i]; break;
      case "--prompt-file": args.promptFile = argv[++i]; break;
      case "--output": args.output = argv[++i]; break;
      case "--backend": args.backend = argv[++i] as Args["backend"]; break;
      case "--style": {
        const style = argv[++i];
        if (style !== "xiaohei") {
          throw new Error(`Unsupported style: ${style}. Use --style xiaohei.`);
        }
        args.style = style as Args["style"];
        break;
      }
      case "--aspect": args.aspect = argv[++i]; break;
      case "--ref": args.refImages.push(argv[++i]); break;
      case "-v":
      case "--verbose": args.verbose = true; break;
      case "-h":
      case "--help": help(); process.exit(0);
      default: throw new Error(`Unknown argument: ${a}`);
    }
  }
  if (!args.output) throw new Error("--output is required");
  return args;
}

async function buildPrompt(args: Args): Promise<string> {
  const stylePreset = STYLE_PRESETS[args.style];
  let basePrompt: string;
  if (args.promptFile) {
    basePrompt = await readFile(args.promptFile, "utf-8");
  } else if (args.content) {
    const content = await readFile(args.content, "utf-8");
    basePrompt = `Generate one standalone ${args.aspect} horizontal Chinese article illustration.

Content to illustrate:
${content}`;
  } else {
    throw new Error("Either --content or --prompt-file must be provided");
  }

  return `${basePrompt.trim()}

STYLE:
${stylePreset}

HARD IMAGE RULES:
- Generate real raster pixels with image_gen only.
- Preserve all requested Chinese labels exactly; keep them short and mobile-readable.
- Keep the scene focused on one conceptual job.
- 小黑 must carry the main action, not sit as decoration.
- 小黑 has no mouth. Do not draw a smile, frown, white mouth line, teeth, or any facial expression except two white dot eyes.
- Do not make 小黑 cute, mascot-like, emoji-like, or cartoon-animal-like.
`;
}

async function runCodexCli(args: Args, prompt: string): Promise<void> {
  const sessionDir = path.join(tmpdir(), "duyi-gen-img");
  await mkdir(sessionDir, { recursive: true });
  const token = Math.random().toString(36).slice(2, 10);
  const promptFile = path.join(sessionDir, `prompt-${token}.md`);
  await writeFile(promptFile, prompt, "utf-8");

  const cmdArgs = [
    CODEX_WRAPPER,
    "--prompt-file", promptFile,
    "--image", args.output,
    "--aspect", args.aspect,
  ];
  for (const ref of args.refImages) {
    cmdArgs.push("--ref", ref);
  }
  const timeoutMs = process.env.DUYI_CODEX_IMAGEGEN_TIMEOUT_MS ?? process.env.CODEX_CLI_TIMEOUT_MS;
  if (timeoutMs) cmdArgs.push("--timeout", timeoutMs);
  if (process.env.DUYI_CODEX_IMAGEGEN_RETRIES) {
    cmdArgs.push("--retries", process.env.DUYI_CODEX_IMAGEGEN_RETRIES);
  }
  if (process.env.DUYI_CODEX_IMAGEGEN_CACHE_DIR) {
    cmdArgs.push("--cache-dir", process.env.DUYI_CODEX_IMAGEGEN_CACHE_DIR);
  }
  if (process.env.DUYI_CODEX_IMAGEGEN_LOG_FILE) {
    cmdArgs.push("--log-file", process.env.DUYI_CODEX_IMAGEGEN_LOG_FILE);
  }

  return new Promise((resolve, reject) => {
    const child = spawn("bun", cmdArgs, { stdio: "inherit" });
    child.on("error", reject);
    child.on("close", (code) => {
      rm(promptFile, { force: true }).catch(() => {});
      if (code === 0) resolve();
      else reject(new Error(`codex-imagegen exited with code ${code}`));
    });
  });
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const prompt = await buildPrompt(args);

  if (args.verbose) {
    console.error("[generate_image] type:", args.type);
    console.error("[generate_image] backend:", args.backend);
    console.error("[generate_image] style:", args.style);
    console.error("[generate_image] output:", args.output);
  }

  if (args.backend === "codex-cli") {
    await runCodexCli(args, prompt);
    console.log(args.output);
  } else {
    throw new Error(`Backend "${args.backend}" not yet implemented in MVP. Use "codex-cli".`);
  }
}

main().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
