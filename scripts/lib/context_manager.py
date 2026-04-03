"""Cumulative context manager for content scanner.

Handles FIFO trimming, confidence tracking (tentative marking),
contradiction detection and override, and sliding window.
"""

from typing import Any

import yaml


def load_cumulative_fields_config(context_sources_path: str) -> dict[str, Any]:
    """Load cumulative field definitions from context-sources.yaml."""
    with open(context_sources_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    mapping = data.get("context_mapping", {})
    return {f["name"]: f for f in mapping.get("cumulative_fields", [])}


def init_context(field_configs: dict[str, Any]) -> dict[str, Any]:
    """Initialize an empty cumulative context."""
    cumulative = {}
    for name, cfg in field_configs.items():
        ftype = cfg.get("type", "list")
        if ftype == "list":
            cumulative[name] = []
        elif ftype == "dict":
            cumulative[name] = {}
        else:
            cumulative[name] = None
    return {
        "cumulative": cumulative,
        "recent_units": [],
    }


def update_context(
    context: dict[str, Any],
    extractions: dict[str, Any],
    field_configs: dict[str, Any],
    domain_config: dict[str, Any],
    unit_index: int,
    unit_text: str,
) -> dict[str, Any]:
    """Update cumulative context with new extractions from a checked unit.

    Args:
        context: Current context {cumulative, recent_units}
        extractions: Agent's extracted data for this unit
        field_configs: Cumulative field definitions from context-sources.yaml
        domain_config: domain_config section from domain-config.yaml
        unit_index: Current paragraph index
        unit_text: Current paragraph text

    Returns:
        Updated context dict
    """
    ctx_config = domain_config.get("context", {})
    recent_window = ctx_config.get("recent_window", 3)

    cumulative = context.get("cumulative", {})

    # Process each extraction field
    for field_name, field_cfg in field_configs.items():
        if field_name not in extractions:
            continue
        if field_name not in cumulative:
            continue

        new_data = extractions[field_name]
        if new_data is None:
            continue

        ftype = field_cfg.get("type", "list")
        strategy = field_cfg.get("update_strategy", "append")
        max_size = field_cfg.get("max_size")
        sample_rate = field_cfg.get("sample_rate", 0)
        conf_cfg = field_cfg.get("confidence", {})
        track_confidence = conf_cfg.get("track", False)
        tentative_threshold = conf_cfg.get("tentative_threshold", 0.7)
        correction_strategy = conf_cfg.get("correction_strategy", "override")

        if ftype == "list":
            _update_list_field(
                cumulative, field_name, new_data,
                max_size, track_confidence, tentative_threshold,
                correction_strategy, unit_index,
            )
        elif ftype == "dict":
            _update_dict_field(
                cumulative, field_name, new_data,
                track_confidence, tentative_threshold,
                correction_strategy, unit_index,
            )

        # Sampling: for fields with sample_rate > 0, only update every N units
        # (Applied at extraction level by the agent, not here)

    # Update sliding window
    recent = context.get("recent_units", [])
    recent.append({
        "index": unit_index,
        "text": unit_text,
    })
    if len(recent) > recent_window:
        recent = recent[-recent_window:]

    return {
        "cumulative": cumulative,
        "recent_units": recent,
    }


def _update_list_field(
    cumulative: dict, field_name: str, new_data: Any,
    max_size: int | None, track_confidence: bool,
    tentative_threshold: float, correction_strategy: str,
    unit_index: int,
):
    """Update a list-type cumulative field with FIFO and confidence."""
    items = cumulative[field_name]

    # Normalize new_data to list
    if isinstance(new_data, dict):
        new_items = [new_data]
    elif isinstance(new_data, list):
        new_items = new_data
    else:
        return

    for item in new_items:
        if track_confidence:
            confidence = item.get("confidence", 1.0)
            item["tentative"] = confidence < tentative_threshold
            item["source_paragraph"] = unit_index

            # Check for contradictions with existing items
            if correction_strategy == "override":
                contradicted = _find_contradictory_list(item, items, field_name)
                if contradicted is not None:
                    if confidence > items[contradicted].get("confidence", 0):
                        items[contradicted] = item
                    continue  # Don't append either way

        items.append(item)

    # FIFO trimming
    if max_size and len(items) > max_size:
        cumulative[field_name] = items[-max_size:]


def _update_dict_field(
    cumulative: dict, field_name: str, new_data: Any,
    track_confidence: bool, tentative_threshold: float,
    correction_strategy: str, unit_index: int,
):
    """Update a dict-type cumulative field (merge strategy)."""
    target = cumulative[field_name]

    if isinstance(new_data, dict):
        entries = new_data.items()
    else:
        return

    for key, value in entries:
        entry = {"value": value, "updated_at": unit_index}
        if track_confidence:
            # Confidence may be embedded in the value if it's a dict
            if isinstance(value, dict) and "confidence" in value:
                conf = value["confidence"]
                entry["confidence"] = conf
                entry["tentative"] = conf < tentative_threshold
                entry["value"] = value.get("value", value)
            else:
                entry["confidence"] = 1.0
                entry["tentative"] = False

        if correction_strategy == "override" and key in target:
            existing = target[key]
            # Override if new confidence > existing
            if track_confidence:
                new_conf = entry.get("confidence", 1.0)
                old_conf = existing.get("confidence", 1.0)
                if existing.get("tentative", False) and new_conf > old_conf:
                    target[key] = entry
                elif not existing.get("tentative", False):
                    pass  # Keep existing non-tentative
                else:
                    target[key] = entry
            else:
                target[key] = entry
        else:
            target[key] = entry


def _find_contradictory_list(
    new_item: dict, existing: list[dict], field_name: str,
) -> int | None:
    """Check if new_item contradicts any existing item in a list field.

    Returns index of contradicted item, or None.
    Simple heuristic: same field value content treated as same fact.
    """
    new_text = new_item.get("fact", new_item.get("info", ""))
    if not new_text:
        return None

    for i, existing_item in enumerate(existing):
        ex_text = existing_item.get("fact", existing_item.get("info", ""))
        if not ex_text:
            continue
        # Simple contradiction: same key terms but different content
        # This is a heuristic; LLM (Phase 2) does better contradiction detection
        if _is_contradictory(new_text, ex_text):
            return i

    return None


def _is_contradictory(text_a: str, text_b: str) -> bool:
    """Simple contradiction heuristic for Chinese text.

    Checks if two texts about the same entity have different state descriptions.
    This is intentionally conservative - only flags clear contradictions.
    """
    # Extract entity-state pairs using common patterns
    # "角色A受伤" vs "角色A健康" → contradictory
    # This is a simplified version; real contradiction detection is done by LLM
    if not text_a or not text_b:
        return False

    # Overlap ratio: if texts share significant content, they might be about the same thing
    chars_a = set(text_a)
    chars_b = set(text_b)
    overlap = len(chars_a & chars_b) / min(len(chars_a), len(chars_b), 1)

    # High overlap but different text → potential contradiction
    if overlap > 0.7 and text_a != text_b:
        return True

    return False
