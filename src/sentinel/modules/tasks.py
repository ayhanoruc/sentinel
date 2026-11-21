"""Tasks, and the contract before a task's first edit.

The gate is an exact check: an edit of a file in the repo passes only while the session has a task that is approved and
not done. What makes a good contract is the agent's and the person's business; the code checks only that the sections
of the task file have content and that an approval was recorded with the person's words.
"""
from __future__ import annotations

import re

from .. import core, sysutil

SECTION = "tasks"
SIZES = ("trivial", "normal", "large")
CLOCK_SLACK_S = 5           # a message and the command that follows it are stamped by two clocks of one machine


def task_file(ctx, tid: str):
    return ctx.session.dir / "tasks" / f"{tid}.md"


def _index(ctx) -> None:
    """tasks.md: every task of the session with its state, for the person and for the session after a compact."""
    lines = [f"# Tasks of session {ctx.sid[:8]}", ""]
    for t in ctx.session.tasks().values():
        when = sysutil.clock(t.get("done") or t.get("approved") or t["opened"])
        state = {"open": "contract not approved yet", "approved": "approved", "done": "done"}[t["status"]]
        parent = f", step of {t['parent']}" if t["parent"] else ""
        link = f" — [contract](tasks/{t['id']}.md)" if task_file(ctx, t["id"]).is_file() else ""
        lines.append(f"- **{t['id']}** {t['title']} ({t['size']}{parent}): {state} {when}{link}")
        if t.get("basis") and t["size"] in ("normal", "large"):
            how = "approved on a standing instruction, the contract not confirmed by the person" if t.get("standing") else "approved on"
            lines.append(f"  - {how}: \"{t['basis']}\"" + ("" if t.get("verified") else " (not checked against the conversation)"))
    sysutil.atomic_write(ctx.session.dir / "tasks.md", "\n".join(lines) + "\n")


def _sections(ctx, size: str) -> list[str]:
    off = {"world-model": "world_model", "proof": "proof"}
    return [s for s in ctx.cfg["tasks"]["sections"][size] if ctx.cfg["tasks"].get(off.get(s, ""), True)]


def _empty_sections(text: str) -> list[str]:
    """The headings of a task file whose section has no content (the template's hint comments do not count)."""
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    parts = re.split(r"^## +(.+)$", body, flags=re.M)
    return [parts[i].strip() for i in range(1, len(parts), 2) if not parts[i + 1].strip()]


# ------------------------------------------------------------------------------------------------- the gate
def gated_path(ctx) -> str | None:
    """The repo-relative path of the file this call edits, when the gate applies to it."""
    if ctx.tool not in core.EDIT_TOOLS:
        return None
    path = ctx.tin.get("file_path") or ctx.tin.get("notebook_path")
    rel = ctx.rel(path) if path else None
    if rel is None or rel == ".sentinel" or rel.startswith(".sentinel/") or core.match_any(rel, ctx.cfg["tasks"]["exempt"]):
        return None
    return rel


def on_pre_tool_use(ctx, out) -> None:
    if not ctx.cfg["tasks"].get("gate", True) or gated_path(ctx) is None:
        return
    tasks = ctx.session.tasks().values()
    if any(t["status"] == "approved" for t in tasks):
        return
    pending = [t for t in tasks if t["status"] == "open"]
    if pending:
        t = pending[-1]
        ctx.moment("task-pending")
        out.deny(ctx.text("moments/task-pending.md", id=t["id"], path=task_file(ctx, t["id"])))
    else:
        ctx.moment("no-task")
        out.deny(ctx.text("moments/no-task.md"))


