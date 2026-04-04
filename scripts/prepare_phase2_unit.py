#!/usr/bin/env python3
"""CLI: Prepare Phase 2 prompt structure for a single unit.

Assembles the 6-part LLM prompt (system, context, domain_context,
phase1_hints, content, output_format) for a given paragraph index.
Does NOT call LLM — only marshals data.

Usage:
    python3 prepare_phase2_unit.py \
      --split-json /tmp/split.json \
      --context-json /tmp/context.json \
      --phase1-violations /tmp/phase1_violations.json \
      --config context/domain-config.yaml \
      --unit-index 3
"""

import argparse
import json
import sys

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
    args = parser.parse_args()

    domain_config = load_config(args.config)
    context_cfg = domain_config.get("context", {})
    enable_hints = context_cfg.get("enable_phase1_hints", True)

    # Load split data
    with open(args.split_json, "r", encoding="utf-8") as f:
        split_data = json.load(f)

    l2_units = split_data.get("l2_units", [])
    if args.unit_index < 0 or args.unit_index >= len(l2_units):
        print(f"Error: unit_index {args.unit_index} out of range "
              f"(0-{len(l2_units)-1})", file=sys.stderr)
        sys.exit(1)

    unit = l2_units[args.unit_index]
    total_units = len(l2_units)

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
        "content": unit["text"],
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

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
