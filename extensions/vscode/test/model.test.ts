// The panel's reading of a `.sentinel/` folder, against folders written the way Sentinel writes them.
import { test } from "node:test";
import * as assert from "node:assert/strict";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { awaiting, ledgerItems, progressEntries, readEvents, readRepo, shown } from "../src/model";
import { html, view } from "../src/render";

const NOW = 1_800_000_000;

function world() {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "sentinel-panel-"));
  const root = path.join(base, "repo");
  const home = path.join(base, "home");
  fs.mkdirSync(path.join(root, ".sentinel", "sessions"), { recursive: true });
  fs.writeFileSync(path.join(root, ".sentinel", "config.toml"), "[handoff]\nenabled = true\n");
  return { base, root, home };
}

function write(file: string, text: string) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
}

function events(list: object[]): string {
  return list.map((e) => JSON.stringify(e)).join("\n") + "\n";
}

function session(root: string, id8: string, evs: object[]) {
  const dir = path.join(root, ".sentinel", "sessions", id8);
  write(path.join(dir, "events.jsonl"), events(evs));
  return dir;
}

test("a session's state, tasks, progress, reviews and title are read as Sentinel wrote them", () => {
  const { root, home, base } = world();
  const dir = session(root, "aaaaaaaa", [
    { t: NOW - 600, e: "session_start", source: "startup" },
    { t: NOW - 590, e: "prompt" },
    { t: NOW - 500, e: "task_open", id: "T1", title: "Calendar", size: "normal", parent: null },
    { t: NOW - 400, e: "task_approve", id: "T1", basis: "evet, böyle olsun", standing: false },
    { t: NOW - 300, e: "task_open", id: "T2", title: "Navigation", size: "normal", parent: null },
    { t: NOW - 290, e: "task_open", id: "T3", title: "a step", size: "normal", parent: "T1" },
    { t: NOW - 60, e: "prompt" },
  ]);
  write(path.join(dir, "tasks", "T1.md"), "# T1 · Calendar\n\n## Understanding\n<!-- hint for the agent -->\nA month view.\n");
  write(path.join(dir, "progress.md"), [
    "# Progress of session aaaaaaaa", "", "## 2026-11-21",
    "- **04:03** (T1) Calendar rewritten.", "- **04:20** Translations done.", "",
    "## 04:40 · The calendar can be looked at", "", "You can open **Fabrika › Takvim** now.", "",
    "- what changed: the month view", "",
  ].join("\n"));
  write(path.join(dir, "reviews", "R1.json"), JSON.stringify({
    id: "R1", task: "T1", depth: "full", passed: true, t: NOW - 200, files: ["src/a.ts"], nq: 2,
    answers: { "1": "Only the calendar.", "2": "" },
    findings: { k1: { kind: "numeric-literal", file: "src/a.ts", line: 3, text: "LIMIT = 8", disp: "kept", reason: "eight rows fit a day" } },
  }));
  write(path.join(dir, "reviews", "R1.md"), "Review R1\n\nQuestions:\n  1. Scope: does it do what the contract says?\n      [answered] Only the calendar.\n  2. Proof?\n      [open]\n\nWhat to do:\n1. x\n");
  const transcript = path.join(base, "t.jsonl");
  write(transcript, events([
    { type: "user", message: { role: "user", content: "<command-name>/x</command-name>" } },
    { type: "user", message: { role: "user", content: "Takvimi yap lütfen" } },
    { type: "custom-title", customTitle: "maestro-metal (fork)" },
  ]));
  write(path.join(home, "board", "aaaaaaaa-1111.json"), JSON.stringify({ sid: "aaaaaaaa-1111", transcript }));

  const repo = readRepo(root, { now: NOW, bootTime: NOW - 86400, sentinelHome: home });
  const s = repo.sessions[0];
  assert.equal(s.state, "working");
  assert.equal(s.live, true);
  assert.equal(s.title, "maestro-metal (fork)");
  assert.deepEqual(s.tasks.map((t) => [t.id, t.status]), [["T1", "approved"], ["T2", "open"], ["T3", "open"]]);
  assert.equal(s.tasks[0].basis, "evet, böyle olsun");
  assert.ok(s.tasks[0].contract?.includes("A month view."));
  assert.deepEqual(awaiting(s).map((t) => t.id), ["T2"]); // a step is covered by its task's contract
  assert.deepEqual(s.progress.map((p) => p.title), ["04:40 · The calendar can be looked at", "· 04:20", "· 04:03"]); // newest first
  assert.equal(s.progress[2].body, "Calendar rewritten.");
  assert.equal(s.progress[0].day, "2026-11-21");
  const r = s.reviews[0];
  assert.equal(r.answers[0].question, "Scope: does it do what the contract says?");
  assert.equal(r.open, 1); // question 2 is not answered
  assert.deepEqual(r.kept.map((k) => k.reason), ["eight rows fit a day"]);

  const v = view([repo], NOW, 24, false)[0].sessions[0];
  assert.ok(!v.tasks[0].html?.includes("hint for the agent")); // the template's hints are the agent's, not the person's
  assert.ok(!v.tasks[0].html?.includes("T1 · Calendar")); // the heading is on the row already
  assert.deepEqual(v.awaiting, ["T2"]);
});

