from scimed_scout.discovery.pico_matching import assess_pico
from scimed_scout.storage import CandidateRecord
from scimed_scout.discovery.orchestrator import ReviewDiscoveryOrchestrator
from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.sources.base import SearchRecord, SearchResult
from scimed_scout.storage import SQLiteLedger, ProjectRecord


def candidate():
    return CandidateRecord("C","P","SGLT2 inhibitors for HFpEF","Cardiology",
        question_type="EFFECTIVENESS",population="Adults with HFpEF",
        intervention_exposure_index_test="SGLT2 inhibitors",
        comparator_reference="Placebo", outcomes=["Cardiovascular mortality"],
        eligible_designs=["RCTs"])


def rec(id,title,meta=None,doi=None,source="PubMed"):
    return {"source_record_id":id,"title":title,"source":source,
            "payload":{"metadata":meta or {},"doi":doi or ""}}


def test_aliases_and_missing_outcome_or_comparator_do_not_exclude():
    audit, records = assess_pico(candidate(),[rec("1","SGLT2 inhibitors in heart failure with preserved ejection fraction: randomized trial")])
    assert audit["pico_design_family_leads"] == 1
    assert audit["rows"][0]["dimensions"]["comparator_or_reference"]["status"] == "UNKNOWN"
    assert audit["rows"][0]["fulltext_eligibility"] == "NOT_CHECKED"
    assert len(records) == 1


def test_different_hf_subtype_and_nonrandomized_report_not_counted():
    audit, _ = assess_pico(candidate(),[
        rec("1","SGLT2 inhibitors in HFrEF: randomized trial"),
        rec("2","SGLT2 inhibitors in HFpEF: retrospective cohort study"),
        rec("3","SGLT2 inhibitors for HFpEF: trial protocol", {"publicationTypes":["Randomized Controlled Trial"]})])
    assert audit["pico_design_family_leads"] == 0
    assert audit["distinct_reports_assessed"] == 3
    assert audit["status_counts"]["MANUAL_CONFLICT_CHECK"] == 2


def test_duplicate_metadata_is_merged_and_registered_followup_grouped():
    records = [
        rec("1","SGLT2 inhibitors for HFpEF",{"pubtype":["Randomized Controlled Trial"],"nct_id":"NCT00000001"}, "10.1/a"),
        rec("2","SGLT2 inhibitors for HFpEF",{"abstractText":"Patients with HFpEF received SGLT2 inhibitors."}, "10.1/a","Europe PMC"),
        rec("3","SGLT2 inhibitors in HFpEF: randomized trial follow-up",{"nct_id":"NCT00000001"},"10.1/b"),
    ]
    audit,_ = assess_pico(candidate(),records)
    assert audit["distinct_reports_assessed"] == 2
    assert audit["pico_design_report_leads"] == 2
    assert audit["pico_design_family_leads"] == 1


def test_unrelated_hits_and_missing_metadata_remain_unknown_not_excluded():
    audit, _ = assess_pico(candidate(),[rec("1","An unrelated study"),rec("2","")])
    assert audit["status_counts"]["INSUFFICIENT_BIBLIOGRAPHIC_SIGNAL"] == 2
    assert audit["confirmed_independent_eligible_studies"] is None


def test_ambiguous_registrations_not_counted():
    audit,_=assess_pico(candidate(),[rec("1","SGLT2 inhibitors in HFpEF: randomized trial",{"trial_registration_ids":["NCT00000001","NCT00000002"]})])
    assert audit["pico_design_report_leads"] == 1
    assert audit["pico_design_family_leads"] == 0


def test_production_gate_blocks_unrelated_hits_without_excluding_them(tmp_path):
    class Source:
        def __init__(self,name): self.name=name
        def search(self,query,*,limit=20):
            if self.name in ("PubMed","Europe PMC") and "systematic review" not in query.casefold() and "meta-analysis" not in query.casefold():
                rows=[SearchRecord(self.name,f"{self.name}{i}",f"Unrelated cohort study {i}",doi=f"10.1/{i}") for i in range(5)]
                return SearchResult(self.name,query,SourceStatus.SEARCHED_POSITIVE,rows,len(rows))
            return SearchResult(self.name,query,SourceStatus.SEARCHED_NEGATIVE,[],0)
    names=["PubMed","Europe PMC","OpenAlex","Crossref","Semantic Scholar","PROSPERO","OSF Registries","ClinicalTrials.gov"]
    with SQLiteLedger(tmp_path/"pico.sqlite") as ledger:
        ledger.upsert_project(ProjectRecord("P","Cardiology"))
        ledger.upsert_candidate(candidate())
        result=ReviewDiscoveryOrchestrator(ledger,[Source(x) for x in names],require_pico_signals=True).verify_candidate("C")
        assert result.evidence.unique_primary_study_candidates >= 4
        assert result.evidence.pico_audit["pico_design_family_leads"] == 0
        assert result.candidate_status == CandidateStatus.PROVISIONAL_BACKUP
        assert any("PICO/design cues" in reason for reason in result.pending)
        assert len(ledger.list_external_evidence("C","PRIMARY_STUDY")) >= 4


def test_real_emperor_preserved_and_reduced_bibliographic_signals():
    # Frozen, short source-backed excerpts, not generated clinical labels.
    # https://pubmed.ncbi.nlm.nih.gov/34449189/
    # https://pubmed.ncbi.nlm.nih.gov/32865377/
    rows = [
        rec("34449189", "Empagliflozin in Heart Failure with a Preserved Ejection Fraction",
            {"pubtype":["Randomized Controlled Trial"], "trial_registration_id":"NCT03057951"}),
        rec("32865377", "Cardiovascular and Renal Outcomes with Empagliflozin in Heart Failure",
            {"abstractText":"heart failure and a reduced ejection fraction",
             "pubtype":["Randomized Controlled Trial"], "trial_registration_id":"NCT03057977"}),
    ]
    audit, _ = assess_pico(candidate(), rows)
    by_id = {r["record_id"]:r for r in audit["rows"]}
    assert by_id["34449189"]["status"] == "PICO_DESIGN_LEAD"
    assert by_id["32865377"]["status"] == "INSUFFICIENT_BIBLIOGRAPHIC_SIGNAL"
    assert audit["pico_design_family_leads"] == 1
    # A class mention must not stand in for a specific member of that class.
    specific = candidate()
    specific.intervention_exposure_index_test = "Empagliflozin"
    audit, _ = assess_pico(specific, [rec("1", "SGLT2 inhibitors in HFpEF: randomized trial")])
    assert audit["pico_design_family_leads"] == 0


def test_europe_pmc_native_nested_publication_types():
    audit, _ = assess_pico(candidate(), [
        rec("1", "Empagliflozin in HFpEF",
            {"pubTypeList":{"pubType":["randomized controlled trial"]}}, source="Europe PMC")])
    assert audit["pico_design_family_leads"] == 1


def test_nonrandomized_scope_does_not_count_rct_only():
    topic = candidate()
    topic.eligible_designs = ["Non-randomized studies"]
    audit, _ = assess_pico(topic, [rec("1","SGLT2 inhibitors in HFpEF: randomized trial")])
    assert audit["pico_design_family_leads"] == 0
