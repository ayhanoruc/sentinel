"""Activation, the standing rules and their reminder, learning from corrections, the texts' override order, the
plain-command allowance, a private module, and the setup commands."""
from __future__ import annotations

import json

from conftest import transcript


def ctx_of(answer) -> str:
    return answer.get("hookSpecificOutput", {}).get("additionalContext", "") if isinstance(answer, dict) else ""


def test_a_repo_without_the_config_gets_nothing(bare):
    assert bare.start() == ""
    assert bare.pre("Write", file_path=str(bare.repo / "a.py"), content="x") == {}
    assert not (bare.repo / ".sentinel").exists()                 # and nothing is written into it


def test_the_rules_come_at_start_and_again_after_the_context_grew(w, tmp_path):
    text = ctx_of(w.start())
    assert "Standing rules" in text and "sentinel progress" in text and "sentinel learn" in text
    t = transcript(tmp_path / "t.jsonl", [{"user": "hi"}, {"assistant": "ok", "tokens": 100_000}])
    assert w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=str(t)) == ""      # 100k: not yet
    assert w.post("Read") == ""                                   # no transcript: the size is unknown, nothing is said
    t = transcript(tmp_path / "t.jsonl", [{"user": "hi"}, {"assistant": "ok", "tokens": 310_000}])
    again = ctx_of(w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=str(t)))
    assert "A reminder of the standing rules" in again
    once = ctx_of(w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=str(t)))
    assert "reminder" not in once                                 # not again until another 300k


def test_a_flow_that_is_off_drops_its_line_from_the_rules(w):
    w.activate("[progress]\nenabled = false\n[learn]\nenabled = false\n")
    text = ctx_of(w.start())
    assert "Standing rules" in text and "sentinel progress" not in text and "sentinel learn" not in text
    assert "if:progress" not in text


def test_a_subagent_gets_no_reminder(w, tmp_path):
    w.start()
    t = transcript(tmp_path / "t.jsonl", [{"user": "hi"}, {"assistant": "ok", "tokens": 900_000}])
    out = w.hook("PostToolUse", tool_name="Read", tool_input={}, transcript_path=str(t), agent_id="sub1")
    assert out == ""


def test_a_correction_is_recorded_and_becomes_part_of_the_text(w):
    w.start()
    code, out = w.cli("learn", "Never rerun the whole suite when one test failed.", "--incident", "ran 40 minutes twice")
    assert code == 0 and "P1" in out
    code, out = w.cli("learn", "Answer in short bullets.", "--scope", "user", "--where", "core")
    assert code == 0 and "U1" in out
    text = ctx_of(w.start(source="resume"))
    assert "Never rerun the whole suite" in text and "Answer in short bullets" in text
    assert "ran 40 minutes" not in text                           # the incident stays in the file, not in the prompt
    code, out = w.cli("unlearn", "P1")
    assert code == 0
    assert "Never rerun" not in ctx_of(w.start(source="resume"))
    assert w.cli("unlearn", "P9")[0] == 1


def test_a_learned_rule_can_target_another_text(w):
    w.start()
    assert w.cli("learn", "Always name the migration in the contract.", "--where", "contract")[0] == 0
    code, out = w.cli("task", "open", "add a column", "--size", "normal")
    assert "Always name the migration" in out


def test_a_repo_text_overrides_the_users_which_overrides_the_package(w):
    (w.home / "texts" / "rules").mkdir(parents=True)
    (w.home / "texts" / "rules" / "core.md").write_text("USER RULES", encoding="utf-8")
    assert "USER RULES" in ctx_of(w.start())
    w.write(".sentinel/texts/rules/core.md", "REPO RULES")
    assert "REPO RULES" in ctx_of(w.start(source="resume"))


