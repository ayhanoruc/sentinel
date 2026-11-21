/**
 * Reads a repository's `.sentinel/` folder into what the panel shows: each session's state, its tasks with their
 * contracts, its reviews, its progress notes, and the repository's assumption ledger and hand-off briefs.
 *
 * Nothing here imports `vscode`, so it runs under plain Node in the tests. Reads are cheap on purpose: the hooks append
 * to a session's `events.jsonl` at every tool call, so the panel refreshes often. An event log is read from where the
 * last read stopped; a session's transcript (hundreds of megabytes) is only ever read at its head or its tail.
 */
import * as fs from "fs";
import * as os from "os";
import * as path from "path";

export interface SentinelEvent {
  t: number;
  e: string;
  [field: string]: unknown;
}

export type TaskStatus = "open" | "approved" | "done";

export interface Task {
  id: string;
  title: string;
  size: string;
  parent: string | null;
  status: TaskStatus;
  opened: number;
  approved?: number;
  done?: number;
  basis?: string;
  standing?: boolean;
  file: string;
  contract?: string; // the contract file's text, when it exists
}

export interface ReviewAnswer {
  n: number;
  question: string;
  answer: string;
}

export interface KeptChoice {
  file: string;
  line: number;
  text: string;
  reason: string;
}

export interface Review {
  id: string;
  task: string | null;
  passed: boolean;
  t: number;
  files: string[];
  answers: ReviewAnswer[];
  open: number; // questions and flagged lines still unanswered
  kept: KeptChoice[];
  file: string;
}

export interface ProgressEntry {
  key: string;
  title: string;
  day: string | null;
  body: string; // markdown
}

export type SessionState = "working" | "idle" | "waiting" | "ended" | "cut" | "unknown";

export interface Session {
  id8: string;
  sid: string | null;
  title: string | null;
  dir: string;
  state: SessionState;
  since: number | null; // when it entered that state
  lastSeen: number | null;
  live: boolean;
  holdingCompaction: boolean;
  tasks: Task[];
  reviews: Review[];
  progress: ProgressEntry[];
  progressFile: string | null;
}

export interface LedgerItem {
  key: string;
  text: string; // markdown, one entry
}

export interface Handoff {
  name: string;
  file: string;
  mtime: number;
  text: string;
}

export interface Repo {
  root: string;
  name: string;
  sessions: Session[]; // every session, ordered: live first, then by last activity
  ledger: LedgerItem[]; // newest first
  ledgerFile: string | null;
  handoffs: Handoff[]; // newest first
}

export interface ReadOptions {
  sentinelHome?: string; // ~/.sentinel by default: where each session's registry entry lives
  now?: number; // seconds since the epoch
  bootTime?: number | null; // when the machine last started, in seconds since the epoch
  recentHours?: number;
}

/* ------------------------------------------------------------------------------------------------ event logs */

interface LogCache {
  size: number;
  offset: number;
  partial: string;
  events: SentinelEvent[];
}

const logs = new Map<string, LogCache>();

/** A session's events, read from where the last read stopped. A log that shrank was rewritten: read again whole. */
export function readEvents(file: string): SentinelEvent[] {
  let size: number;
  try {
    size = fs.statSync(file).size;
  } catch {
    logs.delete(file);
    return [];
  }
  let cache = logs.get(file);
  if (!cache || size < cache.offset) {
    cache = { size: 0, offset: 0, partial: "", events: [] };
    logs.set(file, cache);
  }
  if (size > cache.offset) {
    const fd = fs.openSync(file, "r");
    try {
      const buf = Buffer.alloc(size - cache.offset);
      fs.readSync(fd, buf, 0, buf.length, cache.offset);
      const text = cache.partial + buf.toString("utf8");
      const lines = text.split("\n");
      cache.partial = lines.pop() ?? ""; // a line a hook is still writing
      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const ev = JSON.parse(line);
          if (ev && typeof ev.e === "string" && typeof ev.t === "number") cache.events.push(ev);
        } catch {
          // a torn line is skipped: the rest of the record stands
        }
      }
      cache.offset = size;
    } finally {
      fs.closeSync(fd);
    }
  }
  cache.size = size;
  return cache.events;
}

/* ------------------------------------------------------------------------------------------------ helpers */

function readText(file: string): string | null {
  try {
    return fs.readFileSync(file, "utf8");
  } catch {
    return null;
  }
}

function str(v: unknown): string {
  return typeof v === "string" ? v : v == null ? "" : String(v);
}

/** HTML comments are hints for the agent inside a template; the person never needs them. */
export function stripComments(text: string): string {
  return text.replace(/<!--[\s\S]*?-->/g, "");
}

