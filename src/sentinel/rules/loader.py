"""Rule loading and merging logic."""

from __future__ import annotations

import os
import re
from pathlib import Path
from dataclasses import dataclass, field

# ===========================================================================
# CONFIGURATION
# ===========================================================================
GLOBAL_RULES_DIR = Path.home() / ".sentinel" / "rules"
PROJECT_RULES_DIR = Path(".sentinel") / "rules"
DEFAULT_RULES_FILE = Path(__file__).parent / "defaults" / "common.md"


@dataclass
class Rule:
    """A single rule with its metadata."""

    category: str
    level: str  # MUST, SHOULD, AVOID, NEVER
    text: str
    tags: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"- {self.level}: {self.text}"


@dataclass
class RuleSet:
    """A collection of rules organized by category."""

    source: str  # 'common', 'project', 'session'
    categories: dict[str, list[Rule]] = field(default_factory=dict)

    def add_rule(self, category: str, rule: Rule) -> None:
        if category not in self.categories:
            self.categories[category] = []
        self.categories[category].append(rule)

    def to_markdown(self) -> str:
        """Convert rules to markdown format."""
        lines = []
        for category, rules in self.categories.items():
            lines.append(f"## {category}")
            lines.append("")
            for rule in rules:
                lines.append(str(rule))
            lines.append("")
        return "\n".join(lines)


class RulesLoader:
    """Loads and merges rules from multiple sources."""

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = Path(project_dir) if project_dir else Path.cwd()
        self._session_rules: list[str] = []

    def _parse_rules_file(self, path: Path, source: str) -> RuleSet:
        """Parse a markdown rules file into a RuleSet."""
        ruleset = RuleSet(source=source)

        if not path.exists():
            return ruleset

        content = path.read_text(encoding="utf-8")
        current_category = "General"
        current_tags: list[str] = []

        for line in content.split("\n"):
            line = line.strip()

            # Category header: ## [Category Name] or ## [Tag: name]
            if line.startswith("## "):
                header = line[3:].strip()
                # Check for tag annotation
                tag_match = re.match(r"\[Tag:\s*([^\]]+)\]", header)
                if tag_match:
                    current_tags = [t.strip() for t in tag_match.group(1).split(",")]
                    current_category = f"Tagged: {', '.join(current_tags)}"
                else:
                    current_category = header.strip("[]")
                    current_tags = []
                continue

            # Rule line: - LEVEL: text
            rule_match = re.match(r"-\s*(MUST|SHOULD|AVOID|NEVER):\s*(.+)", line)
            if rule_match:
                level = rule_match.group(1)
                text = rule_match.group(2)
                rule = Rule(
                    category=current_category,
                    level=level,
                    text=text,
                    tags=current_tags.copy(),
                )
                ruleset.add_rule(current_category, rule)

        return ruleset

    def load_common_rules(self) -> RuleSet:
        """Load common rules (global, applies to all projects)."""
        common_path = GLOBAL_RULES_DIR / "common.md"
        if not common_path.exists() and DEFAULT_RULES_FILE.exists():
            # Fall back to bundled defaults
            return self._parse_rules_file(DEFAULT_RULES_FILE, "common")
        return self._parse_rules_file(common_path, "common")

    def load_project_rules(self) -> RuleSet:
        """Load project-specific rules."""
        project_path = self.project_dir / PROJECT_RULES_DIR / "project.md"
        return self._parse_rules_file(project_path, "project")

    def load_session_rules(self) -> RuleSet:
        """Load session-specific rules (in-memory)."""
        ruleset = RuleSet(source="session")
        for rule_text in self._session_rules:
            # Parse simple rule format: "LEVEL: text" or just "text" (defaults to MUST)
            match = re.match(r"(MUST|SHOULD|AVOID|NEVER):\s*(.+)", rule_text)
            if match:
                level, text = match.groups()
            else:
                level, text = "MUST", rule_text
            rule = Rule(category="Session Rules", level=level, text=text)
            ruleset.add_rule("Session Rules", rule)
        return ruleset

    def add_session_rule(self, rule: str) -> None:
        """Add a rule for the current session only."""
        self._session_rules.append(rule)

    def clear_session_rules(self) -> None:
        """Clear all session rules."""
        self._session_rules.clear()

    def get_merged_rules(self, tags: list[str] | None = None) -> str:
        """
        Get all rules merged into a single markdown string.

        Rules are merged in order: common → project → session
        Later rules with the same text override earlier ones.

        Args:
            tags: Optional list of tags to filter rules by.

        Returns:
            Markdown string with all applicable rules.
        """
        common = self.load_common_rules()
        project = self.load_project_rules()
        session = self.load_session_rules()

        # Merge all categories
        all_categories: dict[str, list[Rule]] = {}

        for ruleset in [common, project, session]:
            for category, rules in ruleset.categories.items():
                if category not in all_categories:
                    all_categories[category] = []

                for rule in rules:
                    # Filter by tags if specified
                    if tags:
                        # Include rule if: no tags (general rule) OR has matching tag
                        is_general_rule = not rule.tags
                        has_matching_tag = rule.tags and any(t in tags for t in rule.tags)
                        if not (is_general_rule or has_matching_tag):
                            continue

                    # Check for duplicates (by text)
                    existing_texts = [r.text for r in all_categories[category]]
                    if rule.text not in existing_texts:
                        all_categories[category].append(rule)

        # Format output
        lines = []
        for category, rules in all_categories.items():
            if not rules:
                continue
            lines.append(f"## {category}")
            lines.append("")
            for rule in rules:
                lines.append(str(rule))
            lines.append("")

        return "\n".join(lines)


