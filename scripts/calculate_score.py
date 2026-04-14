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

from lib.scoring import calculate_score, compute_correlation_groups, _determine_grade
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
    parser.add_argument("--perspectives", default=None,
                        help="Path to perspective_results JSON (Phase 3). "
                             "When provided, perspective scores are weighted into the final score.")
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

    # Step 3: Apply perspective weighting if Phase 3 results provided
    if args.perspectives:
        try:
            with open(args.perspectives, "r", encoding="utf-8") as f:
                perspective_data = json.load(f)
            if isinstance(perspective_data, list):
                scores = [p["score"] for p in perspective_data if "score" in p]
                if scores:
                    perspective_avg = sum(scores) / len(scores) * 10  # Convert 1-10 to 10-100
                    rp_config = domain_config.get("reader_perspectives", {})
                    weight = float(rp_config.get("weight", 0.1)) if isinstance(rp_config, dict) else 0.1

                    rule_score = result.get("score", 100)
                    final_score = rule_score * (1 - weight) + perspective_avg * weight
                    final_score = round(final_score, 1)

                    result["rule_score"] = rule_score
                    result["perspective_avg"] = round(perspective_avg, 1)
                    result["perspective_weight"] = weight
                    result["score"] = final_score

                    # Re-grade based on new score
                    grade_thresholds = scoring_config.get("grade_thresholds", {})
                    result["grade"] = _determine_grade(
                        final_score,
                        result.get("critical_count", 0),
                        result.get("warning_count", 0),
                        grade_thresholds,
                    )
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            print(f"WARNING: Could not apply perspective weighting: {e}", file=sys.stderr)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
