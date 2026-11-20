"""The review before a commit with its ledger, how a `git commit` command is read, and the session board's guards."""
from __future__ import annotations

import re

import pytest

from sentinel import gitutil

CODE = '''import os
import time

RETRIES = 7
RETRY_STATUSES = {429, 502, 503}
BATCH = 37


def load(cfg):
    host = cfg.get("host", "localhost")
    port = os.environ.get("PORT", "8080")
    try:
        time.sleep(3)
        return fetch(host, port, timeout=45)[:50]
    except Exception:
        pass  # TODO handle
'''


def denied(answer: dict) -> str:
    return answer.get("permissionDecisionReason", "") if answer.get("permissionDecision") == "deny" else ""


def fill_contract(w, tid="T1"):
    p = w.session_dir() / "tasks" / f"{tid}.md"
    p.write_text(re.sub(r"(<!--.*?-->)", r"\1\nx", p.read_text(encoding="utf-8"), flags=re.S), encoding="utf-8")


def normal_task(w, title="loader"):
    w.cli("task", "open", title, "--size", "normal")
    fill_contract(w, f"T{len(list((w.session_dir() / 'tasks').glob('T*.md')))}")
    w.say("tamam, böyle olsun")
    assert w.cli("task", "approve", "--basis", "tamam")[0] == 0


# ------------------------------------------------------------------------------------------------- the review
def test_a_commit_is_held_until_every_flagged_line_and_question_is_settled(w):
    w.start()
    normal_task(w)
    w.edit("src/loader.py", CODE)
    w.git("add", "-A")
    reason = denied(w.bash('git commit -m "add loader"'))
    assert "held for review" in reason and "R1" in reason and "src/loader.py" in reason
    kinds = set(re.findall(r"F\d+ \[open\] ([\w-]+)", reason))
    assert kinds == {"numeric-literal", "default-fallback", "broad-except", "fixed-sleep", "timeout-retry", "truncation", "todo"}, kinds
    assert "the numbers 429, 502, 503" in reason and "the number 37" in reason       # one finding for a line's numbers
    assert reason.count("numeric-literal") == 2                                      # 7, 45, 3 and 50 belong to other findings
    assert "no test command was seen" in reason and "Questions:" in reason and "6." in reason

    code, out = w.cli("review", "set", "F1", "kept")
    assert code == 1 and "reason" in out                                       # a kept line needs its reason
    flagged = sorted(int(n) for n in re.findall(r"F(\d+) \[open\]", reason))
    for n in flagged:
        assert w.cli("review", "set", f"F{n}", "kept", f"reason for {n}")[0] == 0
    still = denied(w.bash('git commit -m "add loader"'))
    assert "6 question(s) open" in still and "flagged line(s) open" not in still
    for q in range(1, 7):
        assert w.cli("review", "answer", str(q), f"answer {q}")[0] == 0
    assert w.cli("review", "answer", "9", "x")[0] == 1
    assert denied(w.bash('git commit -m "add loader"')) == ""                 # passes

    ledger = (w.repo / ".sentinel" / "assumptions.md").read_text(encoding="utf-8")
    assert ledger.count("\n- **src/loader.py:") == len(flagged) and "reason for 1" in ledger and "T1" in ledger
    assert (w.session_dir() / "reviews" / "R1.md").is_file()
    assert denied(w.bash('git commit -m "add loader"')) == ""                 # a retry of the same commit is not reviewed again


def test_a_change_after_the_review_asks_only_about_what_is_new(w):
    w.start()
    normal_task(w)
    w.edit("src/a.py", "x = cfg.get('a', 'b')\n")
    reason = denied(w.bash("git commit -am wip"))
    assert "F1 [open] default-fallback" in reason
    w.cli("review", "set", "F1", "kept", "the documented default")
    for q in range(1, 7):
        w.cli("review", "answer", str(q), "ok")
    w.edit("src/a.py", "x = cfg.get('a', 'b')\nLIMIT = 500\n")
    w.git("add", "-A")
    again = denied(w.bash("git commit -m wip"))
    assert "F2 [open] numeric-literal" in again and "F1 [kept: the documented default]" in again
    assert "1 flagged line(s) open" in again and "question(s) open" not in again
    w.edit("src/a.py", "x = cfg.get('a', 'b')\n")                             # the new line is taken out again
    assert denied(w.bash("git commit -m wip")) == ""                          # it is gone, nothing is open


