"""The review before a commit, and the assumption ledger.

Detectors flag exact patterns on the lines a change adds; each flagged line needs a disposition (fixed, or kept with its
reason). For a task that is not trivial the agent also answers the numbered questions. The commit passes when nothing
is open. Kept lines go to `.sentinel/assumptions.md`, so the numbers and fallbacks someone chose stay on record.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

from .. import core, gitutil, sysutil
from . import testing

SECTION = "review"
TEXT_MAX = 140              # characters of a flagged line shown; the line number points to the rest

# name, where it applies (code: not test files; tests: test files; any), pattern, why it is flagged
DETECTORS: list[tuple[str, str, str, str]] = [
    ("default-fallback", "code",
     r"\.get\([^()]*,\s*(?!None\b)[^)\s][^)]*\)|\bgetenv\([^()]*,|\benviron\.get\([^()]*,|\bor\s+[\"'\d\[{(]|\|\|\s*[\"'\d\[{]|\?\?\s*[\"'\d\[{]",
     "a fallback value: a missing input would look like a valid one"),
    ("broad-except", "any", r"^\s*except\s*:|\bexcept\s+(?:Base)?Exception\b|\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}",
     "catches every error: the caller may never learn that it failed"),
    ("fixed-sleep", "any", r"\btime\.sleep\(|\basyncio\.sleep\(\s*[\d.]|(?<![\w-])sleep\s+\d|\bStart-Sleep\b|\bsetTimeout\([^,]+,\s*\d|\bThread\.sleep\(",
     "a fixed wait: it is either too short on a slow day or wasted on a fast one"),
    ("timeout-retry", "code", r"(?i)\b(?:timeout|retries|max_retries|retry|attempts|max_attempts|backoff)\w*\s*[=:]\s*\d",
     "a limit someone chose: why this value"),
    ("truncation", "code", r"\[\s*:\s*\d{2,}\s*\]|\[\s*-\d{2,}\s*:\s*\]|\|\s*(?:head|tail)\b|\.slice\(\s*0\s*,\s*\d+\s*\)|\blimit\s*=\s*\d+|\bSelect-Object\s+-(?:First|Last)\b",
     "cuts at a fixed size: what is cut is not seen"),
    ("silenced-check", "any", r"#\s*noqa|#\s*type:\s*ignore|eslint-disable|@ts-ignore|@ts-expect-error|--no-verify\b|\|\|\s*true\b|2>\s*/dev/null|2>\s*\$null|\bverify\s*=\s*False\b|-ErrorAction\s+SilentlyContinue|\bcheck\s*=\s*False\b",
     "a check or an error is silenced"),
    ("skipped-test", "tests", r"pytest\.mark\.(?:skip|xfail)|@unittest\.skip|\b(?:it|test|describe)\.(?:skip|only)\(|\bx(?:it|describe)\(",
     "a test that does not run, or that hides the others"),
    ("hardcoded-place", "code", r"[A-Za-z]:[\\/]+Users[\\/]|/home/\w+|/Users/\w+|https?://(?:localhost|127\.0\.0\.1)|\b\d{1,3}(?:\.\d{1,3}){3}\b",
     "a path or address of one machine"),
    ("todo", "any", r"\b(?:TODO|FIXME|XXX|HACK)\b", "work left undone and marked in the code"),
    ("test-depends-on-today", "tests", r"\bdatetime\.(?:now|today|utcnow)\(|\bdate\.today\(|\bDate\.now\(|\bnew Date\(\s*\)|\btime\.time\(",
     "the test's result depends on the day it runs"),
    ("mock-assertion", "tests", r"\bassert_called|\bassert_any_call|\.call_count\b|\btoHaveBeenCalled",
     "asserts that a mock was called, not that the behaviour is right"),
]
_COMMENT = ("#", "//", "/*", "*", "--", "<!--")
_STRINGS = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")
_NUMBER = re.compile(r"(?<![\w.])-?\d[\d_]*(?:\.\d+)?(?![\w.])")


def detectors(cfg: dict) -> list[tuple[str, str, re.Pattern, str]]:
    off = set(cfg["review"]["disable"])
    table = [d for d in DETECTORS if d[0] not in off] if cfg["review"]["detectors"] else []    # a repo's own always apply
    table += [(p["name"], p.get("where", "any"), p["regex"], p.get("why", "matches a pattern this repository added"))
              for p in cfg["review"]["patterns"] if p["name"] not in off]
    return [(n, where, re.compile(rx), why) for n, where, rx, why in table]


def _key(kind: str, file: str, text: str, nth: int = 1) -> str:
    """A flagged line's identity within one change: its kind, its file, its text, and which occurrence of that text it
    is among the lines the change adds. Not its line number, which moves; but a second `except Exception:` in the same
    file is a second line to answer for."""
    flat = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha1(f"{kind}|{file}|{flat}{'' if nth == 1 else f'|{nth}'}".encode("utf-8")).hexdigest()[:10]


def scan(cfg: dict, repo: Path, files: list[str]) -> dict[str, dict]:
    """The flagged lines among what `files` add over HEAD, by their identity."""
    found: dict[str, dict] = {}
    table = detectors(cfg)
    off = set(cfg["review"]["disable"]) | (set() if cfg["review"]["detectors"] else {"numeric-literal", "test-without-assert"})
    ignore = {float(n) for n in cfg["review"]["ignore_numbers"]}
    for file, lines in gitutil.added_lines(repo, files).items():
        is_test = testing.is_test(file, cfg)
        seen_numbers: set[str] = set()
        times: dict[tuple[str, str], int] = {}

        def key(kind: str, text: str) -> str:
            flat = re.sub(r"\s+", " ", text).strip()
            times[kind, flat] = times.get((kind, flat), 0) + 1
            return _key(kind, file, text, times[kind, flat])

        for n, raw in lines:
            text = raw.strip()
            if not text:
                continue
            comment = text.startswith(_COMMENT)
            flagged = False
            for kind, where, rx, why in table:
                if (where == "code" and is_test) or (where == "tests" and not is_test):
                    continue
                if comment and kind not in ("todo", "silenced-check"):
                    continue
                if rx.search(text):
                    flagged = True
                    found[key(kind, text)] = {"kind": kind, "file": file, "line": n, "text": text[:TEXT_MAX], "why": why}
            # numbers: one finding for a line, and only when no other detector already asks about that line
            if "numeric-literal" not in off and not is_test and not comment and not flagged:
                new = []
                for m in _NUMBER.finditer(_STRINGS.sub('""', text)):
                    lit = m.group(0).replace("_", "")
                    if float(lit) not in ignore and lit not in seen_numbers:
                        seen_numbers.add(lit)
                        new.append(lit)
                if new:
                    found[key("numeric-literal", text)] = {
                        "kind": "numeric-literal", "file": file, "line": n, "text": text[:TEXT_MAX],
                        "why": f"the number{'s' if len(new) > 1 else ''} {', '.join(new)}: {'values' if len(new) > 1 else 'a value'} someone chose"}
        if is_test and file.endswith(".py") and "test-without-assert" not in off:
            for f in _tests_without_assert(repo / file, {n for n, _ in lines}):
                found.setdefault(_key("test-without-assert", file, f["text"]), {**f, "file": file})
    return found


def _tests_without_assert(path: Path, added: set[int]) -> list[dict]:
    """Python test functions touched by the change that assert nothing."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test"):
            continue
        if not added & set(range(node.lineno, (node.end_lineno or node.lineno) + 1)):
            continue
        checks = False
        for sub in ast.walk(node):
            name = sub.func.attr if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) else (
                sub.func.id if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) else "")
            if isinstance(sub, ast.Assert) or re.search(r"assert|raises|expect|fail", name, re.I):
                checks = True
                break
        if not checks:
            out.append({"kind": "test-without-assert", "line": node.lineno, "text": f"def {node.name}(…)",
                        "why": "a test that asserts nothing cannot fail"})
    return out


