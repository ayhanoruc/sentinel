"""The `sentinel` command: what the agent runs to talk to Sentinel, and what the person runs to set it up and look in.

Each command prints what happened and what to do next. A command that belongs to a session finds it from
`SENTINEL_SESSION` (set by the SessionStart hook), `--session`, or, when a repo has exactly one running session, that
one.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, config as config_mod, core, sysutil


def _session(args) -> tuple[Path | None, str, str]:
    """(repo root, session id, why not) for this call."""
    sid = getattr(args, "session", None) or os.environ.get("SENTINEL_SESSION") or ""
    if sid:
        reg = core.registered(sid)
        if reg is None:                                    # an id given by its first characters
            match = [r for r, _ in core.all_sessions() if r["sid"].startswith(sid)]
            reg = match[0] if len(match) == 1 else None
        if reg is None:
            return None, "", f"No session {sid} is registered on this machine. `sentinel board --all` lists them."
        return Path(reg["root"]), reg["sid"], ""
    root = core.find_root(Path(os.environ.get("SENTINEL_ROOT") or os.getcwd()))
    if root is None:
        return None, "", "Sentinel is not active here: no .sentinel/config.toml in this folder or above it. `sentinel init` activates it."
    cfg = config_mod.load(root, core.home())
    live = [s for _, s in core.all_sessions() if s.root.resolve() == root.resolve() and core.is_live(s, cfg)]
    if len(live) == 1:
        return root, live[0].sid, ""
    if not live:
        return root, "", "No running session was found for this repository (SENTINEL_SESSION is not set)."
    return root, "", ("Several sessions run in this repository and SENTINEL_SESSION is not set. Name yours: --session <id>. Running: "
                      + ", ".join(s.sid[:8] for s in live))


def build_parser() -> argparse.ArgumentParser:
    from . import install, modules

    ap = argparse.ArgumentParser(prog="sentinel", description="Sentinel: a discipline layer for Claude Code sessions.")
    ap.add_argument("--version", action="version", version=f"sentinel {__version__}")
    ap.add_argument("--session", help="the session this command is for (default: SENTINEL_SESSION)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for mod in modules.load():
        if hasattr(mod, "cli"):
            before = set(sub.choices)
            mod.cli(sub)
            for name in set(sub.choices) - before:           # a command of a flow that is off says so
                if sub.choices[name].get_default("section") is None:
                    sub.choices[name].set_defaults(section=mod.SECTION)
    install.cli(sub)
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    fn = getattr(args, "fn", None)
    if fn is None:
        print("Give a command. `sentinel --help` lists them.")
        return 2
    if getattr(args, "standalone", False):                    # init, uninstall, doctor: no session, maybe no repo yet
        code, text = fn(args)
        print(text)
        return code
    root, sid, why = _session(args)
    needs = getattr(args, "needs_session", True)
    if root is None or (needs and not sid):
        print(why)
        return 1
    ctx = core.Ctx({}, root, sid)
    section = getattr(args, "section", None)
    if section and not ctx.on(section):
        print(f"This flow is switched off here: [{section}] enabled = false in {root / '.sentinel' / 'config.toml'}.")
        return 1
    code, text = fn(args, ctx)
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
