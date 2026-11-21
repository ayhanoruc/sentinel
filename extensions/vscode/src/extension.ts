/**
 * The Sentinel panel: a read-only view, in the editor's right side bar, of what the agents of this workspace wrote for
 * the person: each session's progress notes, its contracts, its reviews, and the repository's assumption ledger and
 * hand-off briefs. It refreshes itself when Sentinel's files change.
 */
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { readRepo } from "./model";
import { view } from "./render";

const VIEW = "sentinel.panel";
const SHOW_ALL = "sentinel.showAll"; // the view's filter, kept per workspace and mirrored in a context key for its menu
const DEBOUNCE_MS = 400; // the hooks write several files per tool call: one refresh for the burst
const POLL_MS = 15_000; // a safety net for a missed file event, and how often "live" and "3 min ago" are re-read

class Panel implements vscode.WebviewViewProvider {
  private view?: vscode.WebviewView;
  private watchers: vscode.Disposable[] = [];
  private timer?: NodeJS.Timeout;
  private poll?: NodeJS.Timeout;
  private sent = "";

  constructor(private readonly ctx: vscode.ExtensionContext) {
    this.watch();
    ctx.subscriptions.push(
      vscode.workspace.onDidChangeWorkspaceFolders(() => {
        this.watch();
        this.schedule(0);
      }),
      vscode.workspace.onDidChangeConfiguration((e) => e.affectsConfiguration("sentinel") && this.schedule(0)),
      {
        dispose: () => {
          this.stop();
          this.watchers.forEach((w) => w.dispose());
        },
      },
    );
    void vscode.commands.executeCommand("setContext", SHOW_ALL, this.showAll);
  }

  get showAll(): boolean {
    return this.ctx.workspaceState.get<boolean>(SHOW_ALL, false);
  }

  async setShowAll(all: boolean): Promise<void> {
    await this.ctx.workspaceState.update(SHOW_ALL, all);
    await vscode.commands.executeCommand("setContext", SHOW_ALL, all);
    this.schedule(0);
  }

  resolveWebviewView(v: vscode.WebviewView): void {
    this.view = v;
    const media = vscode.Uri.joinPath(this.ctx.extensionUri, "media");
    v.webview.options = { enableScripts: true, localResourceRoots: [media] };
    v.webview.html = this.page(v.webview, media);
    v.webview.onDidReceiveMessage((m) => this.onMessage(m));
    v.onDidChangeVisibility(() => (v.visible ? this.start() : this.stop()));
    v.onDidDispose(() => {
      this.stop();
      this.view = undefined;
    });
    this.start();
  }

  refresh(force = false): void {
    if (!this.view?.visible) return;
    if (force) this.sent = "";
    const recentHours = vscode.workspace.getConfiguration("sentinel").get<number>("recentHours", 24);
    const now = Date.now() / 1000;
    let message: object;
    try {
      const repos = roots().map((root) => readRepo(root, { now, recentHours }));
      message = { type: "model", repos: view(repos, now, recentHours, this.showAll), showAll: this.showAll, folders: folderCount() };
    } catch (err) {
      message = { type: "error", message: err instanceof Error ? err.message : String(err) };
    }
    const text = JSON.stringify(message);
    if (text === this.sent) return; // nothing changed that the panel shows
    this.sent = text;
    void this.view.webview.postMessage(message);
  }

  schedule(delay = DEBOUNCE_MS): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.refresh(), delay);
  }

  private start(): void {
    this.refresh(true);
    if (!this.poll) this.poll = setInterval(() => this.refresh(), POLL_MS);
  }

  private stop(): void {
    if (this.poll) clearInterval(this.poll);
    if (this.timer) clearTimeout(this.timer);
    this.poll = this.timer = undefined;
  }

  private watch(): void {
    this.watchers.forEach((w) => w.dispose());
    this.watchers = [];
    for (const folder of vscode.workspace.workspaceFolders ?? []) {
      const w = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(folder, ".sentinel/**"));
      const changed = () => this.schedule();
      this.watchers.push(w, w.onDidChange(changed), w.onDidCreate(changed), w.onDidDelete(changed));
    }
  }

  private async onMessage(m: any): Promise<void> {
    if (m?.type === "ready") return this.refresh(true);
    if (m?.type === "showAll") return this.setShowAll(Boolean(m.value));
    if (m?.type === "open" && typeof m.path === "string") return openFile(m.path);
    if (m?.type === "link" && typeof m.href === "string") {
      const href: string = m.href;
      if (/^https?:\/\//i.test(href)) {
        await vscode.env.openExternal(vscode.Uri.parse(href));
        return;
      }
      const target = decodeURI(href.split("#")[0]);
      if (!target) return;
      const base = typeof m.base === "string" && m.base ? path.dirname(m.base) : roots()[0] ?? "";
      const candidates = [path.resolve(base, target), ...roots().map((r) => path.resolve(r, target))];
      const found = candidates.find((c) => fs.existsSync(c));
      if (found) return openFile(found);
      void vscode.window.showInformationMessage(`Sentinel: ${target} was not found.`);
    }
  }

  private page(webview: vscode.Webview, media: vscode.Uri): string {
    const nonce = [...Array(32)].map(() => Math.floor(Math.random() * 36).toString(36)).join("");
    const css = webview.asWebviewUri(vscode.Uri.joinPath(media, "panel.css"));
    const js = webview.asWebviewUri(vscode.Uri.joinPath(media, "panel.js"));
    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${webview.cspSource}; img-src ${webview.cspSource} https: data:; script-src 'nonce-${nonce}';">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link href="${css}" rel="stylesheet">
<title>Sentinel</title>
</head>
<body>
<div id="root"><p class="muted pad">Reading Sentinel's files…</p></div>
<script nonce="${nonce}" src="${js}"></script>
</body>
</html>`;
  }
}

/** The workspace folders where Sentinel is active. */
function roots(): string[] {
  return (vscode.workspace.workspaceFolders ?? [])
    .map((f) => f.uri.fsPath)
    .filter((p) => fs.existsSync(path.join(p, ".sentinel", "config.toml")));
}

function folderCount(): number {
  return vscode.workspace.workspaceFolders?.length ?? 0;
}

async function openFile(file: string): Promise<void> {
  try {
    await vscode.window.showTextDocument(vscode.Uri.file(file), { preview: true, preserveFocus: false });
  } catch (err) {
    void vscode.window.showWarningMessage(`Sentinel: could not open ${file}: ${err instanceof Error ? err.message : err}`);
  }
}

export function activate(ctx: vscode.ExtensionContext): void {
  const panel = new Panel(ctx);
  ctx.subscriptions.push(
    vscode.window.registerWebviewViewProvider(VIEW, panel, { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.commands.registerCommand("sentinel.refresh", () => panel.refresh(true)),
    vscode.commands.registerCommand("sentinel.showAll", () => panel.setShowAll(true)),
    vscode.commands.registerCommand("sentinel.showRecent", () => panel.setShowAll(false)),
    vscode.commands.registerCommand("sentinel.focus", () => vscode.commands.executeCommand(`${VIEW}.focus`)),
  );
}

export function deactivate(): void {
  // the subscriptions are disposed by the editor
}
