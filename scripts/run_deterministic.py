#!/usr/bin/env python3
"""CLI: Run all Phase 1 deterministic rules against text.

Usage:
    python3 run_deterministic.py \
      --input chapters/chapter-01.md \
      --rules-dir workspace-checker/rules/deterministic/ \
      --config workspace-checker/context/domain-config.yaml \
      --context-dir workspace-checker/context/ \
      --genre xianxia

Output: JSON { violations[], summary }
"""

import argparse
import json
import math
import os
import re
import statistics
import sys
from typing import Any

from lib.rule_loader import classify_rule, load_rules
from lib.text_utils import load_config, split_text


# ---------------------------------------------------------------------------
# Violation helper
# ---------------------------------------------------------------------------

def make_violation(rule: dict, para_idx: int | None, sent_idx: int | None,
                   text: str, message: str | None = None) -> dict:
    """Build a standardized violation record."""
    return {
        "rule_id": rule["id"],
        "rule_name": rule.get("name", ""),
        "location": {
            "paragraph": para_idx,
            "sentence": sent_idx,
        },
        "original_text": text[:200] if text else "",
        "severity": rule.get("severity", "warning"),
        "weight": rule.get("weight", 3),
        "issue": message or rule.get("message", ""),
        "source": "deterministic",
        "correlation_group": None,
        "is_primary": True,
    }


# ---------------------------------------------------------------------------
# Type handlers
# ---------------------------------------------------------------------------

def check_pattern(rule: dict, l1_units: list[dict], **_kw) -> list[dict]:
    """Single regex pattern matching per sentence."""
    violations = []
    pat = rule.get("pattern", "")
    if not pat:
        return violations
    for l1 in l1_units:
        if re.search(pat, l1["text"]):
            violations.append(make_violation(
                rule, l1.get("paragraph_index"), l1["index"], l1["text"]))
    return violations


def check_patterns(rule: dict, l1_units: list[dict], **_kw) -> list[dict]:
    """Multiple regex patterns, any match triggers."""
    violations = []
    patterns = rule.get("patterns", [])
    for l1 in l1_units:
        for pat in patterns:
            if re.search(pat, l1["text"]):
                violations.append(make_violation(
                    rule, l1.get("paragraph_index"), l1["index"], l1["text"]))
                break  # one violation per sentence for this rule
    return violations


def check_density(rule: dict, full_text: str, l1_units: list[dict],
                  **_kw) -> list[dict]:
    """Word density: count each word occurrence, flag if density exceeds threshold.

    Threshold format: "每3000字允许1次（单词）"
    Logic: per 3000 chars, each word may appear at most 1 time.
    """
    violations = []
    words = rule.get("words", [])
    if not words:
        return violations

    threshold = rule.get("threshold", "")
    # Parse: per 3000 chars, max 1 occurrence per word
    char_window = 3000
    max_per_word = 1
    m = re.search(r"每(\d+)字允许(\d+)次", str(threshold))
    if m:
        char_window = int(m.group(1))
        max_per_word = int(m.group(2))

    total_chars = len(full_text)
    # If text < char_window, use whole text
    if total_chars <= char_window:
        for word in words:
            count = full_text.count(word)
            if count > max_per_word:
                violations.append(make_violation(
                    rule, None, None, word,
                    f"'{word}' 出现 {count} 次，超过阈值（每{char_window}字≤{max_per_word}次）"))
    else:
        # Slide through text in char_window chunks
        for start in range(0, total_chars, char_window):
            chunk = full_text[start:start + char_window]
            for word in words:
                count = chunk.count(word)
                if count > max_per_word:
                    violations.append(make_violation(
                        rule, None, None, word,
                        f"'{word}' 在窗口[{start}:{start+char_window}]出现 {count} 次，"
                        f"超过阈值（每{char_window}字≤{max_per_word}次）"))

    return violations


def check_fatigue(rule: dict, full_text: str, genre: str, **_kw) -> list[dict]:
    """Fatigue words: each word may appear at most once per chapter for the given genre."""
    violations = []
    genre_profiles = rule.get("genre_profiles", {})
    words = genre_profiles.get(genre, [])
    if not words:
        # Try all genres combined if specific genre not found
        for g_words in genre_profiles.values():
            words.extend(g_words)
    if not words:
        return violations

    for word in words:
        count = full_text.count(word)
        if count > 1:
            violations.append(make_violation(
                rule, None, None, word,
                f"疲劳词 '{word}' 出现 {count} 次，超过阈值（每章≤1次）"))

    return violations


def check_keyword_list(rule: dict, full_text: str, **_kw) -> list[dict]:
    """Keyword list: count keywords/words, max 1 per chapter."""
    violations = []
    # Some rules use 'keywords', others use 'words'
    words = rule.get("keywords", rule.get("words", []))
    if not words:
        return violations

    for word in words:
        count = full_text.count(word)
        if count > 1:
            violations.append(make_violation(
                rule, None, None, word,
                f"'{word}' 出现 {count} 次，超过阈值（全章≤1次）"))

    return violations


