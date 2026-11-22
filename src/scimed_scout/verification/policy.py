from __future__ import annotations

from dataclasses import dataclass

from scimed_scout.designs import ReviewQuestionType


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    literature_sources: tuple[str, ...]
    registry_sources: tuple[str, ...]
    pipeline_sources: tuple[str, ...]
    min_complete_literature_sources: int = 2
    require_prospero: bool = True
    require_osf: bool = True
    require_pipeline_source: bool = False


DEFAULT_LITERATURE = ("PubMed", "Europe PMC", "OpenAlex", "Crossref", "Semantic Scholar")


def policy_for_question_type(question_type: str) -> VerificationPolicy:
    value = (question_type or "").strip().upper()

    interventional = {
        ReviewQuestionType.EFFECTIVENESS.value,
        ReviewQuestionType.SAFETY_HARMS.value,
        ReviewQuestionType.IMPLEMENTATION.value,
    }
    if value in interventional:
        return VerificationPolicy(
            literature_sources=DEFAULT_LITERATURE,
            registry_sources=("PROSPERO", "OSF Registries"),
            pipeline_sources=("ClinicalTrials.gov",),
            require_pipeline_source=True,
        )

    return VerificationPolicy(
        literature_sources=DEFAULT_LITERATURE,
        registry_sources=("PROSPERO", "OSF Registries"),
        pipeline_sources=("ClinicalTrials.gov",),
        require_pipeline_source=False,
    )
