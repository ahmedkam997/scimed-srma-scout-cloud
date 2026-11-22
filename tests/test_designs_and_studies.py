from scimed_scout.designs import (
    DiagnosticDesignFeature,
    ReviewQuestionType,
    StudyDesignFamily,
    StudyDesignProfile,
    SynthesisMode,
    recommended_appraisal_tool,
)
from scimed_scout.studies import EvidenceFamilyResolver, FamilyLinkStatus, StudyRecord


def profile(family=StudyDesignFamily.COHORT, question=ReviewQuestionType.ETIOLOGY_RISK, design="retrospective cohort"):
    return StudyDesignProfile(
        question_type=question,
        synthesis_mode=SynthesisMode.ASSOCIATION_META_ANALYSIS,
        design_family=family,
        specific_design=design,
        design_verified=True,
    )


def test_open_custom_design_preserves_unlisted_design_label():
    p = StudyDesignProfile(
        question_type=ReviewQuestionType.OTHER,
        synthesis_mode=SynthesisMode.OTHER,
        design_family=StudyDesignFamily.OTHER,
        specific_design="adaptive platform registry-embedded natural experiment",
        design_verified=True,
        custom_design_label="registry-embedded adaptive natural experiment",
    )
    assert p.effective_design_label == "registry-embedded adaptive natural experiment"


def test_dta_profile_supports_multiple_design_features_and_quadas3():
    p = StudyDesignProfile(
        question_type=ReviewQuestionType.DIAGNOSTIC_ACCURACY,
        synthesis_mode=SynthesisMode.DTA_META_ANALYSIS,
        design_family=StudyDesignFamily.DIAGNOSTIC_ACCURACY,
        specific_design="prospective paired comparative diagnostic accuracy study",
        design_verified=True,
        diagnostic_features={
            DiagnosticDesignFeature.SINGLE_GATE,
            DiagnosticDesignFeature.PROSPECTIVE,
            DiagnosticDesignFeature.PAIRED_COMPARATIVE,
            DiagnosticDesignFeature.MULTIPLE_INDEX_TESTS,
        },
    )
    assert DiagnosticDesignFeature.PAIRED_COMPARATIVE in p.diagnostic_features
    assert recommended_appraisal_tool(p) == "QUADAS-3"


def test_prediction_model_uses_probast_ai():
    p = StudyDesignProfile(
        question_type=ReviewQuestionType.PREDICTION_MODEL,
        synthesis_mode=SynthesisMode.PREDICTION_MODEL_SYNTHESIS,
        design_family=StudyDesignFamily.PREDICTION_MODEL,
        specific_design="external validation cohort",
        design_verified=True,
    )
    assert recommended_appraisal_tool(p) == "PROBAST+AI"


def test_observational_publications_from_same_cohort_are_flagged_not_auto_merged():
    a = StudyRecord(
        study_id="A",
        title="Long-term cardiovascular outcomes in cohort X",
        design=profile(),
        cohort_name="Cohort X",
        data_source="National registry",
        sample_size=5000,
        independence_verified=True,
        eligibility_verified=True,
    )
    b = StudyRecord(
        study_id="B",
        title="Renal outcomes among participants in cohort X",
        design=profile(),
        cohort_name="Cohort X",
        data_source="National registry",
        sample_size=5000,
        independence_verified=True,
        eligibility_verified=True,
    )
    audit = EvidenceFamilyResolver().audit([a, b])
    assert len(audit.families) == 2
    assert len(audit.possible_links) == 1
    assert audit.possible_links[0].status == FamilyLinkStatus.POSSIBLE_SAME_FAMILY


def test_four_independent_nonrandomized_studies_meet_family_count():
    studies = [
        StudyRecord(
            study_id=f"S{i}",
            title=f"Cohort {i}",
            design=profile(),
            manually_verified_family_id=f"F{i}",
            independence_verified=True,
            eligibility_verified=True,
        )
        for i in range(1, 5)
    ]
    audit = EvidenceFamilyResolver().audit(studies)
    assert audit.verified_independent_study_count == 4
    assert not audit.family_uncertainty_is_decision_changing()
