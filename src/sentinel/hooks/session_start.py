"""SessionStart hook - Injects rules at session start."""

from __future__ import annotations

from ..rules import get_merged_rules


def handle_session_start(input_data: dict) -> dict:
    """
    Handle SessionStart hook event.

    Injects the merged rules into the session context at startup.

    Args:
        input_data: Hook input data from Claude Code.

    Returns:
        Hook output with rules as additional context.
    """
    # Load merged rules
    rules = get_merged_rules()

    if not rules.strip():
        # No rules configured, just add the recall warning
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": """# Sentinel Active

Sentinel is active but no rules are configured.
Run `sentinel init` in your project to set up default rules.

If you need rules during this session, use `sentinel_add_rule()` to add them.
""",
            }
        }

    # Build context with rules and recall warning
    context = f"""# Sentinel Rules (Active for this Session)

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
"""

    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
