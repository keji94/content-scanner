#!/usr/bin/env python3
"""CLI: Validate a workspace for completeness and consistency.

Checks rule files, domain config, and context sources for common issues:
- Duplicate rule IDs
- Invalid rule types
- Missing required fields (check_prompt for LLM rules)
- Broken correlation group references
- Severity/weight consistency

Usage:
    python3 validate_workspace.py \
      --workspace examples/chinese-novel \
      --check all
"""

import argparse
import json
import os
import sys

import yaml

from lib.rule_loader import load_rules
from lib.text_utils import load_config


def main():
    parser = argparse.ArgumentParser(
        description="Validate workspace integrity and consistency"
    )
    parser.add_argument("--workspace", required=True,
                        help="Path to workspace directory")
    parser.add_argument("--check", default="all",
                        choices=["integrity", "conflicts", "all"],
                        help="Type of check to run")
    args = parser.parse_args()

    ws = args.workspace
    errors = []
    warnings = []
    info = []

    # Load domain config
    config_path = os.path.join(ws, "context", "domain-config.yaml")
    if os.path.exists(config_path):
        domain_config = load_config(config_path)
    else:
        errors.append(f"Missing domain config: {config_path}")
        domain_config = {}

    # Check deterministic rules
    det_dir = os.path.join(ws, "rules", "deterministic")
    if os.path.isdir(det_dir):
        det_rules = load_rules(det_dir)
        _check_rules(det_rules, "deterministic", errors, warnings)
    else:
        warnings.append(f"No deterministic rules directory: {det_dir}")
        det_rules = []

    # Check LLM rules
    llm_dir = os.path.join(ws, "rules", "llm")
    if os.path.isdir(llm_dir):
        llm_rules = load_rules(llm_dir)
        _check_rules(llm_rules, "llm", errors, warnings)
    else:
        warnings.append(f"No LLM rules directory: {llm_dir}")
        llm_rules = []

    # Cross-check: duplicate IDs across all rules
    if args.check in ("all", "conflicts"):
        all_rules = det_rules + llm_rules
        seen_ids = {}
        for rule in all_rules:
            rid = rule.get("id", "")
            if rid in seen_ids:
                errors.append(
                    f"Duplicate rule ID '{rid}' in {seen_ids[rid]} and current file"
                )
            else:
                seen_ids[rid] = rule.get("_source_file", "unknown")

        # Check correlation group references
        scoring = domain_config.get("scoring", {})
        corr_groups = scoring.get("correlation_groups", {})
        all_ids = {r.get("id") for r in all_rules}
        for group_name, rule_ids in corr_groups.items():
            if isinstance(rule_ids, list):
                for rid in rule_ids:
                    if rid and rid not in all_ids:
                        warnings.append(
                            f"Correlation group '{group_name}' references "
                            f"non-existent rule ID '{rid}'"
                        )

        # Check severity/weight consistency
        for rule in all_rules:
            sev = rule.get("severity", "warning")
            weight = rule.get("weight", 3)
            if sev == "critical" and weight < 5:
                warnings.append(
                    f"Rule '{rule.get('id')}' is critical but has low weight ({weight})"
                )
            if sev == "suggestion" and weight > 5:
                warnings.append(
                    f"Rule '{rule.get('id')}' is suggestion but has high weight ({weight})"
                )

    # Output
    result = {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "summary": {
            "deterministic_rules": len(det_rules),
            "llm_rules": len(llm_rules),
        },
    }

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    if errors:
        print("", file=sys.stderr)
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


def _check_rules(
    rules: list[dict], source: str,
    errors: list[str], warnings: list[str],
):
    """Check a list of rules for integrity issues."""
    known_types = {
        "pattern", "patterns", "density", "fatigue", "keyword_list",
        "consecutive", "length_check", "pattern_list", "consecutive_pattern",
        "settings_gate", "statistical",
    }

    for rule in rules:
        rid = rule.get("id", "")
        phase = rule.get("phase", 1)

        # Required fields
        if not rid:
            errors.append(f"Rule missing 'id' in {source}")
        if not rule.get("name"):
            warnings.append(f"Rule '{rid}' missing 'name'")

        # Phase-specific checks
        if phase == 1:
            rtype = rule.get("type", "")
            if rtype and rtype not in known_types:
                warnings.append(
                    f"Rule '{rid}' has unknown type '{rtype}' "
                    f"(known: {', '.join(sorted(known_types))})"
                )
        elif phase == 2:
            if not rule.get("check_prompt"):
                errors.append(f"LLM rule '{rid}' missing 'check_prompt'")

        # Severity check
        sev = rule.get("severity", "")
        if sev not in ("critical", "warning", "suggestion", ""):
            warnings.append(f"Rule '{rid}' has unusual severity '{sev}'")


if __name__ == "__main__":
    main()
