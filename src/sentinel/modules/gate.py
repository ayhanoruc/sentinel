"""The check before a command that cannot be undone.

A pattern table over the command's text: a tripwire that makes the agent look at the target and name the way back at
the moment it is about to act. It is not a sandbox; Claude Code's permission modes are the boundary.
"""
from __future__ import annotations

import hashlib
import re

SECTION = "gate"
_SEG = r"[^|;&\n]*"         # the rest of one simple command

PATTERNS: list[tuple[str, str, str]] = [
    ("rm-recursive", rf"(?<![\w-])rm\s+(?:-[a-zA-Z-]+\s+)*(?:-[a-zA-Z]*[rR][a-zA-Z]*|--recursive)\b", "deletes a folder and everything in it"),
    ("remove-recursive", rf"\bRemove-Item\b{_SEG}-Recurse|\b(?:rd|rmdir)\s+/s\b|\bdel\s+/s\b", "deletes a folder and everything in it"),
    ("git-reset-hard", rf"\bgit\b{_SEG}\breset\b{_SEG}--hard", "throws away uncommitted work and moves the branch"),
    ("git-clean", rf"\bgit\b{_SEG}\bclean\b{_SEG}\s-[a-zA-Z]*[fdxX]", "deletes untracked files"),
    ("git-force-push", rf"\bgit\b{_SEG}\bpush\b{_SEG}(?:--force\b|--force-with-lease|\s-[a-zA-Z]*f\b)", "overwrites the branch on the remote"),
    ("git-branch-delete", rf"\bgit\b{_SEG}\bbranch\b{_SEG}\s(?-i:-D)\b|\bgit\b{_SEG}\bpush\b{_SEG}--delete\b", "deletes a branch"),
    ("git-discard", rf"\bgit\b{_SEG}\bcheckout\b{_SEG}\s--\s+\S|\bgit\b{_SEG}\bcheckout\s+\.(?:\s|$)|\bgit\b{_SEG}\brestore\b(?!{_SEG}--staged)|\bgit\b{_SEG}\bstash\s+(?:drop|clear)\b", "throws away uncommitted changes"),
    ("git-worktree-remove", rf"\bgit\b{_SEG}\bworktree\s+remove\b{_SEG}--force", "deletes a working tree with its uncommitted changes"),
    ("docker-destroy", rf"\bdocker\b{_SEG}\b(?:volume\s+(?:rm|prune)|system\s+prune)\b|\bdocker\b{_SEG}\bdown\b{_SEG}(?:\s-v\b|--volumes\b)", "deletes container volumes: their data is gone"),
    ("sql-destroy", r"\bDROP\s+(?:TABLE|DATABASE|SCHEMA|VIEW|INDEX)\b|\bTRUNCATE\s+(?:TABLE\s+)?[\w.\"]+|\bDELETE\s+FROM\s+[\w.\"]+\s*(?:;|\"|'|$)|\bdropdb\b|\bpg_restore\b[^|;&\n]*(?:--clean\b|\s-c\b)", "destroys stored data"),
    ("permissions", rf"\bicacls\b{_SEG}/(?:grant|deny|remove|reset|inheritance|setowner)|\btakeown\b|\bSet-Acl\b|\bch(?:mod|own)\s+(?:(?-i:-[a-zA-Z]*R[a-zA-Z]*)|--recursive)\b", "changes who can read or write: others who use the target may be locked out"),
    ("kill-by-name", rf"\btaskkill\b{_SEG}/IM\b|\b(?:pkill|killall)\b|\bStop-Process\b{_SEG}-Name\b", "stops every process of that name, not only yours"),
    ("disk", r"\bmkfs(?:\.\w+)?\b|\bdiskpart\b|\bdd\s+[^|;&\n]*\bof=|\bshred\b|\btruncate\s+-s\s*0\b", "overwrites a disk or a file's content"),
    ("cloud-delete", rf"\b(?:doctl|aws|az|gcloud|kubectl|terraform|wrangler|netlify|flyctl|heroku)\b{_SEG}\b(?:delete|destroy|terminate|purge)\b", "deletes a cloud resource"),
]
_SINGLE_QUOTED = re.compile(r"'[^']*'")
_DOUBLE_QUOTED = re.compile(r'"[^"`$\\]*"')
_PLAIN = re.compile(r"^\s*sentinel(?:\.exe)?(?:\s+[^\n\r;&|`$<>()]*)?$")


def is_plain_sentinel(command: str) -> bool:
    """One `sentinel …` command with nothing chained to it or substituted into it. Quoted text may hold any character
    a shell does not expand: everything inside single quotes, and inside double quotes everything but `$`, a backtick
    and a backslash."""
    bare = _DOUBLE_QUOTED.sub('""', _SINGLE_QUOTED.sub("''", command))
    return bool(_PLAIN.match(bare))


def patterns(cfg: dict) -> list[tuple[str, re.Pattern, str]]:
    off = set(cfg["gate"]["disable"])
    table = [p for p in PATTERNS if p[0] not in off]
    table += [(p["name"], p["regex"], p.get("why", "matches a pattern this repository added")) for p in cfg["gate"]["patterns"]
              if p["name"] not in off]
    return [(n, re.compile(rx, re.I), why) for n, rx, why in table]


def token_of(command: str) -> str:
    return hashlib.sha1(command.strip().encode("utf-8")).hexdigest()[:8]


def on_pre_tool_use(ctx, out) -> None:
    cmd = ctx.command()
    if not cmd or is_plain_sentinel(cmd):
        return
    hits = [(n, why) for n, rx, why in patterns(ctx.cfg) if rx.search(cmd)]
    if not hits:
        return
    token = token_of(cmd)
    oks = sum(1 for e in ctx.session.all("gate_ok") if e["token"] == token)
    used = sum(1 for e in ctx.session.all("gate_used") if e["token"] == token)
    if oks > used:
        ctx.session.log("gate_used", token=token)
        return
    if not any(e["token"] == token for e in ctx.session.all("gate_ask")):
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
