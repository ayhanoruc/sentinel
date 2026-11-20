"""The flows. One file each; this list is the order their answers are joined in.

A module has `SECTION` (its table in config.toml; the flow runs when `enabled` is true there), handlers named by
HANDLERS for the hook events it cares about, and optionally `cli(sub)` to add its commands. A private module in
`~/.sentinel/modules/*.py` has the same shape and is loaded after these.
"""
from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from .. import core

ORDER = ["context", "crash", "rules", "tasks", "testing", "gate", "board", "review", "progress", "handoff"]

HANDLERS = {
    "SessionStart": "on_session_start",
    "UserPromptSubmit": "on_user_prompt_submit",
    "PreToolUse": "on_pre_tool_use",
    "PostToolUse": "on_post_tool_use",
    "Stop": "on_stop",
    "Notification": "on_notification",
    "PreCompact": "on_pre_compact",
    "SessionEnd": "on_session_end",
}


def load() -> list[ModuleType]:
    mods = [importlib.import_module(f"{__name__}.{name}") for name in ORDER]
    folder = core.home() / "modules"
    if folder.is_dir():
        for f in sorted(folder.glob("*.py")):
            spec = importlib.util.spec_from_file_location(f"sentinel_user_{f.stem}", f)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mods.append(mod)
    return mods
