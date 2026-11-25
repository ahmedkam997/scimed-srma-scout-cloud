from datetime import datetime, timezone
from scimed_scout.discovery.evidence_first import build_clusters, collect_evidence_map, link_candidate, evidence_map_prompt
from scimed_scout.sources.base import SearchRecord, SearchResult
from scimed_scout.domain import SourceStatus
from scimed_scout.storage import CandidateRecord

def row(id,title,nct="",design="Randomized Controlled Trial",year=2022,doi=""):
    return {"source":"PubMed","source_record_id":id,"title":title,
        "payload":{"year":year,"url":"https://pubmed.ncbi.nlm.nih.gov/"+id+"/","doi":doi,
                   "metadata":{"pubtype":[design],"nct_id":nct}}}

def fixtures():
    # Published EMPEROR-Preserved (34449189), DELIVER (36027570),
    # and EMPEROR-Reduced (32865377). Source links are frozen regression data.
    return [
        row("34449189","Empagliflozin in Heart Failure with a Preserved Ejection Fraction","NCT03057951",year=2021),
        row("36027570","Dapagliflozin in Heart Failure with Mildly Reduced or Preserved Ejection Fraction","NCT03619213"),
        row("32865377","Cardiovascular and Renal Outcomes with Empagliflozin in Heart Failure","NCT03057977",year=2020),
        row("4","SGLT2 inhibitors in HFpEF: systematic review",design="Review"),
    ]

def test_real_title_clustering_does_not_claim_eligibility():
    # Actual PRESERVED-HF citation, not an invented title variation.
    # https://pubmed.ncbi.nlm.nih.gov/34711976/
    # https://clinicaltrials.gov/study/NCT03030235
    records=fixtures()+[
        row("34711976","The SGLT2 inhibitor dapagliflozin in heart failure with preserved ejection fraction: a multicenter randomized trial","NCT03030235",year=2021),
    ]
    clusters=build_clusters(records,"EFFECTIVENESS",current_year=2026)
    cell=next(c for c in clusters if c["population_anchor"]=="hfpef" and c["intervention_anchor"]=="sglt2")
    assert cell["distinct_report_leads"]==2
    assert cell["family_lead_count_not_eligible"]==2
    assert cell["confirmed_independent_eligible_studies"] is None
    assert not cell["novelty_confirmed"]
    assert len(cell["reports"])==2
    assert {r["record_id"] for r in cell["reports"]} == {"34449189","34711976"}
    # EMPEROR-Preserved enrolled EF >40%; the literal title anchor is
    # not proof of an EF >=50% population or an eligible outcome.
    assert cell["registered_family_count"] == 2

def test_duplicate_and_companion_reports_do_not_create_cluster():
    a=row("1","Empagliflozin in HFpEF","NCT00000001",doi="10.1/a")
    b=row("2","Empagliflozin in HFpEF: long-term randomized trial follow-up","NCT00000001")
    assert build_clusters([a,b,{**a,"source":"Europe PMC"}],"ALL",current_year=2026)==[]

def test_design_and_population_separation():
    records=[row("1","Colchicine in myocardial infarction","NCT00000001"),
             row("2","Colchicine in myocardial infarction: retrospective cohort study",design="Journal Article"),
             row("3","Colchicine in atrial fibrillation","NCT00000003"),
             row("4","Colchicine in myocardial infarction: study protocol","NCT00000004")]
    assert build_clusters(records,"ALL",current_year=2026)==[]

def test_bounded_queries_failure_and_specialty_scope():
    class Stub:
        calls=[]
        def search(self,query,*,limit):
            self.calls.append((query,limit))
            if len(self.calls)==1:
                return SearchResult("Europe PMC",query,SourceStatus.ACCESS_FAILED,message="timeout")
            return SearchResult("Europe PMC",query,SourceStatus.SEARCHED_NEGATIVE,[],0)
    source=Stub()
    report=collect_evidence_map("Cardiology","EFFECTIVENESS",client=source,now=datetime(2026,11,25,tzinfo=timezone.utc))
    assert len(source.calls)==6
    assert all(x[1] in (25,30) and "PUB_YEAR" in x[0] for x in source.calls)
    assert report["status"]=="PARTIAL_SAMPLE" and not report["novelty_confirmed"]
    assert collect_evidence_map("Neurology",client=source)["status"]=="SPECIALTY_VOCABULARY_NOT_IMPLEMENTED"
    assert len(source.calls)==6

def test_candidate_anchor_link_not_specific_drug_proof():
    records=[row("1","Empagliflozin in HFpEF","NCT00000001"),row("2","Dapagliflozin in HFpEF","NCT00000002")]
    evidence={"clusters":build_clusters(records,"ALL",current_year=2026)}
    c=CandidateRecord("C","P","SGLT2 for HFpEF","Cardiology",question_type="EFFECTIVENESS",population="HFpEF",intervention_exposure_index_test="SGLT2 inhibitors")
    link=link_candidate(c,evidence)
    assert link["links"] and not link["eligibility_confirmed"]
    assert "not" in evidence_map_prompt(evidence).lower()
    c.intervention_exposure_index_test="Empagliflozin"
    assert not link_candidate(c,evidence)["links"]


def test_focused_recovery_expands_real_singleton_without_inventing_eligibility():
    class Stub:
        def __init__(self):
            self.calls=[]
        def search(self,query,*,limit):
            self.calls.append(query)
            rows=[]
            if len(self.calls)==1:
                rows=[SearchRecord("Europe PMC","34449189","Empagliflozin in Heart Failure with a Preserved Ejection Fraction",
                     year=2021,metadata={"pubtype":["Randomized Controlled Trial"],"nct_id":"NCT03057951"})]
            if "TITLE:" in query and "preserved ejection fraction" in query:
                rows=[SearchRecord("Europe PMC","34711976","The SGLT2 inhibitor dapagliflozin in heart failure with preserved ejection fraction: a multicenter randomized trial",
                     year=2021,metadata={"pubtype":["Randomized Controlled Trial"],"nct_id":"NCT03030235"})]
            return SearchResult("Europe PMC",query,SourceStatus.SEARCHED_POSITIVE if rows else SourceStatus.SEARCHED_NEGATIVE,rows,len(rows))
    source=Stub()
    result=collect_evidence_map("Cardiology","EFFECTIVENESS",client=source,now=datetime(2026,11,25,tzinfo=timezone.utc))
    assert result["initial_cluster_count"]==0
    assert len(source.calls)<=6
    assert any(q["anchor_origin"]=="OBSERVED_TITLE_ANCHOR" for q in result["queries"])
    # A named-drug singleton and its class alias can compete for a slot;
    # the source fixture supplies an actual second report for that population.
    assert any(c["population_anchor"]=="hfpef" and c["intervention_anchor"]=="sglt2" for c in result["clusters"])
    assert not result["novelty_confirmed"]


def test_provider_rate_limit_defers_remaining_queries():
    class Limited:
        calls=0
        def search(self,query,*,limit):
            self.calls+=1
            return SearchResult("Europe PMC",query,SourceStatus.ACCESS_FAILED,message="HTTP 429")
    source=Limited()
    result=collect_evidence_map("Cardiology",client=source)
    assert source.calls==1
    assert [x["status"] for x in result["queries"]]==["ACCESS_FAILED","NOT_SEARCHED","NOT_SEARCHED"]
    assert result["status"]=="ACCESS_UNRESOLVED"
