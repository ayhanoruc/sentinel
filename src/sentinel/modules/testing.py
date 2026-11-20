"""Tests: the doctrine given when the agent starts on a test file, and the record of test runs the review reads."""
from __future__ import annotations

import re

from .. import core

SECTION = "testing"


def is_test(rel: str, cfg: dict) -> bool:
    return core.match_any(rel, cfg["testing"]["test_globs"])


def on_pre_tool_use(ctx, out) -> None:
    if ctx.tool not in core.EDIT_TOOLS or out.denies:      # an edit that is being held does not happen: say it later
        return
    path = ctx.tin.get("file_path") or ctx.tin.get("notebook_path")
    rel = ctx.rel(path) if path else None
    if rel is None or not is_test(rel, ctx.cfg):
        return
    task = ctx.session.current_task()
    tid = task["id"] if task else "-"
    if any(e.get("task") == tid for e in ctx.session.all("tests_moment")):
        return                                             # once per task
    ctx.session.log("tests_moment", task=tid)
    ctx.moment("tests")
    out.context(ctx.text("moments/tests.md"))


def on_post_tool_use(ctx, out) -> None:
    cmd = ctx.command()
    if cmd and any(re.search(p, cmd) for p in ctx.cfg["testing"]["commands"]):
        ctx.session.log("test_run", command=cmd[:200])