# ------------------------------------------------------------------------------------------------- one review
def _reviews(ctx) -> list[dict]:
    folder = ctx.session.dir / "reviews"
    out = []
    for f in sorted(folder.glob("R*.json"), key=lambda p: int(p.stem[1:])) if folder.is_dir() else []:
        out.append(json.loads(f.read_text(encoding="utf-8")))
    return out


def _save(ctx, r: dict) -> None:
    sysutil.atomic_write(ctx.session.dir / "reviews" / f"{r['id']}.json", json.dumps(r, ensure_ascii=False, indent=1))
    sysutil.atomic_write(ctx.session.dir / "reviews" / f"{r['id']}.md", render(ctx, r))


def files_for(ctx, repo: Path, taking: list[str] | None = None) -> list[str]:
    """What a review of `repo` covers: this session's edited files that differ from HEAD, plus the files being
    committed that no other running session edited; minus what the settings skip."""
    changed = gitutil.changed_vs_head(repo)
    mine = {gitutil.norm(p) for p in ctx.session.edited()}
    names = [rel for rel in changed if gitutil.norm(repo / rel) in mine]
    if taking:
        from .board import others

        foreign = {gitutil.norm(p) for s in others(ctx) for p in s.edited()}
        names += [rel for rel in taking if rel in changed and rel not in names and gitutil.norm(repo / rel) not in foreign]
    return [n for n in names if not core.match_any(n, ctx.cfg["review"]["skip"])]


