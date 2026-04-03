"""Text splitting utilities for content scanner.

Splits text into L1 (sentence) and L2 (paragraph) units based on domain config.
"""

import re
from typing import Any


def load_config(config_path: str) -> dict[str, Any]:
    """Load domain-config.yaml and return the domain_config section."""
    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("domain_config", data)


def get_separators(config: dict[str, Any]) -> tuple[list[str], str]:
    """Extract L1 and L2 separators from config.

    Returns:
        (l1_seps, l2_sep): L1 separator chars as list, L2 separator string.
    """
    text_units = config.get("text_units", {})
    l1_sep_str = text_units.get("l1_separator", "。！？")
    l2_sep = text_units.get("l2_separator", "\\n")
    # Unescape
    l2_sep = l2_sep.replace("\\n", "\n").replace("\\t", "\t")
    return list(l1_sep_str), l2_sep


def split_l2(text: str, l2_sep: str = "\n") -> list[dict]:
    """Split text into L2 units (paragraphs).

    Returns:
        List of {index, text, char_count} dicts. Empty paragraphs are excluded.
    """
    raw_paragraphs = text.split(l2_sep)
    units = []
    idx = 0
    for p in raw_paragraphs:
        stripped = p.strip()
        if stripped:
            units.append({
                "index": idx,
                "text": stripped,
                "char_count": len(stripped),
            })
            idx += 1
    return units


def split_l1(text: str, l1_seps: list[str] | None = None) -> list[dict]:
    """Split text into L1 units (sentences).

    Args:
        text: The text to split. Can be a full chapter or a single paragraph.
        l1_seps: Sentence-ending punctuation characters. Default: [。, ！, ？]

    Returns:
        List of {index, text, char_count} dicts.
    """
    if l1_seps is None:
        l1_seps = ["。", "！", "？"]

    if not text.strip():
        return []

    # Build regex: split on any L1 separator, keeping the separator with the sentence
    sep_pattern = "[" + re.escape("".join(l1_seps)) + "]"
    # Split keeping delimiters
    parts = re.split(f"({sep_pattern}+)", text)

    sentences = []
    idx = 0
    current = ""
    for part in parts:
        current += part
        if re.match(f"^{sep_pattern}+$", part):
            stripped = current.strip()
            if stripped:
                sentences.append({
                    "index": idx,
                    "text": stripped,
                    "char_count": len(stripped),
                })
                idx += 1
                current = ""

    # Handle trailing text without ending punctuation
    if current.strip():
        sentences.append({
            "index": idx,
            "text": current.strip(),
            "char_count": len(current.strip()),
        })

    return sentences


def split_text(text: str, config: dict[str, Any]) -> dict:
    """Full text splitting into L1 and L2 units.

    Returns:
        {
            l1_units: [...],       # all sentences with global indices
            l2_units: [...],       # all paragraphs with global indices
            l2_to_l1: {...},       # paragraph_index -> [sentence indices]
            metadata: {...}
        }
    """
    l1_seps, l2_sep = get_separators(config)

    l2_units = split_l2(text, l2_sep)
    all_l1_units = []
    l2_to_l1 = {}

    for l2 in l2_units:
        l1_in_para = split_l1(l2["text"], l1_seps)
        start_idx = len(all_l1_units)
        # Remap local indices to global
        for l1 in l1_in_para:
            l1["paragraph_index"] = l2["index"]
            l1["global_index"] = start_idx + l1["index"]
        l2_to_l1[l2["index"]] = list(range(start_idx, start_idx + len(l1_in_para)))
        all_l1_units.extend(l1_in_para)

    metadata = {
        "total_paragraphs": len(l2_units),
        "total_sentences": len(all_l1_units),
        "total_chars": len(text),
        "l1_separator": "".join(l1_seps),
        "l2_separator": repr(l2_sep),
    }

    return {
        "l1_units": all_l1_units,
        "l2_units": l2_units,
        "l2_to_l1": l2_to_l1,
        "metadata": metadata,
    }
