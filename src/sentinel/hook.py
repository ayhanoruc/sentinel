"""The one hook command: `sentinel-hook`. Claude Code calls it for every event with the event as JSON on stdin; it
records the fact in the session's log, lets every enabled module answer, and prints the one merged answer.

In a folder with no `.sentinel/config.toml` above it, it exits at once. An error here never blocks the session: it
goes to `~/.sentinel/errors.log` and stderr, and the hook exits 1 (a non-blocking hook error in Claude Code).
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

from . import core, sysutil


def _root(event: dict) -> Path | None:
    for start in (os.environ.get("CLAUDE_PROJECT_DIR"), event.get("cwd"), os.getcwd()):
        if start:
            root = core.find_root(Path(sysutil.native_path(start)))
            if root:
                return root
    return None


def _background(event: dict) -> list[str]:
    """The background tasks Claude Code says are still running at a turn's end, each as one line."""
    out = []
    for b in event.get("background_tasks") or []:
        if isinstance(b, dict):
            out.append(str(b.get("description") or b.get("command") or b.get("summary") or b.get("id") or b)[:200])
        else:
            out.append(str(b)[:200])
    return out


def _facts(ctx, out) -> None:
    """What happened, recorded whatever flows are on: the modules and the board read the session from this."""
    ev, s, name = ctx.event, ctx.session, ctx.name
    if name == "SessionStart":
        from . import gitutil

        known = core.registered(ctx.sid) or {}
        core.register(ctx.sid, ctx.root, transcript=sysutil.native_path(ev.get("transcript_path") or ""),
                      head_start=known.get("head_start") or gitutil.head(ctx.root))
        s.log("session_start", source=ev.get("source"))
        env_file = os.environ.get("CLAUDE_ENV_FILE")
        if env_file:                           # the CLI learns which session it speaks for
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(f"SENTINEL_SESSION={ctx.sid}\nexport SENTINEL_SESSION\n")
    elif name == "UserPromptSubmit":
        s.log("prompt")
    elif name == "Stop":
        s.log("stop", background=_background(ev))
    elif name == "Notification":
        s.log("notification", ntype=ev.get("notification_type"))
    elif name == "SessionEnd":
        s.log("session_end", reason=ev.get("reason"))
    elif name == "PostToolUse":
        if ctx.tool in core.EDIT_TOOLS:
            path = ctx.tin.get("file_path") or ctx.tin.get("notebook_path")
            if path:
                p = Path(sysutil.native_path(str(path)))
                s.log("edit", path=str(p if p.is_absolute() else ctx.cwd / p))
        elif ctx.tool in core.SHELL_TOOLS and ctx.tin.get("run_in_background"):
            s.log("bash_bg", what=str(ctx.tin.get("description") or ctx.command())[:200])
    elif name == "PreToolUse" and ctx.tool in core.SHELL_TOOLS:
        from .modules.gate import is_agent_command

        cmd = ctx.command()
        if is_agent_command(cmd):           # the agent's own command, with nothing chained to it: no prompt, and its session set
            # set for every command of the call: an agent often writes several `sentinel` commands in one
            prefix = f"$env:SENTINEL_SESSION='{ctx.sid}'; " if ctx.tool == "PowerShell" else f"export SENTINEL_SESSION={ctx.sid}; "
            out.allow({**ctx.tin, "command": prefix + cmd.strip()})


def run(event: dict) -> str:
    """The answer to one event ("" for nothing)."""
    root = _root(event)
    sid = event.get("session_id")
    name = event.get("hook_event_name", "")
    if root is None or not sid or not name:
        return ""
    from . import modules

    ctx, out = core.Ctx(event, root, sid), core.Out()
    _facts(ctx, out)
    handler = modules.HANDLERS.get(name)
    for mod in modules.load() if handler else []:
        fn = getattr(mod, handler, None)
        if fn is not None and ctx.on(mod.SECTION):
            fn(ctx, out)
    return out.render(name)


def main() -> None:
    raw = sys.stdin.buffer.read()
    try:
        event = json.loads(raw.decode("utf-8", errors="replace")) if raw.strip() else {}
        text = run(event)
        debug = os.environ.get("SENTINEL_DEBUG_LOG")
        if debug:
            sysutil.append_line(Path(debug), json.dumps({"in": event, "out": text}, ensure_ascii=False))
        if text:
            sys.stdout.buffer.write(text.encode("ascii", errors="backslashreplace") if text.startswith("{") else text.encode("utf-8"))
        sys.exit(0)
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001: nothing here may stop the person's session; the error is recorded and shown
        try:
            sysutil.append_line(core.home() / "errors.log",
                                f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} {traceback.format_exc()}")
        except OSError:
            pass
        sys.stderr.write("sentinel-hook error (the session goes on; see ~/.sentinel/errors.log): "
                         + traceback.format_exc().strip().splitlines()[-1] + "\n")
        sys.exit(1)
