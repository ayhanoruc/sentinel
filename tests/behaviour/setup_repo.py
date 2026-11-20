"""A scratch repository for a behavioural run, with Sentinel active in it.

    python setup_repo.py <folder> <path to sentinel-hook> [--big N] [--config "<toml>"]

`--big N` adds N text files of about 12,000 tokens each under data/ (to fill a session's context); file 3 and file 7
each hold one line with a code word, so a run can be asked something only a full read answers.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from sentinel import install  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("folder")
ap.add_argument("hook")
ap.add_argument("--big", type=int, default=0)
ap.add_argument("--config", default="")
a = ap.parse_args()

repo = Path(a.folder).resolve()
for extra in (repo, repo.parent / f"{repo.name}-home", repo.parent / f"{repo.name}-debug.jsonl"):
    if extra.is_dir():
        shutil.rmtree(extra)
    elif extra.is_file():
        extra.unlink()
(repo / "src").mkdir(parents=True)
(repo / "src" / "app.py").write_text('def greet(name):\n    return "hello " + name\n', encoding="utf-8")
(repo / "README.md").write_text("# demo\n", encoding="utf-8")
(repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
words = {3: "the code word of part 3 is HERON", 7: "the code word of part 7 is BASALT"}
for i in range(1, a.big + 1):
    lines = [f"Record {i}-{n}: station {n * 7 % 113} reported value {n * 31 % 997} at minute {n % 60}, status nominal, "
             f"operator note number {n * 13 % 401} unchanged." for n in range(1, 381)]
    if i in words:
        lines.insert(190, words[i])
    (repo / "data").mkdir(exist_ok=True)
    (repo / "data" / f"part{i}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def git(*args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


git("init", "-q", "-b", "main")
git("config", "user.email", "t@example.com")
git("config", "user.name", "T")
git("add", "-A")
git("commit", "-q", "-m", "first")


class A:
    dir, local, hook_command = str(repo), False, a.hook


code, text = install.init(A)
if a.config:
    cfg = repo / ".sentinel" / "config.toml"
    cfg.write_text(a.config.replace("\\n", "\n"), encoding="utf-8")
print(text.splitlines()[0])
print("config:", (repo / ".sentinel" / "config.toml").read_text(encoding="utf-8")[:200].replace("\n", " | ") if a.config else "default")
