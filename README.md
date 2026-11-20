# Sentinel v2

A discipline layer for Claude Code sessions. It gives the agent the right message at the moment it applies, checks with
code what code can check exactly, and keeps a session's working state in files that survive a compaction, a restart
and a hand-off. Design and reasons: [docs/SPEC.md](docs/SPEC.md). What was tested and how: [docs/TESTING.md](docs/TESTING.md).

## Install and activate

```
uv tool install <this repository>      # once per machine: puts `sentinel` and `sentinel-hook` on PATH
cd <your repository>
sentinel init                          # activates Sentinel here
sentinel doctor                        # checks the setup and times one hook call
```

`sentinel init` writes `.sentinel/config.toml` (its presence activates Sentinel in the repository), registers one hook
command for eight Claude Code events in `.claude/settings.json`, sets Claude Code's automatic compaction there to 80
percent of the context (`[context] compact_at_percent`), and adds four small skills and one subagent under
`.claude/`. `sentinel uninstall` takes the hook, that setting and those files out again and leaves the data.
Sessions started in the repository after that use it; nothing changes in other repositories.

## What it does

| Flow | When | What happens | Switch |
|---|---|---|---|
| Standing rules | session start, after a compaction, every 300k tokens of context | a short text: how to write to the person, how to work | `[rules]` |
| Learning | the person corrects the agent | `sentinel learn` appends the rule to the text it belongs to | `[learn]` |
| Task and contract | the first edit of a piece of work | the edit waits until a task is open and its contract (understanding, scope, options, assumptions, questions, world model, proof) is approved with the person's words | `[tasks]` |
| World model | in the contract, again at the review | expected outcomes as checkable statements, thought through with lenses (`sentinel lens`) | `[tasks] world_model` |
| Field note | in the contract, only if the person agrees | a subagent researches standards and prior art and returns a short sourced note | `[tasks] field_note` |
| Tests doctrine | the first edit of a test file; the review | tests must be able to fail, prefer end-to-end with printed steps, no tests for their own sake | `[testing]` |
| Review and ledger | a `git commit` | flagged lines (numbers, fallbacks, broad excepts, sleeps, truncations, silenced checks, weak tests) need a disposition, six questions an answer; kept lines go to `.sentinel/assumptions.md` | `[review]` |
| Irreversible commands | `rm -rf`, `git reset --hard`, force-push, `down -v`, `DROP`, ACL changes, cloud deletes | held once: look at the target, name the way back, acknowledge, run | `[gate]` |
| Progress file | every 20 minutes of open work | a reminder to add a note the person can read without asking | `[progress]` |
| Session board | always | `sentinel board`: every session on the machine, its task, last note, claims; a commit that would take another session's files is held | `[board]` |
| Context | when the context is 80 percent full; at the compaction; after it | Claude Code compacts by itself at 80 percent (`sentinel init` sets it); the compaction waits until the agent has written its notes; instructions for the summary; cleaned history, notes, tasks and rules given back | `[context]` |
| Crash report | a session resumed after the machine restarted | what was open and what was running | `[crash]` |
| Hand-off | `sentinel handoff` | a brief with the facts filled in and the narrative left to write | `[handoff]` |

Every flow has `enabled` in `.sentinel/config.toml`; every number there has its reason beside it.
Every text the agent receives is a Markdown file under `src/sentinel/texts/` that a repository (`.sentinel/texts/`) or
the user (`~/.sentinel/texts/`) can replace.

## Commands

For the agent: `task open|approve|done|list`, `lens`, `review [set|answer|status]`, `catalogue`, `gate ok`,
`progress`, `claim`, `release`, `learn`, `unlearn`, `rules`, `park [done]`, `handoff`.
For you: `init`, `uninstall`, `doctor`, `config`, `board`, `status`, `transcript <file>`.
In a session: `/sentinel-park` (before `/compact`), `/sentinel-handoff`, `/sentinel-review`, `/sentinel-board`.

## Adding a flow

One file in `src/sentinel/modules/` with a `SECTION`, handlers named after the hook events (`on_pre_tool_use(ctx,
out)`, …) and optionally `cli(sub)`; one line in `modules/__init__.py`. A private module goes in
`~/.sentinel/modules/` and is switched on with its own section in the config.

## Development

```
uv sync
uv run pytest                      # the automated tests: real git repositories, the hook's real entry point
uv run python tests/behaviour/run.py <repo> "<prompt>"   # one turn of a real Claude Code session, with what Sentinel did
```
