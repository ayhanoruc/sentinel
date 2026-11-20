"""The session board: what every session on this machine is doing, what each has claimed, and the guards that keep two
sessions in one checkout from stepping on each other.

Nothing is stored for the board: each session's line is read from its own event log.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import core, gitutil, sysutil

SECTION = "board"


def others(ctx) -> list[core.Session]:
    """The other sessions on this machine that count as running."""
    return [s for _, s in core.all_sessions() if s.sid[:8] != ctx.sid[:8] and core.is_live(s, ctx.cfg)]


def _label(s: core.Session) -> str:
    task = s.current_task()
    return f"session {s.sid[:8]} in {s.root.name}" + (f" ({task['id']}: {task['title']})" if task else "")


# ------------------------------------------------------------------------------------------------- hooks
def on_user_prompt_submit(ctx, out) -> None:
    """HEAD moved since this session last looked, and not by this session."""
    now = gitutil.head(ctx.root)
    if now is None:
        return
    seen = ctx.session.last("head")
    if seen and seen["sha"] != now:
        code, log = gitutil.git(ctx.root, "log", "--oneline", f"{seen['sha']}..{now}")
        count = len(log.splitlines()) if code == 0 else 0
        ctx.moment("head-moved")
        out.context(f"The repository's HEAD moved since your last turn, and not by you: {seen['sha'][:8]} → {now[:8]}"
                    + (f" ({count} commits)" if count else " (history was rewritten or the branch changed)")
                    + f". Look before you rely on what you read earlier: `git log --oneline {seen['sha'][:8]}..{now[:8]}`.")
    if not seen or seen["sha"] != now:
        ctx.session.log("head", sha=now)


def on_post_tool_use(ctx, out) -> None:
    cmd = ctx.command()
    if cmd and gitutil.HEAD_MOVERS.search(cmd):          # this session's own move: remember where HEAD is now
        now = gitutil.head(ctx.root)
        seen = ctx.session.last("head")
        if now and (not seen or seen["sha"] != now):
            ctx.session.log("head", sha=now)


def on_pre_tool_use(ctx, out) -> None:
    cmd = ctx.command()
    if not cmd:
        return
    live = others(ctx)
    for s in live:                                         # a resource another session claimed
        for res, claim in s.claims().items():
            if re.search(rf"(?<![\w-]){re.escape(res)}(?![\w-])", cmd, re.I):
                ctx.moment("claim-warning")
                out.context(f"`{res}` is claimed by {_label(s)}" + (f": {claim['note']}" if claim.get("note") else "")
                            + ". This command names it. Check with that session or the person before you change it.")
    info = gitutil.commit_command(cmd, ctx.cwd)
    if info is None or info["repo"] is None or info["limited"]:
        return
    repo = info["repo"]
    taking = gitutil.staged(repo) + (gitutil.modified(repo) if info["all"] else [])
    mine = {gitutil.norm(p) for p in ctx.session.edited()}
    foreign: dict[str, list[str]] = {}
    for rel in dict.fromkeys(taking):
        key = gitutil.norm(repo / rel)
        if key in mine:
            continue
        for s in live:
            if key in {gitutil.norm(p) for p in s.edited()}:
                foreign.setdefault(_label(s), []).append(rel)
    if foreign:
        lines = [f"- {who}: {', '.join(files)}" for who, files in foreign.items()]
        ctx.moment("commit-foreign")
        out.deny("This commit is held: it would take files another running session edited and you did not.\n"
                 + "\n".join(lines)
                 + "\nCommit only your own files: `git commit --only -m \"…\" -- <your files>`, then check with `git show --stat HEAD`.")


# ------------------------------------------------------------------------------------------------- commands
def claim(args, ctx) -> tuple[int, str]:
    res = args.resource.strip()
    if not res:
        return 1, "Name the resource: a Docker project, a port, an image tag, a server."
    holders = [s for s in others(ctx) if res in s.claims()]
    ctx.session.log("claim", res=res, note=(args.note or "").strip())
    text = f"Claimed `{res}`. Other sessions are warned when a command of theirs names it. Release it when you are done: `sentinel release {res}`."
    if holders:
        text += "\nNote: it is also claimed by " + "; ".join(_label(s) for s in holders) + ". Sort that out before you use it."
    return 0, text


def release(args, ctx) -> tuple[int, str]:
    if args.resource not in ctx.session.claims():
        return 1, f"This session holds no claim on `{args.resource}`."
    ctx.session.log("release", res=args.resource)
    return 0, f"Released `{args.resource}`."


def _age(t: float | None) -> str:
    if t is None:
        return "?"
    m = int((sysutil.now() - t) / 60)
    return f"{m} min" if m < 120 else f"{m // 60} h" if m < 48 * 60 else f"{m // 1440} d"


def board(args, ctx) -> tuple[int, str]:
    cfg = ctx.cfg
    rows = []
    for reg, s in core.all_sessions():
        live = core.is_live(s, cfg)
        if not live and not args.all:
            continue
        act = s.activity()
        state = {"working": "working", "idle": "idle", "waiting": "WAITING FOR YOU", "ended": "ended"}.get(act["state"], "?")
        if not live and act["state"] != "ended":
            state = "not live"
        task = s.current_task()
        note = s.last("progress")
        lines = [f"{s.sid[:8]}  {Path(reg['root']).name}  [{gitutil.branch(s.root)}]  {state} for {_age(act['since'])}"
                 + ("  (this session)" if s.sid[:8] == ctx.sid[:8] and ctx.sid else "")]
        lines.append(f"    task: {task['id']} {task['title']} ({task['status']})" if task else "    task: none open")
        if note:
            lines.append(f"    last note ({_age(note['t'])} ago): {note['note']}")
        for res, c in s.claims().items():
            lines.append(f"    claims {res}" + (f": {c['note']}" if c.get("note") else ""))
        from .crash import background

        bg = background(s.events())
        if bg and live:
            lines.append(f"    background: {'; '.join(str(b)[:80] for b in bg)}")
        lines.append(f"    files edited: {len(s.edited())}   folder: {s.dir}")
        rows.append("\n".join(lines))
    if not rows:
        return 0, "No running sessions on the board." + ("" if args.all else " `sentinel board --all` shows ended ones too.")
    return 0, "\n\n".join(rows)


def cli(sub) -> None:
    p = sub.add_parser("claim", help="claim a shared resource so other sessions are warned")
    p.add_argument("resource")
    p.add_argument("note", nargs="?", default="")
    p.set_defaults(fn=claim)
    p = sub.add_parser("release", help="release a claim")
    p.add_argument("resource")
    p.set_defaults(fn=release)
    p = sub.add_parser("board", help="what every session on this machine is doing")
    p.add_argument("--all", action="store_true", help="also sessions that ended or are not live")
    p.set_defaults(fn=board, needs_session=False)
