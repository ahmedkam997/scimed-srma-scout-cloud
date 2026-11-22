from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any

from .domain import SourceAudit, SourceStatus
from .evidence import MIN_STUDIES

VALID_FEASIBILITY = {"HIGH", "STRONG MODERATE"}
VALID_EDITORIAL_GRADES = {"A", "B", "CORRECTED C"}

@dataclass(frozen=True, slots=True)
class GateResult:
    number: int
    name: str
    passed: bool
    observed: Any
    requirement: str

def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().upper() in {"YES", "TRUE", "1", "PASS"}

def _explicit_false(value: Any) -> bool:
    return str(value).strip().upper() in {"NO", "FALSE", "0", "FAIL"}

def _sources_support_negative_inference(sources: Any) -> bool:
    if not isinstance(sources, list):
        return False
    return all(
        isinstance(audit, dict)
        and audit.get("status") in tuple(SourceStatus)
        and SourceAudit(
            source=audit.get("source", ""),
            status=SourceStatus(audit["status"]),
        ).supports_negative_inference
        for audit in sources
    )

def _count(data: dict[str, Any], new_key: str, legacy_key: str) -> int:
    value = data.get(new_key, data.get(legacy_key, 0))
    return int(value or 0)

def _design_framework_verified(data: dict[str, Any]) -> bool:
    if "design_framework_verified" in data:
        return _truth(data.get("design_framework_verified"))
    if "study_designs_eligible" in data:
        return _truth(data.get("study_designs_eligible"))
    # Backward compatibility for old RCT-only payloads.
    return str(data.get("design", "")).strip().upper() == "RCT_ONLY"

def _question_framework_coherent(data: dict[str, Any]) -> bool:
    if "question_framework_coherent" in data:
        return _truth(data.get("question_framework_coherent"))
    return _truth(data.get("pico_coherent"))

def evaluate_locked_gates(data: dict[str, Any]) -> list[GateResult]:
    feasibility = str(data.get("feasibility", "")).strip().upper()
    editorial = str(data.get("editorial_grade", "")).strip().upper()
    independent = _count(data, "verified_independent_studies", "verified_independent_rcts")
    usable = _count(data, "verified_usable_studies", "verified_usable_rcts")
    meaningful_synthesis = data.get("meaningful_synthesis", data.get("meaningful_pooling"))
    checks = [
        ("Eligible study-design framework verified", _design_framework_verified(data), data.get("design_framework_verified", data.get("design")), "PASS"),
        ("Verified independent eligible studies", independent >= MIN_STUDIES, independent, f">= {MIN_STUDIES}"),
        ("Verified synthesis-usable studies", usable >= MIN_STUDIES, usable, f">= {MIN_STUDIES}"),
        ("Meaningful defensible synthesis", _truth(meaningful_synthesis), meaningful_synthesis, "PASS"),
        ("Clinical-question novelty", float(data.get("clinical_question_novelty", 0) or 0) >= 3, data.get("clinical_question_novelty", 0), ">= 3/5"),
        ("Overall novelty", float(data.get("overall_novelty", 0) or 0) >= 3, data.get("overall_novelty", 0), ">= 3/5"),
        ("No fatal recent identical evidence-synthesis redundancy", _explicit_false(data.get("fatal_redundancy")) and _sources_support_negative_inference(data.get("sources", [])), data.get("fatal_redundancy"), "FALSE with conclusive supplied source audits"),
        ("Coherent review-question framework", _question_framework_coherent(data), data.get("question_framework_coherent", data.get("pico_coherent")), "PASS"),
        ("Feasibility", feasibility in VALID_FEASIBILITY, feasibility, "HIGH or STRONG MODERATE"),
        ("No fatal methodological flaw", _explicit_false(data.get("fatal_methodological_flaw")), data.get("fatal_methodological_flaw"), "FALSE"),
        ("Clinical importance", float(data.get("clinical_importance", 0) or 0) >= 4, data.get("clinical_importance", 0), ">= 4/5"),
        ("Publication potential", float(data.get("publication_potential", 0) or 0) >= 4, data.get("publication_potential", 0), ">= 4/5"),
        ("New information gain", float(data.get("new_information_gain", 0) or 0) >= 4, data.get("new_information_gain", 0), ">= 4/5"),
        ("Publication-Oriented Score", float(data.get("publication_oriented_score", 0) or 0) >= 75, data.get("publication_oriented_score", 0), ">= 75/100"),
        ("Editorial stress-test grade", editorial in VALID_EDITORIAL_GRADES, editorial, "A, B, or CORRECTED C"),
    ]
    return [GateResult(i, name, passed, observed, requirement) for i, (name, passed, observed, requirement) in enumerate(checks, start=1)]

def final_decision(data: dict[str, Any]) -> dict[str, Any]:
    gates = evaluate_locked_gates(data)
    unresolved = list(data.get("unresolved_type_a") or [])
    passed = all(g.passed for g in gates) and not unresolved
    return {
        "decision": "PROCEED — FIRST-CHOICE" if passed else "DO NOT PROCEED",
        "all_15_gates_passed": all(g.passed for g in gates),
        "unresolved_type_a": unresolved,
        "gates": [asdict(g) for g in gates],
    }

def final_decision_from_audits(
    data: dict[str, Any],
    family_audit,
    usability_ledgers,
) -> dict[str, Any]:
    """Run locked gates using deterministic study-family and synthesis-usability counts."""
    from dataclasses import asdict as _asdict
    from .evidence import derive_evidence_counts

    counts = derive_evidence_counts(family_audit, usability_ledgers)
    payload = dict(data)
    payload["verified_independent_studies"] = counts.verified_independent_studies
    payload["verified_usable_studies"] = counts.verified_usable_studies
    payload["principal_outcome_studies"] = counts.principal_outcome_studies

    # Legacy keys are overwritten too, preventing old callers or AI payloads from inflating counts.
    payload["verified_independent_rcts"] = counts.verified_independent_studies
    payload["verified_usable_rcts"] = counts.verified_usable_studies
    payload["principal_outcome_rcts"] = counts.principal_outcome_studies

    existing = list(payload.get("unresolved_type_a") or [])
    payload["unresolved_type_a"] = list(dict.fromkeys(existing + counts.unresolved_type_a))

    decision = final_decision(payload)
    decision["deterministic_evidence"] = _asdict(counts)
    return decision
