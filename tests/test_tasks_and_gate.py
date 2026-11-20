"""The task gate and the contract, the tests moment, the progress reminder, and the check before an irreversible
command."""
from __future__ import annotations

import re

import pytest

from sentinel.modules import gate


def denied(answer: dict) -> str:
    return answer.get("permissionDecisionReason", "") if answer.get("permissionDecision") == "deny" else ""


# ------------------------------------------------------------------------------------------------- tasks
def test_an_edit_waits_for_a_task_and_then_for_its_approval(w):
    w.start()
    first = denied(w.edit("src/app.py"))
    assert "no task is open" in first and "sentinel task open" in first
    assert not (w.repo / "src" / "app.py").exists()

    code, out = w.cli("task", "open", "Add the export endpoint", "--size", "normal")
    assert code == 0 and "T1" in out and "Present it to the person" in out and "sentinel-field-note" in out
    contract = w.session_dir() / "tasks" / "T1.md"
    assert contract.is_file()
    for heading in ("Understanding", "Scope", "Options and trade-offs", "Assumptions", "Open questions", "World model", "Proof"):
        assert f"## {heading}" in contract.read_text(encoding="utf-8")

    second = denied(w.edit("src/app.py"))
    assert "T1 is open but its contract is not approved" in second

    code, out = w.cli("task", "approve", "T1", "--basis", "evet, böyle yap")
    assert code == 1 and "sections" in out and "Understanding" in out       # an empty contract cannot be approved

    text = contract.read_text(encoding="utf-8")
    contract.write_text(re.sub(r"(<!--.*?-->)", r"\1\nSomething real.", text, flags=re.S), encoding="utf-8")
    assert w.cli("task", "approve", "T1")[0] == 1                            # nor without the person's words
    code, out = w.cli("task", "approve", "T1", "--basis", "evet, böyle yap")
    assert code == 1 and "has not written anything since its contract was opened" in out   # nor in the same turn
    w.tick(60)
    w.say("Evet,   böyle yap. Devam edebilirsin.")
    code, out = w.cli("task", "approve", "T1", "--basis", "hadi başla")
    assert code == 1 and "not in what the person wrote" in out               # nor on words they did not say
    code, out = w.cli("task", "approve", "T1", "--basis", "evet, böyle yap")
    assert code == 0 and "could not be checked" not in out
    assert denied(w.edit("src/app.py")) == ""
    assert (w.repo / "src" / "app.py").is_file()
    index = (w.session_dir() / "tasks.md").read_text(encoding="utf-8")
    assert "T1" in index and "approved on: \"evet, böyle yap\"" in index and "not checked" not in index

    assert w.cli("task", "done", "T1")[0] == 0
    assert "no task is open" in denied(w.edit("src/other.py"))               # the next piece of work needs its own


def fill(w, tid="T1"):
    p = w.session_dir() / "tasks" / f"{tid}.md"
    p.write_text(re.sub(r"(<!--.*?-->)", r"\1\nx", p.read_text(encoding="utf-8"), flags=re.S), encoding="utf-8")


def test_words_from_before_the_contract_approve_only_as_a_standing_instruction(w):
    w.start()
    w.say("Bütün işi yap, ben uyuyorum, bana sormadan devam et.")
    w.tick(120)
    code, out = w.cli("task", "open", "build it all", "--size", "large")
    assert "--standing" in out and "not to wait for them" in out
    fill(w)
    code, out = w.cli("task", "approve", "--basis", "bana sormadan devam et")
    assert code == 1 and "has not written anything since" in out
    assert w.cli("task", "approve", "--standing", "you can skip the questions")[0] == 1      # not their words
    code, out = w.cli("task", "approve", "--standing", "bana sormadan devam et")
    assert code == 0 and "standing instruction" in out and "final message" in out
    index = (w.session_dir() / "tasks.md").read_text(encoding="utf-8")
    assert "approved on a standing instruction, the contract not confirmed by the person" in index
    assert denied(w.edit("src/a.py")) == ""


def test_the_standing_path_can_be_closed(w):
    w.activate("[tasks]\nstanding = false\n")
    w.start()
    w.say("sormadan devam et")
    code, out = w.cli("task", "open", "x", "--size", "normal")
    assert "--standing" not in out
    fill(w)
    code, out = w.cli("task", "approve", "--standing", "sormadan devam et")
    assert code == 1 and "switched off" in out


def test_a_trivial_task_and_a_step_pass_at_once(w):
    w.start()
    code, out = w.cli("task", "open", "fix a typo", "--size", "trivial")
    assert code == 0 and "edits pass now" in out
    assert denied(w.edit("a.py")) == ""
    w.cli("task", "done")
    w.cli("task", "open", "real work", "--size", "normal")
    code, out = w.cli("task", "open", "a step", "--parent", "T2")
    assert code == 1 and "approved" in out                                    # no step inside an unapproved task
    assert "not approved" in denied(w.edit("a.py"))


