"""The context's life: an automatic compaction that waits for the agent's notes, instructions for the summary, and
recovery after a compaction.

Sentinel cannot start a compaction or change the model around one. Claude Code compacts by itself when the context is
`compact_at_percent` full (`sentinel init` writes that into its settings), or when the person runs /compact. What
Sentinel does is hold an automatic compaction back until the notes are written, and make the agent read back the
history, its notes and its tasks afterwards.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .. import core, sysutil, transcript

SECTION = "context"
PCT_ENV = "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"      # Claude Code's own setting: compact when the context is this percent full


def notes_path(ctx) -> Path:
    path = ctx.session.dir / "notes.md"
    if not path.is_file():
        sysutil.atomic_write(path, core.text_path("templates/notes.md", ctx.root).read_text(encoding="utf-8"))
    return path


def _sig(path: Path) -> str:
    """What a notes file holds now, to tell later whether it was written since."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def _fill(session) -> list[dict]:
    """The events of the present fill of the context: since the last compaction was restored, or since a /clear."""
    out: list[dict] = []
    for e in session.events():
        if e["e"] == "restore" or (e["e"] == "session_start" and e.get("source") == "clear"):
            out = []
        else:
            out.append(e)
    return out


def percent_in_force() -> float | None:
    """The percent at which Claude Code compacts in this session, read from the environment it gives its hooks; None
    when it runs on its own trigger (near the very end of the window, where nothing can wait)."""
    try:
        p = float(os.environ.get(PCT_ENV) or "")
    except ValueError:
        return None
    return p if 0 < p <= 100 else None


def _holding(fill: list[dict]) -> dict | None:
    """The hold that is running in this fill: its `compact_hold` event, or None when there is none or it was let go."""
    begun = next((e for e in fill if e["e"] == "compact_hold"), None)
    return None if begun is None or any(e["e"] == "compact_pass" for e in fill) else begun


def _hold(ctx) -> bool:
    """Whether this automatic compaction is held back for the notes. Every way out is an exact fact: the agent said the
    notes are written; the context reached the limit set when the hold began; a request did not get through; the
    size cannot be read."""
    at, until = percent_in_force(), float(ctx.cfg["context"]["hold_until_percent"])
    if at is None or not at < until <= 100:
        return False
    s, fill = ctx.session, _fill(ctx.session)
    if any(e["e"] == "compact_pass" for e in fill):
        return False                              # let go once in this fill: not held again
    path = ctx.event.get("transcript_path")
    reply = transcript.last_reply(Path(sysutil.native_path(path))) if path else None
    begun = next((e for e in fill if e["e"] == "compact_hold"), None)
    if begun is None:
        if reply is None or reply["tokens"] <= 0 or reply["error_after"]:
            return False                          # nothing to measure a hold by
        # The last reply was sent under the trigger, so tokens * 100 / at is no more than the window, and the limit
        # is no more than `until` percent of it.
        s.log("compact_hold", tokens=reply["tokens"], limit=int(reply["tokens"] * until / at), at=at, until=until)
        return True
    if any(e["e"] == "park_done" for e in fill[fill.index(begun):]):
        why = "notes"
    elif reply is None:
        why = "size unknown"
    elif reply["error_after"]:
        why = "a request failed"
    elif reply["tokens"] >= begun["limit"]:
        why = "room"
    else:
        s.log("compact_wait", tokens=reply["tokens"])
        return True
    s.log("compact_pass", why=why, tokens=reply["tokens"] if reply else None)
    return False


def _ask_for_hold(ctx, out) -> bool:
    """Tell the agent, once, that a compaction is being held for its notes."""
    fill = _fill(ctx.session)
    begun = _holding(fill)
    if begun is None or any(e["e"] == "park_ask" and e.get("hold") for e in fill[fill.index(begun):]):
        return False
    notes = notes_path(ctx)
    ctx.session.log("park_ask", tokens=begun["tokens"], hold=True, sig=_sig(notes))
    ctx.moment("park-hold")
    out.context(ctx.text("moments/park-hold.md", tokens=f" ({begun['tokens']:,} tokens)", notes=notes,
                         limit=f"{begun['limit']:,}"))
    return True


def on_user_prompt_submit(ctx, out) -> None:
    if not ctx.sub:
        _ask_for_hold(ctx, out)


def on_post_tool_use(ctx, out) -> None:
    if ctx.sub or _ask_for_hold(ctx, out):
        return
    at = int(ctx.cfg["context"]["park_at_tokens"])
    tokens = None if at <= 0 else ctx.tokens()
    if tokens is None or tokens < at:
        return
    fill = _fill(ctx.session)
    if any(e["e"] in ("park_ask", "compact_hold") for e in fill):
        return                               # asked already in this fill
    notes = notes_path(ctx)
    ctx.session.log("park_ask", tokens=tokens, sig=_sig(notes))
    ctx.moment("park")
    out.context(ctx.text("moments/park.md", tokens=f" ({tokens:,} tokens)", notes=notes))


def on_pre_compact(ctx, out) -> None:
    if ctx.sub:
        return                               # a subagent's own compaction is not this conversation's
    if ctx.event.get("trigger") == "auto" and _hold(ctx):
        out.block("Sentinel is holding this automatic compaction until the agent's notes are written "
                  "([context] hold_until_percent in .sentinel/config.toml).")
        return
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
    notes = notes_path(ctx)
    if args.what != "done":
        ctx.session.log("park_ask", tokens=None, manual=True, sig=_sig(notes))
        return 0, ctx.text("moments/park.md", tokens="", notes=notes)
    fill = _fill(ctx.session)
    asked = next((e for e in reversed(fill) if e["e"] == "park_ask"), None)
    if asked is not None and asked.get("sig") and asked["sig"] == _sig(notes):
        return 1, (f"The notes file has not changed since you were asked to bring it up to date: {notes}\n"
                   "Write it first, then run `sentinel park done` again.")
    held = _holding(fill) is not None
    ctx.session.log("park_done")
    if held:
        return 0, ("Recorded: the notes are current. The compaction that was held goes ahead at your next step. When it "
                   "is over you are given your history, your notes and your tasks: read them, then carry on from the "
                   "next step your notes name.")
    return 0, "Recorded: the notes are current."


def cli(sub) -> None:
    p = sub.add_parser("park", help="bring the notes up to date before a compaction; `park done` when they are written")
    p.add_argument("what", nargs="?", choices=["done"], help="done: the notes are written, a held compaction may go ahead")
    p.set_defaults(fn=park)
