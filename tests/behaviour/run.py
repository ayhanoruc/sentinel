"""One turn of a real Claude Code session against a repository where Sentinel is active, and what Sentinel did in it.

    python run.py <repo> "<prompt>" [--resume <session id>] [--model haiku] [--env KEY=VALUE ...] [--extra "<claude flags>"]

Runs `claude -p` (headless) in <repo> with SENTINEL_HOME and SENTINEL_DEBUG_LOG set beside it, prints the session id,
the agent's final text, the cost, and one line for each hook call of this turn: the event, the tool, and Sentinel's
answer. The behavioural record in docs/TESTING.md is made of these outputs.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ap = argparse.ArgumentParser()
ap.add_argument("repo")
ap.add_argument("prompt")
ap.add_argument("--resume")
ap.add_argument("--model", default="haiku")
ap.add_argument("--env", action="append", default=[])
ap.add_argument("--extra", default="")
ap.add_argument("--tools", default="Bash,Edit,Write,Read,Glob,Grep")
a = ap.parse_args()

repo = Path(a.repo).resolve()
debug = repo.parent / f"{repo.name}-debug.jsonl"
before = debug.stat().st_size if debug.is_file() else 0
env = {**os.environ, "SENTINEL_HOME": str(repo.parent / f"{repo.name}-home"), "SENTINEL_DEBUG_LOG": str(debug)}
for kv in a.env:
    k, _, v = kv.partition("=")
    env[k] = v
for k in [k for k in env if k.startswith("CLAUDE") or k == "ANTHROPIC_API_KEY"]:      # not a nested session of the caller's
    env.pop(k)
cmd = ["claude", "-p", a.prompt, "--model", a.model, "--output-format", "json", "--allowedTools", a.tools]
if a.resume:
    cmd += ["--resume", a.resume]
cmd += shlex.split(a.extra)
r = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500)
try:
    out = json.loads(r.stdout)
except json.JSONDecodeError:
    print("claude did not answer in JSON:", r.stdout[-1500:], r.stderr[-1500:])
    sys.exit(1)
print(f"session {out.get('session_id')}  turns {out.get('num_turns')}  cost ${out.get('total_cost_usd', 0):.3f}  "
      f"{out.get('duration_ms', 0) / 1000:.0f} s  error={out.get('is_error')}")
print("--- final text")
print((out.get("result") or "").strip()[:2500])
print("--- hook calls of this turn")
if debug.is_file():
    with debug.open("rb") as f:
        f.seek(before)
        for line in f.read().decode("utf-8", errors="replace").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = d["in"]
            tin = ev.get("tool_input") or {}
            what = tin.get("command") or tin.get("file_path") or ev.get("source") or ev.get("trigger") or ev.get("notification_type") or ""
            ans = d["out"]
            try:
                whole = json.loads(ans) if ans.startswith("{") else {}
            except json.JSONDecodeError:
                whole = {}
            spec = whole.get("hookSpecificOutput", {})
            verdict = spec.get("permissionDecision") or whole.get("decision") or (
                "context" if spec.get("additionalContext") else ("text" if ans else "-"))
            first = (spec.get("permissionDecisionReason") or spec.get("additionalContext") or whole.get("reason") or ans or "").strip().splitlines()
            print(f"{ev.get('hook_event_name', '?'):17} {ev.get('tool_name', ''):11} {str(what)[:70]:70} {verdict:8} {first[0][:90] if first else ''}")
