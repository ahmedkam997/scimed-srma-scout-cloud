from scimed_scout.discovery.focused_queries import focused_query
from scimed_scout.storage import CandidateRecord

def test_population_and_intervention_are_both_required():
    c=CandidateRecord("C","P","BMI and coronary syndrome","Cardiology",population="Adults with chronic coronary syndrome",
        intervention_exposure_index_test="Body mass index categories")
    for source in ("PubMed","Europe PMC"):
        query=focused_query(c,source,"PRIMARY")
        assert "chronic coronary syndrome" in query
        assert "body mass index" in query and "BMI" in query
        assert " AND " in query
        assert "systematic review" not in query
        assert "systematic review" in focused_query(c,source,"REVIEW")

def test_preserved_ejection_fraction_and_unicode_hyphen():
    c=CandidateRecord("C","P","Trial","Cardiology",population="Heart failure with preserved ejection fraction",
        intervention_exposure_index_test="High‑intensity interval training")
    query=focused_query(c,"Europe PMC","PRIMARY")
    assert "HFpEF" in query and "HIIT" in query
    assert "TITLE_ABS:" in query

def test_missing_population_does_not_fall_back_to_broad_intervention():
    c=CandidateRecord("C","P","Trial","Cardiology",population="",intervention_exposure_index_test="Colchicine")
    assert focused_query(c,"PubMed","PRIMARY")==""
