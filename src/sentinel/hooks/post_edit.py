"""PostToolUse hook - Guardian LLM-based analysis after Edit/Write."""

from __future__ import annotations

from ..rules import get_merged_rules

# ===========================================================================
# CONFIGURATION
# ===========================================================================
# File extensions to analyze
ANALYZABLE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
}

# Minimum content size to trigger analysis (skip tiny changes)
MIN_CONTENT_SIZE = 100



def should_analyze(file_path: str, content: str) -> bool:
    """
    Check if the file should be analyzed.

    Args:
        file_path: Path to the file.
        content: The file content or changed content.

    Returns:
        True if the file should be analyzed.
    """
    if not file_path or not content:
        return False

    # Check extension
    ext = "." + file_path.rsplit(".", 1)[-1] if "." in file_path else ""
    if ext.lower() not in ANALYZABLE_EXTENSIONS:
        return False

    # Check minimum size
    if len(content) < MIN_CONTENT_SIZE:
        return False

    return True


def handle_post_edit(input_data: dict) -> dict | None:
    """
    Handle PostToolUse hook event for Edit/Write tools.

    Injects Guardian analysis prompt with actual Sentinel rules for LLM review.
    The actual analysis is done by Claude, not by static checks.

    Args:
        input_data: Hook input data containing tool info and file content.

    Returns:
        Hook output with Guardian analysis prompt as additional context.
    """
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})

    # Only process Edit and Write tools
    if tool_name not in ("Edit", "Write"):
        return None

    # Extract file path and content
    file_path = tool_input.get("file_path", "")

    # For Edit, analyze the new_string; for Write, analyze content
    if tool_name == "Edit":
        content = tool_input.get("new_string", "")
        change_type = "edited"
    else:
        content = tool_input.get("content", "")
        change_type = "written"

    # Check if we should analyze this
    if not should_analyze(file_path, content):
        return None

    # Load actual rules from common + project + session
    rules = get_merged_rules()

    # Build rules section
    if rules.strip():
        rules_section = f"""**Active Sentinel Rules:**

{rules}

Review the code against ALL the rules above."""
    else:
        rules_section = """**No Sentinel rules configured.**

Check for common issues:
- Silent errors (defaults hiding missing data)
- Magic numbers (hardcoded values)
- Missing validation (unsafe access)
- Bare except clauses"""

    # Build the Guardian analysis prompt for LLM
    analysis_prompt = f"""
---
## SENTINEL GUARDIAN - Code Review

You just {change_type} code in `{file_path}`. Briefly review this code.

{rules_section}

**Code to review:**
```
{content}
```

**Instructions:**
- If you find rule violations or issues, report them briefly
- If no significant issues, just continue (no need to mention Guardian)
- Don't be pedantic - focus on genuine risks
- Format issues as: `[ISSUE] line X: description`

---
"""

    return {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": analysis_prompt,
        }
    }
