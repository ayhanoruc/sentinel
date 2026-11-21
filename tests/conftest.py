"""The tests drive Sentinel the way Claude Code and the agent do: hook events into `hook.run`, commands into
`cli.main`, in a real git repository with its own SENTINEL_HOME. Every call prints one line, so a failing test shows the
whole exchange that led to it.
"""
from __future__ import annotations

import io
import json
import subprocess
import uuid
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from sentinel import cli, hook, install


class World:
    def __init__(self, tmp: Path, monkeypatch):
        self.tmp, self.mp = tmp, monkeypatch
        self.home, self.repo = tmp / "home", tmp / "repo"
        self.repo.mkdir()
        monkeypatch.setenv("SENTINEL_HOME", str(self.home))
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(self.repo))
        monkeypatch.delenv("SENTINEL_SESSION", raising=False)
        monkeypatch.delenv("CLAUDE_ENV_FILE", raising=False)
        monkeypatch.delenv("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", raising=False)   # as in a session Sentinel did not set up
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp / "claude-user"))      # never the real user's Claude Code settings
        monkeypatch.setenv("SENTINEL_BOOT_TIME", "1000")           # the machine booted long before every test clock
        from sentinel import config
        monkeypatch.setitem(config.DEFAULTS["tasks"], "verify_approval", True)   # the tests exercise the check; its default is off
        self.clock = 1_800_000_000.0
        self.tick(0)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        self.write("README.md", "# repo\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "first")

    # -- the machine ------------------------------------------------------------------------------------------
    def tick(self, seconds: float) -> None:
        self.clock += seconds
        self.mp.setenv("SENTINEL_NOW", str(self.clock))

    def git(self, *args: str, cwd: Path | None = None) -> str:
        r = subprocess.run(["git", "-C", str(cwd or self.repo), *args], capture_output=True, text=True)
        assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
        return r.stdout

    def write(self, rel: str, text: str) -> Path:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def activate(self, extra: str = "") -> None:
        class A:
            dir, local, hook_command = str(self.repo), False, "sentinel-hook"
        code, text = install.init(A)
        assert code == 0, text
        cfg = self.repo / ".sentinel" / "config.toml"
        cfg.write_text(cfg.read_text(encoding="utf-8").replace("verify_approval = false", "verify_approval = true"), encoding="utf-8")
        if extra:
            cfg = self.repo / ".sentinel" / "config.toml"
            cfg.write_text(extra, encoding="utf-8")

    # -- Claude Code's side ------------------------------------------------------------------------------------
    def hook(self, name: str, sid: str = "aaaaaaaa-1111", **fields) -> dict | str:
        event = {"hook_event_name": name, "session_id": sid, "cwd": str(self.repo), **fields}
        text = hook.run(event)
        print(f"[hook {sid[:8]} {name} {fields.get('tool_name', '')} {str(fields.get('tool_input', ''))[:80]}] -> {text[:300]}")
        if text.startswith("{"):
            return json.loads(text)
        return text

    def tpath(self, sid: str) -> Path:
        return self.tmp / f"{sid[:8]}.jsonl"

    def start(self, sid: str = "aaaaaaaa-1111", source: str = "startup", **fields):
        if "transcript_path" not in fields:
            self.tpath(sid).touch()
            fields["transcript_path"] = str(self.tpath(sid))
        return self.hook("SessionStart", sid, source=source, **fields)

    def say(self, text: str, sid: str = "aaaaaaaa-1111"):
        """The person writes a message: it lands in the session's transcript, stamped now, and the prompt hook fires."""
        from datetime import datetime, timezone

        last = getattr(self, "_last", {})
        uid = str(uuid.uuid4())
        entry = {"type": "user", "uuid": uid, "parentUuid": last.get(sid), "isSidechain": False,
                 "timestamp": datetime.fromtimestamp(self.clock, timezone.utc).isoformat().replace("+00:00", "Z"),
                 "message": {"role": "user", "content": text}}
        with self.tpath(sid).open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        last[sid] = uid
        self._last = last
        return self.hook("UserPromptSubmit", sid, prompt=text)

    def pre(self, tool: str, sid: str = "aaaaaaaa-1111", **tool_input):
        out = self.hook("PreToolUse", sid, tool_name=tool, tool_input=tool_input)
        return out.get("hookSpecificOutput", {}) if isinstance(out, dict) else {}

    def post(self, tool: str, sid: str = "aaaaaaaa-1111", **tool_input):
        out = self.hook("PostToolUse", sid, tool_name=tool, tool_input=tool_input)
        return out.get("hookSpecificOutput", {}).get("additionalContext", "") if isinstance(out, dict) else ""

    def edit(self, rel: str, text: str = "x = 1\n", sid: str = "aaaaaaaa-1111") -> dict:
        """An agent's edit: the gate's answer, and when it is not held, the file is written and the fact recorded."""
        path = str(self.repo / rel)
        ans = self.pre("Write", sid, file_path=path, content=text)
        if ans.get("permissionDecision") != "deny":
            self.write(rel, text)
            self.post("Write", sid, file_path=path, content=text)
        return ans

    def bash(self, command: str, sid: str = "aaaaaaaa-1111") -> dict:
        return self.pre("Bash", sid, command=command)

    # -- the agent's side --------------------------------------------------------------------------------------
    def cli(self, *argv: str, sid: str | None = "aaaaaaaa-1111") -> tuple[int, str]:
        if sid:
            self.mp.setenv("SENTINEL_SESSION", sid)
        else:
            self.mp.delenv("SENTINEL_SESSION", raising=False)
        self.mp.chdir(self.repo)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(list(argv))
        print(f"[cli {' '.join(argv)[:100]}] -> {code}: {buf.getvalue()[:300]}")
        return code, buf.getvalue()

    def session_dir(self, sid: str = "aaaaaaaa-1111") -> Path:
        return self.repo / ".sentinel" / "sessions" / sid[:8]

    def approved_task(self, sid: str = "aaaaaaaa-1111", size: str = "trivial", title: str = "work") -> None:
        code, out = self.cli("task", "open", title, "--size", size, sid=sid)
        assert code == 0, out


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    world = World(tmp_path, monkeypatch)
    world.activate()
    return world


@pytest.fixture
def bare(tmp_path, monkeypatch) -> World:
    """A repository where Sentinel was not activated."""
    return World(tmp_path, monkeypatch)


def transcript(path: Path, turns: list[dict]) -> Path:
    """A session transcript as Claude Code writes it. Each turn: {"user": text} or {"assistant": text, "tokens": n,
    "tool": (name, input)} or {"compact": True}."""
    lines, parent = [], None
    for t in turns:
        uid = str(uuid.uuid4())
        if t.get("compact"):
            lines.append({"type": "system", "subtype": "compact_boundary", "uuid": uid, "parentUuid": None,
                          "logicalParentUuid": parent, "isSidechain": False})
            parent = uid
            sid = str(uuid.uuid4())
            lines.append({"type": "user", "uuid": sid, "parentUuid": parent, "isCompactSummary": True, "isSidechain": False,
                          "message": {"role": "user", "content": "summary of what came before"}})
            parent = sid
            continue
        if "user" in t:
            entry = {"type": "user", "uuid": uid, "parentUuid": parent, "isSidechain": False,
                     "message": {"role": "user", "content": t["user"]}}
        else:
            content = [{"type": "text", "text": t["assistant"]}]
            if t.get("tool"):
                content.append({"type": "tool_use", "id": "tu", "name": t["tool"][0], "input": t["tool"][1]})
            entry = {"type": "assistant", "uuid": uid, "parentUuid": parent, "isSidechain": False,
                     "message": {"role": "assistant", "content": content,
                                 "usage": {"input_tokens": 10, "cache_read_input_tokens": t.get("tokens", 0),
                                           "cache_creation_input_tokens": 0}}}
        lines.append(entry)
        parent = uid
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return path
