"""Automatic compaction: `sentinel init` sets Claude Code's trigger; an automatic compaction is held back until the
agent's notes are written, and is let go by exact facts (the notes, the room, a request that failed)."""
from __future__ import annotations

import json
import uuid

from conftest import transcript

from sentinel import install
from sentinel import transcript as tr

PCT = "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"


def ctx_of(answer) -> str:
    return answer.get("hookSpecificOutput", {}).get("additionalContext", "") if isinstance(answer, dict) else ""


def at(tmp_path, tokens: int, error: bool = False):
    """A transcript whose last real reply was given `tokens` of context; `error`: an API error entry follows it."""
    t = transcript(tmp_path / f"{uuid.uuid4().hex}.jsonl", [{"user": "a"}, {"assistant": "b", "tokens": tokens - 10}])
    if error:
        with t.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "uuid": "err", "parentUuid": None, "isSidechain": False, "isApiErrorMessage": True,
                                "error": "invalid_request", "message": {"model": "<synthetic>", "role": "assistant",
                                                                        "usage": {"input_tokens": 0, "cache_read_input_tokens": 0}}}) + "\n")
    return str(t)


def held(answer) -> bool:
    return isinstance(answer, dict) and answer.get("decision") == "block"


def kinds(w) -> list[str]:
    path = w.session_dir() / "events.jsonl"
    return [json.loads(line)["e"] for line in path.read_text(encoding="utf-8").splitlines()]


def events(w, kind: str) -> list[dict]:
    path = w.session_dir() / "events.jsonl"
    return [e for e in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if e["e"] == kind]


def init(world, local: bool = False):
    class A:
        dir, hook_command = str(world.repo), "sentinel-hook"
    A.local = local
    return install.init(A)


# ------------------------------------------------------------------------------------------------- the trigger
def test_init_writes_the_percent_into_claude_codes_settings_and_uninstall_takes_out_only_its_own(bare):
    settings = bare.repo / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"env": {"FOO": "1"}}))
    code, out = init(bare)
    assert code == 0 and f"set {PCT}=80" in out
    assert json.loads(settings.read_text())["env"] == {"FOO": "1", PCT: "80"}
    cfg = bare.repo / ".sentinel" / "config.toml"
    cfg.write_text("[context]\ncompact_at_percent = 72.5\n", encoding="utf-8")
    init(bare)
    assert json.loads(settings.read_text())["env"][PCT] == "72.5"          # changed in the settings, written again by init
    code, out = bare.cli("uninstall", sid=None)
    assert code == 0 and f"took {PCT}=72.5 out" in out
    assert json.loads(settings.read_text()) == {"env": {"FOO": "1"}}


def test_uninstall_leaves_a_percent_the_person_set_themselves(bare):
    init(bare)
    settings = bare.repo / ".claude" / "settings.json"
    s = json.loads(settings.read_text())
    s["env"][PCT] = "55"
    settings.write_text(json.dumps(s))
    bare.cli("uninstall", sid=None)
    assert json.loads(settings.read_text())["env"] == {PCT: "55"}


def test_init_leaves_claude_codes_trigger_alone_when_the_percent_is_zero_or_the_flow_is_off(bare):
    (bare.repo / ".sentinel").mkdir()
    cfg = bare.repo / ".sentinel" / "config.toml"
    for text in ("[context]\ncompact_at_percent = 0\n", "[context]\nenabled = false\n"):
        cfg.write_text(text, encoding="utf-8")
        code, out = init(bare)
        assert code == 0 and PCT not in out
        assert "env" not in json.loads((bare.repo / ".claude" / "settings.json").read_text())


def test_doctor_says_when_the_settings_and_the_percent_do_not_agree(w):
    code, out = w.cli("doctor", sid=None)
    assert f"ok    automatic compaction at 80 percent: {PCT}=80" in out
    assert "ok    the compaction waits for the agent's notes until 90 percent" in out
    (w.repo / ".sentinel" / "config.toml").write_text("[context]\ncompact_at_percent = 70\nhold_until_percent = 60\n", encoding="utf-8")
    code, out = w.cli("doctor", sid=None)
    assert f"WARN  compact_at_percent is 70 but" in out and f"has {PCT}=80: run `sentinel init` again" in out
    assert "WARN  hold_until_percent (60) is not above compact_at_percent (70)" in out
    settings = w.repo / ".claude" / "settings.json"
    s = json.loads(settings.read_text())
    del s["env"]
    s["autoCompactEnabled"] = False
    settings.write_text(json.dumps(s))
    code, out = w.cli("doctor", sid=None)
    assert f"{PCT} is in none of Claude Code's settings files" in out
    assert "WARN  automatic compaction is switched off in" in out