# ------------------------------------------------------------------------------------------------- commands
def open_(args, ctx) -> tuple[int, str]:
    tasks = ctx.session.tasks()
    tid = f"T{len(tasks) + 1}"
    title = re.sub(r"\s+", " ", args.title).strip()
    if not title:
        return 1, "Give the task a title: what this piece of work is."
    if args.parent:
        parent = tasks.get(args.parent)
        if parent is None:
            return 1, f"No task {args.parent}. `sentinel task list` shows them."
        if parent["status"] != "approved":
            return 1, f"{args.parent} is {parent['status']}: a step can be opened only inside a task that is approved and not done."
        ctx.session.log("task_open", id=tid, title=title, size="step", parent=args.parent)
        ctx.session.log("task_approve", id=tid, basis=f"step of {args.parent}")
        _index(ctx)
        return 0, f"Step {tid} of {args.parent} is open: {title}\nIt is covered by {args.parent}'s contract. When it is done: `sentinel task done {tid}`."
    ctx.session.log("task_open", id=tid, title=title, size=args.size, parent=None)
    if args.size == "trivial":
        ctx.session.log("task_approve", id=tid, basis="trivial")
        _index(ctx)
        return 0, ctx.text("moments/contract-trivial.md", id=tid, size="trivial")
    body = [f"# {tid} · {title}", ""]
    for name in _sections(ctx, args.size):
        body += [core.text_path(f"templates/sections/{name}.md", ctx.root).read_text(encoding="utf-8").strip(), "", ""]
    path = task_file(ctx, tid)
    sysutil.atomic_write(path, "\n".join(body).rstrip() + "\n")
    _index(ctx)
    note = ("   " + ctx.text("moments/field-note.md")) if ctx.cfg["tasks"]["field_note"] else ""
    text = ctx.text("moments/contract.md", id=tid, size=args.size, path=path, field_note=note)
    return 0, text if note else text.replace("\n\n4. Stop", "\n4. Stop")


def _pick(ctx, tid: str | None, status: str) -> tuple[dict | None, str]:
    tasks = ctx.session.tasks()
    if tid:
        return (tasks.get(tid), "") if tid in tasks else (None, f"No task {tid}. `sentinel task list` shows them.")
    found = [t for t in tasks.values() if t["status"] == status]
    if len(found) == 1:
        return found[0], ""
    return None, (f"No task is {status}." if not found else f"Several tasks are {status}: name one ({', '.join(t['id'] for t in found)}).")


def approve(args, ctx) -> tuple[int, str]:
    t, why = _pick(ctx, args.id, "open")
    if t is None:
        return 1, why
    if t["status"] != "open":
        return 1, f"{t['id']} is already {t['status']}."
    basis = re.sub(r"\s+", " ", args.basis or "").strip()
    standing = re.sub(r"\s+", " ", args.standing or "").strip()
    if bool(basis) == bool(standing):
        return 1, ("Give the person's own words, one of: --basis \"<what they answered to the contract>\", or, when they told "
                   "you not to wait for them, --standing \"<the words they said that with>\".")
    if standing and not ctx.cfg["tasks"]["standing"]:
        return 1, "Approving on a standing instruction is switched off here ([tasks] standing = false): present the contract and wait."
    path = task_file(ctx, t["id"])
    if not path.is_file():
        return 1, f"The contract file is missing: {path}"
    empty = _empty_sections(path.read_text(encoding="utf-8"))
    if empty:
        return 1, (f"{t['id']} cannot be approved yet: these sections of {path} are empty: {', '.join(empty)}.\n"
                   "Fill them (write \"None\" where there is truly nothing), present the contract to the person, then approve.")
    events = ctx.session.events()
    opened = next(i for i, e in enumerate(events) if e["e"] == "task_open" and e["id"] == t["id"])
    verify = bool(ctx.cfg["tasks"]["verify_approval"])
    if verify and basis and not any(e["e"] == "prompt" for e in events[opened + 1:]) and not _said(ctx, "", t["opened"] + 2 * CLOCK_SLACK_S):
        return 1, (f"{t['id']} cannot be approved on --basis yet: the person has not written anything since its contract was opened.\n"
                   "Present the contract in the conversation and stop. Approve when they have answered."
                   + ("\nOnly if they told you earlier not to wait for them: --standing \"<their words>\"." if ctx.cfg["tasks"]["standing"] else ""))
    said = _said(ctx, basis or standing, t["opened"] if basis else None) if verify else True
    if said is False:
        return 1, ("These words are not in what the person wrote" + (" since the contract was opened" if basis else "")
                   + ". Quote their own words exactly; an approval is recorded only on what they said.")
    ctx.session.log("task_approve", id=t["id"], basis=basis or standing, standing=bool(standing), verified=verify and said is True)
    _index(ctx)
    tail = "" if said else " (The words could not be checked against the conversation: its transcript is not readable from here.)"
    if standing:
        return 0, (f"{t['id']} is approved on the person's standing instruction; edits pass now.{tail}\n"
                   "They have not confirmed this contract: put its understanding, assumptions and open questions in your final "
                   "message so they read them.\n"
                   f"When the work is done and shown to work: `sentinel task done {t['id']}`.")
    return 0, (f"{t['id']} is approved; edits pass now. The basis is recorded in {ctx.session.dir / 'tasks.md'}.{tail}\n"
               f"When the work is done and shown to work: `sentinel task done {t['id']}`.")


