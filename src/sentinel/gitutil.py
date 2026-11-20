"""Git, read only: where a repo is, what differs from HEAD, what a `git commit` command would take."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

from . import sysutil

GIT_TIMEOUT_S = 30          # a read-only git call on a large repo answers well inside this; past it the hook gives up on git

# `git [-C dir] [-c k=v] commit …` up to the next shell operator
_COMMIT = re.compile(r"""\bgit\b((?:\s+-[cC]\s+(?:"[^"]*"|'[^']*'|\S+))*)\s+commit\b([^\n]*?)(?=&&|\|\||;|\||\n|$)""")
_CD = re.compile(r"""(?:^|[;&|\n]\s*)(?:cd|Set-Location|pushd)\s+(?:"([^"]+)"|'([^']+)'|([^\s;&|]+))""")
_DASH_C = re.compile(r"""-C\s+(?:"([^"]*)"|'([^']*)'|(\S+))""")
# git verbs after which HEAD may point somewhere else
HEAD_MOVERS = re.compile(r"\bgit\b[^\n|;&]*\b(commit|merge|pull|checkout|switch|rebase|reset|cherry-pick|revert|am)\b")


def git(cwd: Path, *args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=GIT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return r.returncode, r.stdout


def toplevel(path: Path) -> Path | None:
    start = path if path.is_dir() else path.parent
    if not start.is_dir():
        return None
    code, out = git(start, "rev-parse", "--show-toplevel")
    return Path(out.strip()) if code == 0 and out.strip() else None


def head(repo: Path) -> str | None:
    code, out = git(repo, "rev-parse", "HEAD")
    return out.strip() if code == 0 else None


def branch(repo: Path) -> str:
    code, out = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip() if code == 0 else "?"


def _names(repo: Path, *args: str) -> list[str]:
    code, out = git(repo, *args)
    return [ln.strip() for ln in out.splitlines() if ln.strip()] if code == 0 else []


def staged(repo: Path) -> list[str]:
    return _names(repo, "diff", "--cached", "--name-only")


def modified(repo: Path) -> list[str]:
    return _names(repo, "diff", "--name-only")


def changed_vs_head(repo: Path) -> list[str]:
    """Every file that differs from HEAD or is new and not ignored, as the repo names it."""
    names = dict.fromkeys(_names(repo, "diff", "HEAD", "--name-only") if head(repo) else staged(repo))
    for n in _names(repo, "ls-files", "--others", "--exclude-standard"):
        names[n] = None
    return list(names)


def added_lines(repo: Path, files: list[str]) -> dict[str, list[tuple[int, str]]]:
    """For each file, the lines it has that HEAD does not: (line number, text). A new file gives all its lines."""
    out: dict[str, list[tuple[int, str]]] = {}
    if not files:
        return out
    tracked = set(_names(repo, "ls-files", "--", *files))
    has_head = head(repo) is not None
    diffable = [f for f in files if f in tracked and has_head]
    if diffable:
        code, diff = git(repo, "diff", "HEAD", "-U0", "--no-color", "--no-ext-diff", "--", *diffable)
        cur, n = None, 0
        for line in diff.splitlines() if code == 0 else []:
            if line.startswith("+++ "):
                name = line[4:].strip()
                cur = name[2:] if name.startswith("b/") else None
                if cur is not None:
                    out.setdefault(cur, [])
            elif line.startswith("@@"):
                m = re.search(r"\+(\d+)", line)
                n = int(m.group(1)) if m else 0
            elif line.startswith("+") and cur is not None:
                out[cur].append((n, line[1:]))
                n += 1
    for f in files:
        if f in diffable:
            continue
        p = repo / f
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            out[f] = list(enumerate(text.splitlines(), 1))
    return out


def commit_command(command: str, cwd: Path) -> dict | None:
    """What a shell command's `git commit` would do, or None when it holds none.

    `repo` is the repository it runs in: `git -C <dir>`, else the last `cd <dir>` before it, else the shell's folder.
    `all`: it takes every modified tracked file (`-a`). `limited`: it names its own paths (`--only`, or a path list),
    so files others staged stay out. Read from the command's text: a tripwire, not a parser of the shell.
    """
    m = _COMMIT.search(command)
    if not m:
        return None
    candidates: list[Path] = []
    c = _DASH_C.search(m.group(1) or "")
    if c:
        candidates.append(Path(sysutil.native_path(next(g for g in c.groups() if g is not None))))
    cds = list(_CD.finditer(command[: m.start()]))
    if cds:
        candidates.append(Path(sysutil.native_path(next(g for g in cds[-1].groups() if g is not None))))
    candidates.append(cwd)
    repo = None
    for cand in candidates:
        cand = cand if cand.is_absolute() else cwd / cand
        repo = toplevel(cand)
        if repo:
            break
    # Claude Code writes the message as -m "$(cat <<'EOF' … EOF)": the first line then ends inside an open quote. What
    # follows a command substitution or a heredoc mark is message text, never a flag or a path of the commit.
    args = re.split(r"\"?\$\(|<<", m.group(2), maxsplit=1)[0]
    try:
        tokens = shlex.split(args, posix=True)
    except ValueError:
        tokens = args.split()
    takes_value = {"-m", "-F", "-C", "-c", "--message", "--file", "--author", "--date", "--fixup", "--squash",
                   "--reuse-message", "--reedit-message", "--cleanup", "-t", "--template"}
    all_, limited, i = False, False, 0
    while i < len(tokens):
        t = tokens[i]
        if t == "--":
            limited = limited or i + 1 < len(tokens)
            break
        if t in takes_value:
            i += 2
            continue
        if t in ("--all",) or (t.startswith("-") and not t.startswith("--") and "a" in t[1:]):
            all_ = True
            if "m" in t[1:] or "F" in t[1:]:          # -am "message": the next token is the message
                i += 1
        elif t in ("--only", "-o", "--include", "-i"):
            limited = True
        elif t.startswith("-") and not t.startswith("--") and ("m" in t[1:] or "F" in t[1:]):
            i += 1
        elif not t.startswith("-"):
            limited = True                             # a path given to the commit
        i += 1
    return {"repo": repo, "all": all_, "limited": limited, "adds": _adds(command[: m.start()])}


_ADD = re.compile(r"""\bgit\b(?:\s+-[cC]\s+(?:"[^"]*"|'[^']*'|\S+))*\s+add\b([^\n]*?)(?=&&|\|\||;|\||\n|$)""")


def _adds(before: str) -> str | list[str] | None:
    """What `git add` commands in the same shell command stage before the commit: "all" (`-A`, `-u`, `.`, no path),
    the paths named, or None when there is no `git add`. The index a hook sees does not hold these yet (seen in a
    real run: `git add -A && git commit` took another session's untracked file past the guard)."""
    paths: list[str] = []
    found = False
    for m in _ADD.finditer(before):
        found = True
        try:
            tokens = shlex.split(m.group(1), posix=True)
        except ValueError:
            tokens = m.group(1).split()
        named = [t for t in tokens if not t.startswith("-")]
        if not named or any(t in ("-A", "--all", "-u", "--update") for t in tokens) or any(t in (".", "./", "*") for t in named):
            return "all"
        paths += [t.replace("\\", "/").rstrip("/") for t in named]
    return paths if found else None


def taking(repo: Path, info: dict) -> list[str]:
    """The files a commit command would take, as the repo names them: what is staged, what `-a` adds, and what a
    `git add` earlier in the same command stages. A path given to `git add` is matched by name, by folder and as a
    glob; the result may hold more than the commit takes, never less."""
    from fnmatch import fnmatch

    names = dict.fromkeys(staged(repo) + (modified(repo) if info["all"] else []))
    adds = info.get("adds")
    if adds:
        for p in changed_vs_head(repo):
            if adds == "all" or any(p == a or p.startswith(a + "/") or p.endswith("/" + a) or fnmatch(p, a)
                                    or fnmatch(p.rsplit("/", 1)[-1], a) for a in adds):
                names[p] = None
    return list(names)


def norm(path: str | Path) -> str:
    """A path for comparing across sessions: real, and case-folded where the file system is."""
    return os.path.normcase(os.path.realpath(sysutil.native_path(str(path))))
