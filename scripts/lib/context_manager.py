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
                correction_strategy, unit_index, domain_config,
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
    unit_index: int, domain_config: dict[str, Any] | None = None,
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

    # FIFO trimming with optional compression
    if max_size and len(items) > max_size:
        cumulative[field_name] = _trim_list_field(
            items, max_size, domain_config, field_name
        )


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
    Uses entity-state pair extraction for improved accuracy.
    """
    new_text = new_item.get("fact", new_item.get("info", ""))
    if not new_text:
        return None

    for i, existing_item in enumerate(existing):
        ex_text = existing_item.get("fact", existing_item.get("info", ""))
        if not ex_text:
            continue
        if _is_contradictory(new_text, ex_text):
            return i

    return None


def _is_contradictory(text_a: str, text_b: str) -> bool:
    """Entity-aware contradiction detection for Chinese text.

    Strategy:
    1. Extract entity-state pairs from both texts
    2. If same entity has different states → contradiction
    3. If one text refines the other (substring relationship) → not contradiction
    4. Fall back to character overlap heuristic
    """
    if not text_a or not text_b:
        return False

    # Same text → no contradiction
    if text_a == text_b:
        return False

    # Refinement check: if one contains the other, it's a refinement not contradiction
    # e.g., "受了重伤" is refined by "受了重伤，伤口已经溃烂"
    shorter, longer = (text_a, text_b) if len(text_a) <= len(text_b) else (text_b, text_a)
    if shorter in longer:
        return False

    # Entity-state extraction
    pairs_a = _extract_entity_state_pairs(text_a)
    pairs_b = _extract_entity_state_pairs(text_b)

    if pairs_a and pairs_b:
        # Check for same entity with contradictory states
        for entity_a, state_a in pairs_a:
            for entity_b, state_b in pairs_b:
                if entity_a == entity_b and state_a != state_b:
                    # Same entity, different states — check if truly contradictory
                    if _states_are_opposite(state_a, state_b):
                        return True
        # Both have entity-state pairs but no opposing states → not contradictory
        return False

    # Fallback: character overlap heuristic (higher threshold to reduce false positives)
    chars_a = set(text_a)
    chars_b = set(text_b)
    denom = max(min(len(chars_a), len(chars_b)), 1)
    overlap = len(chars_a & chars_b) / denom

    if overlap > 0.8 and text_a != text_b:
        return True

    return False


def _extract_entity_state_pairs(text: str) -> list[tuple[str, str]]:
    """Extract (entity, state) pairs from Chinese text using pattern matching.

    Recognized patterns:
    - "角色A受了重伤" → ("角色A", "受了重伤")
    - "主角A处于愤怒状态" → ("主角A", "愤怒状态")
    - "宝剑已获得" → ("宝剑", "已获得")
    - "老者微微点头" → ("老者", "微微点头")
    """
    import re

    pairs = []

    # Pattern: {entity}{action_verb}{state}
    # Action verbs that connect entity to state
    action_patterns = [
        r"(.{1,6}?)(受了|变成|变成了|处于|属于|位于|拥有|获得|失去了?|变成了?)(.{1,10})",
        r"(.{1,6}?)(已经|已|正在|正)(.{1,10})",
        r"(.{1,6}?)(微微|猛然|突然|渐渐|慢慢)(.{1,6})",
        # State suffixes: {entity}{state_ending}
        r"(.{1,6}?)(毫发无伤|安然无恙|精疲力竭|筋疲力尽|身受重伤|伤势加重|伤势恶化)",
        r"(.{1,6}?)(站在|坐在|躺在|跪在|靠在)(.{1,10})",
    ]

    for pattern in action_patterns:
        for match in re.finditer(pattern, text):
            entity = match.group(1).strip()
            # Handle patterns with 2 or 3 groups
            if match.lastindex >= 3:
                state = match.group(2) + match.group(3)
            else:
                state = match.group(2)
            if entity and state and len(entity) >= 2:
                pairs.append((entity, state))

    return pairs


def _trim_list_field(
    items: list[dict], max_size: int,
    domain_config: dict[str, Any] | None, field_name: str,
) -> list[dict]:
    """Trim a list field using compression or FIFO.

    When domain_config has context.compression.enabled=true,
    compresses old entries into summary items instead of dropping them.
    Otherwise, uses simple FIFO trimming.
    """
    if domain_config is None:
        return items[-max_size:]

    compression_cfg = domain_config.get("context", {}).get("compression", {})
    if not compression_cfg.get("enabled", False):
        return items[-max_size:]

    strategy = compression_cfg.get("strategy", "fifo")
    if strategy != "summarize":
        return items[-max_size:]

    # Compression: merge oldest N items into a summary entry
    summarize_at = compression_cfg.get("summarize_at", 0.8)
    if len(items) <= max_size * summarize_at:
        return items

    # Compress the oldest third into a summary
    n_to_compress = max(1, len(items) // 3)
    to_compress = items[:n_to_compress]
    remaining = items[n_to_compress:]

    # Build a heuristic summary from the compressed items
    compressed_facts = []
    for item in to_compress:
        text = item.get("fact", item.get("info", str(item)))
        if text:
            compressed_facts.append(text[:50])

    summary_text = "；".join(compressed_facts)
    if len(summary_text) > 200:
        summary_text = summary_text[:197] + "..."

    summary_entry = {
        "type": "summary",
        "original_count": len(to_compress),
        "summary": summary_text,
        "source_paragraph": to_compress[0].get("source_paragraph", 0),
    }

    result = [summary_entry] + remaining
    # Final safety trim
    if len(result) > max_size:
        result = result[-max_size:]

    return result


# Opposite character pairs for Chinese state contradiction detection
_OPPOSITE_PAIRS = [
    ("有", "无"), ("得", "失"), ("生", "死"), ("重", "轻"),
    ("进", "退"), ("上", "下"), ("内", "外"), ("安", "危"),
    ("存", "亡"), ("成", "败"), ("开", "关"), ("起", "落"),
    ("增", "减"), ("升", "降"), ("快", "慢"), ("强", "弱"),
    ("好", "坏"), ("新", "旧"), ("来", "去"), ("出", "入"),
    ("合", "分"), ("聚", "散"), ("攻", "守"), ("明", "暗"),
]


def _states_are_opposite(state_a: str, state_b: str) -> bool:
    """Check if two state descriptions contain opposing semantics.

    Returns True only if the states contain contradictory indicators
    (e.g., "已获得" vs "已失去", "毫发无伤" vs "受了重伤").
    Returns False for refinements (e.g., "受了重伤" vs "伤势加重").
    """
    # Check for opposite character pairs across the two states
    for char_a in state_a:
        for pos_char, neg_char in _OPPOSITE_PAIRS:
            if char_a == pos_char and neg_char in state_b:
                return True
            if char_a == neg_char and pos_char in state_b:
                return True

    # Check for negation patterns: "无X" / "不X" / "未X" in one state,
    # while the other state affirms X
    import re
    negation_patterns = [
        (r"无(.{1,2})", "affirm"),
        (r"不(.{1,2})", "affirm"),
        (r"未(.{1,2})", "affirm"),
        (r"没有(.{1,2})", "affirm"),
    ]
    for neg_pattern, _ in negation_patterns:
        neg_match_a = re.search(neg_pattern, state_a)
        neg_match_b = re.search(neg_pattern, state_b)
        if neg_match_a and neg_match_a.group(1) in state_b:
            return True
        if neg_match_b and neg_match_b.group(1) in state_a:
            return True

    # Check for shared state keywords → likely refinement, not contradiction
    state_keywords = {"痛", "怒", "喜", "悲", "惧", "累", "病", "弱", "勇"}
    shared = state_keywords & set(state_a) & set(state_b)
    if shared:
        return False

    return False