def _questions(ctx) -> list[str]:
    text = ctx.text("review/questions.md")
    return [m.group(1).strip() for m in re.finditer(r"^\d+\.\s+(.*)$", text, re.M)]


def _open(r: dict) -> tuple[list[dict], list[int]]:
    lines = [f for f in r["findings"].values() if not f.get("disp")]
    questions = [i for i in range(1, r["nq"] + 1) if not (r["answers"].get(str(i)) or "").strip()] if r["depth"] == "full" else []
    return lines, questions


def prepare(ctx, repo: Path, files: list[str]) -> dict | None:
    """The review that covers this change now: the open one brought up to date, or a new one. None when there is
    nothing to review, or when the last passed review already covers every flagged line and file.

    What was settled carries over only inside one change: the same task, and `HEAD` where it was when the last review
    passed (so its commit did not land). Then only what is new is asked. Once the commit has landed, or the task is
    another, the next commit is a new change: its flagged lines are new decisions and its questions are asked again.
    """
    task = ctx.session.current_task() or (list(ctx.session.tasks().values()) or [None])[-1]
    tid = task["id"] if task else None
    depth = "lines" if task and task["size"] in ("trivial",) else "full"
    found = scan(ctx.cfg, repo, files)
    past = _reviews(ctx)
    last = past[-1] if past else None
    head = gitutil.head(repo)
    if not files or (depth == "lines" and not found):
        return None
    same_change = bool(last) and last["passed"] and last.get("task") == tid and last.get("head") == head
    if same_change and set(found) <= set(last["findings"]) and set(files) <= set(last["files"]):
        return None
    if last and not last["passed"]:
        r = last
    else:
        r = {"id": f"R{len(past) + 1}", "repo": str(repo), "task": tid, "depth": depth, "findings": {},
             "answers": {}, "nq": len(_questions(ctx)), "passed": False, "t": sysutil.now()}
        if last and tid is not None and last.get("task") == tid:   # the same task: its answers stand (work outside a
            # task is never "the same task": two commits without one are two unrelated changes); the last question is asked of
            r["answers"] = {k: v for k, v in last["answers"].items() if same_change or int(k) < r["nq"]}     # every change
    settled = last["findings"] if same_change else {}
    r["files"], r["depth"], r["head"] = files, depth, head
    r["nq"] = len(_questions(ctx))                    # the questions as they are now: an open review follows them
    for k, f in r["findings"].items():
        if k not in found and not f.get("disp"):
            f.update(disp="gone", reason="the line is no longer in the change")
        elif k in found and f.get("disp") == "gone":
            f.update(disp=None, reason="", line=found[k]["line"])          # it is back in the change: open again
    for k, f in found.items():
        if k not in r["findings"]:
            prior = settled.get(k, {})
            carried = prior.get("disp") in ("kept", "fixed")
            r["findings"][k] = {**f, "n": len(r["findings"]) + 1, "disp": prior["disp"] if carried else None,
                                "reason": prior.get("reason", "") if carried else ""}
    _save(ctx, r)
    return r


