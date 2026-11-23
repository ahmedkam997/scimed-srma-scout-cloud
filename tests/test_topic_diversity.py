from types import SimpleNamespace

from scimed_scout.ai.models import CandidateProposal, normalize_question_type
from scimed_scout.discovery.topic_diversity import same_clinical_question, same_discovery_family, select_diverse_ranked
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


def test_generation_removes_near_duplicate_picos_before_literature_search(tmp_path):
    import json

    from scimed_scout.ai.discovery import CandidateDiscoveryService
    from scimed_scout.ai.providers import StaticAIProvider
    from scimed_scout.storage import ProjectRecord, SQLiteLedger

    common = {
        "question_type": "Effectiveness",
        "review_question": "Does adjunctive non-pulmonary vein trigger ablation improve AF outcomes?",
        "population": "Adults with persistent atrial fibrillation undergoing catheter ablation",
        "intervention_exposure_index_test": "Adjunctive non-pulmonary vein trigger ablation plus pulmonary-vein isolation",
        "comparator_reference": "Pulmonary-vein isolation alone",
        "outcomes": ["Freedom from atrial fibrillation at 12 months", "Quality of life"],
        "eligible_designs": ["Randomized controlled trials"],
    }
    candidates = [
        {**common, "title": "Effectiveness of adjunctive non-pulmonary vein trigger ablation versus pulmonary-vein isolation alone in persistent atrial fibrillation"},
        {**common, "title": "Adjunctive non-pulmonary vein trigger ablation versus pulmonary-vein isolation alone in persistent atrial fibrillation"},
    ]
    provider = StaticAIProvider(text=json.dumps({"candidates": candidates}))
    with SQLiteLedger(tmp_path / "diversity.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord(project_id="DIVERSITY", specialty="Cardiology", question_type="ALL"))
        service = CandidateDiscoveryService(provider, ledger)
        generated = service.generate_and_store(
            project_id="DIVERSITY", specialty="Cardiology", count=2,
        )
        assert len(generated) == 1
        assert "near-duplicate clinical PICO" in " ".join(service.generation_warnings)


def test_cardiology_picos_of_same_intervention_are_one_verification_family_not_duplicate_manuscripts():
    ketone1 = topic(
        "k1", title="Effect of Ketone Monoester Supplementation on Left Ventricular Global Longitudinal Strain During Heat Stress",
        population="Endurance athletes aged 18 to 45 years undergoing heat-stress exercise",
        intervention="Ketone monoester supplementation", comparator="Placebo or no supplementation",
        outcomes=["Left ventricular strain", "Troponin I"])
    ketone2 = topic(
        "k2", title="Ketone Monoester on Exercise-Induced Myocardial Strain in Heat Stress",
        population="Adults engaging in endurance exercise under heat stress conditions",
        intervention="Ketone monoester ingestion prior to exercise",
        comparator="Placebo or no supplementation",
        outcomes=["Global longitudinal strain", "Heart rate variability"])
    sglt2a = topic(
        "s1", title="Long Term Outcomes of SGLT2 Inhibitors versus DPP-4 Inhibitors in HFrEF",
        population="Adults with heart failure with reduced ejection fraction HFrEF",
        intervention="SGLT2 inhibitor therapy", comparator="DPP-4 inhibitor therapy",
        outcomes=["All-cause mortality", "Heart failure hospitalization"])
    sglt2b = topic(
        "s2", title="SGLT2 versus DPP4 for HFrEF in Patients with Diabetes",
        population="Adults 45 to 80 years with HFrEF and type 2 diabetes",
        intervention="SGLT2 inhibitor empagliflozin", comparator="DPP-4 inhibitor sitagliptin",
        outcomes=["All-cause mortality", "Renal outcomes"])
    electro = topic(
        "e1", title="Electroacupuncture in resistant hypertension",
        population="Adults with resistant hypertension",
        intervention="Electroacupuncture", comparator="Sham electroacupuncture or standard care",
        outcomes=["Blood pressure variability"])
    assert same_discovery_family(ketone1, ketone2)
    assert same_discovery_family(sglt2a, sglt2b)
    assert not same_discovery_family(electro, ketone1)
    ranked = [RankingResult(x.candidate_id, 90-i, ()) for i,x in enumerate(
        [ketone1, ketone2, sglt2a, sglt2b, electro])]
    by_id = {x.candidate_id:x for x in [ketone1,ketone2,sglt2a,sglt2b,electro]}
    selected, skipped = select_diverse_ranked(ranked, by_id, limit=5)
    assert len(selected) == 3
    assert {x.candidate_id for x in selected} == {"k1","s1","e1"}
    assert len(skipped) == 2
    assert all(x["reason"] == "SAME_CLINICAL_DISCOVERY_FAMILY_BUDGET_ONLY" for x in skipped)


def test_different_doses_or_target_populations_are_not_suppressed_as_same_family():
    a=topic("1",title="Drug Q 5 mg in adults",population="Adults with heart failure",
            intervention="Drug Q 5 mg",comparator="Placebo",outcomes=["Death"])
    b=topic("2",title="Drug Q 10 mg in adults",population="Adults with heart failure",
            intervention="Drug Q 10 mg",comparator="Placebo",outcomes=["Death"])
    c=topic("3",title="Drug Q 5 mg in children",population="Children with heart failure",
            intervention="Drug Q 5 mg",comparator="Placebo",outcomes=["Death"])
    assert not same_discovery_family(a,b)
    assert not same_discovery_family(a,c)
