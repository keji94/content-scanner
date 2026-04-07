#!/usr/bin/env python3
"""CLI: Calculate score from violations.

Usage:
    python3 calculate_score.py \
      --violations /tmp/all_violations.json \
      --config workspace-checker/context/domain-config.yaml
"""

import argparse
import json
import sys

from lib.scoring import calculate_score, compute_correlation_groups
from lib.text_utils import load_config


def main():
    parser = argparse.ArgumentParser(description="Calculate check score")
    parser.add_argument("--violations", required=True,
                        help="Path to violations JSON (all_violations from Phase 1 + 2)")
    parser.add_argument("--config", required=True,
                        help="Path to domain-config.yaml")
    parser.add_argument("--baseline-violations", default=None,
                        help="Path to previous round's violations for diff scoring. "
                             "When provided, violations for affected paragraphs are "
                             "replaced with new violations; unaffected violations are kept.")
    parser.add_argument("--affected-paragraphs", default=None,
                        help="Comma-separated paragraph indices that were modified. "
                             "Only used with --baseline-violations.")
    args = parser.parse_args()

    domain_config = load_config(args.config)
    scoring_config = domain_config.get("scoring", {})
    correlation_config = scoring_config.get("correlation_groups", {})

    with open(args.violations, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Support both flat array and wrapped {"violations": [...]} format
    if isinstance(data, dict):
        violations = data.get("violations", [])
    else:
        violations = data

    # Diff scoring: merge baseline violations for unaffected paragraphs
    if args.baseline_violations and args.affected_paragraphs:
        affected_set = set(int(x.strip()) for x in args.affected_paragraphs.split(","))
        with open(args.baseline_violations, "r", encoding="utf-8") as f:
            baseline_data = json.load(f)
        baseline_violations = (
            baseline_data.get("violations", baseline_data)
            if isinstance(baseline_data, dict)
            else baseline_data
        )
        # Keep baseline violations for paragraphs NOT in affected_set
        kept_baseline = [
            v for v in baseline_violations
            if isinstance(v, dict)
            and v.get("location", {}).get("paragraph", -1) not in affected_set
        ]
        # Replace violations for affected paragraphs with new ones
        new_affected = [
            v for v in violations
            if isinstance(v, dict)
            and v.get("location", {}).get("paragraph", -1) in affected_set
        ]
        violations = kept_baseline + new_affected

    # Step 1: Assign correlation groups
    compute_correlation_groups(violations, correlation_config)

    # Step 2: Calculate score
    result = calculate_score(violations, scoring_config)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
