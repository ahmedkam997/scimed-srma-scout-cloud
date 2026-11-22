from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any

from .domain import SourceAudit, SourceStatus

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

def evaluate_locked_gates(data: dict[str, Any]) -> list[GateResult]:
    feasibility = str(data.get("feasibility", "")).strip().upper()
    editorial = str(data.get("editorial_grade", "")).strip().upper()
    checks = [
        ("RCT-only", str(data.get("design", "")).strip().upper() == "RCT_ONLY", data.get("design"), "RCT_ONLY"),
        ("Verified independent randomized populations", int(data.get("verified_independent_rcts", 0) or 0) >= 7, data.get("verified_independent_rcts", 0), ">= 7"),
        ("Verified quantitatively usable RCTs", int(data.get("verified_usable_rcts", 0) or 0) >= 7, data.get("verified_usable_rcts", 0), ">= 7"),
        ("Meaningful defensible pooled analysis", _truth(data.get("meaningful_pooling")), data.get("meaningful_pooling"), "PASS"),
        ("Clinical-question novelty", float(data.get("clinical_question_novelty", 0) or 0) >= 3, data.get("clinical_question_novelty", 0), ">= 3/5"),
        ("Overall novelty", float(data.get("overall_novelty", 0) or 0) >= 3, data.get("overall_novelty", 0), ">= 3/5"),
        ("No fatal recent identical SRMA redundancy", _explicit_false(data.get("fatal_redundancy")) and _sources_support_negative_inference(data.get("sources", [])), data.get("fatal_redundancy"), "FALSE with conclusive supplied source audits"),
        ("Coherent PICO", _truth(data.get("pico_coherent")), data.get("pico_coherent"), "PASS"),
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
