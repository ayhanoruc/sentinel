# Sentinel

> AI Coding Companion for safe, verified AI-assisted development

Sentinel is an integrated toolset designed to address the critical pitfalls of AI-assisted coding. It combines four components that work together to ensure high-quality, verified code generation.

## Features

### Rules Engine
Hierarchical coding rules that guide AI behavior:
- **Common rules**: Apply to all projects (error handling, configuration, verification)
- **Project rules**: Project-specific conventions and requirements
- **Session rules**: Temporary rules for the current session

### Clarification Protocol
Pre-implementation clarity enforcement:
- Context gathering before coding
- Structured clarification questions
- Understanding summary with approval flow

### Code Guardian
LLM-based code review after every edit:
- Injects review prompt into Claude's context after Edit/Write
- Claude analyzes code against Sentinel rules (not static analysis)
- Checks for: silent errors, magic numbers, missing validation, bare excepts
- One-command fixes for reported issues

### Living Checkpoint
AI-readable project documentation:
- Automated CHECKPOINT.md generation
- Section-by-section updates with approval
- Version history for tracking changes

## Installation

```bash
# Using pip
pip install sentinel-ai

# Using uv (recommended)
uv pip install sentinel-ai
```

## Quick Start

### 1. Initialize in your project

```bash
cd your-project
sentinel init
```

This creates:
- `.sentinel/` directory with rules and checkpoints
- `.claude/settings.json` with hook configurations
- `.mcp.json` with MCP server registration

### 2. Start a new Claude Code session

The hooks will automatically:
- Load rules at session start
- Remind about rules on every message
- Analyze code after every edit

### 3. Use the slash commands

```
/clarify Add user authentication to the API
```
Runs the clarification protocol before implementation.

```
/checkpoint init
```
Creates project documentation checkpoints.

```
/guardian-fix
```
Fixes issues reported by Guardian.

## Commands

### CLI Commands

| Command | Description |
|---------|-------------|
| `sentinel init` | Initialize Sentinel in current project |
| `sentinel status` | Show Sentinel status |
| `sentinel help` | Show help information |

### Slash Commands (in Claude Code)

| Command | Description |
|---------|-------------|
| `/clarify <task>` | Run clarification protocol |
| `/checkpoint init` | Create documentation checkpoints |
| `/checkpoint update` | Update existing checkpoints |
| `/checkpoint status` | Show checkpoint freshness |
| `/guardian-fix` | Fix Guardian-reported issues |
| `/rules show` | Display active rules |
| `/rules add` | Add a session rule |

### MCP Tools (for agent use)

| Tool | Description |
|------|-------------|
| `sentinel_get_rules()` | Get active rules (call if rules not visible) |
| `sentinel_add_rule(rule)` | Add a temporary session rule |
| `sentinel_analyze_code(code)` | Analyze code for issues |

## Configuration

### Rule Format

Rules use a simple markdown format:

```markdown
## Category Name

- MUST: Requirement that must be followed
- SHOULD: Strong recommendation
- AVOID: Pattern to avoid
- NEVER: Hard prohibition

## [Tag: ml-pipeline]
- MUST: Check for lookahead bias
```

### Rule Locations

| Level | Location | Scope |
|-------|----------|-------|
| Common | `~/.sentinel/rules/common.md` | All projects |
| Project | `.sentinel/rules/project.md` | This project |
| Session | In-memory | Current session |

### Hook Configuration

Hooks are configured in `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [{
      "hooks": [{"type": "command", "command": "sentinel-hook session-start"}]
    }],
    "UserPromptSubmit": [{
      "hooks": [{"type": "command", "command": "sentinel-hook user-prompt"}]
    }],
    "PostToolUse": [{
      "matcher": "Edit|Write",
      "hooks": [{"type": "command", "command": "sentinel-hook post-edit"}]
    }]
  }
}
```

## Guardian Checks

Guardian is **LLM-based** - it injects a review prompt after code edits, and Claude analyzes the code. These are the patterns Claude is asked to look for:

### Silent Errors
```python
# Detected: .get() with default that masks missing data
value = data.get("key", "default")

# Suggested fix:
value = data.get("key")
if value is None:
    raise ValueError("Missing required field: key")
```

### Magic Numbers
```python
# Detected: Hardcoded number in function
window = prices[-20:]

# Suggested fix:
LOOKBACK_WINDOW = 20  # Periods for rolling calculation
window = prices[-LOOKBACK_WINDOW:]
```

### Missing Validation
```python
# Detected: Nested access without null check
item = response["data"]["items"][0]

# Suggested fix:
data = response.get("data", {}).get("items", [])
if not data:
    raise ValueError("Invalid response structure")
item = data[0]
```

## Project Structure

```
your-project/
├── .sentinel/
│   ├── rules/
│   │   ├── project.md          # Project-specific rules
│   │   └── session.md          # Session rules (gitignored)
│   └── checkpoints/
│       └── <group>/
│           ├── CHECKPOINT.md   # Current checkpoint
│           └── history/        # Version history
├── .claude/
│   └── settings.json           # Hook configuration
└── .mcp.json                   # MCP server registration
```

## Background

Sentinel was created based on lessons learned from extensive AI-assisted development across trading ML pipelines, robotics systems, and mobile applications. It addresses the critical pitfalls identified in ["The Double-Edged Sword: AI Coding Agents in ML System Development"](https://chimeralabs.tech/blog/ai-coding-agents-double-edged-sword).

## License

MIT

## Contributing

Contributions are welcome! Please read our contributing guidelines before submitting PRs.
