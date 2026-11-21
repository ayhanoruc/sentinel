"""The check before a command that cannot be undone.

A pattern table over the command's text: a tripwire that makes the agent look at the target and name the way back at
the moment it is about to act. It is not a sandbox; Claude Code's permission modes are the boundary.
"""
from __future__ import annotations

import hashlib
import re

from .. import gitutil

SECTION = "gate"
_SEG = r"[^|;&\n]*"         # the rest of one simple command

# a recursive flag wherever it stands in the command: Unix `-r`, `-rf`, `-fR` (only letters `rm` knows, so PowerShell's
# `-Force` is not one), `--recursive`, and PowerShell's `-Recurse` in any of its abbreviations
_RECURSIVE = r"\s(?:(?-i:-(?=[dfiIvrR]*[rR])[dfiIvrR]+)|--recursive|-r(?:e(?:c(?:u(?:r(?:s(?:e)?)?)?)?)?)?)(?![\w-])"

PATTERNS: list[tuple[str, str, str]] = [
    ("rm-recursive", rf"(?<![\w-])(?:rm|Remove-Item|ri|del|erase|rd|rmdir)\b{_SEG}?{_RECURSIVE}|\b(?:rd|rmdir|del|erase)\s+/s\b",
     "deletes a folder and everything in it"),
    ("bulk-delete", rf"\bfind\b{_SEG}\s-delete\b|\bfind\b{_SEG}\s-exec\s+rm\b|\bxargs\b{_SEG}(?<![\w-])rm\b", "deletes every file a search finds"),
    ("git-reset-hard", rf"\bgit\b{_SEG}\breset\b{_SEG}--hard", "throws away uncommitted work and moves the branch"),
    ("git-clean", rf"\bgit\b{_SEG}\bclean\b{_SEG}\s-[a-zA-Z]*[fdxX]", "deletes untracked files"),
    ("git-force-push", rf"\bgit\b{_SEG}\bpush\b{_SEG}(?:--force\b|--force-with-lease|\s-[a-zA-Z]*f\b|\s\+[\w./-])", "overwrites the branch on the remote"),
    ("git-branch-delete", rf"\bgit\b{_SEG}\bbranch\b{_SEG}\s(?-i:-D)\b|\bgit\b{_SEG}\bpush\b{_SEG}--delete\b", "deletes a branch"),
    ("git-discard", rf"\bgit\b{_SEG}\bcheckout\b{_SEG}\s--\s+\S|\bgit\b{_SEG}\bcheckout\s+\.(?:\s|$)|\bgit\b{_SEG}\brestore\b(?!{_SEG}--staged)|\bgit\b{_SEG}\bstash\s+(?:drop|clear)\b"
                    rf"|\bgit\b{_SEG}\b(?:checkout|switch)\b{_SEG}(?:\s(?-i:-[a-zA-Z]*f[a-zA-Z]*)(?![\w-])|\s--force\b|\s--discard-changes\b)",
     "throws away uncommitted changes"),
    ("git-worktree-remove", rf"\bgit\b{_SEG}\bworktree\s+remove\b{_SEG}--force", "deletes a working tree with its uncommitted changes"),
    ("docker-destroy", rf"\bdocker\b{_SEG}\b(?:volume\s+(?:rm|prune)|system\s+prune)\b|\bdocker\b{_SEG}\bdown\b{_SEG}(?:\s-v\b|--volumes\b)", "deletes container volumes: their data is gone"),
    ("sql-destroy", r"\bDROP\s+(?:TABLE|DATABASE|SCHEMA|VIEW|INDEX)\b|\bTRUNCATE\s+(?:TABLE\s+)?[\w.\"]+|\bDELETE\s+FROM\s+[\w.\"]+\s*(?:;|\"|'|$)|\bdropdb\b|\bpg_restore\b[^|;&\n]*(?:--clean\b|\s-c\b)", "destroys stored data"),
    ("permissions", rf"\bicacls\b{_SEG}/(?:grant|deny|remove|reset|inheritance|setowner)|\btakeown\b|\bSet-Acl\b|\bch(?:mod|own)\s+(?:(?-i:-[a-zA-Z]*R[a-zA-Z]*)|--recursive)\b", "changes who can read or write: others who use the target may be locked out"),
    ("kill-by-name", rf"\btaskkill\b{_SEG}/IM\b|\b(?:pkill|killall)\b|\bStop-Process\b{_SEG}-Name\b", "stops every process of that name, not only yours"),
    ("disk", r"\bmkfs(?:\.\w+)?\b|\bdiskpart\b|\bdd\s+[^|;&\n]*\bof=|\bshred\b|\btruncate\s+-s\s*0\b", "overwrites a disk or a file's content"),
    ("cloud-delete", rf"\b(?:doctl|aws|az|gcloud|kubectl|terraform|wrangler|netlify|flyctl|heroku)\b{_SEG}\b(?:delete|destroy|terminate|purge)\b", "deletes a cloud resource"),
]
_SENTINEL = re.compile(r"sentinel(?:\.exe)?(?=[ \t]|$)")
_OUTSIDE_QUOTES = set("\n\r;&|`$<>()\\")      # what chains, redirects or expands outside quotes
_IN_DOUBLE_QUOTES = set("`$\\")               # what still expands inside double quotes
# the commands a person runs to set Sentinel up: never passed without the person's own permission
PERSON_COMMANDS = ("init", "uninstall", "doctor", "transcript")
_PLACE = re.compile(r"\(?\s*(?:cd|chdir|pushd|popd|Set-Location|sl)\b", re.I)


