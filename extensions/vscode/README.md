# Sentinel panel

A read-only panel in the editor's right side bar that shows what the agents of this workspace wrote for you, and
refreshes itself as they write:

- **every session** in `.sentinel/sessions/`, with its name in the harness, its state (working, idle, waiting for
  you, cut by a restart, ended), when it was last active, and a mark when one of its contracts waits for your answer
  or it is writing its notes before a compaction;
- inside a session: its **progress notes** (newest first), its **contracts** (each task with its status, the words it
  was approved on, and the whole contract), its **commit reviews** (the files, the choices kept and why, the answers);
- for the repository: the **assumption ledger** (newest first) and the **hand-off briefs**.

Every part is collapsible, and the panel remembers what you left open. A click on ↗ opens the file. Sessions that are
not running are shown when they were active in the last 24 hours and wrote something for you (`sentinel.recentHours`);
the eye in the panel's title shows them all.

The panel is a view, not a control: approvals stay in the conversation, where the agent takes them.

## Install

```
cd extensions/vscode
npm install
npm run package                                   # writes sentinel-panel.vsix
cursor --install-extension sentinel-panel.vsix    # or: code --install-extension …
```

Then reload the window. The panel opens in the secondary side bar (right) in a workspace whose folder holds
`.sentinel/config.toml`; `Sentinel: Open the Panel` brings it up.

## Develop

```
npm test                                          # the reading of .sentinel/, against folders written as Sentinel writes them
node scripts/preview.mjs <repo> preview.html      # the panel as a page, from a real repository, to look at in a browser
```

`src/model.ts` reads the files (no editor API, so it runs under plain Node), `src/render.ts` turns Markdown into HTML
with raw HTML switched off, `src/extension.ts` is the editor's side, `media/panel.js` builds the view.
