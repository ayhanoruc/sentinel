"""Sentinel MCP Server - Main entry point."""

from __future__ import annotations

import logging
from mcp.server.fastmcp import FastMCP

from .rules import (
    get_merged_rules,
    add_session_rule,
    add_project_rule,
    add_common_rule,
    clear_session_rules,
)
from .guardian import get_analysis_prompt

# Configure logging (never use print in MCP servers!)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("sentinel")

# ===========================================================================
# MCP SERVER SETUP
# ===========================================================================
mcp = FastMCP(
    "sentinel",
    instructions="""Sentinel is your AI Coding Companion for safe, verified development.

**How Guardian Works:**
Guardian is LLM-based, not static analysis. After you edit code, the post-hook injects
a review prompt asking you to check the code against Sentinel rules. You do the analysis.

**Available tools:**
- sentinel_get_rules: Get active coding rules (call if rules aren't visible)
- sentinel_add_session_rule: Add temporary rule (in-memory, this session only)
- sentinel_add_project_rule: Add persistent rule to project (.sentinel/rules/project.md)
- sentinel_add_common_rule: Add persistent rule to global (~/.sentinel/rules/common.md)
- sentinel_clear_session_rules: Clear session-specific rules
- sentinel_analyze_code: Get a review prompt for manual code analysis

**Available prompts (slash commands):**
- /clarify: Run clarification protocol before implementation
- /checkpoint: Manage project documentation checkpoints
- /guardian-fix: Fix issues reported by Guardian

Always follow the Sentinel rules when writing code. If you can't see the rules,
call sentinel_get_rules() to load them into context.""",
)


# ===========================================================================
# MCP TOOLS - Rules Engine
# ===========================================================================
@mcp.tool()
async def sentinel_get_rules(tags: list[str] | None = None) -> str:
    """
    Get active Sentinel coding rules.

    Call this tool if the rules aren't visible in your context.
    Rules guide your code generation to avoid common pitfalls.

    Args:
        tags: Optional list of tags to filter rules (e.g., ["ml-pipeline", "api-integration"])

    Returns:
        Markdown-formatted rules document.
    """
    logger.info(f"Getting rules with tags: {tags}")

    rules = get_merged_rules(tags)

    if not rules.strip():
        return "No rules configured. Run `sentinel init` in your project to set up default rules."

    header = """# Sentinel Active Rules

> Follow these rules when generating or modifying code.

"""
    footer = """

---
*Rules loaded from: common + project + session*
*Call `sentinel_add_rule()` to add session-specific rules.*
"""

    return header + rules + footer


@mcp.tool()
async def sentinel_add_session_rule(rule: str) -> str:
    """
    Add a temporary rule for this session only (in-memory).

    The rule will be active until the session ends or cleared explicitly.
    Use this for quick, temporary rules you don't want to persist.

    Args:
        rule: The rule text. Format: "LEVEL: description" where LEVEL is MUST/SHOULD/AVOID/NEVER
              Example: "MUST: Use async/await for all database operations"
              Example: "AVOID: Direct SQL queries, use ORM instead"

    Returns:
        Confirmation message.
    """
    if not rule or not rule.strip():
        return "Error: Rule cannot be empty."

    logger.info(f"Adding session rule: {rule}")
    return add_session_rule(rule.strip())


@mcp.tool()
async def sentinel_add_project_rule(rule: str, category: str = "Project Rules") -> str:
    """
    Add a persistent rule to project rules (.sentinel/rules/project.md).

    The rule will persist across sessions and apply to this project only.
    Use this for project-specific conventions and requirements.

    Args:
        rule: The rule text. Format: "LEVEL: description" where LEVEL is MUST/SHOULD/AVOID/NEVER
              Example: "MUST: Use TypeScript strict mode"
              Example: "SHOULD: Follow existing naming conventions"
        category: Category to add under (default: "Project Rules")
                  Example: "Error Handling", "Testing", "API Design"

    Returns:
        Confirmation message.
    """
    if not rule or not rule.strip():
        return "Error: Rule cannot be empty."

    logger.info(f"Adding project rule [{category}]: {rule}")
    return add_project_rule(rule.strip(), category)