test("without a custom title the first thing the person asked names the session", () => {
  const { root, home, base } = world();
  session(root, "bbbbbbbb", [{ t: NOW - 10, e: "session_start" }]);
  const transcript = path.join(base, "t.jsonl");
  write(transcript, events([{ type: "user", message: { role: "user", content: [{ type: "text", text: "Add a calendar\nto the home" }] } }]));
  write(path.join(home, "board", "bbbbbbbb-2222.json"), JSON.stringify({ sid: "bbbbbbbb-2222", transcript }));
  assert.equal(readRepo(root, { now: NOW, bootTime: null, sentinelHome: home }).sessions[0].title, "Add a calendar to the home");
});

test("a session cut by a restart, one that ended and one gone quiet are not live; the order puts live ones first", () => {
  const { root, home } = world();
  session(root, "cut00000", [{ t: NOW - 7200, e: "prompt" }]);
  session(root, "ended000", [{ t: NOW - 100, e: "prompt" }, { t: NOW - 90, e: "session_end" }]);
  session(root, "quiet000", [{ t: NOW - 3 * 86400, e: "stop" }]);
  session(root, "waits000", [{ t: NOW - 30, e: "notification", ntype: "permission_prompt" }]);
  session(root, "idle0000", [{ t: NOW - 20, e: "stop" }]);
  const repo = readRepo(root, { now: NOW, bootTime: NOW - 3600, sentinelHome: home });
  const by = Object.fromEntries(repo.sessions.map((s) => [s.id8, s]));
  assert.equal(by.cut00000.state, "cut");
  assert.equal(by.ended000.state, "ended");
  assert.equal(by.waits000.state, "waiting");
  assert.deepEqual([by.cut00000, by.ended000, by.quiet000].map((s) => s.live), [false, false, false]);
  assert.deepEqual(repo.sessions.slice(0, 2).map((s) => s.id8), ["waits000", "idle0000"]);
  // not live and nothing written for the person: off the panel unless everything is asked for
  assert.equal(shown(by.ended000, NOW, 24, false), false);
  assert.equal(shown(by.ended000, NOW, 24, true), true);
  assert.equal(view([repo], NOW, 24, false)[0].hidden, 3);
});

test("a compaction held for the notes shows until it is let go", () => {
  const { root, home } = world();
  session(root, "hold0000", [{ t: NOW - 50, e: "prompt" }, { t: NOW - 40, e: "compact_hold", tokens: 1 }]);
  assert.equal(readRepo(root, { now: NOW, bootTime: null, sentinelHome: home }).sessions[0].holdingCompaction, true);
  fs.appendFileSync(path.join(root, ".sentinel", "sessions", "hold0000", "events.jsonl"), events([{ t: NOW - 30, e: "compact_pass", why: "notes" }]));
  assert.equal(readRepo(root, { now: NOW, bootTime: null, sentinelHome: home }).sessions[0].holdingCompaction, false);
});

test("an event log is read from where the last read stopped, a line being written is kept for later, a rewritten log is read again", () => {
  const { base } = world();
  const file = path.join(base, "events.jsonl");
  fs.writeFileSync(file, events([{ t: 1, e: "prompt" }]) + '{"t": 2, "e": "st');
  assert.deepEqual(readEvents(file).map((e) => e.e), ["prompt"]);
  fs.appendFileSync(file, 'op"}\nnot json\n');
  assert.deepEqual(readEvents(file).map((e) => e.e), ["prompt", "stop"]);
  fs.writeFileSync(file, events([{ t: 3, e: "session_end" }]));
  assert.deepEqual(readEvents(file).map((e) => e.e), ["session_end"]);
});

test("the ledger is read newest first without its keys; hand-off briefs are found where the config puts them", () => {
  const { root, home } = world();
  write(path.join(root, ".sentinel", "assumptions.md"), "# Assumptions kept\n\nIntro.\n\n- **a.py:1** `x = 1`: first _(k)_ <!-- k1 -->\n- **T2, b.ts**: second <!-- R2 aaaa -->\n");
  fs.writeFileSync(path.join(root, ".sentinel", "config.toml"), '[handoff]\nenabled = true\ndir = "notes/briefs"\n');
  write(path.join(root, "notes", "briefs", "2026-11-21-mac.md"), "# Brief\n\nRead this first.\n");
  const repo = readRepo(root, { now: NOW, bootTime: null, sentinelHome: home });
  assert.deepEqual(repo.ledger.map((l) => l.key), ["R2 aaaa", "k1"]);
  assert.ok(!repo.ledger[0].text.includes("<!--"));
  assert.deepEqual(repo.handoffs.map((h) => h.name), ["2026-11-21-mac"]);
  assert.deepEqual(ledgerItems("no list here"), []);
});

test("what an agent writes is shown as text, never run", () => {
  const out = html('<script>alert(1)</script> <img src=x onerror=alert(1)> [x](javascript:alert(1)) **bold**');
  assert.ok(!out.includes("<script>") && !out.includes("<img") && !out.includes('href="javascript:'));
  assert.ok(out.includes("&lt;script&gt;") && out.includes("<strong>bold</strong>"));
});

test("a progress file in the full form keeps each section whole", () => {
  const entries = progressEntries("# Progress\n\n## 14:20 · Hiding screens\n\nWhat changed:\n- one\n- two\n\n### 15:00 · Next\nText\n");
  assert.deepEqual(entries.map((e) => e.title), ["14:20 · Hiding screens", "15:00 · Next"]);
  assert.equal(entries[0].body, "What changed:\n- one\n- two");
});
