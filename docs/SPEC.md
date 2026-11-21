# Sentinel v2: specification

Sentinel is a discipline layer for agentic coding harnesses (Claude Code, OpenHands and programs like them). It does
not make the agent smarter; it makes sure the right message reaches the agent at the moment it applies, checks with
code what code can check exactly, and keeps the session's working state in files that survive compaction, restarts
and hand-offs. It runs on Claude Code today, and this document names Claude Code wherever it describes that harness's
own events, settings and files; the README's "Other harnesses" lists the five pieces an adapter for another one
supplies.

Status: built 21 Nov 2026 and moved to `main`; the version before it is kept on branch `v1`. Test record: [TESTING.md](TESTING.md). Build log: [PROGRESS.md](PROGRESS.md).

## 1. Principles

These come from the owner's "agent bitter lessons" (katkat `usecases/kit/AGENT_BITTER_LESSONS.md`) and from what v1 got
wrong.

1. **A rule arrives at its moment.** v1 repeated every rule on every message. v2 keeps a short set of standing rules and
   delivers everything else when it applies: the contract before a task's first edit, the review before a commit, the
   check before an irreversible command, the notes before compaction.
2. **Code checks exact predicates; the agent judges.** A hook never guesses intent from words. It checks things like
   "an approved task is open", "every flagged line has a disposition", "this exact command was acknowledged". What a
   good contract or a good answer is stays with the agent and the person.
3. **Tool output is the feedback.** The agent talks to Sentinel through one CLI. Each command's output says what
   happened and what to do next, so instructions live where they are used.
4. **State lives in files.** Tasks, contracts, progress notes, reviews, claims and notes are files the person can read
   and a compacted or restarted session can read back.
5. **Every flow can be switched off.** One config file; each flow has `enabled`, and its numbers are named settings
   with a stated reason.
6. **Texts are editable.** Every message the agent receives is a Markdown file that a project or the user can
   override, and corrections from the person are appended to them.

## 2. How it is wired

```
Claude Code ──hook event (JSON on stdin)──▶ sentinel-hook ──▶ each enabled module's handler for that event
                                                │                     │
                                                ▼                     ▼
                                   one merged answer (deny / context / allow)      session files, board
agent ──Bash/PowerShell: `sentinel <command>`──▶ sentinel CLI ──▶ the same modules ──▶ output = the next instruction
```

- **One hook command** (`sentinel-hook`) is registered for `SessionStart`, `UserPromptSubmit`, `PreToolUse`,
  `PostToolUse`, `Stop`, `Notification`, `PreCompact`, `SessionEnd`. It reads the event, loads the config, and calls
  every enabled module that has a handler for the event. Answers are merged: context texts are joined, any deny wins
  (reasons joined), a block at `Stop` wins.
- **Modules** are files in `src/sentinel/modules/`. A module has a `NAME`, optional handlers named after the events
  (`on_pre_tool_use(ctx)`, …) and optional CLI commands. `modules/__init__.py` lists them. A new flow is one file and
  one line. A user can add private modules in `~/.sentinel/modules/*.py` (same interface).
- **The session's identity** reaches the CLI as `SENTINEL_SESSION`: the `SessionStart` hook writes it to
  `CLAUDE_ENV_FILE`, and for a plain `sentinel …` command the `PreToolUse` hook also puts it into the command and
  allows the call without a permission prompt. A plain call holds only `sentinel` commands: one, or several one
  after another (a line break, `;` or `&&` between them; an agent writes its review answers as ten commands in one
  call), with nothing piped, redirected or substituted. It is read as a shell reads it, quote by quote: outside
  quotes no other operator and no expansion; inside double quotes no `$`, backtick or backslash; a quote left open
  is not plain. So `sentinel x && something` is never auto-allowed. Neither are the commands that set Sentinel up (`init`, `uninstall`, `doctor`,
  `transcript`): `init` decides which command the harness runs for every event, so it stays behind the person's own
  permission.
