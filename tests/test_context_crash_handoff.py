"""The context's life (park, the summary's instructions, recovery after a compaction), the cleaned history, the crash
report and the hand-off brief."""
from __future__ import annotations

import json

from conftest import transcript

from sentinel import transcript as tr

A, B = "aaaaaaaa-1111", "bbbbbbbb-2222"


def ctx_of(answer) -> str:
    return answer.get("hookSpecificOutput", {}).get("additionalContext", "") if isinstance(answer, dict) else ""


# ------------------------------------------------------------------------------------------------- transcript
def test_the_context_size_is_read_from_the_last_assistant_entry_and_unknown_after_a_compaction(tmp_path):
    t = transcript(tmp_path / "t.jsonl", [{"user": "a"}, {"assistant": "b", "tokens": 1200}, {"user": "c"}, {"assistant": "d", "tokens": 5000}])
    assert tr.context_tokens(t) == 5010
    t = transcript(tmp_path / "t.jsonl", [{"user": "a"}, {"assistant": "b", "tokens": 900_000}, {"compact": True}])
    assert tr.context_tokens(t) is None
    assert tr.context_tokens(tmp_path / "missing.jsonl") is None


def test_the_history_is_the_stretch_that_was_just_compacted_without_tool_outputs(tmp_path):
    turns = [{"user": "old question"}, {"assistant": "old answer", "tokens": 10}, {"compact": True}]
    turns += [{"user": f"<system-reminder>noise</system-reminder>question {i}"} if i % 2 == 0 else
              {"assistant": f"answer {i}", "tokens": 100, "tool": ("Bash", {"command": "ls -la " + "x" * 400})} for i in range(8)]
    turns += [{"compact": True}]
    t = transcript(tmp_path / "t.jsonl", turns)
    out = tmp_path / "history.md"
    info = tr.history(t, out, 0.25)
    text = out.read_text(encoding="utf-8")
    assert info["entries"] == 8 and info["compactions"] == 2
    assert "old question" not in text and "summary of what came before" not in text
    assert "question 0" in text and "answer 7" in text and "noise" not in text
    assert "→ Bash" in text and "x" * 400 not in text and "…" in text       # the call is kept short, its output is not there
    lines = text.splitlines()
    assert lines[info["recent_line"] - 1] == "### PERSON" and "question 6" in lines[info["recent_line"]]


def test_a_very_long_message_is_cut_with_a_visible_mark(tmp_path):
    t = transcript(tmp_path / "t.jsonl", [{"user": "start " + "y" * 9000}, {"assistant": "ok", "tokens": 1}])
    out = tmp_path / "h.md"
    tr.history(t, out, 0.25)
    assert "more characters cut here" in out.read_text(encoding="utf-8")


# ------------------------------------------------------------------------------------------------- park, compact, restore
def test_the_park_message_comes_once_when_the_context_passes_the_threshold(w, tmp_path):
    w.activate("[context]\npark_at_tokens = 150000\n[rules]\nremind_every_tokens = 0\n")
    w.start()
    small = transcript(tmp_path / "s.jsonl", [{"user": "a"}, {"assistant": "b", "tokens": 100_000}])
    assert w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=str(small)) == ""
    big = transcript(tmp_path / "b.jsonl", [{"user": "a"}, {"assistant": "b", "tokens": 160_000}])
    text = ctx_of(w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=str(big)))
    assert "Your context is nearly full (160,010 tokens)" in text and "notes.md" in text and "sentinel learn" in text
    notes = w.session_dir() / "notes.md"
    assert notes.is_file() and "## Exactly what comes next" in notes.read_text(encoding="utf-8")
    assert w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=str(big)) == ""       # once per fill
    assert w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=str(big), agent_id="x") == ""


def test_before_a_compaction_the_summary_gets_its_instructions(w):
    w.start()
    text = w.hook("PreCompact", trigger="manual", custom_instructions=None)
    assert isinstance(text, str) and "Keep the person's standing instructions" in text and not text.startswith("{")


def test_after_a_compaction_the_agent_is_given_its_history_notes_tasks_and_the_rules(w, tmp_path):
    w.activate("[context]\npark_at_tokens = 150000\n")
    w.start()
    w.approved_task(title="ship it")
    w.cli("progress", "half way")
    turns = [{"user": f"question {i}"} if i % 2 == 0 else {"assistant": f"answer {i}", "tokens": 160_000} for i in range(12)]
    t = transcript(tmp_path / "t.jsonl", turns)
    w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=str(t))                       # parked
    w.hook("PreCompact", trigger="auto", transcript_path=str(t))
    # Claude Code now appends the boundary and the summary, and starts the session again
    with t.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "system", "subtype": "compact_boundary", "uuid": "b1", "parentUuid": None, "logicalParentUuid": "x"}) + "\n")
        f.write(json.dumps({"type": "user", "uuid": "s1", "parentUuid": "b1", "isCompactSummary": True, "message": {"role": "user", "content": "summary"}}) + "\n")
    text = ctx_of(w.start(source="compact", transcript_path=str(t)))
    assert "Your context was compacted" in text and "history-1.md" in text and "12 entries" in text
    assert "notes.md" in text and "tasks.md" in text and "progress.md" in text and "Standing rules" in text
    hist = (w.session_dir() / "history-1.md").read_text(encoding="utf-8")
    assert "question 0" in hist and "answer 11" in hist and "summary" not in hist.split("\n", 3)[3]
    # the next fill of the context parks again
    big = transcript(tmp_path / "b2.jsonl", [{"user": "a"}, {"assistant": "b", "tokens": 170_000}])
    assert "nearly full" in ctx_of(w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=str(big)))


