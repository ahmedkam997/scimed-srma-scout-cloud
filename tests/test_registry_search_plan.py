from scimed_scout.verification.queries import build_search_plan
from scimed_scout.storage import CandidateRecord


def topic(intervention, population, outcome, comparator):
    return CandidateRecord(
        candidate_id="T", project_id="P",
        title=f"{intervention} in {population}",
        specialty="Cardiology", question_type="EFFECTIVENESS",
        review_question="Does intervention improve outcomes?",
        population=population,
        intervention_exposure_index_test=intervention,
        comparator_reference=comparator,
        outcomes=[outcome],
        eligible_designs=["RCT"],
    )


def test_prospero_queries_use_exact_intervention_and_population_not_generic_placebo():
    item=topic(
        "Ketone monoester ingestion (dose per body weight) 30 min before heat stress",
        "Endurance athletes aged 18–45 years undergoing heat-stress exercise",
        "Left ventricular global longitudinal strain",
        "Placebo (matched volume and taste)",
    )
    plan=build_search_plan(item)
    assert plan.registry_queries
    assert len(plan.registry_queries) <= 4
    assert all(' AND ' in q for q in plan.registry_queries)
    assert all('"ketone monoester"' in q for q in plan.registry_queries)
    assert any('"endurance athletes"' in q for q in plan.registry_queries)
    assert not any("placebo" in q.lower() for q in plan.registry_queries)
    assert not any("dose" in q.lower() for q in plan.registry_queries)
    assert not any("body weight" in q.lower() for q in plan.registry_queries)


def test_registry_comparator_keeps_named_active_drug_but_not_standard_care():
    active=topic("SGLT2 inhibitor therapy", "Adults with HFpEF and type 2 diabetes",
                 "Hospitalization for heart failure", "DPP-4 inhibitor therapy")
    plan=build_search_plan(active)
    assert any("sglt2" in q.lower() and "dpp-4" in q.lower() for q in plan.registry_queries)
    assert all(' AND ' in q for q in plan.registry_queries)
    assert not any("therapy" in q.lower() for q in plan.registry_queries)


def test_nonspecific_search_plan_still_returns_original_audit_candidates():
    vague=topic("Treatment", "Adults", "Mortality", "Usual care")
    plan=build_search_plan(vague)
    assert plan.registry_queries
    assert plan.review_queries
    assert plan.primary_queries