def test_what_the_gate_leaves_alone(w, tmp_path):
    w.start()
    assert denied(w.edit(".sentinel/notes.md")) == ""                         # Sentinel's own files
    outside = tmp_path / "elsewhere.py"
    assert w.pre("Write", file_path=str(outside), content="x").get("permissionDecision") != "deny"
    assert w.bash("ls").get("permissionDecision") != "deny"                   # not an edit
    w.activate('[tasks]\nexempt = ["notes/**"]\n')
    assert denied(w.edit("notes/today.md")) == ""
    assert "no task is open" in denied(w.edit("src/a.py"))
    w.activate("[tasks]\ngate = false\n")
    assert denied(w.edit("src/a.py")) == ""                                   # tracking without the gate
    w.activate("[tasks]\nenabled = false\n")
    assert denied(w.edit("src/b.py")) == ""
    code, out = w.cli("task", "list")
    assert code == 1 and "switched off" in out


def test_the_contract_drops_the_sections_that_are_switched_off(w):
    w.activate("[tasks]\nworld_model = false\nproof = false\nfield_note = false\n")
    w.start()
    code, out = w.cli("task", "open", "x", "--size", "large")
    text = (w.session_dir() / "tasks" / "T1.md").read_text(encoding="utf-8")
    assert "## World model" not in text and "## Proof" not in text and "## Way back" in text and "## Impact" in text
    assert "field note" not in out and "3. Present" in out and "\n4. Stop" in out


def test_lenses_are_listed_read_and_extendable(w):
    w.start()
    code, out = w.cli("lens")
    assert code == 0 and all(n in out for n in ("ui", "algorithm", "data", "api", "ops", "agent-text"))
    assert "phone" in w.cli("lens", "ui")[1]
    w.write(".sentinel/texts/lenses/pricing.md", "# Lens: a price\n1. Who pays?\n")
    assert "pricing" in w.cli("lens")[1] and "Who pays?" in w.cli("lens", "pricing")[1]
    assert w.cli("lens", "nope")[0] == 1


# ------------------------------------------------------------------------------------------------- tests moment
def test_the_tests_doctrine_comes_once_per_task_at_the_first_test_file(w):
    w.start()
    w.approved_task()
    first = w.pre("Write", file_path=str(w.repo / "tests" / "test_app.py"), content="def test_x(): assert 1")
    assert "A test earns its place by the failure it would catch" in first.get("additionalContext", "")
    again = w.pre("Write", file_path=str(w.repo / "tests" / "test_other.py"), content="x")
    assert "additionalContext" not in again
    assert "additionalContext" not in w.pre("Write", file_path=str(w.repo / "src" / "app.py"), content="x")
    w.cli("task", "done")
    w.approved_task(title="second")
    assert "A test earns its place" in w.pre("Write", file_path=str(w.repo / "tests" / "test_app.py"), content="x").get("additionalContext", "")


def test_a_held_test_edit_keeps_the_doctrine_for_when_it_happens(w):
    w.start()
    held = w.pre("Write", file_path=str(w.repo / "tests" / "test_app.py"), content="x")
    assert held["permissionDecision"] == "deny"
    w.approved_task()
    assert "A test earns its place" in w.pre("Write", file_path=str(w.repo / "tests" / "test_app.py"), content="x").get("additionalContext", "")


# ------------------------------------------------------------------------------------------------- progress
def test_the_progress_reminder_comes_after_the_interval_and_stops_when_a_note_is_written(w):
    w.start()
    w.cli("task", "open", "long work", "--size", "normal")
    contract = w.session_dir() / "tasks" / "T1.md"
    contract.write_text(re.sub(r"(<!--.*?-->)", r"\1\nx", contract.read_text(encoding="utf-8"), flags=re.S), encoding="utf-8")
    w.say("go")
    assert w.cli("task", "approve", "--basis", "go")[0] == 0
    w.tick(19 * 60)
    assert w.post("Bash", command="ls") == ""
    w.tick(2 * 60)
    text = w.post("Bash", command="ls")
    assert "21 minutes since the last progress note" in text and "sentinel progress" in text
    assert w.post("Bash", command="ls") == ""                                 # asked once in this interval
    code, out = w.cli("progress", "API bitti; testler koşuyor; sırada UI. Senden beklenen yok.")
    assert code == 0
    page = (w.session_dir() / "progress.md").read_text(encoding="utf-8")
    assert "API bitti" in page and "(T1)" in page and re.search(r"## \d{4}-\d{2}-\d{2}", page)
    w.tick(10 * 60)
    assert w.post("Bash", command="ls") == ""                                 # the note reset the clock
    w.tick(11 * 60)
    assert "21 minutes" in w.post("Bash", command="ls")
    w.cli("task", "done")
    w.tick(60 * 60)
    assert w.post("Bash", command="ls") == ""                                 # nothing open: nothing to report


