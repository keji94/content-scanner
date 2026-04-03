"""Scoring engine for content scanner.

Implements correlation grouping, deduplication, score calculation, and grade assignment.
"""

from typing import Any


SEVERITY_ORDER = {"critical": 3, "warning": 2, "suggestion": 1}


def compute_correlation_groups(
    violations: list[dict],
    correlation_config: dict[str, list[str]],
) -> dict[str, list[dict]]:
    """Assign correlation_group to each violation and identify primaries.

    Returns:
        Mapping of group_name -> list of violations in that group.
        Each violation gets 'correlation_group' and 'is_primary' fields set.
    """
    # Build rule_id -> group_name lookup
    rule_to_group: dict[str, str | None] = {}
    for group_name, rule_ids in correlation_config.items():
        for rid in rule_ids:
            rule_to_group[rid] = group_name

    # Assign groups
    for v in violations:
        v["correlation_group"] = rule_to_group.get(v["rule_id"])

    # Group by (location, correlation_group) for dedup
    # Within each (paragraph, sentence, group), keep only highest severity
    groups_by_location: dict[tuple, list[dict]] = {}
    ungrouped: list[dict] = []

    for v in violations:
        cg = v.get("correlation_group")
        if cg is None:
            v["is_primary"] = True
            ungrouped.append(v)
            continue

        loc_key = (v["location"].get("paragraph"), v["location"].get("sentence"), cg)
        groups_by_location.setdefault(loc_key, []).append(v)

    # Within each group, mark highest severity as primary
    for loc_key, group_viols in groups_by_location.items():
        # Sort by severity descending
        group_viols.sort(key=lambda v: SEVERITY_ORDER.get(v["severity"], 0), reverse=True)
        for i, v in enumerate(group_viols):
            v["is_primary"] = (i == 0)

    return groups_by_location  # for reference, mainly side-effects on violations


def calculate_score(
    violations: list[dict],
    scoring_config: dict[str, Any],
) -> dict[str, Any]:
    """Calculate score and grade from violations.

    Args:
        violations: List of violation dicts with correlation_group and is_primary set
        scoring_config: The 'scoring' section from domain-config.yaml

    Returns:
        { score, grade, breakdown }
    """
    weight_map = {
        "critical": scoring_config.get("critical_weight", 10),
        "warning": scoring_config.get("warning_weight", 3),
        "suggestion": scoring_config.get("suggestion_weight", 1),
    }

    # Deduplicate: only count primary violations in correlation groups
    # + all ungrouped violations
    scored_violations = [v for v in violations if v.get("is_primary", True)]

    deduction = 0
    for v in scored_violations:
        if v.get("is_primary", True) or v.get("correlation_group") is None:
            deduction += weight_map.get(v["severity"], 1)

    score = max(0, 100 - deduction)

    # Count by severity
    critical_count = sum(1 for v in violations if v["severity"] == "critical")
    warning_count = sum(1 for v in violations if v["severity"] == "warning")

    # Determine grade
    grade = _determine_grade(score, critical_count, warning_count,
                             scoring_config.get("grade_thresholds", {}))

    return {
        "score": score,
        "grade": grade,
        "deduction": deduction,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "suggestion_count": sum(1 for v in violations if v["severity"] == "suggestion"),
        "total_violations": len(violations),
    }


def _determine_grade(score: int, critical: int, warning: int,
                     thresholds: dict) -> str:
    """Determine letter grade based on score and violation counts.

    Checks from highest grade down, returns first match.
    """
    # Default thresholds
    defaults = {
        "A": {"min_score": 90, "max_critical": 0, "max_warning": 3},
        "B": {"min_score": 80, "max_critical": 0, "max_warning": 5},
        "C": {"min_score": 70, "max_critical": 2},
        "D": {"min_score": 0, "max_critical": 999},
    }

    if not thresholds:
        thresholds = defaults

    for grade_name in ["A", "B", "C", "D"]:
        t = thresholds.get(grade_name, defaults.get(grade_name, {}))
        min_score = t.get("min_score", 0)
        max_critical = t.get("max_critical", 999)
        max_warning = t.get("max_warning", 999999)

        if score >= min_score and critical <= max_critical and warning <= max_warning:
            return grade_name

    return "D"
