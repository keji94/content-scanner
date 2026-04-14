"""Report generator for content scanner.

Assembles the final check report JSON from violations, score, and split data.
"""

from typing import Any


def generate_report(
    violations: list[dict],
    score_result: dict[str, Any],
    split_result: dict[str, Any],
    project: str,
    content_id: str,
    check_mode: str = "full",
    perspective_results: list[dict] | None = None,
) -> dict[str, Any]:
    """Generate the final check report JSON.

    Args:
        violations: All violations (Phase 1 + Phase 2) with correlation groups set
        score_result: Output from scoring.calculate_score()
        split_result: Output from text_utils.split_text()
        project: Project name
        content_id: Chapter/content identifier
        check_mode: "full" or "quick" (Phase 1 only)
        perspective_results: Phase 3 reader perspective results (optional)

    Returns:
        Complete report dict matching SKILL.md output format.
    """
    metadata = split_result.get("metadata", {})

    # Count by source
    det_passed = metadata.get("total_sentences", 0)  # approximation
    det_failed = sum(1 for v in violations if v.get("source") == "deterministic")
    llm_failed = sum(1 for v in violations if v.get("source") == "llm")

    report = {
        "status": "success",
        "check_summary": {
            "project": project,
            "chapter": content_id,
            "check_mode": check_mode,
            "total_paragraphs": metadata.get("total_paragraphs", 0),
            "total_sentences": metadata.get("total_sentences", 0),
            "violations_found": len(violations),
            "critical_count": score_result.get("critical_count", 0),
            "warning_count": score_result.get("warning_count", 0),
            "suggestion_count": score_result.get("suggestion_count", 0),
            "score": score_result.get("score", 100),
            "grade": score_result.get("grade", "A"),
        },
        "violations": violations,
        "score_breakdown": {
            "deterministic": {
                "failed": det_failed,
            },
            "llm": {
                "failed": llm_failed,
            },
            "deduction": score_result.get("deduction", 0),
        },
    }

    # Add Phase 3 perspective review section if available
    if perspective_results:
        report["perspective_review"] = {
            "perspectives": perspective_results,
            "perspective_avg": score_result.get("perspective_avg"),
            "perspective_weight": score_result.get("perspective_weight"),
        }

    return report
