from __future__ import annotations

from scimed_scout.designs import (
    DiagnosticDesignFeature,
    ReviewQuestionType,
    StudyDesignFamily,
    StudyDesignProfile,
    SynthesisMode,
)


def classify_design(question_type: str, design_label: str) -> StudyDesignProfile:
    question = _question_type(question_type)
    label = " ".join((design_label or "").casefold().replace("-", " ").split())
    family = _family(question, label)
    verified = family != StudyDesignFamily.OTHER and bool(label)

    diagnostic_features: set[DiagnosticDesignFeature] = set()
    if family == StudyDesignFamily.DIAGNOSTIC_ACCURACY:
        diagnostic_features = _diagnostic_features(label)

    return StudyDesignProfile(
        question_type=question,
        synthesis_mode=_synthesis_mode(question),
        design_family=family,
        specific_design=design_label.strip(),
        design_verified=verified,
        diagnostic_features=diagnostic_features,
        custom_design_label=design_label.strip() if family == StudyDesignFamily.OTHER else "",
    )


def _question_type(value: str) -> ReviewQuestionType:
    try:
        return ReviewQuestionType((value or "").strip().upper())
    except ValueError:
        return ReviewQuestionType.OTHER


def _family(question: ReviewQuestionType, label: str) -> StudyDesignFamily:
    if question == ReviewQuestionType.DIAGNOSTIC_ACCURACY or any(
        token in label for token in ("diagnostic accuracy", "index test", "sensitivity and specificity")
    ):
        return StudyDesignFamily.DIAGNOSTIC_ACCURACY

    rules = [
        (StudyDesignFamily.RANDOMIZED_EXPERIMENTAL, (
            "randomized", "randomised", "rct", "cluster random", "crossover trial",
            "cross over trial", "factorial trial", "stepped wedge", "platform trial",
        )),
        (StudyDesignFamily.QUASI_EXPERIMENTAL, (
            "quasi experimental", "interrupted time series", "difference in differences",
            "difference-in-differences", "regression discontinuity", "controlled before after",
            "before and after", "before after",
        )),
        (StudyDesignFamily.NONRANDOMIZED_INTERVENTIONAL, (
            "nonrandomized intervention", "non randomized intervention", "nonrandomised intervention",
            "single arm trial", "single-arm trial", "open label intervention",
        )),
        (StudyDesignFamily.CASE_CONTROL, (
            "case control", "case-control", "nested case control", "case cohort", "case-cohort",
        )),
        (StudyDesignFamily.COHORT, (
            "prospective cohort", "retrospective cohort", "ambidirectional cohort", "cohort study", "cohort",
        )),
        (StudyDesignFamily.CROSS_SECTIONAL, (
            "cross sectional", "cross-sectional",
        )),
        (StudyDesignFamily.PREDICTION_MODEL, (
            "prediction model", "predictive model", "model development", "external validation",
            "internal validation",
        )),
        (StudyDesignFamily.PROGNOSTIC, (
            "prognostic", "prognosis",
        )),
        (StudyDesignFamily.PREVALENCE_INCIDENCE, (
            "prevalence", "incidence study", "incidence rate",
        )),
        (StudyDesignFamily.ECOLOGICAL, ("ecological study", "ecologic study")),
        (StudyDesignFamily.REGISTRY_DATABASE, (
            "registry study", "database study", "administrative database", "claims database",
        )),
        (StudyDesignFamily.CASE_SERIES, ("case series",)),
        (StudyDesignFamily.CASE_REPORT, ("case report",)),
        (StudyDesignFamily.MIXED_METHODS, ("mixed methods", "mixed-methods")),
        (StudyDesignFamily.QUALITATIVE, (
            "qualitative", "interview study", "focus group", "grounded theory",
            "phenomenological", "ethnograph",
        )),
        (StudyDesignFamily.ECONOMIC, (
            "cost effectiveness", "cost-effectiveness", "economic evaluation",
            "cost utility", "cost-utility",
        )),
        (StudyDesignFamily.IMPLEMENTATION, (
            "implementation study", "implementation research",
        )),
        (StudyDesignFamily.GENETIC, (
            "genome wide", "genome-wide", "genetic association", "mendelian randomization",
            "mendelian randomisation",
        )),
    ]
    for family, tokens in rules:
        if any(token in label for token in tokens):
            return family
    return StudyDesignFamily.OTHER


