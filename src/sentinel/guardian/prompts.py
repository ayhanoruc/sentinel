"""Guardian prompt templates for LLM-based code analysis."""

from __future__ import annotations


def get_analysis_prompt(
    code: str,
    file_path: str | None = None,
    rules_context: str | None = None,
) -> str:
    """
    Generate an analysis prompt for the LLM to review code.

    Args:
        code: The code to analyze.
        file_path: Optional file path for context.
        rules_context: The actual Sentinel rules to check against.

    Returns:
        Prompt string for LLM analysis.
    """
    file_info = f" in `{file_path}`" if file_path else ""

    if rules_context and rules_context.strip():
        rules_section = f"""**Active Sentinel Rules:**

{rules_context}

Review the code against ALL the rules above."""
    else:
        rules_section = """**No Sentinel rules configured.**

Check for common issues:
- Silent errors (defaults hiding missing required data)
- Magic numbers (hardcoded values in function bodies)
- Missing validation (unsafe dict/list access)
- Bare except clauses (swallowing errors)"""

    return f"""## SENTINEL GUARDIAN - Code Analysis

Review the following code{file_info} for potential issues.

{rules_section}

**Code to Review:**
```
{code}
```

**Instructions:**
- Report only genuine issues that could cause problems
- Be concise - one line per issue with line reference if applicable
- Don't be pedantic about style - focus on correctness and safety
- If no significant issues found, say "No issues found"
- Format: `[ISSUE] line X: brief description`
"""


def get_fix_prompt(issues: str, code: str, file_path: str | None = None) -> str:
    """
    Generate a fix prompt for the LLM to correct reported issues.

    Args:
        issues: The issues to fix (from previous analysis).
        code: The original code.
        file_path: Optional file path for context.

    Returns:
        Prompt string for LLM to generate fixes.
    """
    file_info = f" in `{file_path}`" if file_path else ""

    return f"""## SENTINEL GUARDIAN - Fix Issues

Fix the following issues{file_info}:

**Issues to Fix:**
{issues}

**Original Code:**
```
{code}
```

**Fix Patterns:**

For **Silent Errors** - Replace defaults with validation:
```python
# Before
value = data.get("key", "default")

# After
value = data.get("key")
if value is None:
    raise ValueError("Missing required field: key")
```

For **Magic Numbers** - Extract to named constants:
```python
# Before
window = prices[-20:]

# After
LOOKBACK_WINDOW = 20  # Number of periods for rolling calculation
window = prices[-LOOKBACK_WINDOW:]
```

For **Missing Validation** - Add defensive checks:
```python
# Before
item = response["data"]["items"][0]

# After
data = response.get("data")
if not data or "items" not in data or not data["items"]:
    raise ValueError("Invalid response: missing data.items")
item = data["items"][0]
```

For **Bare Except** - Catch specific exceptions:
```python
# Before
except:
    pass

# After
except (ValueError, KeyError) as e:
    logger.error(f"Operation failed: {{e}}")
    raise
```

**Instructions:**
- Apply the appropriate fix pattern for each issue
- Preserve the original code's intent and functionality
- Add clear error messages with context
- Show the fixed code with brief explanation
"""