def check_consecutive(rule: dict, l1_units: list[dict], **_kw) -> list[dict]:
    """Consecutive sentences containing target_char exceeding threshold."""
    violations = []
    target = rule.get("target_char", "")
    threshold = rule.get("threshold", 6)
    if not target:
        return violations

    run_start = None
    run_count = 0
    for i, l1 in enumerate(l1_units):
        if target in l1["text"]:
            if run_start is None:
                run_start = i
            run_count += 1
        else:
            if run_count >= threshold:
                violations.append(make_violation(
                    rule,
                    l1_units[run_start].get("paragraph_index"),
                    l1_units[run_start]["index"],
                    l1_units[run_start]["text"],
                    f"连续 {run_count} 句含「{target}」，超过阈值 {threshold}"))
            run_start = None
            run_count = 0

    # Check tail
    if run_count >= threshold:
        violations.append(make_violation(
            rule,
            l1_units[run_start].get("paragraph_index"),
            l1_units[run_start]["index"],
            l1_units[run_start]["text"],
            f"连续 {run_count} 句含「{target}」，超过阈值 {threshold}"))

    return violations


def check_length(rule: dict, l2_units: list[dict], **_kw) -> list[dict]:
    """Paragraph length check: flag if >= min_violations paragraphs exceed threshold chars."""
    violations = []
    threshold = rule.get("threshold", 300)
    min_violations = rule.get("min_violations", 2)

    long_paras = []
    for l2 in l2_units:
        if l2["char_count"] > threshold:
            long_paras.append(l2)

    if len(long_paras) >= min_violations:
        for l2 in long_paras:
            violations.append(make_violation(
                rule, l2["index"], None, l2["text"],
                f"段落 {l2['index']} 共 {l2['char_count']} 字，超过 {threshold} 字"))

    return violations


def check_pattern_list(rule: dict, l1_units: list[dict],
                       l2_units: list[dict], full_text: str,
                       **_kw) -> list[dict]:
    """Multiple regex patterns combined (chapter-level).

    For D008 (collective reaction cliches): match against each sentence.
    For D011 (list structure): match against full text.
    """
    violations = []
    patterns = rule.get("patterns", [])
    if not patterns:
        return violations

    # Determine scope: if all patterns span multiple sentences, use full_text
    # Otherwise check per sentence
    has_multi_sentence = any(".*" in p and len(p) > 15 for p in patterns)

    if has_multi_sentence:
        # Full-text scope (e.g., D011 list patterns)
        for pat in patterns:
            if re.search(pat, full_text):
                # Find approximate location
                for l2 in l2_units:
                    if re.search(pat, l2["text"]):
                        violations.append(make_violation(
                            rule, l2["index"], None, l2["text"]))
                        break
                else:
                    violations.append(make_violation(
                        rule, None, None, full_text[:200]))
                break  # one violation per rule
    else:
        # Per-sentence scope (e.g., D008)
        seen = set()
        for l1 in l1_units:
            for pat in patterns:
                if re.search(pat, l1["text"]):
                    key = (l1.get("paragraph_index"), l1["index"])
                    if key not in seen:
                        seen.add(key)
                        violations.append(make_violation(
                            rule, l1.get("paragraph_index"), l1["index"], l1["text"]))
                    break

    return violations


def check_consecutive_pattern(rule: dict, l2_units: list[dict], **_kw) -> list[dict]:
    """Consecutive paragraphs with similar opening patterns.

    Check if >= threshold consecutive paragraphs share the same opening character
    or sentence pattern.
    """
    violations = []
    threshold = rule.get("threshold", 3)
    if len(l2_units) < threshold:
        return violations

    def opening_key(text: str) -> str:
        """Extract a normalized opening key for comparison."""
        stripped = text.strip()
        if not stripped:
            return ""
        # Use first 2 characters as key (covers same char, same name, etc.)
        return stripped[:2]

    run_start = 0
    current_key = opening_key(l2_units[0]["text"])
    run_count = 1

    for i in range(1, len(l2_units)):
        key = opening_key(l2_units[i]["text"])
        if key == current_key and key:
            run_count += 1
        else:
            if run_count >= threshold:
                violations.append(make_violation(
                    rule, l2_units[run_start]["index"], None,
                    l2_units[run_start]["text"],
                    f"连续 {run_count} 段以 '{current_key}' 开头"))
            current_key = key
            run_start = i
            run_count = 1

    # Check tail
    if run_count >= threshold:
        violations.append(make_violation(
            rule, l2_units[run_start]["index"], None,
            l2_units[run_start]["text"],
            f"连续 {run_count} 段以 '{current_key}' 开头"))

    return violations


