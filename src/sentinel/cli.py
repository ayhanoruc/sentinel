"""Sentinel CLI - Command line interface for setup and management."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# ===========================================================================
# CONFIGURATION
# ===========================================================================
GLOBAL_SENTINEL_DIR = Path.home() / ".sentinel"
PROJECT_SENTINEL_DIR = Path(".sentinel")
DEFAULT_RULES_FILE = Path(__file__).parent / "rules" / "defaults" / "common.md"


def init_command(args: list[str]) -> int:
    """
    Initialize Sentinel in the current project.

    Creates:
    - .sentinel/ directory structure
    - Default project rules
    - Claude Code hooks configuration
    - MCP server registration
    """
    print("Initializing Sentinel...")

    project_dir = Path.cwd()
    sentinel_dir = project_dir / ".sentinel"
    claude_dir = project_dir / ".claude"

    # Create .sentinel directory structure
    (sentinel_dir / "rules").mkdir(parents=True, exist_ok=True)
    (sentinel_dir / "checkpoints").mkdir(parents=True, exist_ok=True)

    # Copy default rules to project if not exists
    project_rules = sentinel_dir / "rules" / "project.md"
    if not project_rules.exists():
        project_rules.write_text("""# Project Rules

> Project-specific rules for this repository.
> Add rules that apply to this project's conventions and requirements.

## Project Conventions

- SHOULD: Follow existing code style and patterns in this repository
- SHOULD: Add tests for new functionality

## [Add your project-specific rules below]

""", encoding="utf-8")
        print(f"  Created: {project_rules}")

    # Initialize global sentinel directory if not exists
    if not GLOBAL_SENTINEL_DIR.exists():
        GLOBAL_SENTINEL_DIR.mkdir(parents=True)
        global_rules_dir = GLOBAL_SENTINEL_DIR / "rules"
        global_rules_dir.mkdir(exist_ok=True)

        # Copy default common rules
        if DEFAULT_RULES_FILE.exists():
            shutil.copy(DEFAULT_RULES_FILE, global_rules_dir / "common.md")
            print(f"  Created: {global_rules_dir / 'common.md'}")

    # Create .claude directory for hooks
    claude_dir.mkdir(exist_ok=True)

    # Create/update hooks configuration
    settings_file = claude_dir / "settings.json"
    settings = {}

    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    # Add Sentinel hooks
    settings["hooks"] = {
        "SessionStart": [{
            "hooks": [{
                "type": "command",
                "command": "sentinel-hook session-start"
            }]
        }],
        "UserPromptSubmit": [{
            "hooks": [{
                "type": "command",
                "command": "sentinel-hook user-prompt"
            }]
        }],
        "PostToolUse": [{
            "matcher": "Edit|Write",
            "hooks": [{
                "type": "command",
                "command": "sentinel-hook post-edit"
            }]
        }]
    }

    settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    print(f"  Created: {settings_file}")

    # Create/update MCP configuration
    mcp_file = project_dir / ".mcp.json"
    mcp_config = {}

    if mcp_file.exists():
        try:
            mcp_config = json.loads(mcp_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    if "mcpServers" not in mcp_config:
        mcp_config["mcpServers"] = {}

    mcp_config["mcpServers"]["sentinel"] = {
        "type": "stdio",
        "command": "sentinel-server"
    }

    mcp_file.write_text(json.dumps(mcp_config, indent=2), encoding="utf-8")
    print(f"  Created: {mcp_file}")

    # Create .gitignore entries
    gitignore_file = sentinel_dir / ".gitignore"
    gitignore_content = """# Sentinel gitignore
session.md
*.log
"""
    gitignore_file.write_text(gitignore_content, encoding="utf-8")

    print()
    print("Sentinel initialized successfully!")
    print()
    print("Next steps:")
    print("  1. Review and customize .sentinel/rules/project.md")
    print("  2. Start a new Claude Code session to activate hooks")
    print("  3. Use /clarify before implementation tasks")
    print("  4. Use /checkpoint init to create documentation")
    print()

    return 0


def status_command(args: list[str]) -> int:
    """Show Sentinel status in the current project."""
    project_dir = Path.cwd()
    sentinel_dir = project_dir / ".sentinel"
    claude_dir = project_dir / ".claude"

    print("Sentinel Status")
    print("=" * 40)

    # Check project initialization
    if sentinel_dir.exists():
        print(f"Project initialized: Yes ({sentinel_dir})")
    else:
        print("Project initialized: No")
        print("  Run 'sentinel init' to initialize")
        return 1

    # Check rules
    project_rules = sentinel_dir / "rules" / "project.md"
    global_rules = GLOBAL_SENTINEL_DIR / "rules" / "common.md"

    print()
    print("Rules:")
    print(f"  Common:  {'Yes' if global_rules.exists() else 'No'} ({global_rules})")
    print(f"  Project: {'Yes' if project_rules.exists() else 'No'} ({project_rules})")

    # Check hooks
    settings_file = claude_dir / "settings.json"
    hooks_configured = False
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text(encoding="utf-8"))
            hooks_configured = "hooks" in settings
        except json.JSONDecodeError:
            pass

    print()
    print("Hooks:")
    print(f"  Configured: {'Yes' if hooks_configured else 'No'}")

    # Check MCP
    mcp_file = project_dir / ".mcp.json"
    mcp_configured = False
    if mcp_file.exists():
        try:
            mcp_config = json.loads(mcp_file.read_text(encoding="utf-8"))
            mcp_configured = "sentinel" in mcp_config.get("mcpServers", {})
        except json.JSONDecodeError:
            pass

    print()
    print("MCP Server:")
    print(f"  Registered: {'Yes' if mcp_configured else 'No'}")

    # Check checkpoints
    checkpoints_dir = sentinel_dir / "checkpoints"
    checkpoint_files = list(checkpoints_dir.rglob("CHECKPOINT.md"))

    print()
    print("Checkpoints:")
    if checkpoint_files:
        for cp in checkpoint_files:
            rel_path = cp.relative_to(project_dir)
            print(f"  - {rel_path}")
    else:
        print("  None (run /checkpoint init)")

    print()
    return 0


def help_command(args: list[str]) -> int:
    """Show help information."""
    print("""Sentinel - AI Coding Companion

Usage:
  sentinel <command> [options]

Commands:
  init      Initialize Sentinel in the current project
  status    Show Sentinel status for the current project
  help      Show this help message

After initialization, the following slash commands are available in Claude Code:
  /clarify <task>      Run clarification protocol before implementation
  /checkpoint init     Create project documentation checkpoints
  /checkpoint update   Update existing checkpoints
  /checkpoint status   Show checkpoint freshness
  /guardian-fix        Fix issues reported by Guardian
  /rules show          Display active rules
  /rules add           Add a session rule

For more information, see: https://github.com/chimera-labs/sentinel
""")
    return 0


def main() -> int:
    """Main entry point for the sentinel CLI."""
    args = sys.argv[1:]

    if not args:
        return help_command([])

    command = args[0]
    command_args = args[1:]

    commands = {
        "init": init_command,
        "status": status_command,
        "help": help_command,
        "--help": help_command,
        "-h": help_command,
    }

    handler = commands.get(command)
    if handler is None:
        print(f"Unknown command: {command}")
        print("Run 'sentinel help' for usage information")
        return 1

    return handler(command_args)


if __name__ == "__main__":
    sys.exit(main())
