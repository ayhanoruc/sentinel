"""Sentinel Hooks - Claude Code hook handlers."""

from __future__ import annotations

import json
import sys
from typing import NoReturn

from .session_start import handle_session_start
from .user_prompt import handle_user_prompt
from .post_edit import handle_post_edit

__all__ = ["main", "handle_session_start", "handle_user_prompt", "handle_post_edit"]


def main() -> NoReturn:
    """
    Main entry point for sentinel-hook command.

    Usage:
        sentinel-hook session-start
        sentinel-hook user-prompt
        sentinel-hook post-edit
    """
    import select
    import platform

    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing hook type argument"}), file=sys.stderr)
        sys.exit(1)

    hook_type = sys.argv[1]

    # Read input from stdin (with handling for no input)
    input_data = {}
    try:
        # Check if there's data available on stdin
        if platform.system() == "Windows":
            # Windows: try to read, use empty dict if nothing
            import msvcrt
            if msvcrt.kbhit() or not sys.stdin.isatty():
                input_data = json.load(sys.stdin)
        else:
            # Unix: use select to check for available input
            if select.select([sys.stdin], [], [], 0.1)[0]:
                input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, Exception):
        input_data = {}

    # Dispatch to appropriate handler
    handlers = {
        "session-start": handle_session_start,
        "user-prompt": handle_user_prompt,
        "post-edit": handle_post_edit,
    }

    handler = handlers.get(hook_type)
    if handler is None:
        print(json.dumps({"error": f"Unknown hook type: {hook_type}"}), file=sys.stderr)
        sys.exit(1)

    try:
        result = handler(input_data)
        if result:
            # ensure_ascii=True to avoid Unicode encoding issues on Windows
            print(json.dumps(result, ensure_ascii=True))
        sys.exit(0)
    except Exception as e:
        # Non-blocking error - log but continue
        print(json.dumps({"error": str(e)}, ensure_ascii=True), file=sys.stderr)
        sys.exit(1)
