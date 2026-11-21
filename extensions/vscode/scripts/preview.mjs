// Writes a stand-alone HTML preview of the panel for a repository, with the editor's dark theme colours, so the panel
// can be looked at (and screenshot) without the editor:  node scripts/preview.mjs <repo> <out.html> [--all] [--light]
// Run `npm test` first: it compiles the model and the renderer to out/.
import { createRequire } from "module";
import * as fs from "fs";
import * as path from "path";

const require = createRequire(import.meta.url);
const { readRepo } = require("../out/src/model.js");
const { view } = require("../out/src/render.js");

const [repo, out] = process.argv.slice(2);
const all = process.argv.includes("--all");
const light = process.argv.includes("--light");
const now = Date.now() / 1000;
const model = { type: "model", repos: view([readRepo(path.resolve(repo), { now })], now, 24, all), showAll: all, folders: 1 };
const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const css = fs.readFileSync(path.join(here, "..", "media", "panel.css"), "utf8");
const js = fs.readFileSync(path.join(here, "..", "media", "panel.js"), "utf8");
const theme = light
  ? "--vscode-foreground:#3b3b3b;--vscode-sideBar-background:#f8f8f8;--vscode-descriptionForeground:#717171;--vscode-badge-background:#cccccc;--vscode-badge-foreground:#3b3b3b;--vscode-textLink-foreground:#005fb8;--vscode-list-hoverBackground:#e8e8e8;--vscode-textCodeBlock-background:#e9e9e9;--vscode-charts-green:#388a34;--vscode-charts-yellow:#bf8803;--vscode-charts-red:#e51400;--vscode-editorWarning-foreground:#bf8803;"
  : "--vscode-foreground:#cccccc;--vscode-sideBar-background:#181818;--vscode-descriptionForeground:#9d9d9d;--vscode-badge-background:#616161;--vscode-badge-foreground:#f8f8f8;--vscode-textLink-foreground:#4daafc;--vscode-list-hoverBackground:#2a2d2e;--vscode-textCodeBlock-background:#2b2b2b;--vscode-charts-green:#89d185;--vscode-charts-yellow:#cca700;--vscode-charts-red:#f14c4c;--vscode-editorWarning-foreground:#cca700;";
const page = `<!DOCTYPE html><html><head><meta charset="UTF-8"><style>:root{${theme}--vscode-font-family:'Segoe UI',system-ui,sans-serif;--vscode-font-size:13px;--vscode-editor-font-family:Consolas,monospace;}
${css}</style></head><body><div id="root"></div>
<script>window.acquireVsCodeApi=()=>({getState:()=>null,setState:()=>{},postMessage:(m)=>{if(m.type==="ready")setTimeout(()=>window.postMessage(${JSON.stringify(model).replace(/</g, "\\u003c")},"*"),0);}});</script>
<script>${js}</script></body></html>`;
fs.writeFileSync(out, page);
console.log(`wrote ${out}: ${model.repos[0].sessions.length} sessions shown, ${model.repos[0].hidden} hidden`);