def test_a_plain_sentinel_command_is_allowed_with_its_session_and_a_chained_one_is_not(w):
    w.start()
    a = w.bash('sentinel progress "half way"')
    assert a["permissionDecision"] == "allow"
    assert a["updatedInput"]["command"].startswith("SENTINEL_SESSION=aaaaaaaa-1111 sentinel progress")
    ps = w.pre("PowerShell", command="sentinel board")
    assert ps["updatedInput"]["command"].startswith("$env:SENTINEL_SESSION='aaaaaaaa-1111'; sentinel board")
    quoted = w.bash('sentinel task open "Add shout(name); keep greet & co" --size trivial')
    assert quoted["permissionDecision"] == "allow"                # what a shell does not expand may stand inside quotes
    for chained in ("sentinel board && rm -rf x", "sentinel board; echo hi", "sentinel progress $(cat /etc/passwd)", "echo sentinel",
                    'sentinel progress "$(cat /etc/passwd)"', 'sentinel progress "`id`"', "sentinel progress 'a' | sh"):
        assert w.bash(chained).get("permissionDecision") != "allow", chained


def test_the_session_id_reaches_the_shell_through_the_env_file(w, tmp_path):
    env_file = tmp_path / "env"
    w.mp.setenv("CLAUDE_ENV_FILE", str(env_file))
    w.start()
    assert "SENTINEL_SESSION=aaaaaaaa-1111" in env_file.read_text()


def test_the_cli_finds_the_only_running_session_and_refuses_to_guess_between_two(w):
    w.start("aaaaaaaa-1111")
    assert w.cli("progress", "one", sid=None)[0] == 0             # one running session here: it is that one
    w.start("bbbbbbbb-2222")
    code, out = w.cli("progress", "two", sid=None)
    assert code == 1 and "aaaaaaaa" in out and "bbbbbbbb" in out


def test_a_private_module_is_loaded_and_can_be_switched_off(w):
    (w.home / "modules").mkdir(parents=True)
    (w.home / "modules" / "hello.py").write_text(
        'SECTION = "hello"\n\ndef on_user_prompt_submit(ctx, out):\n    out.context("HELLO FROM A PRIVATE MODULE")\n', encoding="utf-8")
    w.start()
    assert "HELLO" not in ctx_of(w.hook("UserPromptSubmit"))      # its section is not enabled
    w.activate("[hello]\nenabled = true\n")
    assert "HELLO FROM A PRIVATE MODULE" in ctx_of(w.hook("UserPromptSubmit"))


def test_init_keeps_other_hooks_is_idempotent_and_uninstall_takes_only_ours(bare):
    settings = bare.repo / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]},
                                    "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "other-tool"}]}]}}))
    bare.activate()
    bare.activate()
    s = json.loads(settings.read_text())
    assert s["permissions"] == {"allow": ["Bash(ls:*)"]}
    pre = s["hooks"]["PreToolUse"]
    assert len(pre) == 2 and pre[0]["hooks"][0]["command"] == "other-tool"
    assert sum("sentinel-hook" in json.dumps(e) for e in pre) == 1
    assert set(s["hooks"]) == {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop", "Notification", "PreCompact", "SessionEnd"}
    assert (bare.repo / ".claude" / "skills" / "sentinel-park" / "SKILL.md").is_file()
    assert (bare.repo / ".claude" / "agents" / "sentinel-field-note.md").is_file()
    code, out = bare.cli("uninstall", sid=None)
    assert code == 0
    s = json.loads(settings.read_text())
    assert s["hooks"] == {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "other-tool"}]}]}
    assert not (bare.repo / ".claude" / "skills" / "sentinel-park").exists()
    assert (bare.repo / ".sentinel" / "config.toml").is_file()    # the data stays


def test_a_config_that_does_not_parse_is_an_error_not_the_defaults(w):
    (w.repo / ".sentinel" / "config.toml").write_text("[tasks\nenabled = ", encoding="utf-8")
    import tomllib

    import pytest

    with pytest.raises(tomllib.TOMLDecodeError):                  # the hook's main() turns this into a visible hook error
        w.start()
    code, out = w.cli("doctor", sid=None)
    assert code == 1 and "do not load" in out
