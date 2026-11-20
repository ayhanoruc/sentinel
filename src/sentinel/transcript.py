"""A Claude Code session transcript (.jsonl): the context's size now, and the cleaned history of the stretch that was
just compacted: the person's messages, the agent's, its tool calls without their outputs.

The file is not in reading order: it holds branches and copies. The conversation is the chain that ends at the last
entry, followed back through `parentUuid` (`logicalParentUuid` across a compaction). Only each entry's offset is kept
while indexing, never the parsed entries: a transcript can be hundreds of megabytes.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

TAIL_SMALL = 256_000        # bytes read from the end to find the last usage entry; one entry is far smaller
TAIL_LARGE = 4_000_000      # second try, for a turn that ended with very large tool results
PERSON_MAX = 6_000          # characters of one message of the person kept; longer ones are pasted logs, and the cut is marked
AGENT_MAX = 6_000           # the same for one of the agent's texts
TOOL_INPUT_MAX = 300        # characters of a tool call's input kept: enough to see what was run and on what

_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
_NOTIFICATION = re.compile(r"<task-notification>.*?<summary>(.*?)</summary>.*?</task-notification>", re.S)
_COMMAND = re.compile(r"<command-name>(.*?)</command-name>", re.S)


def last_reply(path: Path) -> dict | None:
    """The main conversation's last real reply: `id`, `tokens` (the context it was given: the input side of its
    usage) and `error_after` (an API error entry follows it: a request since then did not get through).

    None right after a compaction, or when the transcript's tail holds no reply: the size is then not known, which
    is different from zero. An API error is written as an assistant entry with zero usage; it is never the reply.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None
    for tail in (TAIL_SMALL, TAIL_LARGE):
        with path.open("rb") as f:
            f.seek(max(0, size - tail))
            lines = f.read().decode("utf-8", errors="replace").splitlines()
        error_after = False
        for line in reversed(lines):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue                          # the first line of a tail is usually cut
            if e.get("type") == "system" and e.get("subtype") == "compact_boundary":
                return None
            if e.get("type") != "assistant" or e.get("isSidechain"):
                continue
            m = e.get("message") or {}
            if e.get("isApiErrorMessage") or m.get("model") == "<synthetic>":
                error_after = True
                continue
            u = m.get("usage") or {}
            if u:
                return {"id": m.get("id") or e.get("uuid"), "error_after": error_after,
                        "tokens": (int(u.get("input_tokens") or 0) + int(u.get("cache_read_input_tokens") or 0)
                                   + int(u.get("cache_creation_input_tokens") or 0))}
        if size <= tail:
            break
    return None


def context_tokens(path: Path) -> int | None:
    """Tokens in the main conversation's context at its last real reply; None when that is not known."""
    reply = last_reply(path)
    return reply["tokens"] if reply else None


def _chain(path: Path, end_offset: int | None) -> list[tuple[int, bool, bool]]:
    """The conversation as (offset, is_boundary, is_summary) from its start to its last entry before `end_offset`.

    The backbone is the last entry's chain of parents. One reply of the model that makes several tool calls at once is
    written as several entries (the same `message.id`), and their results fork: the chain back from the end passes
    through only one of them. So every entry that shares a backbone reply's `message.id` is put back in, after its
    siblings (seen in a real transcript, 21 Nov 2026: a parallel Read was missing from the history).
    """
    index: dict[str, tuple[str | None, int, bool, bool, str | None]] = {}
    replies: dict[str, dict[str, int]] = {}                 # message.id -> {entry uuid: offset}
    last = None
    with path.open("rb") as f:
        off = 0
        for line in f:
            here, off = off, off + len(line)
            if end_offset is not None and here >= end_offset:
                break
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            u = d.get("uuid")
            if not u or d.get("isSidechain"):
                continue
            mid = (d.get("message") or {}).get("id") if d.get("type") == "assistant" else None
            index[u] = (d.get("parentUuid") or d.get("logicalParentUuid"), here,
                        d.get("type") == "system" and d.get("subtype") == "compact_boundary",
                        bool(d.get("isCompactSummary")), mid)
            if mid:
                replies.setdefault(mid, {})[u] = here
            last = u
    back, seen, u = [], set(), last
    while u and u in index and u not in seen:
        seen.add(u)
        back.append(u)
        u = index[u][0]
    back.reverse()
    chain: list[tuple[int, bool, bool]] = []
    for i, u in enumerate(back):
        _, here, boundary, summary, mid = index[u]
        chain.append((here, boundary, summary))
        nxt = index[back[i + 1]][4] if i + 1 < len(back) else None
        if mid and nxt != mid:                              # the reply's last entry on the backbone: add its siblings
            for sib, sib_off in sorted(replies[mid].items(), key=lambda kv: kv[1]):
                if sib not in seen:
                    seen.add(sib)
                    chain.append((sib_off, False, False))
    return chain


