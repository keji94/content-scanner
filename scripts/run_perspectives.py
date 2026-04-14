#!/usr/bin/env python3
"""CLI: Prepare Phase 3 reader perspectives for LLM review.

Loads perspective definitions from the default template and workspace config,
merges them, and outputs the matched perspectives as JSON.

Usage:
    python3 run_perspectives.py \
      --config workspace/context/domain-config.yaml \
      --genre webnovel_review \
      --default-perspectives perspectives/default-perspectives.yaml

Output: JSON { genre, perspectives[], weight }
"""

import argparse
import json
import sys
from typing import Any

from lib.text_utils import load_config


def load_perspectives(path: str) -> dict[str, list[dict]]:
    """Load default perspective templates from YAML file."""
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("perspectives", {})


def merge_overrides(defaults: list[dict], overrides: list[dict]) -> list[dict]:
    """Merge workspace overrides into default perspectives by id.

    If an override has the same id as a default, replace its fields.
    If the override has a new id, append it.
    """
    default_map = {p["id"]: p.copy() for p in defaults}

    for ov in overrides:
        oid = ov.get("id", "")
        if oid in default_map:
            # Merge: override fields replace default fields
            default_map[oid].update({k: v for k, v in ov.items() if k != "id"})
        else:
            # New perspective — append
            defaults = list(defaults) + [ov]
            default_map[oid] = ov

    if not overrides:
        return defaults

    # Preserve order from defaults, then append new ones
    result = []
    seen = set()
    for p in defaults:
        pid = p.get("id", "")
        if pid in default_map and pid not in seen:
            result.append(default_map[pid])
            seen.add(pid)
    for pid, p in default_map.items():
        if pid not in seen:
            result.append(p)
            seen.add(pid)

    return result


def resolve_genre(config: dict[str, Any], cli_genre: str | None) -> str:
    """Determine which genre to use.

    Priority: CLI argument > domain-config > "general"
    """
    rp_config = config.get("reader_perspectives", {})
    if isinstance(rp_config, dict):
        config_genre = rp_config.get("genre", "general")
    else:
        config_genre = "general"
    return cli_genre or config_genre


def resolve_weight(config: dict[str, Any]) -> float:
    """Get perspective weight from config, default 0.1 (10%)."""
    rp_config = config.get("reader_perspectives", {})
    if isinstance(rp_config, dict):
        return float(rp_config.get("weight", 0.1))
    return 0.1


def main():
    parser = argparse.ArgumentParser(description="Prepare Phase 3 reader perspectives")
    parser.add_argument("--config", required=True,
                        help="Path to workspace domain-config.yaml")
    parser.add_argument("--genre", default=None,
                        help="Genre key (overrides domain-config)")
    parser.add_argument("--default-perspectives", required=True,
                        help="Path to perspectives/default-perspectives.yaml")
    args = parser.parse_args()

    # Load config and resolve genre
    config = load_config(args.config)
    genre = resolve_genre(config, args.genre)
    weight = resolve_weight(config)

    # Load default perspectives
    all_perspectives = load_perspectives(args.default_perspectives)

    # Get perspectives for this genre
    if genre not in all_perspectives:
        print(f"WARNING: genre '{genre}' not found in perspectives template, "
              f"falling back to 'general'", file=sys.stderr)
        genre = "general"

    perspectives = all_perspectives.get(genre, [])

    if not perspectives:
        print(f"ERROR: no perspectives found for genre '{genre}'", file=sys.stderr)
        sys.exit(1)

    # Apply workspace overrides if any
    rp_config = config.get("reader_perspectives", {})
    if isinstance(rp_config, dict) and "overrides" in rp_config:
        perspectives = merge_overrides(perspectives, rp_config["overrides"])

    # Output
    result = {
        "genre": genre,
        "weight": weight,
        "perspectives": perspectives,
    }

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
