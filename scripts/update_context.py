#!/usr/bin/env python3
"""CLI: Update cumulative context with new extractions.

Usage:
    python3 update_context.py \
      --context-json /tmp/context.json \
      --extractions /tmp/extractions.json \
      --config workspace-checker/context/domain-config.yaml \
      --context-sources workspace-checker/context/context-sources.yaml \
      --unit-index 5 \
      --unit-text "段落原文..."
"""

import argparse
import json
import sys

from lib.context_manager import (
    init_context,
    load_cumulative_fields_config,
    update_context,
)
from lib.text_utils import load_config


def main():
    parser = argparse.ArgumentParser(description="Update cumulative context")
    parser.add_argument("--context-json", required=True,
                        help="Path to current context JSON (read, then overwrite)")
    parser.add_argument("--extractions", required=True,
                        help="Path to extractions JSON from agent")
    parser.add_argument("--config", required=True,
                        help="Path to domain-config.yaml")
    parser.add_argument("--context-sources", required=True,
                        help="Path to context-sources.yaml")
    parser.add_argument("--unit-index", type=int, required=True,
                        help="Current paragraph index")
    parser.add_argument("--unit-text", default="",
                        help="Current paragraph text (for sliding window)")
    parser.add_argument("--init", action="store_true",
                        help="Initialize empty context instead of updating")
    args = parser.parse_args()

    domain_config = load_config(args.config)
    field_configs = load_cumulative_fields_config(args.context_sources)

    if args.init:
        # Initialize empty context
        context = init_context(field_configs)
    else:
        # Load existing context
        with open(args.context_json, "r", encoding="utf-8") as f:
            context = json.load(f)

        # Load extractions
        with open(args.extractions, "r", encoding="utf-8") as f:
            extractions = json.load(f)

        # Update
        context = update_context(
            context=context,
            extractions=extractions,
            field_configs=field_configs,
            domain_config=domain_config,
            unit_index=args.unit_index,
            unit_text=args.unit_text,
        )

    # Write back
    with open(args.context_json, "w", encoding="utf-8") as f:
        json.dump(context, f, ensure_ascii=False, indent=2)

    # Also output to stdout
    json.dump(context, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