def test_no_progress_reminder_for_trivial_work(w):
    w.start()
    w.approved_task(size="trivial")
    w.tick(3 * 3600)
    assert w.post("Bash", command="ls") == ""


# ------------------------------------------------------------------------------------------------- the gate
HELD = [
    "rm -rf build", "rm -fr /tmp/x", "rm -r -f node_modules", "rm --recursive x", "cd x && rm -rf dist",
    "Remove-Item C:\\tmp\\x -Recurse -Force", "rmdir /s /q build", "git reset --hard HEAD~1", "git clean -fd",
    "git push --force origin main", "git push -f", "git push --force-with-lease", "git branch -D feature",
    "git push origin --delete feature", "git checkout -- src/app.py", "git checkout .", "git restore src/app.py",
    "git stash drop", "git worktree remove --force ../wt", "docker volume rm data", "docker compose down -v",
    "docker compose -p x down --volumes", "docker system prune -af", 'psql -c "DROP TABLE users"', "psql -c 'TRUNCATE orders'",
    'psql -c "DELETE FROM users;"', "dropdb app", "pg_restore --clean -d app dump", "icacls key /inheritance:r /grant:r me:R",
    "chmod -R 777 .", "chown -R me:me /srv", "taskkill /F /IM python.exe", "pkill node", "Stop-Process -Name node",
    "dd if=/dev/zero of=/dev/sda", "mkfs.ext4 /dev/sdb1", "doctl compute droplet delete 123", "terraform destroy",
    "kubectl delete ns prod", "aws s3 rb s3://bucket --force && aws ec2 terminate-instances --instance-ids i-1",
]
PASSES = [
    "rm file.txt", "rm -f file.txt", "ls -la", "git status", "git reset HEAD~1", "git push origin main", "git branch -d merged",
    "git restore --staged a.py", "git checkout main", "git checkout -b new", "git stash", "docker compose down", "docker ps",
    "docker compose up -d", 'psql -c "SELECT * FROM users"', 'psql -c "DELETE FROM users WHERE id = 3"', "chmod +x run.sh",
    "icacls key", "taskkill /PID 123 /F", "kill 123", "kubectl get pods", "terraform plan", "echo format", "grep -r rm .",
    "pg_restore -d app dump", "git clean -n",
]


@pytest.mark.parametrize("command", HELD)
def test_irreversible_commands_are_held(w, command):
    w.start()
    reason = denied(w.bash(command))
    assert "cannot be undone" in reason and "sentinel gate ok" in reason, command


@pytest.mark.parametrize("command", PASSES)
def test_ordinary_commands_pass(w, command):
    w.start()
    assert denied(w.bash(command)) == "", command


def test_an_acknowledged_command_passes_once_and_only_as_it_was(w):
    w.start()
    cmd = "rm -rf build"
    reason = denied(w.bash(cmd))
    token = re.search(r"sentinel gate ok (\w+)", reason).group(1)
    assert token == gate.token_of(cmd)
    assert w.cli("gate", "ok", token)[0] == 1                                  # both answers are required
    assert w.cli("gate", "ok", "deadbeef", "--target", "x", "--rollback", "y")[0] == 1
    assert denied(w.bash(cmd)) != ""                                           # still held
    code, out = w.cli("gate", "ok", token, "--target", "build/ holds 3 generated files", "--rollback", "none needed: regenerated by make")
    assert code == 0
    assert denied(w.bash("rm -rf build dist")) != ""                           # a changed command is a new command
    assert denied(w.bash(cmd)) == ""                                           # passes
    assert denied(w.bash(cmd)) != ""                                           # once
    events = (w.session_dir() / "events.jsonl").read_text(encoding="utf-8")
    assert "build/ holds 3 generated files" in events and "regenerated by make" in events


def test_a_repo_can_add_a_pattern_and_switch_one_off(w):
    w.activate('[gate]\ndisable = ["rm-recursive"]\n[[gate.patterns]]\nname = "prod-deploy"\nregex = "deploy\\\\.sh\\\\s+prod"\nwhy = "deploys to production"\n')
    w.start()
    assert denied(w.bash("rm -rf build")) == ""
    assert "deploys to production" in denied(w.bash("./deploy.sh prod"))
    w.activate("[gate]\nenabled = false\n")
    assert denied(w.bash("git reset --hard")) == ""
