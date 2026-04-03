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
    args = parser.parse_args()

    domain_config = load_config(args.config)
    scoring_config = domain_config.get("scoring", {})
    correlation_config = scoring_config.get("correlation_groups", {})

    with open(args.violations, "r", encoding="utf-8") as f:
        violations = json.load(f)

    # Step 1: Assign correlation groups
    compute_correlation_groups(violations, correlation_config)

    # Step 2: Calculate score
    result = calculate_score(violations, scoring_config)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