def test_a_trivial_task_is_asked_only_about_flagged_lines_and_clean_code_passes(w):
    w.start()
    w.approved_task(size="trivial")
    w.edit("src/clean.py", "def add(a, b):\n    return a + b\n")
    w.git("add", "-A")
    assert denied(w.bash("git commit -m clean")) == ""
    w.edit("src/clean.py", "def add(a, b):\n    return a + b + 37\n")
    reason = denied(w.bash("git commit -am magic"))
    assert "the number 37" in reason and "none for a trivial task" in reason


def test_docs_and_data_are_not_reviewed_and_what_the_session_did_not_touch_is_left_out(w):
    w.start()
    normal_task(w)
    w.edit("docs/guide.md", "wait 5 minutes, retries=3\n")
    w.edit("config.json", '{"timeout": 30}\n')
    w.git("add", "-A")
    assert denied(w.bash("git commit -m docs")) == ""


def test_the_review_states_whether_tests_ran_after_the_last_edit(w):
    w.start()
    normal_task(w)
    w.edit("src/a.py", "LIMIT = 500\n")
    w.post("Bash", command="uv run pytest -q")
    w.tick(60)
    assert "after your last edit" in w.cli("review")[1]
    w.edit("src/a.py", "LIMIT = 600\n")
    assert "before your last edit" in w.cli("review")[1]


def test_test_files_have_their_own_flags(w):
    w.start()
    w.approved_task(size="trivial")
    w.edit("tests/test_app.py", "import datetime\nfrom unittest import mock\n\n\ndef test_nothing():\n    run()\n\n\n"
           "def test_mock(m):\n    m.assert_called_once()\n\n\ndef test_today():\n    assert datetime.datetime.now().year > 2000\n\n\n"
           "@pytest.mark.skip\ndef test_real():\n    assert add(2, 2) == 4\n")
    w.git("add", "-A")
    reason = denied(w.bash("git commit -m tests"))
    kinds = set(re.findall(r"F\d+ \[open\] ([\w-]+)", reason))
    assert kinds == {"test-without-assert", "mock-assertion", "test-depends-on-today", "skipped-test"}, kinds
    assert "def test_nothing" in reason and "numeric-literal" not in reason


def test_a_repo_can_switch_a_detector_off_and_add_one(w):
    w.activate('[review]\ndisable = ["numeric-literal", "todo"]\n[[review.patterns]]\nname = "print-debug"\nregex = "\\\\bprint\\\\("\nwhy = "a debug print"\n')
    w.start()
    w.approved_task(size="trivial")
    w.edit("src/a.py", "LIMIT = 500  # TODO\nprint(LIMIT)\n")
    reason = denied(w.bash("git commit -am x"))
    assert set(re.findall(r"F\d+ \[open\] ([\w-]+)", reason)) == {"print-debug"}
    w.activate("[review]\nenabled = false\n")
    assert denied(w.bash("git commit -am x")) == ""


def test_the_catalogue_has_both_sides(w):
    code, out = w.cli("catalogue", sid=None)
    assert code == 0 and "how the work is done" in out and "in the code" in out


# ------------------------------------------------------------------------------------------------- reading a commit command
@pytest.mark.parametrize("command,all_,limited", [
    ('git commit -m "msg"', False, False),
    ('git commit -am "msg"', True, False),
    ("git commit -a -m msg", True, False),
    ("git commit --all -m msg", True, False),
    ('git commit -m "add a thing"', False, False),            # the message's "a" is not the flag
    ('git commit --amend -m "x"', False, False),
    ('git commit --only -m "x" -- src/a.py', False, True),
    ('git commit -m "x" src/a.py', False, True),
    ('git add -A && git commit -q -m "x; y && z"', False, False),
    ('git -c user.name=x commit -m "x"', False, False),
])
def test_what_a_commit_command_takes(w, command, all_, limited):
    info = gitutil.commit_command(command, w.repo)
    assert info is not None and (info["all"], info["limited"]) == (all_, limited), info
    assert info["repo"].resolve() == w.repo.resolve()


