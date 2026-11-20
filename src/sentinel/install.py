"""Setting Sentinel up in a repository, taking it out again, and checking that it works."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import config as config_mod
from . import core, sysutil

HOOK = "sentinel-hook"
# event -> (matcher or None for every call, timeout in seconds). SessionStart may clean a large transcript after a
# compaction; the others only read and append small files.
EVENTS: dict[str, tuple[str | None, int]] = {
    "SessionStart": (None, 120),
    "UserPromptSubmit": (None, 30),
    "PreToolUse": ("Bash|PowerShell|Edit|Write|NotebookEdit|MultiEdit", 30),
    "PostToolUse": (None, 30),
    "Stop": (None, 30),
    "Notification": (None, 30),
    "PreCompact": (None, 30),
    "SessionEnd": (None, 30),
}
SKILLS = ("park", "handoff", "review", "board")


def _ours(entry: dict) -> bool:
    return any(HOOK in str(h.get("command", "")) for h in entry.get("hooks", []))


def _settings(root: Path, local: bool) -> Path:
    return root / ".claude" / ("settings.local.json" if local else "settings.json")


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def init(args) -> tuple[int, str]:
    root = Path(args.dir).resolve()
    if not root.is_dir():
        return 1, f"No such folder: {root}"
    done = []
    cfg = root / ".sentinel" / "config.toml"
    if cfg.is_file():
        done.append(f"kept the settings that were there: {cfg}")
    else:
        sysutil.atomic_write(cfg, config_mod.TEMPLATE)
        done.append(f"wrote {cfg}")
    ignore = root / ".sentinel" / ".gitignore"
    if not ignore.is_file():
        sysutil.atomic_write(ignore, "sessions/\n")
    path = _settings(root, args.local)
    try:
        settings = _read_json(path)
    except json.JSONDecodeError as exc:
        return 1, f"{path} is not valid JSON ({exc}); nothing was changed in it. Fix it and run `sentinel init` again."
    hooks = settings.setdefault("hooks", {})
    command = args.hook_command or HOOK
    for event, (matcher, timeout) in EVENTS.items():
        kept = [e for e in hooks.get(event, []) if not _ours(e)]
        entry: dict = {"hooks": [{"type": "command", "command": command, "timeout": timeout}]}
        if matcher:
            entry = {"matcher": matcher, **entry}
        hooks[event] = kept + [entry]
    sysutil.atomic_write(path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
    done.append(f"registered the hook for {len(EVENTS)} events in {path}")
    for name in SKILLS:
        sysutil.atomic_write(root / ".claude" / "skills" / f"sentinel-{name}" / "SKILL.md",
                             (core.PACKAGE_TEXTS / "install" / f"skill-{name}.md").read_text(encoding="utf-8"))
    sysutil.atomic_write(root / ".claude" / "agents" / "sentinel-field-note.md",
                         (core.PACKAGE_TEXTS / "install" / "agent-field-note.md").read_text(encoding="utf-8"))
    done.append("wrote the skills /sentinel-park, /sentinel-handoff, /sentinel-review, /sentinel-board and the sentinel-field-note agent under .claude/")
    note = "" if args.hook_command or shutil.which(HOOK) else (
        f"\nNote: `{HOOK}` is not on PATH in this shell. Install the tool (`uv tool install <sentinel repo>`) so Claude Code finds it.")
    return 0, "Sentinel is active in " + str(root) + ":\n" + "\n".join(f"- {d}" for d in done) + (
        "\nSessions started in this repository from now on use it. Settings: .sentinel/config.toml. Check: `sentinel doctor`.") + note


def uninstall(args) -> tuple[int, str]:
    root = Path(args.dir).resolve()
    removed = []
    for local in (False, True):
        path = _settings(root, local)
        if not path.is_file():
            continue
        try:
            settings = _read_json(path)
        except json.JSONDecodeError:
            removed.append(f"{path} is not valid JSON: left as it is")
            continue
        hooks = settings.get("hooks", {})
        changed = False
        for event in list(hooks):
            kept = [e for e in hooks[event] if not _ours(e)]
            changed = changed or len(kept) != len(hooks[event])
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
        if not hooks:
            settings.pop("hooks", None)
        if changed:
            sysutil.atomic_write(path, json.dumps(settings, indent=2, ensure_ascii=False) + "\n")
            removed.append(f"took the hook out of {path}")
    for name in SKILLS:
        folder = root / ".claude" / "skills" / f"sentinel-{name}"
        if folder.is_dir():
            shutil.rmtree(folder)
            removed.append(f"removed {folder}")
    agent = root / ".claude" / "agents" / "sentinel-field-note.md"
    if agent.is_file():
        agent.unlink()
        removed.append(f"removed {agent}")
    if not removed:
        return 0, f"Nothing of Sentinel's was registered in {root}."
    return 0, "\n".join(f"- {r}" for r in removed) + f"\nThe data in {root / '.sentinel'} was left as it is; delete the folder to remove it too."


def doctor(args) -> tuple[int, str]:
    root = core.find_root(Path(args.dir).resolve())
    lines, bad = [], 0

    def check(ok: bool | None, text: str) -> None:
        nonlocal bad
        bad += ok is False
        lines.append(f"{'ok  ' if ok else 'WARN' if ok is None else 'FAIL'}  {text}")

    check(root is not None, f"active here: {root / '.sentinel' / 'config.toml' if root else 'no .sentinel/config.toml in this folder or above'}")
    if root is None:
        return 1, "\n".join(lines) + "\nRun `sentinel init` in the repository's root."
    try:
        cfg = config_mod.load(root, core.home())
        check(True, "settings parse; flows on: " + ", ".join(k for k, v in cfg.items() if v.get("enabled")))
    except Exception as exc:  # noqa: BLE001: whatever stops the settings from loading is the finding
        check(False, f"settings do not load: {exc}")
        return 1, "\n".join(lines)
    registered: dict[str, str] = {}
    for local in (False, True):
        try:
            for event, entries in _read_json(_settings(root, local)).get("hooks", {}).items():
                for e in entries:
                    if _ours(e):
                        registered[event] = next(h["command"] for h in e["hooks"] if HOOK in str(h.get("command", "")))
        except json.JSONDecodeError as exc:
            check(False, f"{_settings(root, local)} is not valid JSON: {exc}")
    missing = [e for e in EVENTS if e not in registered]
    check(not missing, "hook registered for every event" if not missing else f"hook not registered for: {', '.join(missing)} (run `sentinel init`)")
    command = next(iter(registered.values()), HOOK)
    exe = shutil.which(command.split()[0]) or (command.split()[0] if Path(command.split()[0]).is_file() else None)
    check(exe is not None, f"hook command found: {exe}" if exe else f"`{command.split()[0]}` is not on PATH: Claude Code cannot run the hook")
    if exe:
        event = json.dumps({"hook_event_name": "PostToolUse", "session_id": "doctor00-check", "cwd": str(root),
                            "tool_name": "Read", "tool_input": {}})
        t0 = time.perf_counter()
        try:
            r = subprocess.run([exe], input=event.encode(), capture_output=True, timeout=30,
                               env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)})
            ms = int((time.perf_counter() - t0) * 1000)
            check(r.returncode == 0, f"hook runs: one call took {ms} ms" if r.returncode == 0 else f"hook fails: {r.stderr.decode(errors='replace').strip()[-300:]}")
            shutil.rmtree(root / ".sentinel" / "sessions" / "doctor00", ignore_errors=True)
        except (OSError, subprocess.SubprocessError) as exc:
            check(False, f"hook could not be run: {exc}")
    check((root / ".git").exists() or None, "a git repository" if (root / ".git").exists() else "not a git repository: the review, the commit guard and HEAD checks do nothing here")
    park = int(cfg["context"]["park_at_tokens"])
    windows = []
    for p in (Path.home() / ".claude" / "settings.json", _settings(root, False), _settings(root, True)):
        try:
            w = _read_json(p).get("autoCompactWindow")
        except json.JSONDecodeError:
            w = None
        if isinstance(w, (int, float)):
            windows.append((p, int(w)))
    for p, w in windows:
        check(None if park and w <= park else True, f"autoCompactWindow {w:,} in {p} "
              + ("is not above park_at_tokens " + f"{park:,}: the park would come after the compaction" if park and w <= park else "is above the park"))
    errors = core.home() / "errors.log"
    n = errors.read_text(encoding="utf-8", errors="replace").count("\n--- ") + 1 if errors.is_file() and errors.stat().st_size else 0
    check(None if n else True, f"{n} hook error(s) recorded in {errors}" if n else "no hook errors recorded")
    return (1 if bad else 0), "\n".join(lines)


def show_config(args, ctx) -> tuple[int, str]:
    return 0, json.dumps(ctx.cfg, indent=2, ensure_ascii=False)


def status(args, ctx) -> tuple[int, str]:
    s = ctx.session
    counts: dict[str, int] = {}
    for e in s.all("moment"):
        counts[e["name"]] = counts.get(e["name"], 0) + 1
    tasks = s.tasks().values()
    lines = [f"Session {ctx.sid[:8]} in {ctx.root}", f"Folder: {s.dir}", "",
             "Tasks: " + (", ".join(f"{t['id']} {t['status']}" for t in tasks) or "none"),
             "Messages given to the agent, by kind: " + (", ".join(f"{k} ×{v}" for k, v in sorted(counts.items())) or "none"),
             f"Reviews passed: {len(s.all('review_pass'))}   irreversible commands acknowledged: {len(s.all('gate_ok'))}   "
             f"progress notes: {len(s.all('progress'))}   compactions restored: {len(s.all('restore'))}"]
    return 0, "\n".join(lines)


def transcript_cmd(args) -> tuple[int, str]:
    from . import transcript

    path = Path(args.file)
    if not path.is_file():
        return 1, f"No such file: {path}"
    out = Path(args.out) if args.out else path.with_suffix(".history.md")
    info = transcript.history(path, out, args.recent)
    tokens = transcript.context_tokens(path)
    return 0, (f"Wrote {out}: {info['entries']} entries, {info['lines']} lines, the last part begins at line {info['recent_line']}; "
               f"{info['compactions']} compaction(s) on the chain. Context now: {f'{tokens:,} tokens' if tokens is not None else 'not known'}.")


def cli(sub) -> None:
    p = sub.add_parser("init", help="activate Sentinel in a repository")
    p.add_argument("dir", nargs="?", default=".")
    p.add_argument("--local", action="store_true", help="register the hook in .claude/settings.local.json (not shared)")
    p.add_argument("--hook-command", help="the command Claude Code runs for the hook (default: sentinel-hook on PATH)")
    p.set_defaults(fn=init, standalone=True)
    p = sub.add_parser("uninstall", help="take Sentinel's hook and files out of a repository (its data stays)")
    p.add_argument("dir", nargs="?", default=".")
    p.set_defaults(fn=uninstall, standalone=True)
    p = sub.add_parser("doctor", help="check that Sentinel is set up and works here")
    p.add_argument("dir", nargs="?", default=".")
    p.set_defaults(fn=doctor, standalone=True)
    p = sub.add_parser("config", help="the effective settings")
    p.set_defaults(fn=show_config, needs_session=False)
    p = sub.add_parser("status", help="what Sentinel did in this session")
    p.set_defaults(fn=status)
    p = sub.add_parser("transcript", help="write the cleaned history of a session transcript (.jsonl)")
    p.add_argument("file")
    p.add_argument("--out")
    p.add_argument("--recent", type=float, default=0.25, help="the part of the history marked as recent")
    p.set_defaults(fn=transcript_cmd, standalone=True)