def is_plain_sentinel(command: str) -> bool:
    """One `sentinel …` command with nothing chained to it or substituted into it. Read as a shell reads it, quote by
    quote: outside quotes no operator, expansion or line break; inside double quotes no `$`, backtick or backslash;
    inside single quotes anything. A quote left open is not plain."""
    command = command.strip()
    m = _SENTINEL.match(command)
    if not m:
        return False
    quote = ""
    for ch in command[m.end():]:
        if quote == "'":
            quote = "" if ch == "'" else quote
        elif quote == '"':
            if ch == '"':
                quote = ""
            elif ch in _IN_DOUBLE_QUOTES:
                return False
        elif ch in "'\"":
            quote = ch
        elif ch in _OUTSIDE_QUOTES:
            return False
    return not quote


def is_agent_command(command: str) -> bool:
    """A plain `sentinel …` command of the kind the agent runs in a session (a task, a note, a review answer), not one
    that sets Sentinel up or writes to a path the command names."""
    if not is_plain_sentinel(command):
        return False
    words = command.split()[1:]
    i = 0
    while i < len(words) and words[i].startswith("-"):        # `--session <id>` stands before the command
        i += 2 if words[i] == "--session" else 1
    return i >= len(words) or words[i].strip("'\"") not in PERSON_COMMANDS


def patterns(cfg: dict) -> list[tuple[str, re.Pattern, str]]:
    off = set(cfg["gate"]["disable"])
    table = [p for p in PATTERNS if p[0] not in off]
    table += [(p["name"], p["regex"], p.get("why", "matches a pattern this repository added")) for p in cfg["gate"]["patterns"]
              if p["name"] not in off]
    return [(n, re.compile(rx, re.I), why) for n, rx, why in table]


def token_of(command: str, table: list[tuple[str, re.Pattern, str]] | None = None, cwd: str = "") -> str:
    """The identity of what is being acknowledged: the parts of the command that match a pattern, and where they run
    (the shell's folder and every `cd` in the command), not the harmless commands chained around them.
    `rm -rf build && ls` and `rm -rf build && git status` are the same act; `cd other && rm -rf build` is another."""
    parts = [p.strip() for p in re.split(r"&&|\|\||;|\||\n", command) if p.strip()]
    hit = [p for p in parts if _PLACE.match(p) or any(rx.search(p) for _, rx, _ in table or [])]
    return hashlib.sha1("\n".join([cwd, *(hit or [command.strip()])]).encode("utf-8")).hexdigest()[:8]


def on_pre_tool_use(ctx, out) -> None:
    cmd = ctx.command()
    if not cmd or is_plain_sentinel(cmd):
        return
    table = patterns(ctx.cfg)
    hits = [(n, why) for n, rx, why in table if rx.search(cmd)]
    if not hits:
        return
    token = token_of(cmd, table, gitutil.norm(ctx.cwd))
    oks = sum(1 for e in ctx.session.all("gate_ok") if e["token"] == token)
    used = sum(1 for e in ctx.session.all("gate_used") if e["token"] == token)
    if oks > used:
        ctx.session.log("gate_used", token=token)
        return
    asked = [e for e in ctx.session.all("gate_ask") if e["token"] == token]
    if not asked or asked[-1]["command"] != cmd[:500]:           # the record holds the command as it was last held
        ctx.session.log("gate_ask", token=token, command=cmd[:500], patterns=[n for n, _ in hits])
    ctx.moment("gate")
    out.deny(ctx.text("moments/gate.md", token=token, patterns="; ".join(f"{n}: {why}" for n, why in hits)))


def ok(args, ctx) -> tuple[int, str]:
    asked = [e for e in ctx.session.all("gate_ask") if e["token"] == args.token]
    if not asked:
        return 1, f"No held command has the token {args.token}. The token is in the message that held the command."
    target, rollback = (args.target or "").strip(), (args.rollback or "").strip()
    if not target or not rollback:
        return 1, "Say both: --target \"<what you looked at and saw>\" and --rollback \"<how to undo it, or why there is no way back>\"."
    ctx.session.log("gate_ok", token=args.token, target=target, rollback=rollback, command=asked[-1]["command"])
    return 0, "Recorded. Run the same command again: it passes once."


def cli(sub) -> None:
    p = sub.add_parser("gate", help="acknowledge a held irreversible command")
    gs = p.add_subparsers(dest="gate_cmd", required=True)
    o = gs.add_parser("ok")
    o.add_argument("token")
    o.add_argument("--target")
    o.add_argument("--rollback")
    o.set_defaults(fn=ok)
