"""Progress notes for the person on long work: a file they can open at any time, and the reminder to keep it fresh."""
from __future__ import annotations

import re

from .. import sysutil

SECTION = "progress"


def path_of(ctx):
    return ctx.session.dir / "progress.md"


def on_post_tool_use(ctx, out) -> None:
    every = float(ctx.cfg["progress"]["every_minutes"]) * 60
    if ctx.sub or every <= 0:
        return
    # long work is under way while a normal or large task is approved and not done (its steps do not count on their own)
    work = [t for t in ctx.session.tasks().values() if t["status"] == "approved" and t["size"] in ("normal", "large")]
    if not work:
        return
    task = work[-1]
    note = ctx.session.last("progress")
    since = max(task.get("approved") or task["opened"], note["t"] if note else 0)
    asked = ctx.session.last("progress_ask")
    now = sysutil.now()
    if now - since < every or (asked and asked["t"] > since and now - asked["t"] < every):
        return                              # not due yet, or asked already in this interval
    ctx.session.log("progress_ask")
    ctx.moment("progress")
    out.context(ctx.text("moments/progress.md", minutes=int((now - since) / 60)))


def note(args, ctx) -> tuple[int, str]:
    text = re.sub(r"\s+", " ", args.note).strip()
    if not text:
        return 1, "Give the note: what is done, what is running, what comes next, what waits for the person."
    path, now = path_of(ctx), sysutil.now()
    last = ctx.session.last("progress")
    if not path.is_file():
        sysutil.atomic_write(path, f"# Progress of session {ctx.sid[:8]}\n")
    if last is None or sysutil.day(last["t"]) != sysutil.day(now):
        sysutil.append_line(path, f"\n## {sysutil.day(now)}")
    task = ctx.session.current_task()
    sysutil.append_line(path, f"- **{sysutil.clock(now)}**" + (f" ({task['id']})" if task else "") + f" {text}")
    ctx.session.log("progress", note=text)
    return 0, f"Noted in {path}."


def cli(sub) -> None:
    p = sub.add_parser("progress", help="add a progress note for the person")
    p.add_argument("note")
    p.set_defaults(fn=note)