def _said(ctx, words: str, after: float | None) -> bool | None:
    """Whether the person wrote these words (since `after`, when given). None when the conversation cannot be read."""
    from pathlib import Path

    from .. import transcript

    path = (core.registered(ctx.sid) or {}).get("transcript")
    if not path or not Path(path).is_file():
        return None
    flat = re.sub(r"\s+", " ", words).strip().casefold()
    for when, text in transcript.person_messages(Path(path)):
        if after is not None and (when is None or when < after - CLOCK_SLACK_S):
            continue
        if flat in re.sub(r"\s+", " ", text).casefold():
            return True
    return False


def done(args, ctx) -> tuple[int, str]:
    t, why = _pick(ctx, args.id, "approved")
    if t is None:
        return 1, why
    if t["status"] == "done":
        return 1, f"{t['id']} is already done."
    closed =[t["id"]] + [s["id"] for s in ctx.session.tasks().values() if s["parent"] == t["id"] and s["status"] != "done"]
    for tid in closed:
        ctx.session.log("task_done", id=tid)
    _index(ctx)
    more = f" (with its steps {', '.join(closed[1:])})" if len(closed) > 1 else ""
    return 0, f"{t['id']} is done{more}. The next piece of work needs its own task."


def list_(args, ctx) -> tuple[int, str]:
    tasks = ctx.session.tasks()
    if not tasks:
        return 0, "No tasks in this session yet. Open one: sentinel task open \"<title>\" [--size trivial|normal|large]"
    _index(ctx)
    return 0, (ctx.session.dir / "tasks.md").read_text(encoding="utf-8")


def lens(args, ctx) -> tuple[int, str]:
    names: dict[str, str] = {}
    for base in (core.PACKAGE_TEXTS, core.home() / "texts", ctx.root / ".sentinel" / "texts"):
        folder = base / "lenses"
        if folder.is_dir():
            for f in sorted(folder.glob("*.md")):
                names[f.stem] = f.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
    if not args.name:
        return 0, "Lenses for the contract's World model. Read the ones that fit: `sentinel lens <name>`\n" + "\n".join(
            f"  {n:12} {title}" for n, title in names.items())
    if args.name not in names:
        return 1, f"No lens '{args.name}'. There are: {', '.join(names)}"
    return 0, ctx.text(f"lenses/{args.name}.md")


def cli(sub) -> None:
    p = sub.add_parser("task", help="open, approve and close the tasks of this session")
    ts = p.add_subparsers(dest="task_cmd", required=True)
    o = ts.add_parser("open", help="open a task (and get its contract)")
    o.add_argument("title")
    o.add_argument("--size", choices=SIZES, default="normal")
    o.add_argument("--parent", help="the approved task this is a step of")
    o.set_defaults(fn=open_)
    a = ts.add_parser("approve", help="record the person's approval of a task's contract")
    a.add_argument("id", nargs="?")
    a.add_argument("--basis", help="the person's words, from their answer to the contract")
    a.add_argument("--standing", help="the person's words telling you not to wait for them")
    a.set_defaults(fn=approve)
    d = ts.add_parser("done", help="close a task")
    d.add_argument("id", nargs="?")
    d.set_defaults(fn=done)
    ls = ts.add_parser("list", help="the tasks of this session")
    ls.set_defaults(fn=list_)
    le = sub.add_parser("lens", help="the lenses for a contract's world model")
    le.add_argument("name", nargs="?")
    le.set_defaults(fn=lens, needs_session=False)
