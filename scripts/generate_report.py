#!/usr/bin/env python3
"""CLI: Generate final check report.

Usage:
    python3 generate_report.py \
      --violations /tmp/all_violations.json \
      --score /tmp/score.json \
      --split /tmp/split.json \
      --config workspace-checker/context/domain-config.yaml \
      --project my-project --content-id chapter-5
"""

import argparse
import json
import sys

from lib.report import generate_report
from lib.scoring import compute_correlation_groups
from lib.text_utils import load_config


def main():
    parser = argparse.ArgumentParser(description="Generate check report")
    parser.add_argument("--violations", required=True,
                        help="Path to all violations JSON")
    parser.add_argument("--score", required=True,
                        help="Path to score result JSON")
    parser.add_argument("--split", required=True,
                        help="Path to split result JSON")
    parser.add_argument("--config", required=True,
                        help="Path to domain-config.yaml")
    parser.add_argument("--project", default="", help="Project name")
    parser.add_argument("--content-id", default="", help="Chapter/content identifier")
    parser.add_argument("--check-mode", default="full", choices=["full", "quick"],
                        help="Check mode")
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

    with open(args.score, "r", encoding="utf-8") as f:
        score_result = json.load(f)

    with open(args.split, "r", encoding="utf-8") as f:
        split_result = json.load(f)

    # Ensure correlation groups are assigned
    compute_correlation_groups(violations, correlation_config)

    report = generate_report(
        violations=violations,
        score_result=score_result,
        split_result=split_result,
        project=args.project,
        content_id=args.content_id,
        check_mode=args.check_mode,
    )

    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