@mcp.tool()
async def sentinel_add_common_rule(rule: str, category: str = "Custom Rules") -> str:
    """
    Add a persistent rule to global/common rules (~/.sentinel/rules/common.md).

    The rule will persist across sessions and apply to ALL projects.
    Use this for personal coding standards you want everywhere.

    Args:
        rule: The rule text. Format: "LEVEL: description" where LEVEL is MUST/SHOULD/AVOID/NEVER
              Example: "MUST: Always use type hints in Python"
              Example: "NEVER: Commit .env files"
        category: Category to add under (default: "Custom Rules")
                  Example: "Security", "Code Style", "Documentation"

    Returns:
        Confirmation message.
    """
    if not rule or not rule.strip():
        return "Error: Rule cannot be empty."

    logger.info(f"Adding common rule [{category}]: {rule}")
    return add_common_rule(rule.strip(), category)


@mcp.tool()
async def sentinel_clear_session_rules() -> str:
    """
    Clear all session-specific rules.

    Common and project rules will remain active.

    Returns:
        Confirmation message.
    """
    logger.info("Clearing session rules")
    return clear_session_rules()


# ===========================================================================
# MCP TOOLS - Guardian
# ===========================================================================
@mcp.tool()
async def sentinel_analyze_code(
    code: str,
    file_path: str | None = None,
) -> str:
    """
    Get a Guardian analysis prompt for code review.

    This returns a prompt that guides you to review code for common issues.
    The actual analysis is done by you (the LLM), not by static checks.

    Use this when you want to manually trigger a code review.
    Guardian also runs automatically after Edit/Write via hooks.

    Args:
        code: The code content to analyze.
        file_path: Optional file path for context.

    Returns:
        Analysis prompt with the code and review guidelines.
    """
    logger.info(f"Generating analysis prompt for: {file_path or 'inline'}")

    # Get current rules for context
    rules = get_merged_rules()

    # Generate the analysis prompt
    prompt = get_analysis_prompt(
        code=code,
        file_path=file_path,
        rules_context=rules if rules.strip() else None,
    )

    return prompt


# ===========================================================================
# MCP PROMPTS - Slash Commands
# ===========================================================================
@mcp.prompt()
def clarify(task: str) -> str:
    """
    Run the Sentinel Clarification Protocol before implementing a task.

    This protocol ensures thorough understanding through:
    1. Context gathering (related files, patterns, docs)
    2. Clarification questions
    3. Understanding summary for approval

    Args:
        task: Description of the task to clarify.
    """
    return f"""# Sentinel Clarification Protocol

## Task
{task}

## Instructions

Before implementing this task, follow the Sentinel Clarification Protocol:

### Phase 1: Context Gathering
1. Identify related files and modules in the codebase
2. Read existing patterns and conventions
3. Check for relevant documentation
4. Load applicable rules: call `sentinel_get_rules()` if not visible
5. Note any architectural constraints

### Phase 2: Clarification Questions
Based on your context gathering, ask clarifying questions about:
- **Scope**: What specific components/endpoints are affected?
- **Approach**: What technical approach should be used?
- **Edge Cases**: How should edge cases be handled?
- **Integration**: How does this integrate with existing code?
- **Constraints**: Are there performance/security/compatibility requirements?

Present your questions clearly, grouped by category.

### Phase 3: Understanding Summary
After receiving answers, provide a structured summary:

```
## Implementation Plan

**Approach:** [Describe the technical approach]
**Scope:**
- New: [List new files/components]
- Modified: [List files to modify]
**Key Decisions:**
- [Decision 1]
- [Decision 2]

[Wait for user approval before proceeding]
```

Only proceed with implementation after explicit approval.

---
*Sentinel Clarification Protocol - Ensuring clarity before code*
"""


