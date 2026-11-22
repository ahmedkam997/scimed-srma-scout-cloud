from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from scimed_scout.domain import SourceAudit, SourceStatus
from .constants import MIN_DISCOVERY_STUDIES

VALID_FEASIBILITY = {"HIGH", "STRONG MODERATE"}
VALID_EDITORIAL_GRADES = {"A", "B", "CORRECTED C"}

@dataclass(frozen=True, slots=True)
class DiscoveryGateResult:
    number: int
    name: str
    passed: bool
    observed: Any
    requirement: str

def evaluate_discovery_gates(data: dict[str, Any]) -> list[DiscoveryGateResult]:
    feasibility = str(data.get("feasibility", "")).strip().upper()
    editorial = str(data.get("editorial_grade", "")).strip().upper()
    studies = int(data.get("unique_primary_study_candidates", 0) or 0)
    complete_literature = int(data.get("complete_literature_sources", 0) or 0)
    checks = [
        ("Eligible study-design framework defined", _truth(data.get("design_framework_defined")), data.get("design_framework_defined"), "PASS"),
        ("Unique primary-study candidates discovered", studies >= MIN_DISCOVERY_STUDIES, studies, f">= {MIN_DISCOVERY_STUDIES}"),
        ("Minimum scholarly literature coverage completed", complete_literature >= 2, complete_literature, ">= 2 conclusive literature sources"),
        ("Meaningful synthesis appears plausible", _truth(data.get("meaningful_synthesis_plausible")), data.get("meaningful_synthesis_plausible"), "PASS"),
        ("Clinical-question novelty", _score(data.get("clinical_question_novelty")) >= 3, data.get("clinical_question_novelty", 0), ">= 3/5"),
        ("Overall novelty", _score(data.get("overall_novelty")) >= 3, data.get("overall_novelty", 0), ">= 3/5"),
        ("No fatal recent identical review redundancy", _explicit_false(data.get("fatal_redundancy")) and _sources_support_negative_inference(data.get("sources", [])), data.get("fatal_redundancy"), "FALSE with conclusive required source audits"),
        ("Coherent review-question framework", _truth(data.get("question_framework_coherent")), data.get("question_framework_coherent"), "PASS"),
        ("Review feasibility", feasibility in VALID_FEASIBILITY, feasibility, "HIGH or STRONG MODERATE"),
        ("No fatal methodological flaw", _explicit_false(data.get("fatal_methodological_flaw")), data.get("fatal_methodological_flaw"), "FALSE"),
        ("Clinical importance", _score(data.get("clinical_importance")) >= 4, data.get("clinical_importance", 0), ">= 4/5"),
        ("Publication potential", _score(data.get("publication_potential")) >= 4, data.get("publication_potential", 0), ">= 4/5"),
        ("New information gain", _score(data.get("new_information_gain")) >= 4, data.get("new_information_gain", 0), ">= 4/5"),
        ("Publication-Oriented Score", _score(data.get("publication_oriented_score")) >= 75, data.get("publication_oriented_score", 0), ">= 75/100"),
        ("Editorial stress-test grade", editorial in VALID_EDITORIAL_GRADES, editorial, "A, B, or CORRECTED C"),
    ]
    return [DiscoveryGateResult(i, name, passed, observed, requirement) for i, (name, passed, observed, requirement) in enumerate(checks, 1)]

def final_discovery_decision(data: dict[str, Any]) -> dict[str, Any]:
    gates = evaluate_discovery_gates(data)
    unresolved = list(data.get("unresolved_type_a") or [])
    passed = all(g.passed for g in gates) and not unresolved
    return {
        "decision": "QUALIFIED — FIRST-CHOICE REVIEW TOPIC" if passed else "DO NOT INCLUDE IN FINAL DISCOVERY LIST",
        "all_discovery_gates_passed": all(g.passed for g in gates),
        "unresolved_type_a": unresolved,
        "gates": [asdict(g) for g in gates],
    }

def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() in {"YES", "TRUE", "1", "PASS"}

def _explicit_false(value: Any) -> bool:
    if isinstance(value, bool):
        return value is False
    return str(value).strip().upper() in {"NO", "FALSE", "0", "FAIL"}

def _score(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0

def _sources_support_negative_inference(sources: Any) -> bool:
    if not isinstance(sources, list) or not sources:
        return False
    for audit in sources:
        if not isinstance(audit, dict):
            return False
        try:
            status = SourceStatus(audit.get("status"))
        except (TypeError, ValueError):
            return False
        if not SourceAudit(source=str(audit.get("source") or ""), status=status).supports_negative_inference:
            return False
    return True
