"""The settings: defaults, then the user's `~/.sentinel/config.toml`, then the repo's `.sentinel/config.toml`.

Every number here is a named setting with its reason in TEMPLATE, which `sentinel init` writes into a repo.
"""
from __future__ import annotations

import copy
import tomllib
from pathlib import Path

DEFAULTS: dict = {
    "rules": {"enabled": True, "remind_every_tokens": 300_000},
    "learn": {"enabled": True},
    "tasks": {
        "enabled": True,
        "gate": True,
        "standing": True,
        "exempt": [],
        "world_model": True,
        "field_note": True,
        "proof": True,
        "sections": {
            "normal": ["understanding", "scope", "options", "assumptions", "questions", "world-model", "proof"],
            "large": ["understanding", "scope", "options", "assumptions", "questions", "world-model", "impact",
                      "way-back", "proof"],
        },
    },
    "review": {
        "enabled": True,
        "skip": ["*.md", "*.txt", "*.rst", "docs/**", "*.lock", "*.json", "*.yaml", "*.yml", "*.toml", "*.csv",
                 "*.svg", "*.html", "*.css", ".sentinel/**"],
        "disable": [],
        "patterns": [],
        # numbers that are unit arithmetic or indexing far more often than a choice someone made
        "ignore_numbers": [0, 1, 2, -1, 10, 100, 1000, 1024, 60, 3600, 24],
    },
    "testing": {
        "enabled": True,
        "test_globs": ["test_*.py", "*_test.py", "tests/**", "test/**", "*.test.*", "*.spec.*", "__tests__/**"],
        "commands": [r"\bpytest\b", r"\bnpm\s+(run\s+)?test\b", r"\b(vitest|jest|mocha)\b", r"\bgo\s+test\b",
                     r"\bcargo\s+test\b", r"\bdotnet\s+test\b", r"\b(mvn|gradle\w*)\s+test\b",
                     r"\bpython\s+-m\s+unittest\b"],
    },
    "gate": {"enabled": True, "disable": [], "patterns": []},
    "progress": {"enabled": True, "every_minutes": 20},
    "board": {"enabled": True, "stale_after_hours": 24},
    "context": {"enabled": True, "compact_at_percent": 80, "hold_until_percent": 90, "park_at_tokens": 0,
                "recent_fraction": 0.25},
    "crash": {"enabled": True},
    "handoff": {"enabled": True, "dir": ".sentinel/handoff"},
}

TEMPLATE = """\
# Sentinel settings for this repository. This file's presence is what activates Sentinel here.
# Every flow has `enabled`; values left out take the defaults shown (docs: SPEC.md section 6).

[rules]                         # the short standing rules, given at session start and after a compact
enabled = true
remind_every_tokens = 300000    # given again each time the context has grown this much (the owner's figure)

[learn]                         # corrections from the person are recorded into the texts
enabled = true

[tasks]                         # a task and its contract before the first edit
enabled = true
gate = true                     # an edit waits for an approved task; false keeps the tracking and drops the gate
standing = true                 # the agent may approve on your earlier words telling it not to wait (recorded as such); false: it always waits
exempt = []                     # globs (repo-relative) that never need a task, e.g. ["notes/**"]
world_model = true              # the contract holds expected outcomes; lenses: `sentinel lens`
field_note = true               # the agent may propose a short research note on standards and prior art
proof = true                    # the contract says how the work will be shown to work

[review]                        # flagged lines and questions before a commit; kept lines go to .sentinel/assumptions.md
enabled = true
# skip = ["*.md", "docs/**", ...]   files the review leaves out (default: docs, lock and data files)
disable = []                    # detector names to switch off, e.g. ["numeric-literal"]
# [[review.patterns]]           a detector of your own
# name = "print-debug"
# regex = "\\\\bprint\\\\("
# why = "a debug print left in"

[testing]                       # the test doctrine at the first test edit; test facts in the review
enabled = true

[gate]                          # look at the target and name the way back before an irreversible command
enabled = true
disable = []                    # pattern names to switch off
# [[gate.patterns]]
# name = "prod-deploy"
# regex = "deploy\\\\.sh\\\\s+prod"
# why = "deploys to production"

[progress]                      # progress notes for the person on long work
enabled = true
every_minutes = 20              # long enough not to interrupt short work, short enough that a look-in finds a fresh note

[board]                         # who is doing what on this machine; claims; the shared-checkout commit guard
enabled = true
stale_after_hours = 24          # a session silent this long is not counted as live

[context]                       # automatic compaction that waits for the agent's notes; cleaned history and recovery after it
enabled = true
compact_at_percent = 80         # Claude Code compacts by itself when the context is this full (the owner's figure). `sentinel init` writes it into .claude/settings as CLAUDE_AUTOCOMPACT_PCT_OVERRIDE: run it again after changing this. 0 = leave Claude Code's own trigger
hold_until_percent = 90         # the compaction waits for the agent's notes, at the latest until the context is this full (half of the room left above 80). 0 = do not wait
park_at_tokens = 0              # an extra, earlier reminder to write the notes at this many tokens. 0 = off
recent_fraction = 0.25          # the part of the compacted history the agent is told to read first

[crash]                         # what was cut when the machine restarted
enabled = true

[handoff]                       # a brief for another session or machine
enabled = true
dir = ".sentinel/handoff"
"""


def _merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load(root: Path | None, home: Path) -> dict:
    """The effective settings. A file that does not parse is an error the caller reports: never silently the defaults."""
    cfg = copy.deepcopy(DEFAULTS)
    for path in (home / "config.toml", (root / ".sentinel" / "config.toml") if root else None):
        if path and path.is_file():
            with path.open("rb") as f:
                _merge(cfg, tomllib.load(f))
    return cfg
