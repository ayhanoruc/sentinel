"""SessionStart hook - Injects rules at session start."""

from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime

from ..rules import get_merged_rules


def _get_snapshot_path() -> Path:
    """Get the path to the context snapshot file."""
    return Path.cwd() / ".sentinel" / "snapshots" / "context_snapshot.md"


def _check_and_load_snapshot() -> str | None:
    """
    Check if a context snapshot exists and load it.

    Returns the snapshot content if found, None otherwise.
    Also moves the snapshot to history after loading.
    """
    snapshot_path = _get_snapshot_path()

    if not snapshot_path.exists():
        return None

    try:
        content = snapshot_path.read_text(encoding="utf-8")

        # Move to history to prevent re-injection
        history_dir = snapshot_path.parent / "history"
        history_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        history_path = history_dir / f"snapshot_{timestamp}.md"
        snapshot_path.rename(history_path)

        return content
    except (OSError, IOError):
        return None


def handle_session_start(input_data: dict) -> dict:
    """
    Handle SessionStart hook event.

    Injects the merged rules into the session context at startup.
    Also checks for and injects context snapshots from /clear_redundant.

    Args:
        input_data: Hook input data from Claude Code.

    Returns:
        Hook output with rules as additional context.
    """
    # Check for context snapshot (from /clear_redundant)
    snapshot = _check_and_load_snapshot()

    # Load merged rules
    rules = get_merged_rules()

    # Build the context parts
    context_parts = []

    # Add snapshot if present (highest priority - this is the preserved context)
    if snapshot:
        context_parts.append(f"""# Restored Context (from /clear_redundant)

{snapshot}

---
*Context restored by Sentinel. Previous conversation history preserved above.*

""")

    # Add rules
    if rules.strip():
        context_parts.append(f"""# Sentinel Rules (Active for this Session)

{rules}

---

## Rule Recall Instructions

These rules guide your code generation. Follow them when writing or modifying code.

If you cannot see these rules later in the conversation, call:
```
sentinel_get_rules()
```
to reload them into context.

---
*Sentinel - AI Coding Companion*
""")
    else:
        context_parts.append("""# Sentinel Active

Sentinel is active but no rules are configured.
Run `sentinel init` in your project to set up default rules.

If you need rules during this session, use `sentinel_add_rule()` to add them.
""")

    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(context_parts),
        }
    }