def _read(f, offset: int) -> dict:
    f.seek(offset)
    return json.loads(f.readline())


def _person_text(content) -> str:
    parts = [content] if isinstance(content, str) else [c.get("text", "") for c in content or []
                                                         if isinstance(c, dict) and c.get("type") == "text"]
    text = _REMINDER.sub("", "\n".join(parts)).strip()
    text = _NOTIFICATION.sub(lambda m: f"[background task finished: {m.group(1).strip()}]", text)
    if "<command-name>" in text:                  # a slash command the person ran, and its echo
        m = _COMMAND.search(text)
        return f"[ran {m.group(1).strip()}]" if m else ""
    if text.startswith(("<local-command-caveat>", "<local-command-stdout>")):
        return ""
    return text


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[:limit]}\n[… {len(text) - limit} more characters cut here]"


def history(path: Path, out: Path, recent_fraction: float, end_offset: int | None = None) -> dict:
    """Write the cleaned history of the newest stretch of the conversation to `out`.

    The stretch is what lies after the last compaction on the chain. When the chain ends in a compaction that has just
    happened (only its boundary and summary follow), it is the stretch before that compaction. `end_offset` (the
    transcript's size when the compaction began) makes that exact. Returns the counts and `recent_line`: the line of
    `out` where the last `recent_fraction` of the stretch begins.
    """
    chain = _chain(path, end_offset)
    bounds = [i for i, (_, boundary, _) in enumerate(chain) if boundary]
    start, stop = (bounds[-1] + 1 if bounds else 0), len(chain)
    with path.open("rb") as f:
        if bounds and end_offset is None:
            tail = [_read(f, off) for off, _, _ in chain[bounds[-1] + 1:]]
            if all(d.get("isCompactSummary") or d.get("isMeta") or d.get("type") == "system" for d in tail):
                stop = bounds[-1]
                start = bounds[-2] + 1 if len(bounds) > 1 else 0
        blocks: list[str] = []
        for off, boundary, summary in chain[start:stop]:
            if boundary or summary:
                continue
            d = _read(f, off)
            m = d.get("message") or {}
            role = m.get("role") or d.get("type")
            if role == "user":
                text = _person_text(m.get("content"))
                if text:
                    blocks.append("### PERSON\n" + _cut(text, PERSON_MAX))
            elif role == "assistant":
                lines = []
                for c in m.get("content") or []:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "text" and c.get("text", "").strip():
                        lines.append(_cut(c["text"].strip(), AGENT_MAX))
                    elif c.get("type") == "tool_use":
                        arg = json.dumps(c.get("input", {}), ensure_ascii=False)
                        lines.append(f"→ {c.get('name', '?')} {arg[:TOOL_INPUT_MAX]}{'…' if len(arg) > TOOL_INPUT_MAX else ''}")
                if lines:
                    blocks.append("### AGENT\n" + "\n".join(lines))
    first_recent = max(0, len(blocks) - max(1, round(len(blocks) * recent_fraction))) if blocks else 0
    head = ["# Cleaned history of the compacted stretch",
            f"{len(blocks)} entries: the person's messages, the agent's texts and tool calls. Tool outputs are left out.",
            ""]
    body: list[str] = []
    recent_line = len(head) + 1
    for i, b in enumerate(blocks):
        if i == first_recent:
            recent_line = len(head) + len(body) + 1
        body.extend(b.splitlines() + [""])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(head + body), encoding="utf-8", newline="\n")
    return {"entries": len(blocks), "lines": len(head) + len(body), "recent_line": recent_line,
            "compactions": len(bounds)}


def person_messages(path: Path) -> list[tuple[float | None, str]]:
    """What the person wrote since the last compaction, oldest first: (when, as seconds since the epoch, or None when
    the entry carries no time; the text without reminders and command echoes)."""
    from datetime import datetime

    chain = _chain(path, None)
    bounds = [i for i, (_, boundary, _) in enumerate(chain) if boundary]
    out: list[tuple[float | None, str]] = []
    with path.open("rb") as f:
        for off, boundary, summary in chain[(bounds[-1] + 1 if bounds else 0):]:
            if boundary or summary:
                continue
            d = _read(f, off)
            m = d.get("message") or {}
            if (m.get("role") or d.get("type")) != "user":
                continue
            text = _person_text(m.get("content"))
            if not text or text.startswith("[background task finished"):
                continue
            when = None
            stamp = d.get("timestamp")
            if isinstance(stamp, str):
                try:
                    when = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    when = None
            out.append((when, text))
    return out
