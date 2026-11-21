"""What every module shares: where things live, a session's event log and the state read from it, the texts, the
answer a hook gives back.

A session's state is never stored: it is read from its append-only `events.jsonl`, so hooks that run side by side
cannot overwrite each other and the log is the record of what happened.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import config as config_mod
from . import sysutil

PACKAGE_TEXTS = Path(__file__).resolve().parent / "texts"
TAIL_BYTES = 16_384         # the end of a session's log read to see whether it is running: an event is a few hundred bytes
TAIL_EVENTS = 20            # how many of its last events that reading gives back
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit", "MultiEdit")
SHELL_TOOLS = ("Bash", "PowerShell")
# a learned rule's target and the text it is appended to
LEARN_TARGETS = {"core": "rules/core.md", "contract": "moments/contract.md", "review": "moments/review.md",
                 "tests": "moments/tests.md", "park": "moments/park.md"}
# other texts that carry a target's learned rules too
LEARN_ALSO = {"moments/park-hold.md": "park"}


def home() -> Path:
    return Path(os.environ.get("SENTINEL_HOME") or Path.home() / ".sentinel")


def find_root(start: Path) -> Path | None:
    """The nearest folder at or above `start` that holds `.sentinel/config.toml`: a repo where Sentinel is active."""
    try:
        start = start.resolve()
    except OSError:
        return None
    for p in (start, *start.parents):
        if (p / ".sentinel" / "config.toml").is_file():
            return p
    return None


# ---------------------------------------------------------------------------------------------------- sessions
class Session:
    """One Claude Code session's files in a repo, and its event log."""

    def __init__(self, root: Path, sid: str):
        self.root, self.sid = root, sid
        self.dir = root / ".sentinel" / "sessions" / sid[:8]
        self._events: list[dict] | None = None
        self._tail: list[dict] | None = None

    @property
    def log_path(self) -> Path:
        return self.dir / "events.jsonl"

    def events(self) -> list[dict]:
        if self._events is None:
            out = []
            if self.log_path.is_file():
                for line in self.log_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue                 # a torn line is skipped: the rest of the record still stands
            self._events = out
        return self._events

    def log(self, kind: str, **fields) -> dict:
        ev = {"t": sysutil.now(), "e": kind, **fields}
        sysutil.append_line(self.log_path, json.dumps(ev, ensure_ascii=False))
        if self._events is not None:
            self._events.append(ev)
        if self._tail is not None:
            self._tail = (self._tail + [ev])[-TAIL_EVENTS:]
        return ev

    def all(self, *kinds: str) -> list[dict]:
        return [e for e in self.events() if e["e"] in kinds]

    def last(self, *kinds: str) -> dict | None:
        for e in reversed(self.events()):
            if e["e"] in kinds:
                return e
        return None

    # -- state read from the log ------------------------------------------------------------------------------
    def tasks(self) -> dict[str, dict]:
        """Every task by id, in the order opened: title, size, parent, status (open, approved, done), basis."""
        out: dict[str, dict] = {}
        for e in self.events():
            if e["e"] == "task_open":
                out[e["id"]] = {"id": e["id"], "title": e["title"], "size": e["size"], "parent": e.get("parent"),
                                "status": "open", "opened": e["t"], "basis": None}
            elif e["e"] == "task_approve" and e["id"] in out:
                out[e["id"]].update(status="approved", basis=e.get("basis"), approved=e["t"],
                                    standing=bool(e.get("standing")), verified=bool(e.get("verified")))
            elif e["e"] == "task_done" and e["id"] in out:
                out[e["id"]].update(status="done", done=e["t"])
        return out

    def current_task(self) -> dict | None:
        """The task the work belongs to now: the last one opened that is not done."""
        live = [t for t in self.tasks().values() if t["status"] != "done"]
        return live[-1] if live else None

    def edited(self) -> list[str]:
        seen: dict[str, None] = {}
        for e in self.all("edit"):
            seen[e["path"]] = None
        return list(seen)

    def claims(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for e in self.events():
            if e["e"] == "claim":
                out[e["res"]] = e
            elif e["e"] == "release":
                out.pop(e["res"], None)
            elif e["e"] == "session_end":
                out.clear()                       # a session that ended holds nothing
        return out

    def activity(self) -> dict:
        """What the session is doing: working, idle (turn ended) or waiting (it asked the person); since when."""
        e = self.last("prompt", "stop", "notification", "session_end", "session_start")
        if e is None:
            return {"state": "unknown", "since": None}
        state = {"prompt": "working", "stop": "idle", "session_end": "ended", "session_start": "idle"}.get(e["e"])
        if e["e"] == "notification":
            state = "waiting" if e.get("ntype") in ("permission_prompt", "elicitation_dialog") else "idle"
        return {"state": state, "since": e["t"]}

    def tail(self) -> list[dict]:
        """The log's last events, read from its end. Whether a session is running is asked of every session on the
        machine at every shell command; only the end of each log answers that, so only the end is read."""
        if self._events is not None:
            return self._events[-TAIL_EVENTS:]
        if self._tail is not None:
            return self._tail
        try:
            size = self.log_path.stat().st_size
            with self.log_path.open("rb") as f:
                f.seek(max(0, size - TAIL_BYTES))
                lines = f.read().decode("utf-8", errors="replace").splitlines()
        except OSError:
            return []
        out = []
        for line in lines[1:] if size > TAIL_BYTES else lines:        # the first line of a cut tail is half a line
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        self._tail = out[-TAIL_EVENTS:]
        return self._tail

    def last_seen(self) -> float | None:
        ev = self.tail()
        return ev[-1]["t"] if ev else None

    def ended(self) -> bool:
        ev = [e for e in self.tail() if e["e"] not in ("crash_reported", "crash_announced")]
        return bool(ev) and ev[-1]["e"] == "session_end"


# ---------------------------------------------------------------------------------------------------- registry
def registry_path(sid: str) -> Path:
    return home() / "board" / f"{sid}.json"


def register(sid: str, root: Path, **fields) -> None:
    """Where a session lives, written when it starts: the CLI finds a session's repo from its id here."""
    path = registry_path(sid)
    data = registered(sid) or {"sid": sid, "started": sysutil.now()}
    data.update(root=str(root), **fields)
    sysutil.atomic_write(path, json.dumps(data, ensure_ascii=False, indent=1))


def registered(sid: str) -> dict | None:
    try:
        return json.loads(registry_path(sid).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def all_sessions() -> list[tuple[dict, Session]]:
    """Every session registered on this machine whose repo still holds its files."""
    out = []
    folder = home() / "board"
    if folder.is_dir():
        for f in sorted(folder.glob("*.json")):
            try:
                reg = json.loads(f.read_text(encoding="utf-8"))
                s = Session(Path(reg["root"]), reg["sid"])
            except (OSError, json.JSONDecodeError, KeyError):
                continue
            if s.log_path.is_file():
                out.append((reg, s))
    return out


def is_live(s: Session, cfg: dict) -> bool:
    """Counted as running: not ended, heard from since the machine's last boot and within `stale_after_hours`."""
    seen = s.last_seen()
    if seen is None or s.ended():
        return False
    boot = sysutil.boot_time()
    if boot is not None and seen < boot:
        return False
    return sysutil.now() - seen <= float(cfg["board"]["stale_after_hours"]) * 3600


# ---------------------------------------------------------------------------------------------------- texts
def text_path(name: str, root: Path | None) -> Path:
    for base in ((root / ".sentinel" / "texts") if root else None, home() / "texts", PACKAGE_TEXTS):
        if base and (base / name).is_file():
            return base / name
    raise FileNotFoundError(f"sentinel text not found: {name}")


def learned(target: str, root: Path | None) -> list[dict]:
    """The corrections recorded for a text, the user's first, then the repo's."""
    out = []
    for scope, base in (("user", home() / "learned"), ("project", (root / ".sentinel" / "learned") if root else None)):
        f = base / f"{target}.md" if base else None
        if f and f.is_file():
            for line in f.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^- \[(\w+) ([\d-]+)\] (.*?)(?:\s+\(incident: (.*)\))?$", line)
                if m:
                    out.append({"id": m.group(1), "date": m.group(2), "rule": m.group(3), "incident": m.group(4),
                                "scope": scope, "file": f})
    return out


def render(name: str, root: Path | None, **values) -> str:
    """A text with its `{name}` places filled and the corrections recorded for it appended."""
    body = text_path(name, root).read_text(encoding="utf-8")
    for k, v in values.items():
        body = body.replace("{" + k + "}", str(v))
    target = next((t for t, n in LEARN_TARGETS.items() if n == name), None) or LEARN_ALSO.get(name)
    rules = learned(target, root) if target else []
    if rules:
        body = body.rstrip() + "\n\nLearned from the person's corrections:\n" + "\n".join(f"- {r['rule']}" for r in rules)
    return body.strip()


# ---------------------------------------------------------------------------------------------------- one hook call
class Out:
    """What the modules answer to one event, merged into the one answer Claude Code takes."""

    def __init__(self):
        self.contexts: list[str] = []
        self.denies: list[str] = []
        self.blocks: list[str] = []
        self.compact: list[str] = []
        self.allowed = False
        self.updated_input: dict | None = None

    def context(self, text: str) -> None:
        if text and text.strip():
            self.contexts.append(text.strip())

    def deny(self, text: str) -> None:
        self.denies.append(text.strip())

    def block(self, text: str) -> None:
        self.blocks.append(text.strip())

    def allow(self, updated_input: dict | None = None) -> None:
        self.allowed, self.updated_input = True, updated_input

    def render(self, event: str) -> str:
        """The text for stdout ("" when there is nothing to say)."""
        ctx = "\n\n".join(self.contexts)
        if event == "PreCompact":
            if self.blocks:                                       # the compaction does not run now
                return json.dumps({"decision": "block", "reason": "\n\n".join(self.blocks)})
            return "\n\n".join(self.compact)                      # plain text: added to the summary's instructions
        if event == "PreToolUse":
            spec: dict = {"hookEventName": event}
            if self.denies:
                spec.update(permissionDecision="deny", permissionDecisionReason="\n\n".join(self.denies))
            elif self.allowed:
                spec.update(permissionDecision="allow", permissionDecisionReason="a Sentinel command")
                if self.updated_input is not None:
                    spec["updatedInput"] = self.updated_input
            if ctx and not self.denies:
                spec["additionalContext"] = ctx
            return json.dumps({"hookSpecificOutput": spec}) if len(spec) > 1 else ""
        if event == "Stop" and self.blocks:
            return json.dumps({"decision": "block", "reason": "\n\n".join(self.blocks)})
        if ctx and event in ("SessionStart", "UserPromptSubmit", "PostToolUse", "Stop"):
            return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": ctx}})
        return ""


class Ctx:
    """One hook call, or one CLI call (then `event` is empty)."""

    def __init__(self, event: dict, root: Path, sid: str, cfg: dict | None = None):
        self.event, self.root, self.sid = event, root, sid
        self.cfg = cfg if cfg is not None else config_mod.load(root, home())
        self.session = Session(root, sid)
        self.name: str = event.get("hook_event_name", "")
        self.tool: str = event.get("tool_name", "")
        self.tin: dict = event.get("tool_input") or {}
        self.sub = bool(event.get("agent_id"))                    # a subagent's call: no main-conversation moments
        self.cwd = Path(sysutil.native_path(event.get("cwd") or os.getcwd()))
        self._tokens: int | None | bool = False

    def on(self, section: str) -> bool:
        return bool(self.cfg.get(section, {}).get("enabled", False))

    def text(self, name: str, **values) -> str:
        """A text for the agent. A line that ends with `<!-- if:section -->` is given only while that flow is on, and
        one that ends with `<!-- if:section.key -->` only while that setting is true."""
        lines = []
        for line in render(name, self.root, **values).splitlines():
            m = re.search(r"\s*<!-- if:([\w-]+)(?:\.([\w-]+))? -->\s*$", line)
            if m is None:
                lines.append(line)
            elif (bool(self.cfg.get(m.group(1), {}).get(m.group(2))) if m.group(2) else self.on(m.group(1))):
                lines.append(line[: m.start()])
        return "\n".join(lines)

    def rel(self, path: str | Path) -> str | None:
        """A path as the repo names it, or None when it lies outside the repo."""
        try:
            p = Path(sysutil.native_path(str(path)))
            if not p.is_absolute():
                p = self.cwd / p
            return p.resolve().relative_to(self.root.resolve()).as_posix()
        except (ValueError, OSError):
            return None

    def command(self) -> str:
        return str(self.tin.get("command") or "") if self.tool in SHELL_TOOLS else ""

    def tokens(self) -> int | None:
        """The main conversation's context size now, from the transcript; None when it cannot be read."""
        if self._tokens is False:
            from .transcript import context_tokens

            path = self.event.get("transcript_path")
            self._tokens = context_tokens(Path(sysutil.native_path(path))) if path else None
        return self._tokens  # type: ignore[return-value]

    def moment(self, name: str) -> None:
        """Count a message given to the agent (`sentinel status` shows how often each one fired)."""
        self.session.log("moment", name=name)


def match_any(path: str, globs: list[str]) -> bool:
    """A repo-relative path against globs; `dir/**` covers everything under it, a bare pattern matches the file name too."""
    from fnmatch import fnmatch

    name = path.rsplit("/", 1)[-1]
    for g in globs:
        if g.endswith("/**"):
            base = g[:-3]
            if path == base or path.startswith(base + "/") or f"/{base}/" in f"/{path}":
                return True
        elif fnmatch(path, g) or fnmatch(name, g):
            return True
    return False
