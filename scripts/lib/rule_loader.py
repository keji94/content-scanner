"""Rule loader for content scanner.

Loads deterministic rules from YAML files and classifies them by type
for dispatch to appropriate checking functions.
Also supports LLM rule filtering and batching for Phase 2.
"""

import glob
import os
from typing import Any

import yaml


def load_rules(rules_dir: str) -> list[dict[str, Any]]:
    """Load all YAML rule files from a directory.

    Each YAML file may contain a single rule dict or a list of rule dicts.
    """
    rules = []
    if not os.path.isdir(rules_dir):
        return rules
    pattern = os.path.join(rules_dir, "*.yaml")
    for path in sorted(glob.glob(pattern)):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if data is None:
            continue
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "id" in item:
                    rules.append(item)
        elif isinstance(data, dict) and "id" in data:
            rules.append(data)
    return rules


def load_llm_rules(rules_dir: str) -> list[dict[str, Any]]:
    """Load LLM rules (phase: 2) from a rules directory.

    Returns only rules with phase == 2, sorted by severity
    (critical first, then warning, then suggestion).
    """
    all_rules = load_rules(rules_dir)
    llm_rules = [r for r in all_rules if r.get("phase") == 2]
    severity_order = {"critical": 0, "warning": 1, "suggestion": 2}
    llm_rules.sort(key=lambda r: severity_order.get(r.get("severity", "warning"), 1))
    return llm_rules


def filter_rules_for_paragraph(
    rules: list[dict[str, Any]],
    paragraph_text: str,
    phase1_hints: list[dict] | None = None,
) -> list[dict[str, Any]]:
    """Pre-filter LLM rules for a specific paragraph.

    Filtering logic:
    1. Rules with no keyword_triggers and no applies_when always pass.
    2. Rules with keyword_triggers: pass if ANY keyword appears in the text.
    3. Rules with applies_when only (no keyword_triggers): always pass
       (content signals require LLM-level analysis, can't be determined cheaply).

    This is a lightweight deterministic pre-filter. The LLM still makes
    the final decision on each rule during Phase 2.
    """
    if not rules:
        return rules

    filtered = []
    for rule in rules:
        keyword_triggers = rule.get("keyword_triggers")
        if keyword_triggers and isinstance(keyword_triggers, list):
            # Check if any keyword appears in the paragraph
            if any(kw in paragraph_text for kw in keyword_triggers):
                filtered.append(rule)
            # keyword defined but none matched → skip this rule
            continue
        # No keyword_triggers → rule always applies
        filtered.append(rule)

    return filtered


def batch_rules(
    rules: list[dict[str, Any]],
    max_batch_size: int = 8,
) -> list[dict[str, Any]]:
    """Split filtered rules into priority-based batches.

    Batches are ordered by severity:
    - Batch 1: critical rules
    - Batch 2: warning rules
    - Batch 3: suggestion rules

    Each batch contains at most max_batch_size rules.
    If a severity group exceeds max_batch_size, it is split into sub-batches.

    Returns a list of batch dicts:
    [{batch_label: str, priority: str, rules: [...]}]
    """
    if not rules:
        return []

    groups: dict[str, list[dict]] = {
        "critical": [],
        "warning": [],
        "suggestion": [],
    }
    for rule in rules:
        sev = rule.get("severity", "warning")
        groups.setdefault(sev, []).append(rule)

    batches = []
    for priority in ("critical", "warning", "suggestion"):
        group = groups[priority]
        if not group:
            continue
        for i in range(0, len(group), max_batch_size):
            chunk = group[i : i + max_batch_size]
            batches.append({
                "batch_label": f"{priority}_checks"
                if i == 0
                else f"{priority}_checks_{i // max_batch_size + 1}",
                "priority": priority,
                "rules": [
                    {
                        "id": r.get("id", ""),
                        "name": r.get("name", ""),
                        "check_prompt": r.get("check_prompt", ""),
                    }
                    for r in chunk
                ],
            })

    return batches


def classify_rule(rule: dict[str, Any]) -> str:
    """Determine the check type for a rule.

    Classification logic:
    - 'type' field present → use it directly
    - has 'pattern' field → 'pattern' (single regex)
    - has 'patterns' field → 'patterns' (multiple regex)
    - otherwise → infer from other fields
    """
    # Explicit type takes priority
    if "type" in rule:
        return rule["type"]

    # Infer from fields
    if "pattern" in rule:
        return "pattern"
    if "patterns" in rule:
        return "patterns"

    # Default fallback
    return "unknown"


def load_genre_profile(rule: dict[str, Any], genre: str) -> list[str] | None:
    """For fatigue-type rules, get the word list for the given genre."""
    profiles = rule.get("genre_profiles", {})
    return profiles.get(genre)


def group_rules_by_type(rules: list[dict[str, Any]]) -> dict[str, list[dict]]:
    """Group rules by their classified type."""
    groups: dict[str, list[dict]] = {}
    for rule in rules:
        rtype = classify_rule(rule)
        rule["_type"] = rtype
        groups.setdefault(rtype, []).append(rule)
    return groups