def test_the_restore_still_speaks_when_the_transcript_cannot_be_read(w):
    w.start()
    text = ctx_of(w.start(source="compact", transcript_path=str(w.tmp / "gone.jsonl")))
    assert "Your context was compacted" in text and "could not be written" in text


def test_park_on_demand(w):
    w.start()
    code, out = w.cli("park")
    assert code == 0 and "Your context is nearly full and will be compacted soon" in out and "notes.md" in out


# ------------------------------------------------------------------------------------------------- crash
def test_a_session_cut_by_a_restart_is_told_once_when_it_is_resumed(w):
    w.start(A)
    w.cli("task", "open", "deploy", "--size", "trivial", sid=A)
    w.cli("progress", "images shipped", sid=A)
    w.post("Bash", A, command="python suite.py", run_in_background=True, description="release suite")
    w.hook("Stop", A, background_tasks=[{"description": "docker build"}])
    w.post("Bash", A, command="sleep 9", run_in_background=True, description="waiting for the server")
    w.tick(600)
    w.mp.setenv("SENTINEL_BOOT_TIME", str(w.clock))                            # the machine restarts here
    w.tick(300)
    text = ctx_of(w.start(A, source="resume"))
    assert "This session was cut when the machine restarted" in text
    assert "T1 deploy" in text and "docker build" in text and "waiting for the server" in text and "images shipped" in text
    assert "release suite" not in text                                         # it had ended before the last turn end
    assert "cut when the machine restarted" not in ctx_of(w.start(A, source="resume"))      # once


def test_a_session_that_ended_cleanly_or_started_after_the_boot_is_not_reported(w):
    w.start(A)
    w.hook("SessionEnd", A, reason="prompt_input_exit")
    w.tick(600)
    w.mp.setenv("SENTINEL_BOOT_TIME", str(w.clock))
    w.tick(300)
    assert "cut" not in ctx_of(w.start(A, source="resume"))
    assert "cut" not in ctx_of(w.start(B))


def test_a_new_session_is_told_once_about_other_sessions_that_were_cut(w):
    w.start(A)
    w.cli("task", "open", "migrate the data", "--size", "trivial", sid=A)
    w.tick(600)
    w.mp.setenv("SENTINEL_BOOT_TIME", str(w.clock))
    w.tick(300)
    text = ctx_of(w.start(B))
    assert "Other sessions in this repository were cut" in text and "aaaaaaaa" in text and "migrate the data" in text
    assert "This session was cut" not in text
    assert "Other sessions" not in ctx_of(w.start("cccccccc-3333"))            # told once
    assert "This session was cut" not in ctx_of(w.start(A, source="resume"))  # and A was announced: it has its files


# ------------------------------------------------------------------------------------------------- hand-off
def test_the_handoff_brief_holds_the_facts_and_asks_for_the_narrative(w, tmp_path):
    t = transcript(tmp_path / "t.jsonl", [{"user": "build the exporter"}, {"assistant": "on it", "tokens": 50}])
    w.start(A, transcript_path=str(t))
    w.approved_task(A, title="exporter")
    w.edit("src/export.py", "def export():\n    return []\n", sid=A)
    w.git("add", "-A")
    w.git("commit", "-q", "-m", "add the exporter")
    w.cli("progress", "exporter written", sid=A)
    w.cli("claim", "port:9000", "dev server", sid=A)
    code, out = w.cli("handoff", "--for", "the Mac session", sid=A)
    assert code == 0 and "write the three open parts" in out
    brief = next((w.repo / ".sentinel" / "handoff").glob("*.md")).read_text(encoding="utf-8")
    for part in ("## What happened", "## What to read, in order", "## Half done or waiting", "Written for: the Mac session",
                 "T1 exporter", "exporter written", "add the exporter", "src/export.py", "port:9000: dev server", "history-handoff.md"):
        assert part in brief, part
    assert "build the exporter" in (w.session_dir(A) / "history-handoff.md").read_text(encoding="utf-8")


def test_status_counts_what_sentinel_did(w):
    w.start()
    w.edit("a.py")
    w.bash("rm -rf x")
    code, out = w.cli("status")
    assert code == 0 and "no-task ×1" in out and "gate ×1" in out
