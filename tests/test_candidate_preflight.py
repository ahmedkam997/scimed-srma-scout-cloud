from __future__ import annotations

from scimed_scout.discovery.candidate_preflight import (
    FocusedEvidencePreflight, evaluate_preflight, search_query,
)
from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.ranking import CandidateRankingService
from scimed_scout.sources.base import SearchRecord, SearchResult
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger


def candidate(cid, intervention):
    return CandidateRecord(
        candidate_id=cid,
        project_id="P1",
        title=intervention + " for adult heart failure",
        specialty="Cardiology",
        question_type="EFFECTIVENESS",
        review_question="Does " + intervention + " improve heart failure outcomes?",
        population="Adults with heart failure",
        intervention_exposure_index_test=intervention,
        comparator_reference="placebo or standard care",
        outcomes=["hospitalization", "mortality"],
        eligible_designs=["randomized controlled trials"],
        rationale="Clinically important uncertain intervention",
        novelty_hypothesis="Potential incremental evidence",
        search_terms=[intervention, "heart failure"],
    )


class FakePubMed:
    name = "PubMed"
    def __init__(self):
        self.queries = []
    def search(self, query, *, limit=20):
        self.queries.append((query, limit))
        if "inclisiran" in query:
            return SearchResult(
                self.name, query, SourceStatus.SEARCHED_POSITIVE,
                records=[
                    SearchRecord("PubMed", "1001",
                                 title="Inclisiran trials for cardiovascular outcomes in adults with heart failure",
                                 year=2026, url="https://pubmed.ncbi.nlm.nih.gov/1001/"),
                    SearchRecord("PubMed", "1002",
                                 title="Unrelated surgery for femoral fractures", year=2026),
                ],
                total_count=140,
            )
        if "unknownbrand" in query:
            return SearchResult(self.name, query, SourceStatus.SEARCHED_NEGATIVE, total_count=0)
        raise RuntimeError("simulated PubMed connection outage")


def test_preflight_links_recent_intervention_records_without_trial_claims():
    a = candidate("C1", "Inclisiran")
    source = FakePubMed()
    query = search_query(a, current_year=2026)
    assert '"inclisiran"[Title/Abstract]' in query
    assert "2021/01/01" in query
    result = source.search(query, limit=10)
    info = evaluate_preflight(a, result)
    assert info["status"] == "SEARCHED_POSITIVE"
    assert info["reported_total_matching_query"] == 140
    assert info["records_sampled"] == 2
    assert info["intervention_title_matches"] == 1
    assert info["recent_intervention_title_matches"] == 1
    assert info["priority_signal"] > 0
    assert info["eligible_independent_studies_confirmed"] is None
    assert info["novelty_confirmed"] is False
    assert info["evidence_leads"][0]["pmid"] == "1001"


def test_pubmed_bibliographic_signal_moves_evidence_sourced_question_ahead_of_similar_formatting(tmp_path):
    with SQLiteLedger(tmp_path / "preflight.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        ledger.upsert_candidate(candidate("A", "Unknownbrand"))
        ledger.upsert_candidate(candidate("Z", "Inclisiran"))
        source = FakePubMed()
        totals = FocusedEvidencePreflight(source).annotate(ledger, "P1")
        assert totals == {"candidates_checked": 2, "topics_with_title_signals": 1}
        assert len(source.queries) == 2
        assert ledger.get_candidate("A").metadata["evidence_preflight"]["status"] == "SEARCHED_NEGATIVE"
        ranked = CandidateRankingService(ledger).rank_project("P1", top_n=1)
        assert ranked[0].candidate_id == "Z"
        assert "not eligibility" in ranked[0].reasons[-1]
        assert ledger.get_candidate("Z").status == CandidateStatus.SHORTLISTED
        assert ledger.get_candidate("A").status == CandidateStatus.DISCOVERED


def test_preflight_access_failure_does_not_imply_no_trials(tmp_path):
    with SQLiteLedger(tmp_path / "failed.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Cardiology"))
        ledger.upsert_candidate(candidate("FAIL", "Noncommon therapy"))
        output = FocusedEvidencePreflight(FakePubMed()).annotate(ledger, "P1")
        info = ledger.get_candidate("FAIL").metadata["evidence_preflight"]
        assert output["candidates_checked"] == 1
        assert output["topics_with_title_signals"] == 0
        assert info["status"] == "ACCESS_FAILED"
        assert info["eligible_independent_studies_confirmed"] is None
        assert info["priority_signal"] == 0


def test_unrelated_disease_and_commentaries_do_not_gain_source_priority():
    candidate = CandidateRecord(
        candidate_id="C10",project_id="P1",title="Electroacupuncture in resistant hypertension",
        specialty="Cardiology",population="Adults with resistant hypertension",
        intervention_exposure_index_test="Electroacupuncture",comparator_reference="Sham",
        outcomes=["Blood pressure variability"],eligible_designs=["RCTs"],
    )
    records=[
        SearchRecord("PubMed","X1",
          "Electroacupuncture for neuropathic pain in mice",year=2026),
        SearchRecord("PubMed","X2",
          "Commentary on electroacupuncture for essential hypertension",year=2026),
        SearchRecord("PubMed","X3",
          "Electroacupuncture for essential hypertension: a systematic review and meta-analysis",year=2025),
        SearchRecord("PubMed","X4",
          "Electroacupuncture for hypertension: a hypothesis-generating framework",year=2026),
    ]
    result=SearchResult("PubMed","electroacupuncture",SourceStatus.SEARCHED_POSITIVE,
        records=records,total_count=3500)
    signal=evaluate_preflight(candidate,result)
    assert signal["intervention_title_matches"] == 4
    assert signal["plausible_original_report_title_matches"] == 0
    assert signal["priority_signal"] == 0
    assert signal["eligible_independent_studies_confirmed"] is None


def test_original_like_hypertension_trial_title_is_prioritized_without_confirming_eligibility():
    candidate=CandidateRecord(
        candidate_id="C11",project_id="P1",title="Electroacupuncture for resistant hypertension",
        specialty="Cardiology",population="Adults with resistant hypertension",
        intervention_exposure_index_test="Electroacupuncture",comparator_reference="Sham",
    )
    result=SearchResult("PubMed","electroacupuncture hypertension",SourceStatus.SEARCHED_POSITIVE,
        records=[SearchRecord("PubMed","Y1",
          "Electroacupuncture for resistant hypertension in adults: a randomized clinical trial",
          year=2025,url="https://pubmed.ncbi.nlm.nih.gov/10/")],
        total_count=1)
    signal=evaluate_preflight(candidate,result)
    assert signal["plausible_original_report_title_matches"] == 1
    assert signal["priority_signal"] > 0
    assert signal["evidence_leads"][0]["fulltext_eligibility"] == "NOT_CHECKED"
