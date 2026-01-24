"""Context cleanup - Process transcript keeping content verbatim, only compressing tool outputs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _compress_tool_result(tool_name: str, tool_input: dict, result_text: str) -> str:
    """
    Compress a tool result to a 1-liner.
    Only compresses the RESULT, not the tool call itself.
    """
    if tool_name == "Read":
        path = tool_input.get("file_path", "unknown")
        lines = result_text.count('\n') + 1 if result_text else 0
        return f"[Read {path} - {lines} lines]"

    elif tool_name == "Glob":
        pattern = tool_input.get("pattern", "")
        matches = result_text.count('\n') + 1 if result_text.strip() else 0
        return f"[Glob '{pattern}' - {matches} matches]"

    elif tool_name == "Grep":
        pattern = tool_input.get("pattern", "")
        matches = result_text.count('\n') + 1 if result_text.strip() else 0
        return f"[Grep '{pattern}' - {matches} matches]"

    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")[:60]
        lines = result_text.count('\n') + 1 if result_text else 0
        return f"[Bash '{cmd}...' - {lines} lines output]"

    elif tool_name == "Edit":
        path = tool_input.get("file_path", "unknown")
        return f"[Edit {path} - done]"

    elif tool_name == "Write":
        path = tool_input.get("file_path", "unknown")
        return f"[Write {path} - done]"

    elif tool_name == "Task":
        desc = tool_input.get("description", "")
        return f"[Task '{desc}' - completed]"

    elif tool_name == "WebFetch":
        url = tool_input.get("url", "")[:50]
        return f"[WebFetch {url}... - done]"

    elif tool_name == "WebSearch":
        query = tool_input.get("query", "")
        return f"[WebSearch '{query}' - done]"

    else:
        return f"[{tool_name} - done]"


def process_transcript(transcript_path: str) -> str:
    """
    Process transcript: keep everything verbatim, only compress tool outputs.

    Args:
        transcript_path: Path to the JSONL transcript file

    Returns:
        Processed conversation text (not a summary - actual conversation)
    """
    transcript_file = Path(transcript_path)

    if not transcript_file.exists():
        return f"ERROR: Transcript file not found: {transcript_path}"

    # Read and parse transcript
    messages = []
    try:
        with open(transcript_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except (OSError, IOError) as e:
        return f"ERROR: Could not read transcript: {e}"

    # Process messages - keep verbatim, only compress tool results
    output_parts = []
    output_parts.append(f"# Processed Context (from /clear_redundant)")
    output_parts.append(f"Generated: {datetime.now().isoformat()}")
    output_parts.append(f"Original messages: {len(messages)}")
    output_parts.append("")
    output_parts.append("---")
    output_parts.append("")

    # Track pending tool calls to match with results
    pending_tool_calls = {}  # id -> {name, input}

    for msg in messages:
        # Skip non-message entries (file-history-snapshot, etc.)
        msg_type = msg.get("type", "")
        if msg_type not in ("user", "assistant"):
            continue

        # Message content is nested under "message" key
        inner_msg = msg.get("message", {})
        role = inner_msg.get("role", "")
        content = inner_msg.get("content", "")

        if role == "user":
            # Stop processing when we hit the clear_redundant trigger
            if isinstance(content, str):
                content_lower = content.strip().lower()
                if content_lower.startswith("clear_redundant") or content_lower.startswith("/clear_redundant"):
                    break  # Stop here - everything after is cleanup noise

            # Keep user messages VERBATIM
            if isinstance(content, str):
                output_parts.append(f"**USER:**")
                output_parts.append(content)
                output_parts.append("")
            elif isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                        elif item.get("type") == "tool_result":
                            # This is a tool result from user turn - compress it
                            tool_use_id = item.get("tool_use_id", "")
                            result_content = item.get("content", "")

                            # Get the tool info from pending calls
                            tool_info = pending_tool_calls.pop(tool_use_id, None)
                            if tool_info:
                                compressed = _compress_tool_result(
                                    tool_info["name"],
                                    tool_info["input"],
                                    result_content if isinstance(result_content, str) else str(result_content)
                                )
                                text_parts.append(compressed)
                            else:
                                # Unknown tool result - keep short version
                                if isinstance(result_content, str) and len(result_content) > 200:
                                    text_parts.append(f"[Tool result: {len(result_content)} chars]")
                                else:
                                    text_parts.append(f"[Tool result]")

                if text_parts:
                    output_parts.append(f"**USER:**")
                    output_parts.append("\n".join(text_parts))
                    output_parts.append("")

        elif role == "assistant":
            # Keep assistant TEXT verbatim, track tool calls
            if isinstance(content, str):
                output_parts.append(f"**ASSISTANT:**")
                output_parts.append(content)
                output_parts.append("")
            elif isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            # Keep text verbatim
                            text_parts.append(item.get("text", ""))
                        elif item.get("type") == "tool_use":
                            # Track tool call for later result matching
                            tool_id = item.get("id", "")
                            tool_name = item.get("name", "unknown")
                            tool_input = item.get("input", {})

                            pending_tool_calls[tool_id] = {
                                "name": tool_name,
                                "input": tool_input
                            }

                            # Show tool call (short version)
                            if tool_name in ("Read", "Glob", "Grep"):
                                path = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("pattern", "")
                                text_parts.append(f"→ {tool_name}: {path}")
                            elif tool_name == "Edit":
                                path = tool_input.get("file_path", "")
                                text_parts.append(f"→ Edit: {path}")
                            elif tool_name == "Write":
                                path = tool_input.get("file_path", "")
                                text_parts.append(f"→ Write: {path}")
                            elif tool_name == "Bash":
                                cmd = tool_input.get("command", "")[:60]
                                text_parts.append(f"→ Bash: {cmd}...")
                            else:
                                text_parts.append(f"→ {tool_name}")

                if text_parts:
                    output_parts.append(f"**ASSISTANT:**")
                    output_parts.append("\n".join(text_parts))
                    output_parts.append("")

    return "\n".join(output_parts)


def save_snapshot(content: str, project_dir: Path | None = None) -> Path:
    """
    Save snapshot to the snapshots directory.

    Args:
        content: Snapshot content
        project_dir: Project directory (defaults to cwd)

    Returns:
        Path to saved snapshot
    """
    if project_dir is None:
        project_dir = Path.cwd()

    snapshots_dir = project_dir / ".sentinel" / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = snapshots_dir / "context_snapshot.md"
    snapshot_path.write_text(content, encoding="utf-8")

    return snapshot_path
