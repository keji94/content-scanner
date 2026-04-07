#!/usr/bin/env python3
"""CLI: Prepare Phase 2 prompt structure for a single unit.

Assembles the 6-part LLM prompt (system, context, domain_context,
phase1_hints, content, output_format) for a given paragraph index.
Also pre-filters and batches LLM rules when --rules-dir is provided.
Does NOT call LLM — only marshals data.

Usage:
    python3 prepare_phase2_unit.py \
      --split-json /tmp/split.json \
      --context-json /tmp/context.json \
      --phase1-violations /tmp/phase1_violations.json \
      --config context/domain-config.yaml \
      --unit-index 3 \
      --rules-dir workspace/rules/llm/
"""

import argparse
import json
import sys

from lib.rule_loader import batch_rules, filter_rules_for_paragraph, load_llm_rules
from lib.text_utils import load_config


def load_json(path, fallback=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "violations" in data:
            return data["violations"]
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback if fallback is not None else []


def main():
    parser = argparse.ArgumentParser(
        description="Prepare Phase 2 prompt structure for one unit"
    )
    parser.add_argument("--split-json", required=True,
                        help="Path to split result JSON")
    parser.add_argument("--context-json", required=True,
                        help="Path to cumulative context JSON")
    parser.add_argument("--phase1-violations", required=True,
                        help="Path to Phase 1 violations JSON")
    parser.add_argument("--config", required=True,
                        help="Path to domain-config.yaml")
    parser.add_argument("--unit-index", type=int, required=True,
                        help="Paragraph index to prepare")
    parser.add_argument("--affected-paragraphs", default=None,
                        help="Comma-separated list of paragraph indices to check "
                             "(for selective re-scan in fix loop). "
                             "If omitted, all paragraphs are checked.")
    parser.add_argument("--rules-dir", default=None,
                        help="Directory containing LLM rule YAML files")
    parser.add_argument("--learned-dir", default=None,
                        help="Directory containing learned rule YAML files")
    args = parser.parse_args()

    domain_config = load_config(args.config)
    context_cfg = domain_config.get("context", {})
    enable_hints = context_cfg.get("enable_phase1_hints", True)
    rule_filter_cfg = domain_config.get("rule_filtering", {})

    # Load split data
    with open(args.split_json, "r", encoding="utf-8") as f:
        split_data = json.load(f)

    l2_units = split_data.get("l2_units", [])

    # If --affected-paragraphs is set, skip units not in the affected set
    affected_set = None
    if args.affected_paragraphs:
        try:
            affected_set = set(int(x.strip()) for x in args.affected_paragraphs.split(","))
        except ValueError:
            print(f"Error: invalid --affected-paragraphs format: {args.affected_paragraphs}",
                  file=sys.stderr)
            sys.exit(1)

        if args.unit_index not in affected_set:
            # Signal to caller that this unit should be skipped
            result = {
                "unit_index": args.unit_index,
                "total_units": len(l2_units),
                "skip": True,
                "reason": "not_in_affected_set",
            }
            json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
            return

    if args.unit_index < 0 or args.unit_index >= len(l2_units):
        print(f"Error: unit_index {args.unit_index} out of range "
              f"(0-{len(l2_units)-1})", file=sys.stderr)
        sys.exit(1)

    unit = l2_units[args.unit_index]
    total_units = len(l2_units)
    paragraph_text = unit["text"]

    # Load context
    context = load_json(args.context_json, fallback={"cumulative": {}, "recent_units": []})
    if not isinstance(context, dict):
        context = {"cumulative": {}, "recent_units": []}

    # Load Phase 1 violations and filter for this unit
    p1_violations = load_json(args.phase1_violations, fallback=[])
    unit_hints = []
    if enable_hints and isinstance(p1_violations, list):
        unit_hints = [
            v for v in p1_violations
            if isinstance(v, dict)
            and v.get("location", {}).get("paragraph") == args.unit_index
        ]

    # Load, filter, and batch LLM rules if rules-dir is provided
    rule_batches = None
    if args.rules_dir:
        all_llm_rules = load_llm_rules(args.rules_dir)

        # Also load learned rules if available
        learned_rules = []
        if args.learned_dir:
            learned_rules = load_llm_rules(args.learned_dir)
            # Only include active learned rules
            learned_rules = [
                r for r in learned_rules
                if r.get("status", "active") == "active"
            ]

        combined_rules = all_llm_rules + learned_rules

        # Pre-filter rules for this paragraph
        filtering_enabled = rule_filter_cfg.get("enabled", True)
        if filtering_enabled:
            filtered_rules = filter_rules_for_paragraph(
                combined_rules, paragraph_text, unit_hints
            )
        else:
            filtered_rules = combined_rules

        # Batch rules by priority
        max_batch_size = rule_filter_cfg.get("max_rules_per_batch", 8)
        rule_batches = batch_rules(filtered_rules, max_batch_size)

    # Build output
    result = {
        "unit_index": args.unit_index,
        "total_units": total_units,
        "system_prompt": (
            f"你是内容扫描器，正在检查第{args.unit_index + 1}段/节。"
            f"\n当前单元索引: {args.unit_index}/{total_units - 1}"
        ),
        "context": {
            "cumulative": context.get("cumulative", {}),
            "recent_units": context.get("recent_units", []),
        },
        "domain_context": None,
        "phase1_hints": unit_hints if unit_hints else None,
        "content": paragraph_text,
        "output_format": {
            "type": "array",
            "items": {
                "rule_id": "string",
                "sentence_index": "int",
                "severity": "critical|warning|suggestion",
                "original_text": "string",
                "issue": "string",
                "suggestion": "string",
                "context_conflict": "string (optional)",
            },
            "empty_if_clean": True,
        },
    }

    # Include rule batches when available
    if rule_batches is not None:
        result["rule_batches"] = rule_batches

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
