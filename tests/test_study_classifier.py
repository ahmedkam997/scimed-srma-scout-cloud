from scimed_scout.designs import (
    DiagnosticDesignFeature,
    StudyDesignFamily,
    SynthesisMode,
)
from scimed_scout.studies.classifier import classify_design


def test_classifier_maps_dta_and_features():
    profile = classify_design(
        "DIAGNOSTIC_ACCURACY",
        "prospective paired comparative diagnostic accuracy study",
    )
    assert profile.design_family == StudyDesignFamily.DIAGNOSTIC_ACCURACY
    assert profile.synthesis_mode == SynthesisMode.DTA_META_ANALYSIS
    assert profile.design_verified
    assert DiagnosticDesignFeature.PROSPECTIVE in profile.diagnostic_features
    assert DiagnosticDesignFeature.PAIRED_COMPARATIVE in profile.diagnostic_features


def test_classifier_maps_common_nonrandomized_designs():
    assert classify_design("ETIOLOGY_RISK", "retrospective cohort study").design_family == StudyDesignFamily.COHORT
    assert classify_design("ASSOCIATION", "case-control study").design_family == StudyDesignFamily.CASE_CONTROL
    assert classify_design("PREVALENCE_INCIDENCE", "cross-sectional study").design_family == StudyDesignFamily.CROSS_SECTIONAL


def test_unknown_design_is_not_auto_verified():
    profile = classify_design("OTHER", "novel adaptive observational framework")
    assert profile.design_family == StudyDesignFamily.OTHER
    assert not profile.design_verified