- **Subagents:** gates (task, irreversible command, commit) apply to every call. Moments that manage the main
  conversation (park, restore, progress, rules reminder) are not sent to subagents (events that carry `agent_id`).
- **Failure:** a hook error never blocks the session. It is written to `~/.sentinel/errors.log`, printed on stderr,
  and the hook exits 1 (Claude Code shows it as a non-blocking hook error).

## 3. Activation and installation

- Install the tool once per machine: `uv tool install <repo>` gives `sentinel` and `sentinel-hook` on PATH.
- Activate per repository: `sentinel init` in the repo root writes
  - `.sentinel/config.toml` (its presence is what activates Sentinel there) and `.sentinel/.gitignore`,
  - the hook entries into `.claude/settings.json` (merged, existing entries kept; `--local` uses
    `settings.local.json`),
  - four thin skills (`/sentinel-park`, `/sentinel-handoff`, `/sentinel-review`, `/sentinel-board`) and the
    `sentinel-field-note` subagent under `.claude/`.
- `sentinel uninstall` removes the hook entries and those files and leaves `.sentinel/` data alone.
  `sentinel doctor` checks the installation.
- A hook that runs in a directory with no `.sentinel/config.toml` above it exits at once.

## 4. Files

```
~/.sentinel/                         user level (SENTINEL_HOME overrides the location)
  config.toml                        user defaults for every project
  texts/…  learned/…                 the user's own texts and learned rules
  modules/*.py                       private modules
  board/<session>.json               one file per session on this machine
  errors.log
<repo>/.sentinel/
  config.toml                        activates Sentinel; project settings
  texts/…  learned/…                 project texts and learned rules
  assumptions.md                     the ledger: every flagged line that was kept, with its reason
  handoff/…                          hand-off briefs
  sessions/<id8>/                    one folder per session (git-ignored)
    events.jsonl                     everything that happened, append-only; the state is derived from it
    tasks.md  tasks/T1.md …          the task index and each task's contract
    progress.md  notes.md            progress notes for the person; the agent's own notes for after a compact
    reviews/R1.json  R1.md           commit reviews
    history-<n>.md                   cleaned conversation history written at each compaction
```

Texts are looked up in this order: the repo's `.sentinel/texts/`, the user's `~/.sentinel/texts/`, the package. Learned
rules (`learned/<target>.md`, user then repo) are appended to their target text.

## 5. The flows

Each flow lists its switch in `config.toml`.

### 5.1 Standing rules — `[rules]`

- **What:** a short text (`rules/core.md`): how to write to the person (their language, plain complete sentences,
  established terms kept), and how to work (context first, do not treat the person as the expert, surface assumptions
  and chosen numbers, prefer the robust way, long commands to the background, keep the progress file, record
  corrections).
