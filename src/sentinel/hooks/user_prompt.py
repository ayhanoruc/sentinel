"""UserPromptSubmit hook - Injects rules on every message."""

from __future__ import annotations

import re
from pathlib import Path

from ..rules import get_merged_rules
from .context_cleanup import process_transcript, save_snapshot

# ===========================================================================
# CONFIGURATION
# ===========================================================================
IMPLEMENTATION_KEYWORDS = [
    r"\badd\b", r"\bimplement\b", r"\bcreate\b", r"\bbuild\b", r"\bfix\b",
    r"\bupdate\b", r"\bmodify\b", r"\bchange\b", r"\brefactor\b", r"\bwrite\b",
]


def is_implementation_task(prompt: str) -> bool:
    """Check if the prompt looks like an implementation task."""
    prompt_lower = prompt.lower()
    if prompt_lower.startswith("/"):
        return False
    return any(re.search(p, prompt_lower) for p in IMPLEMENTATION_KEYWORDS)


def _handle_clear_redundant(input_data: dict) -> dict:
    """
    Handle /clear_redundant command.

    Reads the transcript, processes it, saves snapshot, and instructs to run /clear.
    """
    transcript_path = input_data.get("transcript_path", "")

    if not transcript_path:
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": """# Context Cleanup Failed

Could not find transcript path. This may be a Claude Code version issue.

You can manually create a snapshot by summarizing the key points of this conversation,
then saving to `.sentinel/snapshots/context_snapshot.md` before running `/clear`.
""",
            }
        }

    # Process transcript and save snapshot
    snapshot_content = process_transcript(transcript_path)
    snapshot_path = save_snapshot(snapshot_content)

    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": f"""# Context Snapshot Created - Index Generation Required

Snapshot saved to: `{snapshot_path}`

## Your Task: Generate Index

Read the snapshot and prepend an index header. Use this exact format:

```markdown
## Index

### Metadata
- Messages: [count from header]
- Date: [today's date]
- Project: [project name from context]

### Topics
- [3-5 bullet points summarizing main topics discussed]

### Key Decisions
- [2-4 bullet points of important decisions made]

### Files Touched
- Created: [files created]
- Modified: [files modified]
- Read: [key files read for context]

---
```

**Steps:**
1. Read `{snapshot_path}` to understand the conversation
2. Generate the index based on content
3. Use Edit to prepend the index right after the "---" line (after "Original messages: X")
4. Confirm done, then tell user to run `/clear`
""",
        }
    }


def handle_user_prompt(input_data: dict) -> dict:
    """
    Handle UserPromptSubmit hook event.

    Injects Sentinel rules into context on every message.
    Also handles /clear_redundant command for context cleanup.
    """
    prompt = input_data.get("prompt", "")

    # Check for clear_redundant command (with or without slash)
    prompt_lower = prompt.strip().lower()
    if prompt_lower.startswith("clear_redundant") or prompt_lower.startswith("/clear_redundant"):
        return _handle_clear_redundant(input_data)

    # Load rules
    rules = get_merged_rules()

    context_parts = []

    if rules.strip():
        context_parts.append("# SENTINEL RULES")
        context_parts.append(rules)
        context_parts.append("---")
        context_parts.append("*Follow these rules. Call `sentinel_get_rules()` if not visible.*")

    # Suggest clarify for implementation tasks
    if prompt and is_implementation_task(prompt):
        context_parts.append("")
        context_parts.append("*Implementation task detected. Consider `/clarify` first.*")

    # Use hookSpecificOutput format as per Claude Code docs
    if context_parts:
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "\n".join(context_parts),
            }
        }
    return {}