# ------------------------------------------------------------------------------------------------- the hold
def test_an_automatic_compaction_is_held_until_the_notes_are_written(w, tmp_path):
    w.mp.setenv(PCT, "80")
    w.start()
    assert held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 700_000)))
    hold = events(w, "compact_hold")[0]
    assert hold["tokens"] == 700_000 and hold["limit"] == 787_500 and "compact" not in kinds(w)
    text = ctx_of(w.hook("PostToolUse", tool_name="Read", tool_input={}))
    assert "holding the compaction back" in text and "(700,000 tokens)" in text and "787,500 tokens" in text
    assert "notes.md" in text and "sentinel park done" in text and "sentinel learn" in text
    assert w.hook("PostToolUse", tool_name="Read", tool_input={}) == ""                       # told once
    assert held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 705_000)))  # the notes are not written yet
    code, out = w.cli("park", "done")
    assert code == 1 and "has not changed since you were asked" in out
    assert held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 708_000)))
    notes = w.session_dir() / "notes.md"
    notes.write_text(notes.read_text(encoding="utf-8") + "\nNext: run the suite.\n", encoding="utf-8")
    code, out = w.cli("park", "done")
    assert code == 0 and "The compaction that was held goes ahead at your next step" in out
    t = at(tmp_path, 712_000)
    text = w.hook("PreCompact", trigger="auto", transcript_path=t)
    assert isinstance(text, str) and "Keep the person's standing instructions" in text
    assert events(w, "compact_pass")[0]["why"] == "notes" and events(w, "compact")[0]["end_offset"] > 0
    assert len(events(w, "compact_wait")) == 2
    # the compaction failed on Claude Code's side and is tried again: it is not held a second time in this fill
    assert isinstance(w.hook("PreCompact", trigger="auto", transcript_path=t), str)
    code, out = w.cli("status")
    assert "Automatic compactions held for the notes: 1   let go on notes: 1" in out


def test_the_hold_ends_by_itself_when_the_context_reaches_its_limit(w, tmp_path):
    w.mp.setenv(PCT, "80")
    w.start()
    assert held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 160_000)))    # the limit: 180,000
    assert held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 179_999)))
    assert isinstance(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 180_000)), str)
    assert events(w, "compact_pass")[0] | {"t": 0} == {"t": 0, "e": "compact_pass", "why": "room", "tokens": 180_000}


def test_the_hold_ends_when_a_request_did_not_get_through(w, tmp_path):
    """At the window's very end Claude Code cannot send the request: nothing may hold a compaction then."""
    w.mp.setenv(PCT, "80")
    w.start()
    assert not held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 700_000, error=True)))   # no hold begins on a failed request
    assert "compact_hold" not in kinds(w)
    assert held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 700_000)))
    assert not held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 700_000, error=True)))
    assert events(w, "compact_pass")[0]["why"] == "a request failed"


def test_the_hold_ends_when_the_size_cannot_be_read(w, tmp_path):
    w.mp.setenv(PCT, "80")
    w.start()
    assert not held(w.hook("PreCompact", trigger="auto", transcript_path=str(tmp_path / "gone.jsonl")))
    assert held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 700_000)))
    assert not held(w.hook("PreCompact", trigger="auto", transcript_path=str(tmp_path / "gone.jsonl")))
    assert events(w, "compact_pass")[0]["why"] == "size unknown"


