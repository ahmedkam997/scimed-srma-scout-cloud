from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ReviewQuestionType(StrEnum):
    EFFECTIVENESS = "EFFECTIVENESS"
    SAFETY_HARMS = "SAFETY_HARMS"
    DIAGNOSTIC_ACCURACY = "DIAGNOSTIC_ACCURACY"
    PROGNOSIS = "PROGNOSIS"
    ETIOLOGY_RISK = "ETIOLOGY_RISK"
    PREVALENCE_INCIDENCE = "PREVALENCE_INCIDENCE"
    ASSOCIATION = "ASSOCIATION"
    PREDICTION_MODEL = "PREDICTION_MODEL"
    ECONOMIC = "ECONOMIC"
    IMPLEMENTATION = "IMPLEMENTATION"
    QUALITATIVE = "QUALITATIVE"
    MIXED_METHODS = "MIXED_METHODS"
    OTHER = "OTHER"


class StudyDesignFamily(StrEnum):
    RANDOMIZED_EXPERIMENTAL = "RANDOMIZED_EXPERIMENTAL"
    NONRANDOMIZED_INTERVENTIONAL = "NONRANDOMIZED_INTERVENTIONAL"
    QUASI_EXPERIMENTAL = "QUASI_EXPERIMENTAL"
    COHORT = "COHORT"
    CASE_CONTROL = "CASE_CONTROL"
    CROSS_SECTIONAL = "CROSS_SECTIONAL"
    DIAGNOSTIC_ACCURACY = "DIAGNOSTIC_ACCURACY"
    PROGNOSTIC = "PROGNOSTIC"
    PREDICTION_MODEL = "PREDICTION_MODEL"
    PREVALENCE_INCIDENCE = "PREVALENCE_INCIDENCE"
    ECOLOGICAL = "ECOLOGICAL"
    REGISTRY_DATABASE = "REGISTRY_DATABASE"
    CASE_SERIES = "CASE_SERIES"
    CASE_REPORT = "CASE_REPORT"
    QUALITATIVE = "QUALITATIVE"
    MIXED_METHODS = "MIXED_METHODS"
    ECONOMIC = "ECONOMIC"
    IMPLEMENTATION = "IMPLEMENTATION"
    GENETIC = "GENETIC"
    OTHER = "OTHER"


class DiagnosticDesignFeature(StrEnum):
    SINGLE_GATE = "SINGLE_GATE"
    TWO_GATE_CASE_CONTROL = "TWO_GATE_CASE_CONTROL"
    COHORT_BASED = "COHORT_BASED"
    CROSS_SECTIONAL = "CROSS_SECTIONAL"
    PROSPECTIVE = "PROSPECTIVE"
    RETROSPECTIVE = "RETROSPECTIVE"
    PAIRED_COMPARATIVE = "PAIRED_COMPARATIVE"
    UNPAIRED_COMPARATIVE = "UNPAIRED_COMPARATIVE"
    RANDOMIZED_TEST_COMPARISON = "RANDOMIZED_TEST_COMPARISON"
    MULTIPLE_INDEX_TESTS = "MULTIPLE_INDEX_TESTS"
    MULTIPLE_THRESHOLDS = "MULTIPLE_THRESHOLDS"
    PARTIAL_VERIFICATION = "PARTIAL_VERIFICATION"
    DIFFERENTIAL_VERIFICATION = "DIFFERENTIAL_VERIFICATION"
    OTHER = "OTHER"


class SynthesisMode(StrEnum):
    EFFECT_META_ANALYSIS = "EFFECT_META_ANALYSIS"
    DTA_META_ANALYSIS = "DTA_META_ANALYSIS"
    PROPORTION_PREVALENCE_META_ANALYSIS = "PROPORTION_PREVALENCE_META_ANALYSIS"
    RATE_META_ANALYSIS = "RATE_META_ANALYSIS"
    ASSOCIATION_META_ANALYSIS = "ASSOCIATION_META_ANALYSIS"
    PROGNOSTIC_META_ANALYSIS = "PROGNOSTIC_META_ANALYSIS"
    PREDICTION_MODEL_SYNTHESIS = "PREDICTION_MODEL_SYNTHESIS"
    ECONOMIC_SYNTHESIS = "ECONOMIC_SYNTHESIS"
    QUALITATIVE_SYNTHESIS = "QUALITATIVE_SYNTHESIS"
    MIXED_METHODS_SYNTHESIS = "MIXED_METHODS_SYNTHESIS"
    NARRATIVE_SYSTEMATIC_REVIEW = "NARRATIVE_SYSTEMATIC_REVIEW"
    OTHER = "OTHER"


@dataclass(slots=True)
class StudyDesignProfile:
    question_type: ReviewQuestionType
    synthesis_mode: SynthesisMode
    design_family: StudyDesignFamily
    specific_design: str
    design_verified: bool = False
    diagnostic_features: set[DiagnosticDesignFeature] = field(default_factory=set)
    custom_design_label: str = ""
    appraisal_tool: str = ""

    @property
    def effective_design_label(self) -> str:
        return self.custom_design_label.strip() or self.specific_design.strip() or self.design_family.value


def recommended_appraisal_tool(profile: StudyDesignProfile) -> str:
    if profile.appraisal_tool.strip():
        return profile.appraisal_tool.strip()
    if profile.question_type == ReviewQuestionType.DIAGNOSTIC_ACCURACY or profile.design_family == StudyDesignFamily.DIAGNOSTIC_ACCURACY:
        return "QUADAS-3"
    if profile.question_type == ReviewQuestionType.PREDICTION_MODEL or profile.design_family == StudyDesignFamily.PREDICTION_MODEL:
        return "PROBAST+AI"
    if profile.design_family == StudyDesignFamily.RANDOMIZED_EXPERIMENTAL:
        return "RoB 2"
    if profile.design_family in {
        StudyDesignFamily.NONRANDOMIZED_INTERVENTIONAL,
        StudyDesignFamily.QUASI_EXPERIMENTAL,
    }:
        return "ROBINS-I or design-appropriate validated tool"
    return "Design-appropriate validated risk-of-bias / critical-appraisal tool"