def _load_settings_release(context_dir: str) -> list[dict] | None:
    """Load settings_release.json from context dir or subdirs."""
    candidates = [
        os.path.join(context_dir, "settings_release.json"),
        os.path.join(context_dir, "state", "settings_release.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("settings", data)
    return None


def check_settings_gate(rule: dict, full_text: str, context_dir: str,
                        l1_units: list[dict], **_kw) -> list[dict]:
    """Settings gate checks (D013-D015).

    Reads settings_release.json and checks for:
    - D013: unreleased settings referenced
    - D014: knowledge level exceeded
    - D015: released settings reintroduced as new
    """
    violations = []
    rule_id = rule.get("id", "")
    settings = _load_settings_release(context_dir)
    if settings is None:
        return violations

    if rule_id == "D013":
        # Check for unreleased settings referenced
        for setting in settings:
            if setting.get("status") != "unreleased":
                continue
            name = setting.get("name", "")
            if name and name in full_text:
                # Find the sentence
                for l1 in l1_units:
                    if name in l1["text"]:
                        violations.append(make_violation(
                            rule, l1.get("paragraph_index"), l1["index"],
                            l1["text"],
                            f"引用了未释放设定 '{name}'"))
                        break
                else:
                    violations.append(make_violation(
                        rule, None, None, name,
                        f"引用了未释放设定 '{name}'"))

    elif rule_id == "D014":
        # Check for knowledge level violation
        # Simplified: check if detailed descriptions exist for limited knowledge settings
        signal_patterns = [
            r"内部结构", r"核心原理", r"运作机制", r"本质是",
            r"真正的原因", r"背后的真相", r"深层原理",
        ]
        for setting in settings:
            status = setting.get("status", "")
            if status not in ("released", "partially_released"):
                continue
            name = setting.get("name", "")
            knowledge = setting.get("knowledge_level", "")
            # If knowledge level suggests only surface knowledge
            surface_keywords = ["外观", "表面", "基本", "名称", "存在"]
            if any(kw in knowledge for kw in surface_keywords):
                for pat in signal_patterns:
                    for l1 in l1_units:
                        if name in l1["text"] and re.search(pat, l1["text"]):
                            violations.append(make_violation(
                                rule, l1.get("paragraph_index"), l1["index"],
                                l1["text"],
                                f"对设定 '{name}' 的描述超出认知级别 '{knowledge}'"))
                            break

    elif rule_id == "D015":
        # Check for released settings reintroduced as new
        reintroduction_signals = [
            "第一次见到", "从未见过", "竟然是", "居然是",
            "第一次看到", "头一回见", "前所未见",
        ]
        for setting in settings:
            if setting.get("status") != "released":
                continue
            name = setting.get("name", "")
            if not name:
                continue
            for l1 in l1_units:
                if name in l1["text"]:
                    for signal in reintroduction_signals:
                        if signal in l1["text"]:
                            violations.append(make_violation(
                                rule, l1.get("paragraph_index"), l1["index"],
                                l1["text"],
                                f"已释放设定 '{name}' 被当作新发现重新引入"))
                            break

    return violations


def check_statistical(rule: dict, full_text: str,
                      l1_units: list[dict], l2_units: list[dict],
                      **_kw) -> list[dict]:
    """Statistical checks: TTR, sentence length std, paragraph length std, active voice ratio."""
    violations = []
    metric = rule.get("metric", "")
    threshold = rule.get("threshold", 0)
    comparison = rule.get("comparison", "less_than")
    rule_id = rule.get("id", "")

    value = None

    if metric == "ttr":
        value = _calc_ttr(full_text)
    elif metric == "sentence_length_std":
        value = _calc_sentence_length_std(l1_units)
    elif metric == "paragraph_length_std":
        value = _calc_paragraph_length_std(l2_units)
    elif metric == "active_voice_ratio":
        value = _calc_active_voice_ratio(l1_units)
    elif metric == "total_char_count":
        value = len(re.sub(r'\s', '', full_text))

    if value is None:
        return violations

    triggered = False
    if comparison == "less_than" and value < threshold:
        triggered = True
    elif comparison == "greater_than" and value > threshold:
        triggered = True

    if triggered:
        violations.append(make_violation(
            rule, None, None, "",
            f"{rule.get('name', metric)} = {value:.4f}，"
            f"{'<' if comparison == 'less_than' else '>'} 阈值 {threshold}"))

    return violations


def _calc_ttr(text: str) -> float:
    """Calculate Type-Token Ratio using jieba segmentation.

    Falls back to character-level TTR if jieba is unavailable.
    """
    try:
        import jieba
        tokens = list(jieba.cut(text))
        # Filter whitespace and punctuation
        tokens = [t for t in tokens if t.strip() and not re.match(r'^[\s\W]+$', t)]
    except ImportError:
        # Fallback: character-level TTR
        tokens = [c for c in text if not c.isspace()]

    if not tokens:
        return 1.0

    unique = len(set(tokens))
    total = len(tokens)
    return unique / total if total > 0 else 0.0


def _calc_sentence_length_std(l1_units: list[dict]) -> float:
    """Calculate standard deviation of sentence lengths."""
    if len(l1_units) < 2:
        return 0.0
    lengths = [l1["char_count"] for l1 in l1_units]
    return statistics.stdev(lengths)


def _calc_paragraph_length_std(l2_units: list[dict]) -> float:
    """Calculate standard deviation of paragraph lengths."""
    if len(l2_units) < 2:
        return 0.0
    lengths = [l2["char_count"] for l2 in l2_units]
    return statistics.stdev(lengths)


def _calc_active_voice_ratio(l1_units: list[dict]) -> float:
    """Estimate active voice ratio.

    Heuristic: detect common passive markers in Chinese.
    Passive indicators: 被、受、遭、让、叫、给、为...所
    """
    if not l1_units:
        return 1.0

    passive_patterns = [
        r"被[^，。！？]{1,10}[了着过]",
        r"受[^，。！？]{1,10}[了着过]",
        r"遭[^，。！？]{1,10}[了着过]",
        r"让[^，。！？]{1,10}[了着过]",
        r"为[^，。！？]{0,5}所",
        r"是[^，。！？]{0,10}的",  # "是...的" cleft sentences
    ]

    total = len(l1_units)
    passive_count = 0
    for l1 in l1_units:
        for pat in passive_patterns:
            if re.search(pat, l1["text"]):
                passive_count += 1
                break

    return (total - passive_count) / total if total > 0 else 1.0


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

TYPE_HANDLERS = {
    "pattern": check_pattern,
    "patterns": check_patterns,
    "density": check_density,
    "fatigue": check_fatigue,
    "keyword_list": check_keyword_list,
    "consecutive": check_consecutive,
    "length_check": check_length,
    "pattern_list": check_pattern_list,
    "consecutive_pattern": check_consecutive_pattern,
    "settings_gate": check_settings_gate,
    "statistical": check_statistical,
}


def run_all(rules: list[dict], full_text: str,
            l1_units: list[dict], l2_units: list[dict],
            genre: str, context_dir: str) -> dict:
    """Run all deterministic rules and return {violations, summary}."""
    all_violations = []
    rules_run = 0
    rules_by_type: dict[str, int] = {}

    for rule in rules:
        rtype = classify_rule(rule)
        rules_run += 1
        rules_by_type[rtype] = rules_by_type.get(rtype, 0) + 1

        handler = TYPE_HANDLERS.get(rtype)
        if handler is None:
            continue

        kwargs = {
            "rule": rule,
            "full_text": full_text,
            "l1_units": l1_units,
            "l2_units": l2_units,
            "genre": genre,
            "context_dir": context_dir,
        }
        # Only pass relevant kwargs to each handler
        import inspect
        sig = inspect.signature(handler)
        filtered_kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
        # Always pass **_kw compatible handlers
        if "_kw" in sig.parameters or "kwargs" in sig.parameters:
            filtered_kwargs = kwargs

        try:
            viols = handler(**filtered_kwargs)
            all_violations.extend(viols)
        except Exception as e:
            print(f"Warning: rule {rule.get('id', '?')} failed: {e}", file=sys.stderr)

    summary = {
        "rules_run": rules_run,
        "rules_by_type": rules_by_type,
        "total_violations": len(all_violations),
        "critical_count": sum(1 for v in all_violations if v["severity"] == "critical"),
        "warning_count": sum(1 for v in all_violations if v["severity"] == "warning"),
        "suggestion_count": sum(1 for v in all_violations if v["severity"] == "suggestion"),
    }

    return {
        "violations": all_violations,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run Phase 1 deterministic rules")
    parser.add_argument("--input", required=True, help="Path to text file")
    parser.add_argument("--rules-dir", required=True, help="Directory with deterministic rule YAMLs")
    parser.add_argument("--config", required=True, help="Path to domain-config.yaml")
    parser.add_argument("--context-dir", default="", help="Directory with context files (for settings_gate)")
    parser.add_argument("--genre", default="xianxia", help="Genre for fatigue word selection")
    args = parser.parse_args()

    config = load_config(args.config)
    rules = load_rules(args.rules_dir)

    with open(args.input, "r", encoding="utf-8") as f:
        text = f.read()

    split_result = split_text(text, config)

    result = run_all(
        rules=rules,
        full_text=text,
        l1_units=split_result["l1_units"],
        l2_units=split_result["l2_units"],
        genre=args.genre,
        context_dir=args.context_dir,
    )

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