# Module-level singleton for convenience
_loader: RulesLoader | None = None


def _get_loader() -> RulesLoader:
    global _loader
    if _loader is None:
        project_dir = os.environ.get("SENTINEL_PROJECT_DIR", os.getcwd())
        _loader = RulesLoader(Path(project_dir))
    return _loader


def get_merged_rules(tags: list[str] | None = None) -> str:
    """Get all merged rules as markdown."""
    return _get_loader().get_merged_rules(tags)


def add_session_rule(rule: str) -> str:
    """Add a session rule (in-memory, temporary). Returns confirmation message."""
    _get_loader().add_session_rule(rule)
    return f"Added session rule: {rule}"


def add_project_rule(rule: str, category: str = "Project Rules") -> str:
    """
    Add a rule to project rules file (.sentinel/rules/project.md).
    Persists across sessions for this project.

    Args:
        rule: Rule text (e.g., "MUST: Use async for all DB operations")
        category: Category to add under (default: "Project Rules")

    Returns:
        Confirmation message.
    """
    project_path = _get_loader().project_dir / PROJECT_RULES_DIR / "project.md"

    # Ensure directory exists
    project_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content or create new
    if project_path.exists():
        content = project_path.read_text(encoding="utf-8")
    else:
        content = "# Project Rules\n\n> Project-specific rules for this repository.\n\n"

    # Check if category exists
    category_header = f"## {category}"
    if category_header in content:
        # Add under existing category
        lines = content.split("\n")
        new_lines = []
        added = False
        for i, line in enumerate(lines):
            new_lines.append(line)
            if line.strip() == category_header and not added:
                # Find the end of this category (next ## or end of file)
                # Add rule after the header and any existing rules
                j = i + 1
                while j < len(lines) and not lines[j].strip().startswith("## "):
                    new_lines.append(lines[j])
                    j += 1
                # Add the new rule before the next section
                if not new_lines[-1].strip().startswith("- "):
                    new_lines.append("")
                new_lines.append(f"- {rule}")
                added = True
                # Skip the lines we already added
                for k in range(i + 1, j):
                    lines[k] = None
        content = "\n".join(line for line in new_lines if line is not None)
    else:
        # Add new category at the end
        content = content.rstrip() + f"\n\n{category_header}\n\n- {rule}\n"

    project_path.write_text(content, encoding="utf-8")
    return f"Added to project rules [{category}]: {rule}"


def add_common_rule(rule: str, category: str = "Custom Rules") -> str:
    """
    Add a rule to common/global rules file (~/.sentinel/rules/common.md).
    Persists across sessions and applies to all projects.

    Args:
        rule: Rule text (e.g., "MUST: Always use type hints")
        category: Category to add under (default: "Custom Rules")

    Returns:
        Confirmation message.
    """
    common_path = GLOBAL_RULES_DIR / "common.md"

    # Ensure directory exists
    common_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content or copy from defaults
    if common_path.exists():
        content = common_path.read_text(encoding="utf-8")
    elif DEFAULT_RULES_FILE.exists():
        content = DEFAULT_RULES_FILE.read_text(encoding="utf-8")
    else:
        content = "# Sentinel Common Rules\n\n> Global rules for all projects.\n\n"

    # Check if category exists
    category_header = f"## {category}"
    if category_header in content:
        # Add under existing category (same logic as project)
        lines = content.split("\n")
        new_lines = []
        added = False
        for i, line in enumerate(lines):
            new_lines.append(line)
            if line.strip() == category_header and not added:
                j = i + 1
                while j < len(lines) and not lines[j].strip().startswith("## "):
                    new_lines.append(lines[j])
                    j += 1
                if not new_lines[-1].strip().startswith("- "):
                    new_lines.append("")
                new_lines.append(f"- {rule}")
                added = True
                for k in range(i + 1, j):
                    lines[k] = None
        content = "\n".join(line for line in new_lines if line is not None)
    else:
        # Add new category at the end
        content = content.rstrip() + f"\n\n{category_header}\n\n- {rule}\n"

    common_path.write_text(content, encoding="utf-8")
    return f"Added to common rules [{category}]: {rule}"


def clear_session_rules() -> str:
    """Clear all session rules. Returns confirmation message."""
    _get_loader().clear_session_rules()
    return "Cleared all session rules."