/** What a session is doing, read from its last event of a kind that says so (the same rule as `sentinel board`). */
function activity(events: SentinelEvent[]): { state: SessionState; since: number | null } {
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    switch (e.e) {
      case "prompt":
        return { state: "working", since: e.t };
      case "stop":
      case "session_start":
        return { state: "idle", since: e.t };
      case "session_end":
        return { state: "ended", since: e.t };
      case "notification": {
        const kind = str(e.ntype);
        return { state: kind === "permission_prompt" || kind === "elicitation_dialog" ? "waiting" : "idle", since: e.t };
      }
    }
  }
  return { state: "unknown", since: null };
}

function tasksOf(events: SentinelEvent[], dir: string): Task[] {
  const out = new Map<string, Task>();
  for (const e of events) {
    const id = str(e.id);
    if (e.e === "task_open") {
      out.set(id, {
        id,
        title: str(e.title),
        size: str(e.size) || "normal",
        parent: e.parent ? str(e.parent) : null,
        status: "open",
        opened: e.t,
        file: path.join(dir, "tasks", `${id}.md`),
      });
    } else if (e.e === "task_approve" && out.has(id)) {
      Object.assign(out.get(id)!, { status: "approved", approved: e.t, basis: str(e.basis), standing: Boolean(e.standing) });
    } else if (e.e === "task_done" && out.has(id)) {
      Object.assign(out.get(id)!, { status: "done", done: e.t });
    }
  }
  for (const t of out.values()) {
    const text = readText(t.file);
    if (text !== null) t.contract = text;
  }
  return [...out.values()];
}

/** The question texts of a review, read from its rendered file (`  3. <question>` lines under "Questions:"). */
function questionTexts(md: string): Map<number, string> {
  const out = new Map<number, string>();
  const start = md.indexOf("\nQuestions:");
  if (start < 0) return out;
  const end = md.indexOf("\nWhat to do:", start);
  for (const line of md.slice(start, end < 0 ? undefined : end).split("\n")) {
    const m = /^ {2}(\d+)\.\s+(.*)$/.exec(line);
    if (m) out.set(Number(m[1]), m[2].trim());
  }
  return out;
}

function reviewsOf(dir: string): Review[] {
  const folder = path.join(dir, "reviews");
  let names: string[];
  try {
    names = fs.readdirSync(folder).filter((n) => /^R\d+\.json$/.test(n));
  } catch {
    return [];
  }
  const out: Review[] = [];
  for (const name of names.sort((a, b) => Number(a.slice(1, -5)) - Number(b.slice(1, -5)))) {
    let r: any;
    try {
      r = JSON.parse(fs.readFileSync(path.join(folder, name), "utf8"));
    } catch {
      continue; // a review being written: it is read at the next refresh
    }
    const mdFile = path.join(folder, name.replace(/\.json$/, ".md"));
    const questions = questionTexts(readText(mdFile) ?? "");
    const answers: ReviewAnswer[] = [];
    const nq = Number(r.nq) || 0;
    let open = 0;
    for (let n = 1; n <= nq; n++) {
      const answer = str(r.answers?.[String(n)]).trim();
      if (!answer && r.depth === "full") open++;
      if (answer) answers.push({ n, question: questions.get(n) ?? `Question ${n}`, answer });
    }
    const kept: KeptChoice[] = [];
    for (const f of Object.values<any>(r.findings ?? {})) {
      if (!f.disp) open++;
      if (f.disp === "kept") kept.push({ file: str(f.file), line: Number(f.line) || 0, text: str(f.text), reason: str(f.reason) });
    }
    out.push({
      id: str(r.id) || name.slice(0, -5),
      task: r.task ? str(r.task) : null,
      passed: Boolean(r.passed),
      t: Number(r.t) || 0,
      files: Array.isArray(r.files) ? r.files.map(str) : [],
      answers,
      open,
      kept,
      file: fs.existsSync(mdFile) ? mdFile : path.join(folder, name),
    });
  }
  return out;
}

/**
 * A progress file as entries. An entry starts at a heading (`##` to `####`) or, in the one-line form `sentinel
 * progress "<note>"` writes, at a `- **HH:MM**` line; a heading that is only a date names the day of what follows.
 */
