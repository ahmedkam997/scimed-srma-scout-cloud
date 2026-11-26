import pytest
from scimed_scout.discovery.structured_extraction_v2 import abstract_counts,registry_leads,jats_leads,collect
from scimed_scout.discovery.competitor_priority_v2 import hybrid
from scimed_scout.discovery.registry_reference_suggestions import suggest
from scimed_scout.storage import CandidateRecord

def report():
    return {"source":"PubMed","source_record_id":"29067426","title":"ROLARR","payload":{"url":"https://pubmed.ncbi.nlm.nih.gov/29067426/","metadata":{"pmid":"29067426","pmcid":"PMC5818805","abstractText":"Conversion: 19 of 236 patients; 28 of 230 patients."}}}

def test_real_published_numeric_fixture_is_not_eligible():
    leads=abstract_counts(report())
    assert [(x["events"],x["denominator"]) for x in leads]==[(19,236),(28,230)]
    assert all(not x["arm_mapping_verified"] for x in leads)

def registry():
    return {"protocolSection":{"identificationModule":{"nctId":"NCT00000001"},"designModule":{"studyType":"INTERVENTIONAL","designInfo":{"allocation":"RANDOMIZED","interventionModel":"PARALLEL"},"enrollmentInfo":{"count":50}}},"resultsSection":{"outcomeMeasuresModule":{"outcomeMeasures":[{"title":"Death","timeFrame":"30 days","paramType":"COUNT_OF_PARTICIPANTS","unitOfMeasure":"Participants","groups":[{"id":"A","title":"Treatment"},{"id":"B","title":"Control"}],"denoms":[{"units":"Participants","counts":[{"groupId":"A","value":"25"},{"groupId":"B","value":"25"}]}],"classes":[{"categories":[{"measurements":[{"groupId":"A","value":"0"},{"groupId":"B","value":"3"}]}]}]}]}}}

def test_registry_count_zero_and_ambiguous_not_pooled():
    s=registry();r=registry_leads(s,"NCT00000001")
    assert r["numeric_outcome_leads"][0]["groups"][0]["events"]==0
    assert r["allocation"]=="RANDOMIZED" and not r["eligibility_confirmed"] and not r["pooling_allowed"]
    s["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"][0]["denoms"].append({"units":"Participants","counts":[{"groupId":"A","value":"25"}]})
    assert not registry_leads(s,"NCT00000001")["numeric_outcome_leads"]
    assert registry_leads(s,"NCT00000002")["status"]=="IDENTITY_MISMATCH"

def test_linked_reports_still_retrieve_registry_outcomes():
    r=report();r["payload"]["metadata"]["trial_registration_id"]="NCT00000001"
    audit=suggest([r],lookup=lambda n:registry())
    assert audit["source_calls"]==1 and audit["remaining_registry_ids"]==0
    assert audit["structured_registry_leads"][0]["numeric_outcome_leads"]
    assert not audit["independence_confirmed"]

def xml(pmc="5818805"):
    return f'<article><front><article-meta><article-id pub-id-type="pmid">29067426</article-id><article-id pub-id-type="pmc">{pmc}</article-id></article-meta></front><body><sec><title>Methods</title><p>Participants were randomized.</p></sec><sec><title>Results</title><table-wrap id="T1"><caption>Conversion</caption><table><tr><th colspan="2">Results</th></tr><tr><td>19</td><td>28</td></tr></table></table-wrap></sec></body></article>'.encode()

def test_exact_jats_identity_preserves_layout():
    x=jats_leads(report(),xml())
    assert x["tables"][0]["rows"][0][0]["colspan"]=="2" and x["methods"]
    assert not x["pooling_allowed"]
    assert jats_leads(report(),xml("1234567"))["status"]=="IDENTITY_MISMATCH"
    assert jats_leads(report(),b'<!DOCTYPE article [<!ENTITY a "bad">]><article/>')["status"]=="UNRESOLVED"

def test_failed_xml_route_rotates_and_stops():
    calls=[]
    def fail(u):calls.append(u);raise TimeoutError()
    a=collect([report()],fetcher=fail)
    b=collect([report()],fetcher=fail,previous=a)
    c=collect([report()],fetcher=fail,previous=b)
    assert a["source_calls"]==b["source_calls"]==1 and c["source_calls"]==0
    assert "europepmc" in calls[0] and "oai" in calls[1]

def test_rank_only_preserves_entire_inventory():
    c=CandidateRecord("c","p","Q","Cardiology",population="heart failure",intervention_exposure_index_test="dapagliflozin",comparator_reference="placebo")
    rows=[{"source":"PubMed","source_record_id":str(i),"title":t,"payload":{}} for i,t in enumerate(["Heart failure exercise","Abdominal surgery","Dapagliflozin versus placebo in heart failure","Dapagliflozin in diabetes"])]
    ranked=hybrid(c,rows)
    assert len(ranked)==len(rows) and set(r["source_record_id"] for r in ranked)==set(r["source_record_id"] for r in rows)

def test_exact_pmid_recovery_does_not_replace_other_source(tmp_path):
    from scimed_scout.storage import SQLiteLedger,ProjectRecord
    from scimed_scout.discovery.structured_extraction_v2 import recover_pubmed_abstracts
    with SQLiteLedger(tmp_path/"r.sqlite") as ledger:
        ledger.upsert_project(ProjectRecord("p","Medicine"));ledger.upsert_candidate(CandidateRecord("c","p","Q","Medicine"))
        ledger.upsert_external_evidence("c","PRIMARY_STUDY","29067426",source="Other",title="Other source",payload={"metadata":{"pmid":"29067426"}})
        raw=b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>29067426</PMID><Article><ArticleTitle>ROLARR</ArticleTitle><Abstract><AbstractText>19 of 236 patients.</AbstractText></Abstract></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
        a=recover_pubmed_abstracts(ledger,"c",None,fetcher=lambda ids:raw)
        assert a["retrieved"]==1 and len(ledger.list_external_evidence("c"))==2
        assert recover_pubmed_abstracts(ledger,"c",None,previous=a,fetcher=lambda ids:raw)["source_calls"]==0
