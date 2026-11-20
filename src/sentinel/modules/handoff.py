"""A brief for another session or another machine: the facts filled in from the session's files and git, the narrative
left for the agent to write."""
from __future__ import annotations

from pathlib import Path

from .. import core, gitutil, sysutil, transcript

SECTION = "handoff"


def handoff(args, ctx) -> tuple[int, str]:
    s, now = ctx.session, sysutil.now()
    folder = ctx.root / ctx.cfg["handoff"]["dir"]
    path = folder / f"{sysutil.day(now)}-{ctx.sid[:8]}.md"
    reg = core.registered(ctx.sid) or {}
    lines = [f"# Hand-off brief, {sysutil.day(now)} {sysutil.clock(now)}", "",
             f"From session {ctx.sid[:8]} in `{ctx.root.name}` (branch {gitutil.branch(ctx.root)})."
             + (f" Written for: {args.reader}." if args.reader else ""), "",
             "## What happened", "<!-- What was asked, what was done, what was decided and why. Results first. -->", "",
             "## What to read, in order", "<!-- Each file with what it is for. -->", "",
             "## Half done or waiting", "<!-- The exact state and the next step of each. -->", "",
             "## Facts from the session's record", "", "### Tasks"]
    tasks = s.tasks().values()
    lines += [f"- {t['id']} {t['title']} ({t['size']}): {t['status']}" for t in tasks] or ["- none opened"]
    notes = s.all("progress")
    lines += ["", "### Progress notes"] + ([f"- {sysutil.day(e['t'])} {sysutil.clock(e['t'])}: {e['note']}" for e in notes] or ["- none"])
    start = reg.get("head_start")
    code, log = gitutil.git(ctx.root, "log", "--oneline", f"{start}..HEAD") if start else (1, "")
    lines += ["", f"### Commits since the session started ({(start or '?')[:8]}..HEAD)"] + (
        [f"- {ln}" for ln in log.splitlines()] if code == 0 and log.strip() else ["- none"])
    edited = [ctx.rel(p) or p for p in s.edited()]
    lines += ["", "### Files edited"] + ([f"- {p}" for p in edited] or ["- none"])
    claims = s.claims()
    lines += ["", "### Claims held"] + ([f"- {r}: {c.get('note', '')}" for r, c in claims.items()] or ["- none"])
    kept = [e for e in s.all("gate_ok")]
    lines += ["", "### Irreversible commands run"] + (
        [f"- `{e['command'][:120]}` (looked at: {e['target']}; way back: {e['rollback']})" for e in kept] or ["- none"])
    hist = "not written"
    tpath = reg.get("transcript")
    if tpath and Path(tpath).is_file():
        out = s.dir / "history-handoff.md"
        try:
            info = transcript.history(Path(tpath), out, float(ctx.cfg["context"]["recent_fraction"]))
            hist = f"{out} ({info['entries']} entries since the last compaction)"
        except (OSError, ValueError) as exc:
            hist = f"not written: {exc}"
    lines += ["", "### Where the rest is", f"- Session folder: {s.dir}", f"- Cleaned conversation history: {hist}",
              f"- Assumptions kept at reviews: {ctx.root / '.sentinel' / 'assumptions.md'}", ""]
    sysutil.atomic_write(path, "\n".join(lines))
    s.log("handoff", path=str(path))
    return 0, ctx.text("moments/handoff.md", path=path)


def cli(sub) -> None:
    p = sub.add_parser("handoff", help="write a brief for another session or machine")
    p.add_argument("--for", dest="reader", default="", help="who will read it")
    p.set_defaults(fn=handoff)