def _synthesis_mode(question: ReviewQuestionType) -> SynthesisMode:
    mapping = {
        ReviewQuestionType.EFFECTIVENESS: SynthesisMode.EFFECT_META_ANALYSIS,
        ReviewQuestionType.SAFETY_HARMS: SynthesisMode.EFFECT_META_ANALYSIS,
        ReviewQuestionType.DIAGNOSTIC_ACCURACY: SynthesisMode.DTA_META_ANALYSIS,
        ReviewQuestionType.PROGNOSIS: SynthesisMode.PROGNOSTIC_META_ANALYSIS,
        ReviewQuestionType.ETIOLOGY_RISK: SynthesisMode.ASSOCIATION_META_ANALYSIS,
        ReviewQuestionType.PREVALENCE_INCIDENCE: SynthesisMode.PROPORTION_PREVALENCE_META_ANALYSIS,
        ReviewQuestionType.ASSOCIATION: SynthesisMode.ASSOCIATION_META_ANALYSIS,
        ReviewQuestionType.PREDICTION_MODEL: SynthesisMode.PREDICTION_MODEL_SYNTHESIS,
        ReviewQuestionType.ECONOMIC: SynthesisMode.ECONOMIC_SYNTHESIS,
        ReviewQuestionType.IMPLEMENTATION: SynthesisMode.EFFECT_META_ANALYSIS,
        ReviewQuestionType.QUALITATIVE: SynthesisMode.QUALITATIVE_SYNTHESIS,
        ReviewQuestionType.MIXED_METHODS: SynthesisMode.MIXED_METHODS_SYNTHESIS,
        ReviewQuestionType.OTHER: SynthesisMode.OTHER,
    }
    return mapping[question]


def _diagnostic_features(label: str) -> set[DiagnosticDesignFeature]:
    features: set[DiagnosticDesignFeature] = set()
    checks = [
        (DiagnosticDesignFeature.PROSPECTIVE, ("prospective",)),
        (DiagnosticDesignFeature.RETROSPECTIVE, ("retrospective",)),
        (DiagnosticDesignFeature.PAIRED_COMPARATIVE, ("paired comparative", "paired design")),
        (DiagnosticDesignFeature.UNPAIRED_COMPARATIVE, ("unpaired comparative", "unpaired design")),
        (DiagnosticDesignFeature.RANDOMIZED_TEST_COMPARISON, ("randomized test", "randomised test")),
        (DiagnosticDesignFeature.MULTIPLE_INDEX_TESTS, ("multiple index tests", "two index tests")),
        (DiagnosticDesignFeature.MULTIPLE_THRESHOLDS, ("multiple thresholds",)),
        (DiagnosticDesignFeature.PARTIAL_VERIFICATION, ("partial verification",)),
        (DiagnosticDesignFeature.DIFFERENTIAL_VERIFICATION, ("differential verification",)),
        (DiagnosticDesignFeature.TWO_GATE_CASE_CONTROL, ("two gate", "two-gate", "case control", "case-control")),
        (DiagnosticDesignFeature.COHORT_BASED, ("cohort",)),
        (DiagnosticDesignFeature.CROSS_SECTIONAL, ("cross sectional", "cross-sectional")),
        (DiagnosticDesignFeature.SINGLE_GATE, ("single gate", "single-gate")),
    ]
    for feature, tokens in checks:
        if any(token in label for token in tokens):
            features.add(feature)
    return features