@mcp.prompt()
def checkpoint(action: str = "status") -> str:
    """
    Manage project documentation checkpoints.

    Actions:
    - init: Create initial checkpoint structure
    - update: Update existing checkpoints with recent changes
    - status: Show checkpoint freshness and coverage

    Args:
        action: The action to perform (init, update, or status).
    """
    if action == "init":
        return """# Sentinel Checkpoint Init

## Instructions

Create project documentation checkpoints by following these steps:

### Phase 1: Repository Analysis
1. Scan the directory structure
2. Identify logical boundaries (backend, frontend, mobile, infra, etc.)
3. Detect the tech stack in each area
4. Estimate documentation scope per area

### Phase 2: Group Proposal
Present a proposal like:

```
Based on analysis, I suggest these checkpoint groups:

- /backend/CHECKPOINT.md (~X lines)
  └─ Description of what this covers

- /frontend/CHECKPOINT.md (~X lines)
  └─ Description of what this covers

[Approve] [Modify Groups]
```

Wait for user approval before proceeding.

### Phase 3: Checkpoint Generation
For each approved group:

1. **Deep Analysis**: Read all relevant files, identify patterns, data flows, key decisions
2. **Propose Index**: Show the table of contents, wait for approval
3. **Write Sections** - CRITICAL WORKFLOW:
   ```
   For each section:
   a) Show preview of section content to user
   b) Wait for user approval
   c) IMMEDIATELY write/append that section to the file using Edit tool
   d) Confirm section was written
   e) Move to next section
   ```

**CRITICAL**: Write to the file IMMEDIATELY after each section is approved.
- Do NOT collect all approvals first then write at the end
- Do NOT wait until all sections are reviewed
- Each approval → immediate file write → then next section
- Use Edit tool to append each section incrementally

**IMPORTANT**: Do NOT one-shot the entire file. This is iterative work - the user wants to review each section before you proceed to the next.

### Checkpoint Format Rules
- Max 2000 lines per checkpoint
- No verbosity - concise descriptions only
- No code dumps (pseudocode only if critical)
- Focus on: architecture, data flows, integrations, core logic
- Always include: current state, setup commands
- Include Decision Log for architectural choices

### Quick Reference Format
Start each checkpoint with:
```markdown
## Quick Reference

| Section | Lines | Keywords |
|---------|-------|----------|
| [Name] | [range] | [searchable terms] |
```

---
*Sentinel Living Checkpoint - AI-readable project documentation*
"""
    elif action == "update":
        return """# Sentinel Checkpoint Update

## Instructions

Update existing checkpoints with recent changes:

### Phase 1: Change Detection
1. Identify files changed since last checkpoint update
2. Map changes to relevant checkpoint sections
3. Determine which checkpoints need updates

### Phase 2: Targeted Update
For each affected checkpoint:
1. Read the current checkpoint
2. Read the changed code
3. Identify what needs to be added/modified
4. Preserve existing structure
5. Add reasoning for changes
6. Update "Last updated" timestamp
7. Update Decision Log if architectural changes were made

### Phase 3: Version Archive (Optional)
If significant changes, offer to archive the previous version:
- Copy to `.sentinel/checkpoints/<group>/history/YYYY-MM-DD.md`
- This enables diffing between versions

### Rules
- Don't destroy existing content
- Be concise - same rules as init
- Add clear reasoning for changes

---
*Sentinel Living Checkpoint - Keeping documentation in sync*
"""
    else:  # status
        return """# Sentinel Checkpoint Status

## Instructions

Check the status of project checkpoints:

1. Find all CHECKPOINT.md files in the project
2. For each checkpoint:
   - Read the "Last updated" timestamp
   - Compare against recent file modifications in that area
   - Determine if checkpoint is current, stale, or missing

3. Present a summary:

```
## Checkpoint Status

| Checkpoint | Last Updated | Status | Action Needed |
|------------|--------------|--------|---------------|
| /backend/CHECKPOINT.md | 2026-01-15 | Stale | 5 files changed |
| /frontend/CHECKPOINT.md | 2026-01-20 | Current | - |
| /mobile/ | - | Missing | Run /checkpoint init |

Recommendations:
- Run `/checkpoint update` to refresh stale checkpoints
- Run `/checkpoint init` to create missing checkpoints
```

---
*Sentinel Living Checkpoint - Documentation health check*
"""


