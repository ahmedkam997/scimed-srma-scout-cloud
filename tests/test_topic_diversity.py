from types import SimpleNamespace

from scimed_scout.ai.models import CandidateProposal, normalize_question_type
from scimed_scout.discovery.topic_diversity import same_clinical_question, select_diverse_ranked
from scimed_scout.ranking import RankingResult


def topic(candidate_id, *, title, population, intervention, comparator, outcomes, question_type="EFFECTIVENESS"):
    return SimpleNamespace(
        candidate_id=candidate_id,
        title=title, population=population,
        intervention_exposure_index_test=intervention,
        comparator_reference=comparator,
        outcomes=outcomes,
        question_type=question_type,
    )


def test_actual_cardiology_af_duplicate_collapses():
    a=topic("af1",
        title="Effectiveness of adjunctive non-pulmonary vein trigger ablation versus pulmonary-vein isolation alone in persistent atrial fibrillation",
        population="Adults with persistent atrial fibrillation undergoing catheter ablation",
        intervention="Adjunctive non-pulmonary vein trigger ablation plus pulmonary-vein isolation",
        comparator="Pulmonary-vein isolation alone",
        outcomes=["Freedom from atrial fibrillation at 12 months", "Procedure-related complications", "Quality of life scores"])
    b=topic("af2",
        title="Adjunctive non-pulmonary vein trigger ablation versus pulmonary-vein isolation alone in persistent atrial fibrillation",
        population="Adults with persistent atrial fibrillation undergoing catheter ablation",
        intervention="Adjunctive non-pulmonary vein trigger ablation plus pulmonary-vein isolation",
        comparator="Pulmonary-vein isolation alone",
        outcomes=["Freedom from atrial fibrillation at 12 months", "Procedural complications", "Quality of life"])
    assert same_clinical_question(a,b)


def test_actual_ketone_duplicates_collapse():
    a=topic("k1", title="Ketone Monoester Ingestion and Cardiovascular Response During Heat Stress Exercise in Endurance Athletes",
        population="Endurance athletes (male or female) performing exercise in heat",
        intervention="Ketone monoester ingestion",
        comparator="Placebo or no supplementation",
        outcomes=["Heart rate","Blood pressure","Cardiac output"])
    b=topic("k2",title="Impact of ketone monoester ingestion on cardiovascular response during heat-stress exercise in endurance athletes",
        population="Endurance athletes performing heat-stress exercise",
        intervention="Ketone monoester ingestion",
        comparator="Placebo",
        outcomes=["Heart rate","Blood pressure","Core temperature"])
    assert same_clinical_question(a,b)


def test_do_not_collapse_different_clinical_comparator_outcomes_or_populations():
    base=topic("1",title="Drug X treatment for heart failure",population="Adults with heart failure",
        intervention="Drug X",comparator="Placebo",outcomes=["mortality"])
    comparator=topic("2",title="Drug X treatment for heart failure",
        population="Adults with heart failure",intervention="Drug X",
        comparator="Active therapy Y",outcomes=["mortality"])
    outcome=topic("3",title="Drug X treatment for heart failure",
        population="Adults with heart failure",intervention="Drug X",
        comparator="Placebo",outcomes=["Quality of life"])
    pediatric=topic("4",title="Drug X treatment for heart failure",
        population="Children with heart failure",intervention="Drug X",
        comparator="Placebo",outcomes=["mortality"])
    for changed in (comparator, outcome, pediatric):
        assert not same_clinical_question(base,changed)


def test_verify_six_distinct_questions_not_first_six_raw_candidates():
    topics = {}
    for i in range(8):
        key = f"C{i}"
        topics[key] = topic(
            key,title=f"Adjunctive therapy X versus placebo for condition {i // 2}",
            population=f"Adults with condition {i // 2}",
            intervention="Adjunctive therapy X", comparator="Placebo",
            outcomes=["Hospital admission", "Mortality"]
        )
    ranked=[RankingResult(f"C{i}",100-i,()) for i in range(8)]
    selected,skipped=select_diverse_ranked(ranked,topics,limit=6)
    assert len(selected)==4
    assert len(skipped)==4
    assert all(x["reason"]=="NEAR_DUPLICATE_PICO_WITHIN_RUN" for x in skipped)


def test_ai_question_type_is_clinical_design_not_publication_format():
    assert normalize_question_type("Intervention")=="EFFECTIVENESS"
    assert normalize_question_type("Meta-analysis of RCTs", designs=["Randomized controlled trials"])=="EFFECTIVENESS"
    assert normalize_question_type("Systematic review/meta-analysis",title="Test A versus Test B")=="EFFECTIVENESS"
    assert normalize_question_type("diagnostic accuracy")=="DIAGNOSTIC_ACCURACY"
    assert normalize_question_type("systematic review",title="Unknown research topic")=="OTHER"


def test_candidate_model_normalizes_ai_labels_before_creating_registry_policy():
    raw={
        "title":"Treatment X compared with placebo for disease A",
        "question_type":"Systematic Review / Meta-Analysis",
        "review_question":"Does treatment X reduce hospitalization?",
        "population":"Adults with disease A",
        "intervention_exposure_index_test":"Treatment X",
        "comparator_reference":"Placebo",
        "outcomes":["Hospitalization"],
        "eligible_designs":["Randomized controlled trials"],
    }
    assert CandidateProposal.from_dict(raw).question_type=="EFFECTIVENESS"
