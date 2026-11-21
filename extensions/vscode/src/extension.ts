/**
 * The Sentinel panel: a read-only view of what the agents of this workspace wrote for the person: each session's
 * progress notes, its contracts, its reviews, and the repository's assumption ledger and hand-off briefs. It refreshes
 * itself when Sentinel's files change.
 *
 * It shows in two places, the same page in both: a view in the activity bar, and an editor tab that opens beside the
 * editor and comes back after a reload (the place to keep it open on the right). The right side bar is not one of
 * them: Cursor reserves it for its own agent and refuses a view container there (seen in its log, 21 Nov 2026).
 */
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";
import { readRepo } from "./model";
import { view } from "./render";

const VIEW = "sentinel.panel";
const TAB = "sentinel.tab";
const SHOW_ALL = "sentinel.showAll"; // the filter, kept per workspace and mirrored in a context key for the view's menu
const DEBOUNCE_MS = 400; // the hooks write several files per tool call: one refresh for the burst
const POLL_MS = 15_000; // a safety net for a missed file event, and how often "live" and "3 min ago" are re-read

/** One place the page is shown: what it last received, so an unchanged model is not sent again. */
interface Target {
  webview: vscode.Webview;
  visible: () => boolean;
  sent: string;
}

class Hub {
  private targets = new Set<Target>();
  private watchers: vscode.Disposable[] = [];
  private timer?: NodeJS.Timeout;
  private poll?: NodeJS.Timeout;
  private tab?: vscode.WebviewPanel;

  constructor(private readonly ctx: vscode.ExtensionContext) {
    this.watch();
    ctx.subscriptions.push(
      vscode.workspace.onDidChangeWorkspaceFolders(() => {
        this.watch();
        this.schedule(0);
      }),
      vscode.workspace.onDidChangeConfiguration((e) => e.affectsConfiguration("sentinel") && this.schedule(0)),
      { dispose: () => this.dispose() },
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

  /** Show the page in a webview; the returned function takes it off again. */
  attach(webview: vscode.Webview, visible: () => boolean): Target {
    const media = vscode.Uri.joinPath(this.ctx.extensionUri, "media");
    webview.options = { enableScripts: true, localResourceRoots: [media] };
    webview.html = page(webview, media);
    const target: Target = { webview, visible, sent: "" };
    webview.onDidReceiveMessage((m) => this.onMessage(m, target));
    this.targets.add(target);
    this.pace();
    return target;
  }

  detach(target: Target): void {
    this.targets.delete(target);
    this.pace();
  }

  /** The panel as an editor tab beside the current editor, or the open one brought forward. */
  openTab(): void {
    if (this.tab) {
      this.tab.reveal(undefined, true);
      return;
    }
    const tab = vscode.window.createWebviewPanel(TAB, "Sentinel", { viewColumn: vscode.ViewColumn.Beside, preserveFocus: true },
      { retainContextWhenHidden: true });
    this.adoptTab(tab);
  }

  /** A tab created now or restored after a reload. */
  adoptTab(tab: vscode.WebviewPanel): void {
    this.tab = tab;
    tab.iconPath = vscode.Uri.joinPath(this.ctx.extensionUri, "media", "icon.svg");
    const target = this.attach(tab.webview, () => tab.visible);
    tab.onDidChangeViewState(() => this.pace(true));
    tab.onDidDispose(() => {
      this.detach(target);
      if (this.tab === tab) this.tab = undefined;
    });
  }

  refresh(force = false): void {
    const shown = [...this.targets].filter((t) => t.visible());
    if (!shown.length) return;
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
    for (const t of shown) {
      if (!force && text === t.sent) continue; // nothing changed that this place shows
      t.sent = text;
      void t.webview.postMessage(message);
    }
  }

  schedule(delay = DEBOUNCE_MS): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => this.refresh(), delay);
  }

  /** Poll while the page is visible somewhere; refresh at once when a place has just come into view. */
  pace(cameIntoView = false): void {
    const anyVisible = [...this.targets].some((t) => t.visible());
    if (anyVisible && !this.poll) {
      this.poll = setInterval(() => this.refresh(), POLL_MS);
      this.refresh(true);
    } else if (!anyVisible && this.poll) {
      clearInterval(this.poll);
      this.poll = undefined;
    } else if (anyVisible && cameIntoView) {
      this.refresh(true);
    }
  }

  private dispose(): void {
    if (this.poll) clearInterval(this.poll);
    if (this.timer) clearTimeout(this.timer);
    this.watchers.forEach((w) => w.dispose());
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

  private async onMessage(m: any, target: Target): Promise<void> {
    if (m?.type === "ready") {
      target.sent = "";
      return this.refresh(true);
    }
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
}

function page(webview: vscode.Webview, media: vscode.Uri): string {
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
    // never in the tab's own column: the panel stays where the person put it
    await vscode.window.showTextDocument(vscode.Uri.file(file), { preview: true, viewColumn: vscode.ViewColumn.One });
  } catch (err) {
    void vscode.window.showWarningMessage(`Sentinel: could not open ${file}: ${err instanceof Error ? err.message : err}`);
  }
}

export function activate(ctx: vscode.ExtensionContext): void {
  const hub = new Hub(ctx);
  ctx.subscriptions.push(
    vscode.window.registerWebviewViewProvider(VIEW, {
      resolveWebviewView(v: vscode.WebviewView) {
        const target = hub.attach(v.webview, () => v.visible);
        v.onDidChangeVisibility(() => hub.pace(true));
        v.onDidDispose(() => hub.detach(target));
      },
    }, { webviewOptions: { retainContextWhenHidden: true } }),
    vscode.window.registerWebviewPanelSerializer(TAB, {
      async deserializeWebviewPanel(tab: vscode.WebviewPanel) {
        hub.adoptTab(tab); // the tab that was open before the reload, in the same place
      },
    }),
    vscode.commands.registerCommand("sentinel.openTab", () => hub.openTab()),
    vscode.commands.registerCommand("sentinel.refresh", () => hub.refresh(true)),
    vscode.commands.registerCommand("sentinel.showAll", () => hub.setShowAll(true)),
    vscode.commands.registerCommand("sentinel.showRecent", () => hub.setShowAll(false)),
    vscode.commands.registerCommand("sentinel.focus", () => vscode.commands.executeCommand(`${VIEW}.focus`)),
  );
}

export function deactivate(): void {
  // the subscriptions are disposed by the editor
}