def test_the_repo_of_a_commit_is_read_from_cd_and_dash_c(w, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    w.git("init", "-q", cwd=other)
    assert gitutil.commit_command(f'cd "{other}" && git commit -m x', w.repo)["repo"].resolve() == other.resolve()
    assert gitutil.commit_command(f"git -C {other.as_posix()} commit -m x", w.repo)["repo"].resolve() == other.resolve()
    assert gitutil.commit_command("git status && git log", w.repo) is None
    assert gitutil.commit_command("echo committed", w.repo) is None


# ------------------------------------------------------------------------------------------------- the board
A, B = "aaaaaaaa-1111", "bbbbbbbb-2222"


def test_a_commit_that_would_take_another_sessions_files_is_held(w):
    w.activate("[review]\nenabled = false\n")
    w.start(A)
    w.start(B)
    w.approved_task(A)
    w.approved_task(B)
    w.edit("src/mine.py", "a = 1\n", sid=A)
    w.edit("src/theirs.py", "b = 1\n", sid=B)
    w.git("add", "-A")                                                        # B staged its file; A now commits
    reason = denied(w.bash('git commit -m "mine"', sid=A))
    assert "another running session edited" in reason and "src/theirs.py" in reason and "bbbbbbbb" in reason
    assert "src/mine.py" not in reason.split("Commit only your own")[0].split("\n", 1)[1]
    assert denied(w.bash('git commit --only -m "mine" -- src/mine.py', sid=A)) == ""
    w.hook("SessionEnd", B, reason="other")
    assert denied(w.bash('git commit -m "mine"', sid=A)) == ""                # B ended: its files are nobody's


def test_commit_all_also_counts_unstaged_files_of_others(w):
    w.activate("[review]\nenabled = false\n")
    w.start(A)
    w.start(B)
    w.approved_task(A)
    w.approved_task(B)
    w.write("src/shared.py", "v = 1\n")
    w.git("add", "-A")
    w.git("commit", "-q", "-m", "base")
    w.edit("src/shared.py", "v = 2\n", sid=B)
    w.edit("src/mine.py", "a = 1\n", sid=A)
    w.git("add", "src/mine.py")
    assert denied(w.bash("git commit -m mine", sid=A)) == ""                  # only A's file is staged
    assert "src/shared.py" in denied(w.bash("git commit -am mine", sid=A))    # -a would sweep B's edit in


def test_claims_warn_other_sessions_and_end_with_the_session(w):
    w.start(A)
    w.start(B)
    code, out = w.cli("claim", "maestro-rel", "release suite running until 23:00", sid=A)
    assert code == 0
    warn = w.pre("Bash", B, command="docker compose -p maestro-rel up -d --build").get("additionalContext", "")
    assert "maestro-rel" in warn and "release suite running" in warn and "aaaaaaaa" in warn
    assert "additionalContext" not in w.pre("Bash", B, command="docker compose -p maestro-rel-2 up")   # another name
    assert "additionalContext" not in w.pre("Bash", A, command="docker compose -p maestro-rel up")     # its own claim
    board = w.cli("board", sid=B)[1]
    assert "claims maestro-rel" in board and "(this session)" in board
    assert w.cli("release", "maestro-rel", sid=A)[0] == 0
    assert "additionalContext" not in w.pre("Bash", B, command="docker compose -p maestro-rel up")
    w.cli("claim", "port:8030", sid=A)
    w.hook("SessionEnd", A, reason="other")
    assert "additionalContext" not in w.pre("Bash", B, command="curl localhost port:8030")


def test_the_board_shows_state_task_and_last_note_and_hides_what_is_not_live(w):
    w.start(A)
    w.hook("UserPromptSubmit", A)
    w.approved_task(A, title="deploy the server")
    w.cli("progress", "images shipped; verifying", sid=A)
    w.start(B)
    w.hook("UserPromptSubmit", B)
    w.hook("Notification", B, notification_type="permission_prompt")
    out = w.cli("board", sid=None)[1]
    assert "aaaaaaaa" in out and "working" in out and "T1 deploy the server" in out and "images shipped; verifying" in out
    assert "bbbbbbbb" in out and "WAITING FOR YOU" in out
    w.hook("Stop", A, background_tasks=[{"description": "release suite"}])
    assert "idle" in w.cli("board", sid=None)[1] and "release suite" in w.cli("board", sid=None)[1]
    w.tick(25 * 3600)
    assert "No running sessions" in w.cli("board", sid=None)[1]              # silent for a day: not live
    assert "aaaaaaaa" in w.cli("board", "--all", sid=None)[1]


def test_head_moved_by_someone_else_is_told_once(w):
    w.start(A)
    assert w.hook("UserPromptSubmit", A) == ""                                # first look: nothing to compare
    w.write("x.txt", "1")
    w.git("add", "-A")
    w.git("commit", "-q", "-m", "someone else")
    out = w.hook("UserPromptSubmit", A)
    assert "HEAD moved since your last turn, and not by you" in out["hookSpecificOutput"]["additionalContext"] and "1 commits" in str(out)
    assert w.hook("UserPromptSubmit", A) == ""
    w.write("y.txt", "1")
    w.git("add", "-A")
    w.git("commit", "-q", "-m", "mine")
    w.post("Bash", A, command='git commit -m "mine"')                         # this session's own commit
    assert w.hook("UserPromptSubmit", A) == ""
