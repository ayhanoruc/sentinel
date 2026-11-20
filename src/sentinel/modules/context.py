"""The context's life: notes before it fills, instructions for the summary, and recovery after a compaction.

Sentinel cannot start a compaction or change the model around one: Claude Code compacts by itself (its
`autoCompactWindow` setting) or when the person runs /compact. What it does is make sure the notes are current before,
and that the agent reads back the history, its notes and its tasks after.
"""
from __future__ import annotations

from pathlib import Path

from .. import core, sysutil, transcript

SECTION = "context"


def notes_path(ctx) -> Path:
    path = ctx.session.dir / "notes.md"
    if not path.is_file():
        sysutil.atomic_write(path, core.text_path("templates/notes.md", ctx.root).read_text(encoding="utf-8"))
    return path


def on_post_tool_use(ctx, out) -> None:
    at = int(ctx.cfg["context"]["park_at_tokens"])
    tokens = None if ctx.sub or at <= 0 else ctx.tokens()
    if tokens is None or tokens < at:
        return
    last = ctx.session.last("park_ask", "restore")
    if last and last["e"] == "park_ask":
        return                               # asked already since the last compaction
    ctx.session.log("park_ask", tokens=tokens)
    ctx.moment("park")
    out.context(ctx.text("moments/park.md", tokens=f" ({tokens:,} tokens)", notes=notes_path(ctx)))


def on_pre_compact(ctx, out) -> None:
    path = ctx.event.get("transcript_path")
    size = None
    if path:
        try:
            size = Path(sysutil.native_path(path)).stat().st_size
        except OSError:
            size = None
    ctx.session.log("compact", trigger=ctx.event.get("trigger"), end_offset=size)
    out.compact.append(ctx.text("moments/precompact.md"))


def on_session_start(ctx, out) -> None:
    if ctx.event.get("source") != "compact":
        return
    n = len(ctx.session.all("restore")) + 1
    hist = ctx.session.dir / f"history-{n}.md"
    mark = ctx.session.last("compact", "restore")
    end = mark.get("end_offset") if mark and mark["e"] == "compact" else None
    path = ctx.event.get("transcript_path")
    try:
        info = transcript.history(Path(sysutil.native_path(path)), hist, float(ctx.cfg["context"]["recent_fraction"]), end)
        where, entries, recent = str(hist), info["entries"], info["recent_line"]
    except (OSError, ValueError, TypeError) as exc:
        where, entries, recent = f"(could not be written: {exc})", 0, 1
    tasks = ctx.session.dir / "tasks.md"
    progress = ctx.session.dir / "progress.md"
    ctx.session.log("restore", n=n, history=where, entries=entries)
    ctx.moment("after-compact")
    out.context(ctx.text("moments/after-compact.md", history=where, entries=entries, recent_line=recent,
                         notes=notes_path(ctx), tasks=tasks if tasks.is_file() else "(no tasks were opened)",
                         progress=progress if progress.is_file() else "(no progress notes yet)"))


def park(args, ctx) -> tuple[int, str]:
    ctx.session.log("park_ask", tokens=None, manual=True)
    return 0, ctx.text("moments/park.md", tokens="", notes=notes_path(ctx))


def cli(sub) -> None:
    p = sub.add_parser("park", help="bring the notes up to date before a compaction")
    p.set_defaults(fn=park)
