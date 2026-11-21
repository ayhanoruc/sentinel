/**
 * The panel's view model: what `model.ts` read, with every Markdown text turned into HTML. The webview only builds
 * the collapsible structure from it; it never parses a file.
 *
 * Raw HTML in the files is not passed through (`html: false`): the files are written by agents, and what they write
 * is shown as text, never run.
 */
import MarkdownIt from "markdown-it";
import { awaiting, Repo, Session, shown, stripComments } from "./model";

const md = new MarkdownIt({ html: false, linkify: true, breaks: false, typographer: false });

export function html(text: string): string {
  return md.render(stripComments(text));
}

export function inline(text: string): string {
  return md.renderInline(stripComments(text));
}

/** A contract without its first heading (the task's id and title, shown on the row already). */
function contractBody(text: string): string {
  return stripComments(text).replace(/^\s*#\s[^\n]*\n/, "");
}

export interface ViewTask {
  id: string;
  title: string;
  size: string;
  parent: string | null;
  status: string;
  awaiting: boolean;
  basis: string | null;
  standing: boolean;
  opened: number;
  file: string;
  html: string | null;
}

export interface ViewSession {
  key: string;
  id8: string;
  title: string;
  state: string;
  since: number | null;
  lastSeen: number | null;
  live: boolean;
  holdingCompaction: boolean;
  current: string | null;
  awaiting: string[];
  dir: string;
  progressFile: string | null;
  progress: { key: string; title: string; day: string | null; html: string }[];
  tasks: ViewTask[];
  reviews: {
    id: string;
    task: string | null;
    passed: boolean;
    open: number;
    t: number;
    files: string[];
    file: string;
    kept: { where: string; text: string; reason: string }[];
    answers: { n: number; question: string; html: string }[];
  }[];
}

export interface ViewRepo {
  key: string;
  root: string;
  name: string;
  sessions: ViewSession[];
  hidden: number;
  ledgerFile: string | null;
  ledger: { key: string; html: string }[];
  handoffs: { name: string; file: string; mtime: number; html: string }[];
}

function session(repoKey: string, s: Session): ViewSession {
  const waiting = awaiting(s);
  const current = [...s.tasks].reverse().find((t) => t.status !== "done") ?? null;
  return {
    key: `${repoKey}/${s.id8}`,
    id8: s.id8,
    title: s.title ?? current?.title ?? `Session ${s.id8}`,
    state: s.state,
    since: s.since,
    lastSeen: s.lastSeen,
    live: s.live,
    holdingCompaction: s.holdingCompaction,
    current: current ? `${current.id} · ${current.title}` : null,
    awaiting: waiting.map((t) => t.id),
    dir: s.dir,
    progressFile: s.progressFile,
    progress: s.progress.map((p) => ({ key: p.key, title: p.title, day: p.day, html: html(p.body) })),
    tasks: [...s.tasks].reverse().map((t) => ({
      id: t.id,
      title: t.title,
      size: t.size,
      parent: t.parent,
      status: t.status,
      awaiting: waiting.includes(t),
      basis: t.basis ?? null,
      standing: Boolean(t.standing),
      opened: t.opened,
      file: t.file,
      html: t.contract === undefined ? null : html(contractBody(t.contract)),
    })),
    reviews: [...s.reviews].reverse().map((r) => ({
      id: r.id,
      task: r.task,
      passed: r.passed,
      open: r.open,
      t: r.t,
      files: r.files,
      file: r.file,
      kept: r.kept.map((k) => ({ where: `${k.file}:${k.line}`, text: k.text, reason: inline(k.reason) })),
      answers: r.answers.map((a) => ({ n: a.n, question: a.question, html: inline(a.answer) })),
    })),
  };
}

export function view(repos: Repo[], now: number, recentHours: number, all: boolean): ViewRepo[] {
  return repos.map((r) => {
    const key = r.root;
    const visible = r.sessions.filter((s) => shown(s, now, recentHours, all));
    return {
      key,
      root: r.root,
      name: r.name,
      sessions: visible.map((s) => session(key, s)),
      hidden: r.sessions.length - visible.length,
      ledgerFile: r.ledgerFile,
      ledger: r.ledger.map((l) => ({ key: l.key, html: inline(l.text) })),
      handoffs: r.handoffs.map((h) => ({ name: h.name, file: h.file, mtime: h.mtime, html: html(h.text) })),
    };
  });
}