@mcp.prompt()
def guardian_fix(ids: str = "all") -> str:
    """
    Fix issues reported by Guardian.

    Args:
        ids: Issue IDs to fix (e.g., "1,3,5") or "all" for all issues.
    """
    return f"""# Sentinel Guardian Fix

## Instructions

Fix the Guardian issues with IDs: {ids}

### Process
1. Review the most recent Guardian report in the conversation
2. For each issue to fix:
   - Understand the problem
   - Apply the suggested fix
   - Verify the fix doesn't break anything

### Fix Patterns

**SILENT_ERROR** - Replace default with validation:
```python
# Before
value = data.get("key", "default")

# After
value = data.get("key")
if value is None:
    raise ValueError("Missing required field: key")
```

**MAGIC_NUMBER** - Extract to constant:
```python
# Before
window = prices[-20:]

# After
LOOKBACK_WINDOW = 20  # Number of periods for rolling calculation

window = prices[-LOOKBACK_WINDOW:]
```

**MISSING_CHECK** - Add validation:
```python
# Before
item = response["data"]["items"][0]

# After
data = response.get("data")
if not data or "items" not in data or not data["items"]:
    raise ValueError("Invalid response structure")
item = data["items"][0]
```

**BARE_EXCEPT** - Catch specific exceptions:
```python
# Before
except:
    pass

# After
except (ValueError, KeyError) as e:
    logger.error(f"Processing failed: {{e}}")
    raise
```

Apply fixes and confirm each change.

---
*Sentinel Guardian Fix - Automated issue resolution*
"""


@mcp.prompt()
def clear_redundant() -> str:
    """
    Clear redundant context while preserving conversation verbatim.

    Processes the transcript: keeps all text, compresses only tool outputs.
    Then triggers /clear and reinjects the processed context.
    """
    return """# Context Cleanup

To clean up the context while preserving your conversation:

**Step 1:** Type exactly this as a chat message (not a command):
```
clear_redundant
```

The Sentinel hook will:
- Read your full transcript
- Keep all user/assistant text VERBATIM
- Compress tool outputs (file contents, grep results) to 1-liners
- Save to `.sentinel/snapshots/context_snapshot.md`

**Step 2:** After the hook confirms, run `/clear`

**Step 3:** The SessionStart hook will inject the processed context automatically.

---
*This MCP prompt cannot access the transcript directly. The hook can.*
"""


@mcp.prompt()
def rules(action: str = "show") -> str:
    """
    Manage Sentinel rules.

    Actions:
    - show: Display all active rules
    - add: Add a new session rule

    Args:
        action: The action to perform.
    """
    if action == "add":
        return """# Add Sentinel Rule

To add a session rule, use the `sentinel_add_rule` tool:

```
sentinel_add_rule("MUST: [Your rule here]")
```

Rule format:
- MUST: Requirement that must be followed
- SHOULD: Strong recommendation
- AVOID: Pattern to avoid
- NEVER: Hard prohibition

Examples:
- "MUST: Use TypeScript strict mode"
- "SHOULD: Prefer composition over inheritance"
- "AVOID: Mutable global state"
- "NEVER: Commit credentials to repository"

The rule will be active for this session only.
"""
    else:  # show
        return """# Sentinel Rules

To view active rules, call the `sentinel_get_rules` tool.

Rules are loaded from three sources:
1. **Common** (~/.sentinel/rules/common.md) - Global rules for all projects
2. **Project** (.sentinel/rules/project.md) - Project-specific rules
3. **Session** - Temporary rules added during this session

Call `sentinel_get_rules()` to load all active rules into context.
Call `sentinel_get_rules(tags=["ml-pipeline"])` to filter by tags.
"""


# ===========================================================================
# ENTRY POINT
# ===========================================================================
def main():
    """Run the Sentinel MCP server."""
    logger.info("Starting Sentinel MCP server")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
