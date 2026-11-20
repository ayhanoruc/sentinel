"""The standing rules: given when a session starts and again each time the context has grown by a set amount; and the
corrections the person gives, recorded into the texts (`sentinel learn`)."""
from __future__ import annotations

import re
import time

from .. import core, sysutil

SECTION = "rules"


def on_session_start(ctx, out) -> None:
    out.context(ctx.text("rules/core.md"))
    # a resumed session already holds context: the next reminder counts from there, not from zero
    ctx.session.log("rules", tokens=int(ctx.event.get("context_tokens") or ctx.tokens() or 0))


def _remind(ctx, out) -> None:
    every = int(ctx.cfg["rules"]["remind_every_tokens"])
    tokens = None if ctx.sub or every <= 0 else ctx.tokens()
    if tokens is None:
        return
    last = ctx.session.last("rules")
    base = last["tokens"] if last else 0
    if tokens < base:                      # compacted since: count from the smaller context
        ctx.session.log("rules", tokens=tokens)
    elif tokens - base >= every:
        ctx.session.log("rules", tokens=tokens)
        ctx.moment("rules-reminder")
        out.context("A reminder of the standing rules, as the conversation has grown:\n\n" + ctx.text("rules/core.md"))


on_user_prompt_submit = _remind
on_post_tool_use = _remind


# ------------------------------------------------------------------------------------------------- learn (CLI)
def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def learn(args, ctx) -> tuple[int, str]:
    if not ctx.on("learn"):
        return 1, "Recording corrections is switched off here ([learn] in .sentinel/config.toml)."
    rule, incident = _one_line(args.rule), _one_line(args.incident or "")
    if not rule:
        return 1, "Give the rule as one or two sentences."
    base = core.home() / "learned" if args.scope == "user" else ctx.root / ".sentinel" / "learned"
    prefix = "U" if args.scope == "user" else "P"
    used = [int(m.group(1)) for f in base.glob("*.md") for m in re.finditer(rf"^- \[{prefix}(\d+) ", f.read_text(encoding="utf-8"), re.M)] if base.is_dir() else []
    lid = f"{prefix}{max(used, default=0) + 1}"
    line = f"- [{lid} {time.strftime('%Y-%m-%d', time.localtime(sysutil.now()))}] {rule}" + (f" (incident: {incident})" if incident else "")
    path = base / f"{args.where}.md"
    sysutil.append_line(path, line)
    if ctx.sid:
        ctx.session.log("learn", id=lid, where=args.where, scope=args.scope)
    reach = "every repository on this machine" if args.scope == "user" else "this repository"
    return 0, (f"Recorded as {lid} in {path}.\nFrom now on it is part of `{core.LEARN_TARGETS[args.where]}` for "
               f"sessions in {reach}.\nTell the person what you recorded and where.")


def unlearn(args, ctx) -> tuple[int, str]:
    for target in core.LEARN_TARGETS:
        for entry in core.learned(target, ctx.root):
            if entry["id"] == args.id:
                f = entry["file"]
                kept = [ln for ln in f.read_text(encoding="utf-8").splitlines() if not ln.startswith(f"- [{args.id} ")]
                sysutil.atomic_write(f, "\n".join(kept) + ("\n" if kept else ""))
                return 0, f"Removed {args.id} from {f}: {entry['rule']}"
    return 1, f"No learned rule {args.id}. `sentinel rules` lists them."


def show(args, ctx) -> tuple[int, str]:
    lines = [ctx.text("rules/core.md"), "", "Corrections recorded, by the text they belong to:"]
    any_ = False
    for target in core.LEARN_TARGETS:
        for e in core.learned(target, ctx.root):
            any_ = True
            lines.append(f"  {e['id']} [{target}, {e['scope']}, {e['date']}] {e['rule']}" + (f"  (incident: {e['incident']})" if e["incident"] else ""))
    if not any_:
        lines.append("  none yet")
    return 0, "\n".join(lines)


def cli(sub) -> None:
    p = sub.add_parser("learn", help="record a correction from the person into the texts")
    p.add_argument("rule")
    p.add_argument("--incident", default="", help="what happened, in one line")
    p.add_argument("--where", choices=sorted(core.LEARN_TARGETS), default="core", help="the text it belongs to (default: the standing rules)")
    p.add_argument("--scope", choices=("user", "project"), default="project", help="project: this repository; user: every repository")
    p.set_defaults(fn=learn, needs_session=False, section="learn")
    p = sub.add_parser("unlearn", help="remove a recorded correction")
    p.add_argument("id")
    p.set_defaults(fn=unlearn, needs_session=False, section="learn")
    p = sub.add_parser("rules", help="show the standing rules and the corrections recorded")
    p.set_defaults(fn=show, needs_session=False)