def test_nothing_is_held_without_the_percent_in_force_or_for_a_manual_or_a_subagents_compaction(w, tmp_path):
    w.start()
    t = at(tmp_path, 700_000)
    assert isinstance(w.hook("PreCompact", trigger="auto", transcript_path=t), str)             # Claude Code runs on its own trigger
    w.mp.setenv(PCT, "80")
    assert "Keep the person's standing instructions" in w.hook("PreCompact", trigger="manual", transcript_path=t)
    before = kinds(w)
    assert w.hook("PreCompact", trigger="auto", transcript_path=t, agent_id="sub-1") == ""
    assert kinds(w) == before                                                                   # not this conversation's compaction
    for off in ("[context]\nhold_until_percent = 0\n", "[context]\nhold_until_percent = 80\n"):
        (w.repo / ".sentinel" / "config.toml").write_text(off, encoding="utf-8")
        assert isinstance(w.hook("PreCompact", trigger="auto", transcript_path=t), str)
    assert "compact_hold" not in kinds(w)
    w.mp.setenv(PCT, "not a number")
    (w.repo / ".sentinel" / "config.toml").write_text("", encoding="utf-8")
    assert isinstance(w.hook("PreCompact", trigger="auto", transcript_path=t), str)


def test_the_persons_next_message_carries_the_hold_message_when_the_turn_had_ended(w, tmp_path):
    w.mp.setenv(PCT, "80")
    w.start()
    assert held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 700_000)))
    assert ctx_of(w.hook("PostToolUse", tool_name="Read", tool_input={}, agent_id="sub-1")) == ""   # not to a subagent
    assert "holding the compaction back" in ctx_of(w.say("carry on"))
    assert "holding the compaction back" not in ctx_of(w.say("and then?"))


def test_after_the_compaction_the_next_fill_is_held_again(w, tmp_path):
    w.mp.setenv(PCT, "80")
    w.start()
    assert held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 700_000)))
    w.hook("PostToolUse", tool_name="Read", tool_input={})
    (w.session_dir() / "notes.md").write_text("Next: the second half.\n", encoding="utf-8")
    assert w.cli("park", "done")[0] == 0
    t = at(tmp_path, 710_000)
    assert not held(w.hook("PreCompact", trigger="auto", transcript_path=t))
    assert "Your context was compacted" in ctx_of(w.start(source="compact", transcript_path=t))
    assert held(w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 702_000)))
    assert len(events(w, "compact_hold")) == 2
    assert "holding the compaction back" in ctx_of(w.hook("PostToolUse", tool_name="Read", tool_input={}))
    assert w.cli("park", "done")[0] == 1                       # these notes are the ones from before the compaction


def test_the_token_reminder_stays_silent_once_a_compaction_is_held(w, tmp_path):
    w.activate("[context]\npark_at_tokens = 150000\n")
    w.mp.setenv(PCT, "80")
    w.start()
    t = at(tmp_path, 160_000)
    assert held(w.hook("PreCompact", trigger="auto", transcript_path=t))
    assert "holding the compaction back" in ctx_of(w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=t))
    assert w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=t) == ""


def test_park_done_without_a_hold_only_records_it(w):
    w.start()
    w.cli("park")
    (w.session_dir() / "notes.md").write_text("Next: nothing.\n", encoding="utf-8")
    code, out = w.cli("park", "done")
    assert code == 0 and out.strip() == "Recorded: the notes are current."


def test_a_correction_learned_for_the_park_is_in_the_hold_message_too(w, tmp_path):
    w.mp.setenv(PCT, "80")
    w.start()
    w.cli("learn", "Name the branch you are on in the notes.", "--where", "park")
    w.hook("PreCompact", trigger="auto", transcript_path=at(tmp_path, 700_000))
    assert "Name the branch you are on in the notes." in ctx_of(w.hook("PostToolUse", tool_name="Read", tool_input={}))


# ------------------------------------------------------------------------------------------------- the size
def test_an_api_error_is_never_the_reply_whose_size_counts(tmp_path):
    from pathlib import Path

    reply = tr.last_reply(Path(at(tmp_path, 500_000, error=True)))
    assert reply["tokens"] == 500_000 and reply["error_after"] is True
    assert tr.context_tokens(Path(at(tmp_path, 500_000, error=True))) == 500_000      # not the error entry's zero
    assert tr.last_reply(Path(at(tmp_path, 500_000)))["error_after"] is False