export function progressEntries(text: string): ProgressEntry[] {
  const out: ProgressEntry[] = [];
  let day: string | null = null;
  let cur: ProgressEntry | null = null;
  const push = (title: string, body: string) => {
    cur = { key: `${day ?? ""}#${out.length}`, title, day, body };
    out.push(cur);
  };
  for (const line of stripComments(text).split(/\r?\n/)) {
    if (/^#\s/.test(line)) continue; // the file's own title
    const heading = /^#{2,4}\s+(.*)$/.exec(line);
    if (heading) {
      const title = heading[1].trim();
      if (/^\d{4}-\d{2}-\d{2}$/.test(title)) {
        day = title;
        cur = null;
      } else {
        push(title, "");
      }
      continue;
    }
    const bullet = /^- \*\*(\d{1,2}:\d{2})\*\*\s*(.*)$/.exec(line);
    if (bullet && (cur === null || (cur as ProgressEntry).title.startsWith("·"))) {
      const rest = bullet[2].replace(/^\((T\d+)\)\s*/, "");
      push(`· ${bullet[1]}`, rest);
      continue;
    }
    if (cur) (cur as ProgressEntry).body += (cur as ProgressEntry).body ? `\n${line}` : line;
    else if (line.trim()) push("Note", line);
  }
  for (const e of out) e.body = e.body.trim();
  return out.filter((e) => e.body || !e.title.startsWith("·"));
}

/* ------------------------------------------------------------------------------------------------ titles */

interface TitleCache {
  checked: number;
  size: number;
  title: string | null;
}

const titles = new Map<string, TitleCache>();
const TITLE_RECHECK_S = 30; // a session is renamed rarely; its transcript grows at every turn
const TAIL_BYTES = 1_000_000; // Claude Code repeats a session's custom title throughout its transcript
const HEAD_BYTES = 256_000;

function readSlice(file: string, from: "head" | "tail", bytes: number): string {
  try {
    const size = fs.statSync(file).size;
    const len = Math.min(bytes, size);
    const fd = fs.openSync(file, "r");
    try {
      const buf = Buffer.alloc(len);
      fs.readSync(fd, buf, 0, len, from === "head" ? 0 : size - len);
      return buf.toString("utf8");
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    return "";
  }
}

/** The name the person gave the session in the harness, or else the first thing they asked in it. */
function sessionTitle(transcript: string, now: number): string | null {
  let size = 0;
  try {
    size = fs.statSync(transcript).size;
  } catch {
    return null;
  }
  const cached = titles.get(transcript);
  if (cached && (cached.size === size || now - cached.checked < TITLE_RECHECK_S)) return cached.title;
  let title: string | null = null;
  const tail = readSlice(transcript, "tail", TAIL_BYTES).split("\n");
  for (let i = tail.length - 1; i >= 0 && title === null; i--) {
    if (!tail[i].includes('"custom-title"')) continue;
    try {
      const d = JSON.parse(tail[i]);
      if (d.type === "custom-title" && d.customTitle) title = str(d.customTitle);
    } catch {
      // the first line of a tail is usually cut
    }
  }
  if (title === null) {
    for (const line of readSlice(transcript, "head", HEAD_BYTES).split("\n")) {
      try {
        const d = JSON.parse(line);
        const c = d?.message?.content;
        const text = typeof c === "string" ? c : Array.isArray(c) ? str(c.find((p: any) => p?.type === "text")?.text) : "";
        if (d.type === "user" && !d.isMeta && text.trim() && !text.trimStart().startsWith("<")) {
          title = text.trim().replace(/\s+/g, " ");
          title = title.length > 80 ? `${title.slice(0, 79)}…` : title;
          break;
        }
      } catch {
        // a line cut at the slice's end
      }
    }
  }
  titles.set(transcript, { checked: now, size, title });
  return title;
}

/** A session's registry entry (`~/.sentinel/board/<sid>.json`): its full id and its transcript. */
function registry(home: string, id8: string): { sid: string; transcript: string } | null {
  let names: string[];
  try {
    names = fs.readdirSync(path.join(home, "board")).filter((n) => n.startsWith(id8) && n.endsWith(".json"));
  } catch {
    return null;
  }
  for (const n of names) {
    try {
      const d = JSON.parse(fs.readFileSync(path.join(home, "board", n), "utf8"));
      return { sid: str(d.sid), transcript: str(d.transcript) };
    } catch {
      continue;
    }
  }
  return null;
}

/* ------------------------------------------------------------------------------------------------ the repo */

/** The ledger's entries, newest first: each `- ` line is one kept choice, as `sentinel` writes it. */
export function ledgerItems(text: string): LedgerItem[] {
  const items: LedgerItem[] = [];
  for (const line of text.split(/\r?\n/)) {
    if (!line.startsWith("- ")) continue;
    const key = /<!--\s*([^>]*?)\s*-->/.exec(line)?.[1] ?? `${items.length}`;
    items.push({ key, text: stripComments(line.slice(2)).trim() });
  }
  return items.reverse();
}

function handoffDir(root: string): string {
  const cfg = readText(path.join(root, ".sentinel", "config.toml")) ?? "";
  const section = /\[handoff\]([\s\S]*?)(?:\n\[|$)/.exec(cfg)?.[1] ?? "";
  const dir = /^\s*dir\s*=\s*"([^"]+)"/m.exec(section)?.[1] ?? ".sentinel/handoff";
  return path.resolve(root, dir);
}

function handoffsOf(root: string): Handoff[] {
  const dir = handoffDir(root);
  let names: string[];
  try {
    names = fs.readdirSync(dir).filter((n) => n.endsWith(".md"));
  } catch {
    return [];
  }
  const out: Handoff[] = [];
  for (const name of names) {
    const file = path.join(dir, name);
    try {
      out.push({ name: name.slice(0, -3), file, mtime: fs.statSync(file).mtimeMs / 1000, text: fs.readFileSync(file, "utf8") });
    } catch {
      continue;
    }
  }
  return out.sort((a, b) => b.mtime - a.mtime);
}

const ORDER: Record<SessionState, number> = { waiting: 0, working: 1, idle: 2, unknown: 3, cut: 4, ended: 5 };

/** Everything the panel shows for one repository where Sentinel is active (`<root>/.sentinel/config.toml`). */
export function readRepo(root: string, opts: ReadOptions = {}): Repo {
  const now = opts.now ?? Date.now() / 1000;
  const boot = opts.bootTime === undefined ? now - os.uptime() : opts.bootTime;
  const recent = (opts.recentHours ?? 24) * 3600;
  const home = opts.sentinelHome ?? path.join(os.homedir(), ".sentinel");
  const sessionsDir = path.join(root, ".sentinel", "sessions");
  const sessions: Session[] = [];
  let folders: string[] = [];
  try {
    folders = fs.readdirSync(sessionsDir, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name);
  } catch {
    folders = [];
  }
  for (const id8 of folders) {
    const dir = path.join(sessionsDir, id8);
    const events = readEvents(path.join(dir, "events.jsonl"));
    const lastSeen = events.length ? events[events.length - 1].t : null;
    let { state, since } = activity(events);
    if (state !== "ended" && lastSeen !== null && boot !== null && lastSeen < boot) state = "cut";
    const live = state !== "ended" && state !== "cut" && lastSeen !== null && now - lastSeen <= recent;
    let holding = false;
    for (const e of events) {
      if (e.e === "compact_hold") holding = true;
      else if (e.e === "compact_pass" || e.e === "restore" || (e.e === "session_start" && e.source === "clear")) holding = false;
    }
    const progressFile = path.join(dir, "progress.md");
    const progressText = readText(progressFile);
    const reg = registry(home, id8);
    sessions.push({
      id8,
      sid: reg?.sid ?? null,
      title: reg?.transcript ? sessionTitle(reg.transcript, now) : null,
      dir,
      state,
      since,
      lastSeen,
      live,
      holdingCompaction: holding && state !== "ended",
      tasks: tasksOf(events, dir),
      reviews: reviewsOf(dir),
      progress: progressText === null ? [] : progressEntries(progressText).reverse(),
      progressFile: progressText === null ? null : progressFile,
    });
  }
  sessions.sort((a, b) => Number(b.live) - Number(a.live) || ORDER[a.state] - ORDER[b.state] || (b.lastSeen ?? 0) - (a.lastSeen ?? 0));
  const ledgerFile = path.join(root, ".sentinel", "assumptions.md");
  const ledgerText = readText(ledgerFile);
  return {
    root,
    name: path.basename(root),
    sessions,
    ledger: ledgerText === null ? [] : ledgerItems(ledgerText),
    ledgerFile: ledgerText === null ? null : ledgerFile,
    handoffs: handoffsOf(root),
  };
}

/** Whether a session belongs on the panel: running, or active lately and with something written for the person. */
export function shown(s: Session, now: number, recentHours: number, all: boolean): boolean {
  if (all || s.live) return true;
  const recent = s.lastSeen !== null && now - s.lastSeen <= recentHours * 3600;
  return recent && (s.tasks.length > 0 || s.progress.length > 0 || s.reviews.length > 0);
}

/** The tasks of a session whose contract waits for the person's answer. */
export function awaiting(s: Session): Task[] {
  return s.tasks.filter((t) => t.status === "open" && t.size !== "trivial" && !t.parent);
}
