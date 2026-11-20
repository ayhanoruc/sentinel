"""What a restart cut. Exact: a session whose last event before the machine's last boot is not its end was open when
the machine went down. It is told once when it is resumed; a new session in the repo is told once about the others."""
from __future__ import annotations

from .. import core, sysutil

SECTION = "crash"


def _cut(s: core.Session, boot: float) -> dict | None:
    """The last thing a session did before the boot, when the boot cut it and nobody has been told yet."""
    before = [e for e in s.events() if e["t"] < boot]
    after = [e for e in s.events() if e["t"] >= boot]
    if not before or before[-1]["e"] == "session_end":
        return None
    if any(e["e"] in ("crash_reported", "crash_announced") for e in after):
        return None
    return before[-1]


def _background(s: core.Session, boot: float) -> list[str]:
    return background([e for e in s.events() if e["t"] < boot])


def background(events: list[dict]) -> list[str]:
    """What was running in the background at the end of `events`: what Claude Code named at the last turn end, and
    what was started after it. By position in the log, not by clock: two events can share a timestamp."""
    last_stop = max((i for i, e in enumerate(events) if e["e"] == "stop"), default=-1)
    running = [str(b) for b in (events[last_stop].get("background") or [])] if last_stop >= 0 else []
    return running + [e["what"] for e in events[last_stop + 1:] if e["e"] == "bash_bg"]


def on_session_start(ctx, out) -> None:
    boot = sysutil.boot_time()
    if boot is None or ctx.event.get("source") not in ("startup", "resume"):
        return
    me = ctx.session
    last = _cut(me, boot)
    if last is not None:
        open_tasks = [t for t in me.tasks().values() if t["status"] != "done"]
        bg = _background(me, boot)
        note = me.last("progress")
        me.log("crash_reported")
        ctx.moment("crash")
        out.context(ctx.text(
            "moments/crash.md", last=f"{sysutil.day(last['t'])} {sysutil.clock(last['t'])}",
            boot=f"{sysutil.day(boot)} {sysutil.clock(boot)}",
            tasks="\n".join(f"- {t['id']} {t['title']} ({t['status']})" for t in open_tasks) or "- none",
            background="\n".join(f"- {b}" for b in bg) or "- none recorded",
            progress=note["note"] if note else "none", notes=me.dir / "notes.md"))
    lines = []
    for folder in sorted((ctx.root / ".sentinel" / "sessions").glob("*")):
        if not folder.is_dir() or folder.name == ctx.sid[:8]:
            continue
        other = core.Session(ctx.root, folder.name)
        cut = _cut(other, boot)
        if cut is None or any(e["t"] >= boot for e in other.events()):
            continue
        open_tasks = [t for t in other.tasks().values() if t["status"] != "done"]
        lines.append(f"- session {folder.name} (last activity {sysutil.day(cut['t'])} {sysutil.clock(cut['t'])}): "
                     + ("; ".join(f"{t['id']} {t['title']}" for t in open_tasks) or "no open task") + f". Folder: {folder}")
        other.log("crash_announced", to=ctx.sid[:8])
    if lines:
        ctx.moment("crash-other")
        out.context(ctx.text("moments/crash-other.md", boot=f"{sysutil.day(boot)} {sysutil.clock(boot)}", sessions="\n".join(lines)))
