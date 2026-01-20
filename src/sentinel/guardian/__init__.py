"""Code Guardian - LLM-based code analysis and verification.

Guardian works by injecting analysis prompts into Claude's context,
allowing the LLM to review code against Sentinel rules.

This is NOT static analysis - the actual review is done by Claude.
"""

from .prompts import get_analysis_prompt, get_fix_prompt

__all__ = ["get_analysis_prompt", "get_fix_prompt"]
