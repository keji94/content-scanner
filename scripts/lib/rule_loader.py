"""Rule loader for content scanner.

Loads deterministic rules from YAML files and classifies them by type
for dispatch to appropriate checking functions.
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
