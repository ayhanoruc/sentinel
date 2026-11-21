"""Writes docs/overview.svg: one session as a line, with what Sentinel tells the agent on its left and what it holds
on its right. Run it again after a flow is added or renamed:

    python docs/diagram.py

The picture is a file, not a Mermaid block, so that it reads the same on a git host, in an editor and in print. It
carries its own light ground: an image in a README cannot follow the reader's theme.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

W = 960
CENTER = W // 2
CARD_W, CARD_H = 325, 60
LEFT_X, RIGHT_X = 36, W - 36 - CARD_W
PILL_W, PILL_H = 190, 26
ROW_0, ROW_STEP = 190, 74

INK, MUTED, LINE = "#1C2420", "#56615B", "#DDE1DA"
GROUND, CARD = "#F6F7F4", "#FFFFFF"
TOLD, HELD = "#2F7D5C", "#B5561B"          # green: a message at its moment; orange: an action that waits

SANS = "'Segoe UI', system-ui, -apple-system, Helvetica, Arial, sans-serif"
MONO = "ui-monospace, 'Cascadia Mono', Consolas, Menlo, monospace"

# (the moment on the line, told: (name, line, line) or None, held: (name, line, line) or None)
ROWS = [
    ("session starts",
     ("Standing rules", "How to write to the person and how to work.", "Again every 300k tokens and after a compaction."), None),
    ("resumed after a restart",
     ("Crash report", "What was open and what ran in the background", "when the machine went down."), None),
    ("first edit of a task",
     ("World model and lenses", "Expected outcomes as checkable statements;", "lenses for UI, algorithm, data, API, operations."),
     ("Task and contract", "The edit waits until a task is open and the person", "approved its contract in their own words.")),
    ("first edit of a test file",
     ("Tests doctrine", "A test must be able to fail. End to end, printing", "its steps. No test written for its own sake."), None),
    ("an irreversible command", None,
     ("Irreversible-command check", "`rm -rf`, `reset --hard`, force-push, `DROP`: held", "once. Look at the target, name the way back.")),
    ("long work",
     ("Progress notes", "Every 20 minutes of open work: a note the person", "can read without asking."), None),
    ("the person corrects",
     ("Learning", "The correction is recorded into the text it belongs", "to and is part of that message from then on."), None),
    ("two sessions, one checkout",
     ("Session board", "Who is doing what on this machine, what each", "claimed, when HEAD was moved by someone else."),
     ("Shared-checkout guard", "A commit that would take files another running", "session edited is held.")),
    ("git commit", None,
     ("Review and assumption ledger", "Numbers, fallbacks, broad excepts, sleeps need a", "disposition; six questions an answer. Kept: ledger.")),
    ("context 80 % full",
     ("Notes before the compaction", "Write the notes now: where you are, the exact next", "step, open doubts. Then `sentinel park done`."),
     ("Compaction waits for the notes", "The harness compacts by itself at 80 percent; the", "compaction is held until the notes are written.")),
    ("after the compaction",
     ("Restore", "The cleaned history of the compacted stretch, the", "notes, the open tasks and the rules are given back."), None),
    ("hand-off",
     ("Hand-off brief", "Facts filled in from the session's files; the story", "written for a reader with none of the context."), None),
]
FILES = [
    "tasks.md and each task's contract · progress.md · notes.md · history-<n>.md · reviews · events.jsonl",
    "assumptions.md (the ledger) · learned rules · hand-off briefs · the board of every session on the machine",
]


def spans(text: str) -> str:
    """Text with `code` parts set in the monospace face."""
    parts = text.split("`")
    return "".join(escape(p) if i % 2 == 0 else f'<tspan font-family="{MONO}" font-size="11.5">{escape(p)}</tspan>'
                   for i, p in enumerate(parts))


def card(x: int, cy: int, colour: str, name: str, one: str, two: str) -> list[str]:
    top = cy - CARD_H // 2
    return [
        f'<rect x="{x}" y="{top}" width="{CARD_W}" height="{CARD_H}" rx="8" fill="{CARD}" stroke="{LINE}"/>',
        f'<rect x="{x}" y="{top}" width="4" height="{CARD_H}" rx="2" fill="{colour}"/>',
        f'<text x="{x + 16}" y="{top + 22}" font-size="13.5" font-weight="600" fill="{INK}">{escape(name)}</text>',
        f'<text x="{x + 16}" y="{top + 38}" font-size="12" fill="{MUTED}">{spans(one)}</text>',
        f'<text x="{x + 16}" y="{top + 52}" font-size="12" fill="{MUTED}">{spans(two)}</text>',
    ]


def build() -> str:
    last = ROW_0 + ROW_STEP * (len(ROWS) - 1)
    files_top = last + 66
    height = files_top + 98 + 28
    pill_x = CENTER - PILL_W // 2
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" '
        f'font-family="{SANS}" role="img" aria-label="One agent session as a line from its start to its hand-off. '
        'On the left of the line, what Sentinel tells the agent at each moment; on the right, what it holds until an '
        'exact condition is met; below, the files that keep the session\'s state.">',
        "<!-- written by docs/diagram.py: change the rows there, not here -->",
        f'<rect width="{W}" height="{height}" rx="14" fill="{GROUND}" stroke="{LINE}"/>',
        f'<text x="36" y="52" font-size="22" font-weight="700" fill="{INK}">Sentinel around one agent session</text>',
        f'<text x="36" y="78" font-size="12.5" fill="{MUTED}">The line in the middle is one conversation in an agentic '
        'coding harness, from its start to its hand-off.</text>',
        f'<text x="36" y="96" font-size="12.5" fill="{MUTED}">Left of it: what the agent is told at that moment. '
        'Right of it: what waits until an exact condition is met.</text>',
        f'<text x="{LEFT_X + CARD_W // 2}" y="136" font-size="11" font-weight="700" letter-spacing="1.2" text-anchor="middle" '
        f'fill="{TOLD}">TOLD AT ITS MOMENT</text>',
        f'<text x="{CENTER}" y="136" font-size="11" font-weight="700" letter-spacing="1.2" text-anchor="middle" '
        f'fill="{INK}">THE SESSION</text>',
        f'<text x="{RIGHT_X + CARD_W // 2}" y="136" font-size="11" font-weight="700" letter-spacing="1.2" text-anchor="middle" '
        f'fill="{HELD}">HELD UNTIL A CONDITION IS MET</text>',
        f'<line x1="{CENTER}" y1="148" x2="{CENTER}" y2="{last + 34}" stroke="{INK}" stroke-width="3" stroke-linecap="round"/>',
        f'<circle cx="{CENTER}" cy="{last + 34}" r="5" fill="{INK}"/>',
    ]
    for i, (moment, told, held) in enumerate(ROWS):
        cy = ROW_0 + ROW_STEP * i
        if told:
            out.append(f'<line x1="{LEFT_X + CARD_W}" y1="{cy}" x2="{pill_x}" y2="{cy}" stroke="{TOLD}" stroke-width="1.5"/>')
            out += card(LEFT_X, cy, TOLD, *told)
        if held:
            out.append(f'<line x1="{pill_x + PILL_W}" y1="{cy}" x2="{RIGHT_X}" y2="{cy}" stroke="{HELD}" stroke-width="1.5"/>')
            out += card(RIGHT_X, cy, HELD, *held)
        out.append(f'<rect x="{pill_x}" y="{cy - PILL_H // 2}" width="{PILL_W}" height="{PILL_H}" rx="{PILL_H // 2}" fill="{INK}"/>')
        out.append(f'<text x="{CENTER}" y="{cy + 4}" font-size="12" font-weight="600" text-anchor="middle" fill="#FFFFFF">'
                   f'{escape(moment)}</text>')
    out += [
        f'<rect x="36" y="{files_top}" width="{W - 72}" height="98" rx="8" fill="{CARD}" stroke="{LINE}"/>',
        f'<text x="52" y="{files_top + 24}" font-size="11" font-weight="700" letter-spacing="1.2" fill="{INK}">KEPT IN FILES'
        f'<tspan font-weight="400" letter-spacing="0" fill="{MUTED}" dx="8">what survives a compaction, a restart and a hand-off</tspan></text>',
    ]
    for n, line in enumerate(FILES):
        out.append(f'<text x="52" y="{files_top + 45 + 16 * n}" font-size="11" font-family="{MONO}" fill="{INK}">{escape(line)}</text>')
    out.append(f'<text x="52" y="{files_top + 86}" font-size="12" fill="{MUTED}">The agent answers through one command, '
               f'<tspan font-family="{MONO}" font-size="11.5" fill="{INK}">sentinel …</tspan>, and each command\'s output is its next instruction.</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    target = Path(__file__).resolve().parent / "overview.svg"
    target.write_text(build(), encoding="utf-8", newline="\n")
    print(f"wrote {target}")