def _facts(ctx) -> str:
    edits = [e for e in ctx.session.all("edit") if not testing.is_test(ctx.rel(e["path"]) or e["path"], ctx.cfg)]
    run = ctx.session.last("test_run")
    if run is None:
        return "Tests: no test command was seen in this session."
    when = sysutil.clock(run["t"])
    if edits and edits[-1]["t"] > run["t"]:
        return f"Tests: `{run['command'][:80]}` last ran at {when}, before your last edit to the code ({sysutil.clock(edits[-1]['t'])})."
    return f"Tests: `{run['command'][:80]}` ran at {when}, after your last edit to the code."


def render(ctx, r: dict) -> str:
    lines, questions = _open(r)
    task = ctx.session.tasks().get(r["task"]) if r["task"] else None
    status = "complete" if not lines and not questions else ", ".join(
        s for s in (f"{len(lines)} flagged line(s) open" if lines else "", f"{len(questions)} question(s) open" if questions else "") if s)
    shown = []
    for f in sorted(r["findings"].values(), key=lambda f: f["n"]):
        if f.get("disp") == "gone":
            continue
        mark = "open" if not f.get("disp") else f["disp"] + (f": {f['reason']}" if f.get("reason") else "")
        shown.append(f"  F{f['n']} [{mark}] {f['kind']}  {f['file']}:{f['line']}  `{f['text']}`\n      {f['why']}")
    if r["depth"] == "full":
        qs = ["Questions:"] + [f"  {i}. {q}\n      [{'answered' if (r['answers'].get(str(i)) or '').strip() else 'open'}]"
                               + (f" {r['answers'][str(i)]}" if (r["answers"].get(str(i)) or "").strip() else "")
                               for i, q in enumerate(_questions(ctx), 1)]
    else:
        qs = ["Questions: none for a trivial task."]
    return ctx.text("moments/review.md", id=r["id"], task=f" of {task['id']} ({task['title']})" if task else "",
                    status=status, files="\n".join(f"  {f}" for f in r["files"]) or "  (none)", facts=_facts(ctx),
                    findings="\n".join(shown) or "  none", questions="\n".join(qs))


def _pass(ctx, r: dict) -> None:
    r["passed"] = True
    _save(ctx, r)
    ledger = ctx.root / ".sentinel" / "assumptions.md"
    if not ledger.is_file():
        sysutil.atomic_write(ledger, "# Assumptions kept\n\nEvery flagged line that was kept at a review, with the reason given. Newest last.\n\n")
    have = ledger.read_text(encoding="utf-8")
    for k, f in r["findings"].items():
        if f.get("disp") == "kept" and f"<!-- {k} -->" not in have:
            sysutil.append_line(ledger, f"- **{f['file']}:{f['line']}** `{f['text']}`: {f['reason']} _({f['kind']}, {r['task'] or 'no task'}, "
                                        f"{sysutil.day(sysutil.now())}, session {ctx.sid[:8]})_ <!-- {k} -->")
    choices = (r["answers"].get(str(r["nq"])) or "").strip() if r["depth"] == "full" else ""
    if choices and f"<!-- {r['id']} {ctx.sid[:8]} -->" not in have:      # the choices the agent named itself
        sysutil.append_line(ledger, f"- **{r['task'] or 'no task'}, {', '.join(r['files'][:6])}{' …' if len(r['files']) > 6 else ''}**: "
                                    f"{choices} _({sysutil.day(sysutil.now())}, session {ctx.sid[:8]})_ <!-- {r['id']} {ctx.sid[:8]} -->")
    ctx.session.log("review_pass", id=r["id"])