- **When:** at `SessionStart` (start, resume, clear, after compact) and again each time the context has grown by
  `remind_every_tokens` since the last time it was given (default 300 000, the owner's figure).
- A style judge was considered and left out (the owner: memory rules are enough).

### 5.2 Learning from corrections — `[learn]`

- The standing rules tell the agent to record a correction: `sentinel learn "<rule>" --incident "<what happened>"
  [--where core|contract|review|tests|park] [--scope user|project]`.
- The entry (id, date, rule, incident) is appended to `learned/<where>.md` and from then on is part of that text.
  `sentinel rules` shows the effective texts and entries; `sentinel unlearn <id>` removes one.
- The park message (5.9) asks once more for corrections not yet recorded, because that is the last moment before
  context is lost.
- Not built: detecting a correction by a model on every message (cost and noise), automatic retirement.

### 5.3 Tasks and the contract before the first edit — `[tasks]`

- **Tracking:** the agent opens a task for each piece of work: `sentinel task open "<title>" [--size
  trivial|normal|large] [--parent T1]`. The command creates `tasks/T<n>.md` from the size's template and prints what to
  do next. `tasks.md` is the index.
- **The gate (exact):** an `Edit`/`Write`/`NotebookEdit` of a file inside the repo passes only when the session has an
  open task that is approved. Otherwise the first attempt is denied with the reason and the next command to run.
  Paths under `.sentinel/`, paths outside the repo and `exempt` globs are not gated. `gate = false` keeps the task
  tracking and drops the gate.
- **The contract:** for a `normal` or `large` task the agent fills the task file: Understanding, Scope, Options and
  trade-offs, Assumptions, Open questions, World model, Proof. It presents it to the person, sized to the task, and
  waits. `trivial` tasks and sub-tasks of an approved task are approved at once.
- **The approval (exact):** `sentinel task approve T<n> --basis "<the person's words>"` passes only when every section
  of the contract has content, the person has written a message since the contract was opened, and the words given
  are found verbatim in what they wrote since then (read from the session's transcript; case and spacing aside). So the
  agent cannot approve its own contract in the turn it wrote it, nor on words nobody said. This rule came from the
  first real run: the model wrote a good contract and then approved it itself on the original request.
- **A standing instruction** (`standing = true`): when the person said beforehand not to wait for them, the agent
  approves with `--standing "<those words>"`. The words must be in what they wrote; the task is recorded as "approved
  on a standing instruction, the contract not confirmed by the person", and the agent is told to put the contract in
  its final message. `standing = false` closes this path: the agent always waits. The person's words are read from
  the whole session, across its compactions; a compaction's summary quotes the person and is not counted as them.
- **World model** (`world_model = true`): the contract's World model section holds expected outcomes as checkable
  statements. Lenses help the agent think it through from the right seat: `sentinel lens` lists them (UI, algorithm,
  data, API, operations, agent-facing text; one file each, more can be added). The review (5.4) compares what was
  observed against these statements.
- **Field note** (`field_note = true`): when standards or prior art could change the design, the contract message tells
  the agent to propose a field note to the person; only after a yes does it start the `sentinel-field-note` subagent,
  which returns a short, sourced note.
- **Proof** (`proof = true`): the contract states how the work will be shown to work: a manual check that is run and
  recorded, an end-to-end walk, or a kept test, and a test is kept only when the behaviour can break silently later.
- `sentinel task done T<n>` closes a task; the next edit needs a new one.
- **Limits:** edits made through shell commands are not gated. Whether new work is a new task or a sub-task is the
  agent's call.

### 5.4 Review before a commit, and the assumption ledger — `[review]`

- **When:** a shell command that contains `git commit` (also `/sentinel-review` or `sentinel review` at any time).
- **What is reviewed:** the files this session edited that differ from `HEAD`, plus staged files no other session
  edited. Files matching `skip` (docs, lock files, data) are left out; a commit with nothing left passes untouched.
- **Flagged lines (code):** detectors read the added lines and flag exact patterns: a numeric literal, a default or
  fallback value, a broad `except`, a fixed sleep, a timeout or retry count, a fixed truncation, a silenced check
  (`noqa`, `--no-verify`, `|| true`, `2>/dev/null`, `verify=False`), a skipped test, a hard-coded path or address, a
  `TODO`, and in test files a dependence on today's date, a test with no assertion, an assertion on a mock call.
  Detectors are a table of name, pattern, file globs and reason; a project can add its own or switch one off.
- **Dispositions:** each flagged line needs `sentinel review set F<n> fixed` or `… kept "<reason>"`.
- **Questions:** for a non-trivial task the agent answers the numbered questions in `review/questions.md` with
  `sentinel review answer <n> "<text>"`: scope against the contract, the world model's outcomes observed, cases not
  handled, the fragile-pattern catalogue (`sentinel catalogue`: one list for how the work was done, one for the code),
  usual practice, proof. The review also states a fact: whether a test command ran after the last source edit.
- **The gate (exact):** the commit passes when every flagged line has a disposition and every question an answer.
- **One change, one review:** a flagged line is known by its kind, its file, its text and which occurrence of that
  text it is among the added lines, so a second `except Exception:` in a file is a second line to answer for. What was
  settled carries over only inside one change: the same task, with `HEAD` where it was when the last review passed
  (its commit did not land). Then only new flagged lines are asked, and the answers stand. Once the commit has landed,
  or the task is another, the next commit is a new change: its flagged lines are new decisions and its questions are
  asked again. A line that left the change and came back is open again.
- **What is read:** added lines of text files. A new binary file (a NUL in its first 8000 bytes, git's own test) is
  not read. File names are taken from git unquoted (`-z`), so names with non-ASCII letters or spaces are seen.
- **The ledger:** when a review passes, every line that was kept goes to `.sentinel/assumptions.md` with its reason,
  file, date and task. The message also tells the agent to say these to the person.
- **Limits:** the person's own commits in a terminal are not seen. A `git commit` inside quoted text can hold a
  command once.

### 5.5 Tests — `[testing]`

- The doctrine is delivered where it applies: in the contract's Proof section (decide the kind of proof first), at the
  first edit of a test file in a task (the `tests` moment: a test must be able to fail, prefer an end-to-end test that
  prints what it did so a failure can be read later, do not write tests that restate the code), and in the review
  (flags and the Proof question).
- The review's test facts and flags are listed in 5.4.

### 5.6 Check before an irreversible command — `[gate]`

- **When:** a shell command matches a pattern in the table: recursive delete (the flag before or after the target;
  `rm`, `Remove-Item` and its aliases, `-Recurse` in its abbreviations, `rd /s`), bulk delete (`find … -delete`,
  `find … -exec rm`, `xargs rm`), `git reset --hard`, `git clean`, force-push (also `+branch`), branch delete, discard
  of changes (also `checkout -f`, `switch -f`), `docker … down -v` / volume or system prune, SQL `DROP`/`TRUNCATE`/
  `DELETE` without `WHERE`, `pg_restore --clean`, ACL or ownership changes (`icacls`, `chmod -R`, `chown -R`),
  kill by name, disk tools, cloud deletes. A project can add patterns or switch one off.
- **The gate (exact):** the command is denied once with a token. The agent looks at the target, names the way back, and
  runs `sentinel gate ok <token> --target "<what it saw>" --rollback "<how to undo, or why none>"`. The same command
  then passes once. Each acknowledgement is kept in the session's events, with the command as it was last held.
- **What an acknowledgement covers:** the parts of the command that match a pattern, and the place they run in (the
  shell's folder and every `cd` in the command). A harmless command chained around them may change without a new
  acknowledgement (a real run showed the model does that between its two attempts); another target, another folder
  or another `cd` is another act.
- **Limit:** a pattern table is a tripwire, not a sandbox; it complements Claude Code's own permission modes.

### 5.7 Progress file — `[progress]`

- `sentinel progress "<note>"` appends a timestamped note to the session's `progress.md`; the note is written for the
  person, in their language: what is done, what is running, what comes next, what waits for them.
- **The moment (exact):** while a non-trivial task is open, when `every_minutes` have passed since the last note (or
  since the task opened) the next tool call delivers the reminder. Default 20 minutes: long enough not to interrupt
  short work, short enough that a person who looks in finds a fresh note.

### 5.8 Session board — `[board]`

- Each session keeps one file on the machine's board: repo, branch, state (working, idle since, waiting for the
  person), current task, last progress note, claims, background commands, edited files. `sentinel board` shows every
  session; a session with no activity for `stale_after_hours` (default 24) or from before the last boot is shown as
  not live and ignored by the guards.
- **Claims:** `sentinel claim <resource> "<note>"` (a Docker project, a port, an image tag, a server) and
  `sentinel release <resource>`. A shell command that names a resource another live session claimed gets a warning
  with that session's note.
- **Commit guard (exact):** a `git commit` that would include files another live session edited and this session did
  not is denied with the list, unless the command limits itself with `--only` or a path list. What the commit would
  take is what is staged, what `-a` adds, and what a `git add` earlier in the same command stages (the index does not
  hold those yet when the hook looks). The command's words are read quote by quote: a `;` or `&&` inside the message
  is message, and nothing after a command substitution or a heredoc mark is read as a flag or a path.
- **Cost:** whether a session runs is asked of every session on the machine at every shell command, so it is read
  from the end of each session's log; only the running ones are read whole.
- **HEAD moved:** at each prompt, when the repo's `HEAD` differs from what this session last saw and this session did
  not move it, the agent is told the range.

### 5.9 Context: automatic compaction, notes before it, restore after it — `[context]`

- **The trigger:** Claude Code compacts by itself when the context is `compact_at_percent` full (default 80, the
  owner's figure). `sentinel init` writes that number into the repository's Claude Code settings as
  `env.CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, Claude Code's own setting for it; `uninstall` takes its own value out again,
  and `doctor` says when the settings and the config do not agree. The person sets nothing, and a percent fits every
  window size. `0` leaves Claude Code's own trigger (near the very end of the window).
- **The hold:** Claude Code asks the `PreCompact` hook before each automatic compaction. Sentinel answers "not now"
  until the agent's notes are written:
  1. The first time, it records the context's size and a limit (`size × hold_until_percent / compact_at_percent`;
     with the defaults 90 over 80: half of the room that is left above the trigger) and blocks.
  2. At the next tool result, or with the person's next message, the agent is told that a compaction is waiting for
     it: bring `notes.md` up to date now (where it is, the exact next step, background work, open doubts, what no
     file holds yet, corrections not yet recorded), then run `sentinel park done`. That command is refused while the
     notes file is unchanged since the message.
  3. Claude Code asks again before every request. Sentinel lets the compaction go when the agent ran
     `sentinel park done`, when the context reached the limit, when a request did not get through (an API error
     follows the last reply in the transcript), or when the size cannot be read. Once let go, nothing is held again
     until that compaction is over.

  The percent used is the one in force in the session, read from the environment Claude Code gives its hooks: a
  settings file that is out of step means no hold, never a wrong one. A manual `/compact` and a subagent's own
  compaction are never held. `hold_until_percent = 0` switches the hold off.
- **Why the hold is safe** (read in Claude Code 2.1.310's own code, then seen in a real run): a compaction a hook
  blocks is not counted as a failure, shows the person nothing, and is tried again before the next request. The last
  reply before the hold was sent under the trigger, so `size × 100 / percent` is never more than the window and the
  limit is never more than `hold_until_percent` of it. At the window's very end Claude Code cannot send a request at
  all; the "request did not get through" way out is for that case.
- **Park on demand:** `/sentinel-park` (`sentinel park`) gives the same list before a manual `/compact`.
  `park_at_tokens` (default 0: off) adds an earlier reminder at a fixed token count.
- **Compact:** the `PreCompact` hook adds instructions to the summary prompt: keep the person's standing instructions
  and corrections word for word, the current task and next step, open questions, names and ids; details live in files.
- **Restore:** after any compaction the `SessionStart` hook writes the cleaned history of the compacted stretch
  (`history-<n>.md`: the person's messages, the agent's, tool calls without their outputs) and gives the agent the
  recovery message: read the history (from the line where its last quarter begins, then earlier if needed), the notes,
  the open tasks and the progress file; what was proven is gone unless a file holds it. The standing rules follow.
- **Not possible:** running `/compact` from a hook, or changing model or effort around a compaction. The compaction
  itself is always Claude Code's; Sentinel sets when it comes and makes it wait for the notes.

### 5.10 Crash report — `[crash]`

- **Exact:** a session whose events do not end with `session_end` and whose last event is older than the machine's
  last boot was cut by a restart.
- When such a session is resumed, the agent is told once: when it was cut, its open tasks, the background tasks that
  were running at its last turn end, its last progress note, and where its notes are. When a new session starts in
  the repo, it is told once which sessions were cut.
- **Once means once:** the mark that a cut was told stands in the session's log after its last activity and counts at
  every later boot, so an old session that is never resumed is not announced again after each restart. A session
  that was announced to another one still gets its own report when it is resumed: it is the one that needs to know
  what the restart stopped.

### 5.11 Hand-off brief — `[handoff]`

- `sentinel handoff [--for "<reader>"]` (or `/sentinel-handoff`) writes a brief skeleton with the facts filled in from
  the session's files and git: tasks and their state, progress notes, commits made since the session started, files
  edited, claims, the cleaned history's path. The output tells the agent to write the three narrative parts for a
  reader with none of its context: what happened, what to read and in which order, what is half done.

## 6. Configuration

One file per level, TOML; the repo's values override the user's, which override the defaults. `sentinel config`
prints the effective values. Every number has its reason next to it in the template `sentinel init` writes.

| Section | Keys (default) |
|---|---|
| `[rules]` | `enabled` (true), `remind_every_tokens` (300000) |
| `[learn]` | `enabled` (true) |
| `[tasks]` | `enabled` (true), `gate` (true), `exempt` ([]), `world_model` (true), `field_note` (true), `proof` (true), `sections` (the contract's sections per size) |
| `[review]` | `enabled` (true), `skip` (docs, lock and data globs), `disable` ([] detector names), `ignore_numbers` (0, 1, 2, -1, 10, 100, 1000, 1024, 60, 3600, 24: unit arithmetic more often than a choice), `[[review.patterns]]` (extra detectors) |
| `[testing]` | `enabled` (true), `test_globs`, `commands` (test-runner patterns) |
| `[gate]` | `enabled` (true), `disable` ([]), `[[gate.patterns]]` (extra patterns) |
| `[progress]` | `enabled` (true), `every_minutes` (20) |
| `[board]` | `enabled` (true), `stale_after_hours` (24) |
| `[context]` | `enabled` (true), `compact_at_percent` (80; 0 leaves Claude Code's own trigger), `hold_until_percent` (90; 0: the compaction does not wait for the notes), `park_at_tokens` (0: off), `recent_fraction` (0.25) |
| `[crash]` | `enabled` (true) |
| `[handoff]` | `enabled` (true), `dir` (".sentinel/handoff") |

## 7. Commands

Agent: `task open|approve|done|list`, `lens [name]`, `review [set|answer|status]`, `catalogue`, `gate ok`,
`progress`, `claim`, `release`, `board`, `learn`, `unlearn`, `rules`, `park [done]`, `handoff`.
Person: `init`, `uninstall`, `doctor`, `config`, `board`, `status`, `transcript <file>`.

## 8. Decisions taken while building, with the alternatives

| Decision | Why | Alternative |
|---|---|---|
| The agent talks to Sentinel through a CLI, not an MCP server | No server process, no dependency, output arrives as tool output, works the same in every shell | MCP tools (native, but a process per session and a package to keep) |
| Gates deny once and name the next command | The message reaches the agent exactly when it tries the action | Reminders in the prompt (v1): forgotten |
| Activation per repo by `.sentinel/config.toml`; hooks in the repo's `.claude/settings.json` | Visible, versioned, the same on both machines | User-level hooks for every repo (a process on every tool call everywhere) |
| State as an append-only event log per session | Parallel tool calls cannot corrupt it; it doubles as the audit trail | One JSON state file with locking |
| No model-judged hooks in v2 | Cost and latency on every turn; the owner chose rules over a judge for style | `prompt`-type hooks at `Stop` for evidence and style |
| TOML config | Comments next to each number; read with the standard library | JSON, YAML |
| Detectors are line patterns, not parsers (Python tests use `ast`) | Language-agnostic, small, each one explainable | Per-language linters |

## 9. Not in v2

Second opinion on a plan, independent reviewer agent, evidence check on final messages, reading gate, duration memory,
effort switching around compaction, notes between sessions (Claude Code already has session messages), a headless
driver.
