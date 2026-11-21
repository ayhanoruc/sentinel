// The Sentinel panel's webview: builds the collapsible view from the model the extension sends. It parses no file and
// runs no text from one: every HTML string it receives was rendered with raw HTML switched off.
(function () {
  "use strict";
  const vscode = acquireVsCodeApi();
  const state = vscode.getState() || {};
  const open = state.open || {}; // a section's key -> whether the person left it open
  const root = document.getElementById("root");

  const STATE_LABEL = {
    working: "working",
    idle: "idle",
    waiting: "waiting for you",
    ended: "ended",
    cut: "cut by a restart",
    unknown: "",
  };
  const STATUS_LABEL = { open: "not approved", approved: "approved", done: "done" };

  function save() {
    vscode.setState({ open });
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }

  function ago(t) {
    if (!t) return "";
    const s = Math.max(0, Date.now() / 1000 - t);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400 * 2) return `${Math.floor(s / 3600)} h ago`;
    return `${Math.floor(s / 86400)} d ago`;
  }

  function when(t) {
    const n = el("span", "when", ago(t));
    n.dataset.t = String(t || "");
    if (t) n.title = new Date(t * 1000).toLocaleString();
    return n;
  }

  function badge(text, kind) {
    return el("span", `badge ${kind || ""}`.trim(), text);
  }

  function openButton(file, label) {
    const b = el("button", "open", "↗");
    b.title = label || `Open ${file}`;
    b.setAttribute("aria-label", b.title);
    b.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      vscode.postMessage({ type: "open", path: file });
    });
    return b;
  }

  function markdown(html, base) {
    const d = el("div", "md");
    d.innerHTML = html; // rendered by markdown-it with raw HTML off
    if (base) d.dataset.base = base;
    return d;
  }

  /** A collapsible section whose body is built the first time it is opened, and whose state is remembered. */
  function section(key, defaultOpen, cls, summary, body) {
    const d = el("details", cls);
    d.dataset.key = key;
    d.open = Object.prototype.hasOwnProperty.call(open, key) ? open[key] : defaultOpen;
    const s = el("summary");
    summary.forEach((n) => n && s.append(n));
    d.append(s);
    let built = false;
    const build = () => {
      if (built) return;
      built = true;
      const b = el("div", "body");
      body(b);
      d.append(b);
    };
    if (d.open) build();
    d.addEventListener("toggle", () => {
      open[key] = d.open;
      save();
      if (d.open) build();
    });
    return d;
  }

  function title(text, cls) {
    return el("span", cls || "title", text);
  }

  function count(n) {
    return el("span", "count", String(n));
  }

  function progressGroup(s) {
    return section(`${s.key}/progress`, true, "group", [
      title("Progress", "gtitle"), count(s.progress.length), s.progressFile && openButton(s.progressFile, "Open the progress file"),
    ], (b) => {
      if (!s.progress.length) {
        b.append(el("p", "muted", "No progress notes yet."));
        return;
      }
      s.progress.forEach((p, i) => {
        b.append(section(`${s.key}/p/${p.key}`, i === 0, "entry", [
          title(p.title.replace(/^·\s*/, ""), "etitle"), p.day ? el("span", "when", p.day) : null,
        ], (e) => e.append(markdown(p.html, s.progressFile))));
      });
    });
  }

  function taskRow(s, t) {
    const status = t.awaiting ? badge("waiting for your answer", "attention") : badge(STATUS_LABEL[t.status] || t.status, t.status);
    return section(`${s.key}/t/${t.id}`, t.awaiting, "entry", [
      status, title(`${t.id} · ${t.title}`, "etitle"), t.parent ? el("span", "muted small", `step of ${t.parent}`) : null,
      openButton(t.file, "Open the contract"),
    ], (b) => {
      if (t.basis) {
        const p = el("p", "basis");
        p.append(el("span", "muted", t.standing ? "Approved on a standing instruction: " : "Approved on: "), el("q", null, t.basis));
        b.append(p);
      } else if (t.status === "open") {
        b.append(el("p", "muted", t.size === "trivial" ? "A trivial task: no contract to approve." : "Not approved yet."));
      }
      if (t.html) b.append(markdown(t.html, t.file));
      else if (t.size !== "trivial") b.append(el("p", "muted", "The contract file is not there."));
    });
  }

  function contractsGroup(s) {
    const tasks = s.tasks.filter((t) => !t.parent || t.html);
    return section(`${s.key}/contracts`, s.awaiting.length > 0, "group", [
      title("Contracts", "gtitle"), count(tasks.length), s.awaiting.length ? badge(`${s.awaiting.length} waiting`, "attention") : null,
    ], (b) => {
      if (!tasks.length) b.append(el("p", "muted", "No task opened yet."));
      tasks.forEach((t) => b.append(taskRow(s, t)));
    });
  }

  function reviewsGroup(s) {
    const pending = s.reviews.filter((r) => !r.passed).length;
    return section(`${s.key}/reviews`, false, "group", [
      title("Reviews", "gtitle"), count(s.reviews.length), pending ? badge(`${pending} open`, "warn") : null,
    ], (b) => {
      if (!s.reviews.length) b.append(el("p", "muted", "No commit reviewed yet."));
      s.reviews.forEach((r) => {
        b.append(section(`${s.key}/r/${r.id}`, false, "entry", [
          r.passed ? badge("passed", "done") : badge(r.open ? `${r.open} open` : "open", "warn"),
          title(`${r.id}${r.task ? ` · ${r.task}` : ""}`, "etitle"), when(r.t), openButton(r.file, "Open the review"),
        ], (e) => {
          if (r.files.length) {
            e.append(el("div", "label", "Files"));
            const ul = el("ul", "files");
            r.files.forEach((f) => ul.append(el("li", null, f)));
            e.append(ul);
          }
          if (r.kept.length) {
            e.append(el("div", "label", "Choices kept"));
            const ul = el("ul", "kept");
            r.kept.forEach((k) => {
              const li = el("li");
              li.append(el("code", null, k.where), el("div", "code-line", k.text), markdown(k.reason));
              ul.append(li);
            });
            e.append(ul);
          }
          r.answers.forEach((a) => {
            const q = el("div", "qa");
            q.append(el("div", "question", a.question), markdown(a.html));
            e.append(q);
          });
          if (!r.answers.length && !r.kept.length) e.append(el("p", "muted", "Nothing answered yet."));
        }));
      });
    });
  }

  function sessionView(s) {
    const meta = el("div", "meta");
    const label = STATE_LABEL[s.state];
    if (label) meta.append(el("span", `state ${s.state}`, label));
    meta.append(when(s.lastSeen));
    if (s.awaiting.length) meta.append(badge("contract waiting for your answer", "attention"));
    if (s.holdingCompaction) meta.append(badge("writing notes before compaction", "info"));
    const head = el("div", "shead");
    head.append(el("span", `dot ${s.state}`), title(s.title, "stitle"), el("span", "id", s.id8));
    return section(`${s.key}`, s.live, `session ${s.live ? "live" : ""}`.trim(), [head, meta], (b) => {
      if (s.current) {
        const now = el("p", "current");
        now.append(el("span", "muted", "Now: "), document.createTextNode(s.current));
        b.append(now);
      }
      b.append(progressGroup(s), contractsGroup(s), reviewsGroup(s));
    });
  }

  function repoView(r, many, showAll) {
    const wrap = el("div", "repo");
    const live = r.sessions.filter((s) => s.live).length;
    const waiting = r.sessions.filter((s) => s.awaiting.length).length;
    const head = el("div", "rhead");
    head.append(el("span", "rname", r.name));
    const facts = [`${live} running`];
    if (waiting) facts.push(`${waiting} waiting for you`);
    head.append(el("span", "muted small", facts.join(" · ")));
    wrap.append(head);
    if (!r.sessions.length) wrap.append(el("p", "muted pad", "No session with anything to show in the last day."));
    r.sessions.forEach((s) => wrap.append(sessionView(s)));
    if (r.hidden || showAll) {
      const toggle = el("button", "link", showAll ? "Show recent sessions only" : `Show ${r.hidden} older session${r.hidden === 1 ? "" : "s"}`);
      toggle.addEventListener("click", () => vscode.postMessage({ type: "showAll", value: !showAll }));
      wrap.append(toggle);
    }
    wrap.append(section(`${r.key}/ledger`, false, "group repo-group", [
      title("Assumptions kept", "gtitle"), count(r.ledger.length), r.ledgerFile && openButton(r.ledgerFile, "Open the ledger"),
    ], (b) => {
      if (!r.ledger.length) b.append(el("p", "muted", "Nothing kept at a review yet."));
      const ul = el("ul", "ledger");
      r.ledger.forEach((l) => {
        const li = el("li");
        li.append(markdown(l.html, r.ledgerFile));
        ul.append(li);
      });
      b.append(ul);
    }));
    if (r.handoffs.length) {
      wrap.append(section(`${r.key}/handoffs`, false, "group repo-group", [title("Hand-off briefs", "gtitle"), count(r.handoffs.length)], (b) => {
        r.handoffs.forEach((h, i) => {
          b.append(section(`${r.key}/h/${h.name}`, i === 0, "entry", [title(h.name, "etitle"), when(h.mtime), openButton(h.file)], (e) =>
            e.append(markdown(h.html, h.file))));
        });
      }));
    }
    return wrap;
  }

  function render(m) {
    const y = window.scrollY;
    const nodes = [];
    if (m.type === "error") {
      nodes.push(el("p", "error pad", `Sentinel's files could not be read: ${m.message}`));
    } else if (!m.repos.length) {
      nodes.push(el("p", "muted pad", m.folders
        ? "Sentinel is not active in this workspace: no .sentinel/config.toml in its folders. Run `sentinel init` in the repository."
        : "Open a folder where Sentinel is active."));
    } else {
      m.repos.forEach((r) => nodes.push(repoView(r, m.repos.length > 1, m.showAll)));
    }
    root.replaceChildren(...nodes);
    window.scrollTo(0, y);
  }

  window.addEventListener("message", (e) => {
    if (e.data && (e.data.type === "model" || e.data.type === "error")) render(e.data);
  });

  document.addEventListener("click", (e) => {
    const a = e.target instanceof Element ? e.target.closest("a[href]") : null;
    if (!a) return;
    e.preventDefault();
    const base = a.closest("[data-base]");
    vscode.postMessage({ type: "link", href: a.getAttribute("href"), base: base ? base.dataset.base : "" });
  });

  setInterval(() => {
    document.querySelectorAll(".when[data-t]").forEach((n) => {
      const t = Number(n.dataset.t);
      if (t) n.textContent = ago(t);
    });
  }, 30000);

  vscode.postMessage({ type: "ready" });
})();