# ------------------------------------------------------------------------------------------------- the gate
def on_pre_tool_use(ctx, out) -> None:
    cmd = ctx.command()
    info = gitutil.commit_command(cmd, ctx.cwd) if cmd else None
    if info is None or info["repo"] is None:
        return
    repo = info["repo"]
    r = prepare(ctx, repo, files_for(ctx, repo, gitutil.taking(repo, info)))
    if r is None:
        return
    lines, questions = _open(r)
    if not lines and not questions:
        _pass(ctx, r)
        return
    ctx.moment("review")
    out.deny("This commit is held for review.\n\n" + render(ctx, r))


# ------------------------------------------------------------------------------------------------- commands
def _current(ctx) -> dict | None:
    past = _reviews(ctx)
    return past[-1] if past and not past[-1]["passed"] else None


def review(args, ctx) -> tuple[int, str]:
    repo = gitutil.toplevel(ctx.cwd) or gitutil.toplevel(ctx.root)
    if repo is None:
        return 1, "This is not inside a git repository."
    r = prepare(ctx, repo, files_for(ctx, repo, gitutil.staged(repo)))
    if r is None:
        return 0, "Nothing to review: no file of this session that the review covers differs from HEAD, or the last review already covers it."
    return 0, render(ctx, r)


def set_(args, ctx) -> tuple[int, str]:
    r = _current(ctx)
    if r is None:
        return 1, "No review is open. `sentinel review` opens one."
    m = re.fullmatch(r"[Ff]?(\d+)", args.finding)
    f = next((f for f in r["findings"].values() if m and f["n"] == int(m.group(1))), None)
    if f is None:
        return 1, f"No flagged line {args.finding} in {r['id']}."
    reason = re.sub(r"\s+", " ", args.reason or "").strip()
    if args.disposition == "kept" and not reason:
        return 1, "A kept line needs its reason: sentinel review set F<n> kept \"<why this value or this fallback is right>\"."
    f.update(disp=args.disposition, reason=reason)
    _save(ctx, r)
    lines, questions = _open(r)
    return 0, f"F{f['n']} is {args.disposition}. Open now: {len(lines)} flagged line(s), {len(questions)} question(s)." + (
        " Nothing is open: tell the person what you kept and why, then commit." if not lines and not questions else "")


def answer(args, ctx) -> tuple[int, str]:
    r = _current(ctx)
    if r is None:
        return 1, "No review is open. `sentinel review` opens one."
    if r["depth"] != "full":
        return 1, f"{r['id']} has no questions (a trivial task)."
    if not 1 <= args.n <= r["nq"]:
        return 1, f"{r['id']} has questions 1 to {r['nq']}."
    text = (args.text or "").strip()
    if not text:
        return 1, "Give the answer."
    r["answers"][str(args.n)] = text
    _save(ctx, r)
    lines, questions = _open(r)
    return 0, f"Question {args.n} is answered. Open now: {len(lines)} flagged line(s), {len(questions)} question(s)." + (
        " Nothing is open: tell the person what you kept and why, then commit." if not lines and not questions else "")


def status(args, ctx) -> tuple[int, str]:
    r = _current(ctx)
    return (0, render(ctx, r)) if r else (0, "No review is open.")


def catalogue(args, ctx) -> tuple[int, str]:
    return 0, ctx.text("catalogue/dev.md") + "\n\n" + ctx.text("catalogue/code.md")


def cli(sub) -> None:
    p = sub.add_parser("review", help="the review before a commit: flagged lines and questions")
    p.set_defaults(fn=review)
    rs = p.add_subparsers(dest="review_cmd")
    s = rs.add_parser("set", help="say what was done about a flagged line")
    s.add_argument("finding")
    s.add_argument("disposition", choices=("fixed", "kept"))
    s.add_argument("reason", nargs="?", default="")
    s.set_defaults(fn=set_)
    a = rs.add_parser("answer", help="answer a review question")
    a.add_argument("n", type=int)
    a.add_argument("text")
    a.set_defaults(fn=answer)
    st = rs.add_parser("status", help="the open review")
    st.set_defaults(fn=status)
    c = sub.add_parser("catalogue", help="the fragile patterns: in how work is done, and in code")
    c.set_defaults(fn=catalogue, needs_session=False)
