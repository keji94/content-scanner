#!/usr/bin/env python3
"""CLI: Split text into L1/L2 units.

Usage:
    python3 split_text.py --input chapters/chapter-01.md --config domain-config.yaml
"""

import argparse
import json
import sys

from lib.text_utils import load_config, split_text


def main():
    parser = argparse.ArgumentParser(description="Split text into L1/L2 units")
    parser.add_argument("--input", required=True, help="Path to text file")
    parser.add_argument("--config", required=True, help="Path to domain-config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)

    with open(args.input, "r", encoding="utf-8") as f:
        text = f.read()

    result = split_text(text, config)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
