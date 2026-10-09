import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";

export interface PlatformCandidates {
  darwin?: string[];
  win32?: string[];
  linux?: string[];
  default?: string[];
}

interface CdpResponse<T> {
  id?: number;
  result?: T;
  error?: {
    code: number;
    message: string;
  };
}

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

export class CdpConnection {
  private nextId = 1;
  private pending = new Map<number, PendingRequest>();

  private constructor(private readonly socket: WebSocket) {
    this.socket.addEventListener("message", (event) => this.handleMessage(event.data));
    this.socket.addEventListener("close", () => this.rejectAll(new Error("CDP WebSocket closed")));
    this.socket.addEventListener("error", () => this.rejectAll(new Error("CDP WebSocket error")));
  }

  static async connect(wsUrl: string, timeoutMs = 30_000): Promise<CdpConnection> {
    return await new Promise((resolve, reject) => {
      const socket = new WebSocket(wsUrl);
      const timer = setTimeout(() => {
        try {
          socket.close();
        } catch {
          // Ignore close errors during timeout cleanup.
        }
        reject(new Error(`Timed out connecting to Chrome CDP: ${wsUrl}`));
      }, timeoutMs);

      socket.addEventListener("open", () => {
        clearTimeout(timer);
        resolve(new CdpConnection(socket));
      }, { once: true });

      socket.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error(`Failed to connect to Chrome CDP: ${wsUrl}`));
      }, { once: true });
    });
  }

  async send<T = unknown>(
    method: string,
    params: Record<string, unknown> = {},
    options: { sessionId?: string; timeoutMs?: number } = {},
  ): Promise<T> {
    if (this.socket.readyState !== WebSocket.OPEN) {
      throw new Error("CDP WebSocket is not open");
    }

    const id = this.nextId++;
    const payload: Record<string, unknown> = { id, method, params };
    if (options.sessionId) payload.sessionId = options.sessionId;

    return await new Promise<T>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP command timed out: ${method}`));
      }, options.timeoutMs ?? 30_000);

      this.pending.set(id, {
        resolve: (value) => resolve(value as T),
        reject,
        timer,
      });

      this.socket.send(JSON.stringify(payload));
    });
  }

  close(): void {
    try {
      this.socket.close();
    } catch {
      // Ignore close errors.
    }
    this.rejectAll(new Error("CDP connection closed"));
  }

  private handleMessage(data: unknown): void {
    let message: CdpResponse<unknown>;
    try {
      message = JSON.parse(String(data)) as CdpResponse<unknown>;
    } catch {
      return;
    }

    if (!message.id) return;
    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);
    clearTimeout(pending.timer);

    if (message.error) {
      pending.reject(new Error(`CDP error ${message.error.code}: ${message.error.message}`));
      return;
    }

    pending.resolve(message.result);
  }

  private rejectAll(error: Error): void {
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pending.delete(id);
    }
  }
}

export function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function getFreePort(envName?: string): Promise<number> {
  if (envName && process.env[envName]) {
    const value = Number(process.env[envName]);
    if (Number.isInteger(value) && value > 0) return value;
  }

  return await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

export function findChromeExecutable(options: {
  candidates: PlatformCandidates;
  envNames?: string[];
}): string | undefined {
  for (const envName of options.envNames ?? []) {
    const value = process.env[envName]?.trim();
    if (value && fs.existsSync(value)) return value;
  }

  const platformCandidates = options.candidates[process.platform as keyof PlatformCandidates]
    ?? options.candidates.default
    ?? [];
  return platformCandidates.find((candidate) => fs.existsSync(candidate));
}

export function resolveSharedChromeProfileDir(options: {
  envNames?: string[];
  wslWindowsHome?: string | null;
} = {}): string {
  for (const envName of options.envNames ?? []) {
    const value = process.env[envName]?.trim();
    if (value) return expandHome(value);
  }

  if (process.env.WSL_DISTRO_NAME && options.wslWindowsHome) {
    return path.join(options.wslWindowsHome, "AppData", "Local", "wechat-article-suite", "chrome-profile");
  }

  return path.join(os.homedir(), ".wechat-article-suite", "chrome-profile");
}

export async function launchChrome(options: {
  chromePath: string;
  profileDir: string;
  port: number;
  url: string;
  extraArgs?: string[];
}): Promise<ChildProcess> {
  fs.mkdirSync(options.profileDir, { recursive: true });

  const args = [
    `--remote-debugging-port=${options.port}`,
    `--user-data-dir=${options.profileDir}`,
    "--no-first-run",
    "--no-default-browser-check",
    ...(options.extraArgs ?? []),
    options.url,
  ];

  const chrome = spawn(options.chromePath, args, {
    detached: false,
    stdio: "ignore",
  });
  chrome.unref();
  return chrome;
}

export async function waitForChromeDebugPort(
  port: number,
  timeoutMs = 30_000,
  options: { includeLastError?: boolean } = {},
): Promise<string> {
  const start = Date.now();
  let lastError = "";

  while (Date.now() - start < timeoutMs) {
    try {
      const version = await fetchJson<{ webSocketDebuggerUrl?: string }>(
        `http://127.0.0.1:${port}/json/version`,
        2_000,
      );
      if (version.webSocketDebuggerUrl) return version.webSocketDebuggerUrl;
      lastError = "Missing webSocketDebuggerUrl";
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await sleep(300);
  }

  const suffix = options.includeLastError && lastError ? ` Last error: ${lastError}` : "";
  throw new Error(`Timed out waiting for Chrome debug port ${port}.${suffix}`);
}

export async function findExistingChromeDebugPort(options: { profileDir: string }): Promise<number | null> {
  const activePortPath = path.join(options.profileDir, "DevToolsActivePort");
  try {
    const [portLine] = fs.readFileSync(activePortPath, "utf-8").split(/\r?\n/);
    const port = Number(portLine);
    if (!Number.isInteger(port) || port <= 0) return null;
    await waitForChromeDebugPort(port, 1_500);
    return port;
  } catch {
    return null;
  }
}

function fetchJson<T>(url: string, timeoutMs: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const request = http.get(url, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => {
        if ((response.statusCode ?? 0) >= 400) {
          reject(new Error(`HTTP ${response.statusCode}`));
          return;
        }
        try {
          resolve(JSON.parse(body) as T);
        } catch (error) {
          reject(error instanceof Error ? error : new Error(String(error)));
        }
      });
    });

    request.setTimeout(timeoutMs, () => {
      request.destroy(new Error("HTTP request timed out"));
    });
    request.on("error", reject);
  });
}

function expandHome(value: string): string {
  if (value === "~") return os.homedir();
  if (value.startsWith("~/")) return path.join(os.homedir(), value.slice(2));
  return value;
}
