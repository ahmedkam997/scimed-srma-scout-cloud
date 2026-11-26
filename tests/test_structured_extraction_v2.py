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

def test_explicit_hazard_ratio_does_not_convert_rates_or_infer_direction():
    s=registry();o=s["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"][0]
    o["analyses"]=[{"paramType":"Hazard Ratio (HR)","paramValue":"0.75","ciLowerLimit":"0.65","ciUpperLimit":"0.86","ciPctValue":"95","ciNumSides":"2-Sided","groupIds":["A","B"]}]
    r=registry_leads(s,"NCT00000001")["reported_ratio_estimates"]
    assert len(r)==1 and r[0]["ratio"]==0.75 and r[0]["ci95"]==[.65,.86] and not r[0]["direction_verified"] and not r[0]["pooling_allowed"]
    o["analyses"][0]["ciNumSides"]="1-Sided"
    assert not registry_leads(s,"NCT00000001")["reported_ratio_estimates"]

def test_focused_query_does_not_replace_broad_scope():
    from scimed_scout.discovery.competitor_priority_v2 import focused_review_query
    c=CandidateRecord("c","p","Q","Cardiology",population="heart failure",intervention_exposure_index_test="dapagliflozin")
    assert '"heart failure"[ti]' in focused_review_query(c) and '"dapagliflozin"[ti]' in focused_review_query(c)
    c.population="heart failure or kidney disease"
    assert focused_review_query(c)==""

def test_nonstandard_interval_level_preserved_without_false_ci95():
    s=registry();o=s["resultsSection"]["outcomeMeasuresModule"]["outcomeMeasures"][0]
    a={"paramType":"Hazard Ratio (HR)","paramValue":"0.75","ciLowerLimit":"0.65","ciUpperLimit":"0.86","ciPctValue":"95.04","ciNumSides":"TWO_SIDED","groupIds":["A","B"]}
    o["analyses"]=[a]
    r=registry_leads(s,"NCT00000001")["reported_ratio_estimates"][0]
    assert r["ci_percent"]==95.04 and r["reported_ci"]==[.65,.86] and r["ci95"] is None
    a["ciPctValue"]="95";a.pop("ciNumSides")
    r=registry_leads(s,"NCT00000001")["reported_ratio_estimates"][0]
    assert r["ci95"] is None and not r["two_sided_verified"] and not r["pooling_allowed"]

def test_surgical_query_preserves_aliases():
    from scimed_scout.discovery.competitor_priority_v2 import focused_review_query
    c=CandidateRecord("c","p","Q","General Surgery",population="rectal cancer",intervention_exposure_index_test="robotic surgery")
    q=focused_review_query(c)
    assert all(x in q for x in ('"rectal cancer"[ti]','"robotic surgery"[ti]','"robotic"[ti]','"robot-assisted"[ti]'))


@pytest.mark.parametrize("phrase,kind,ratio,lo,hi",[
    ("hazard ratio, 0.74; 95% confidence interval [CI], 0.65 to 0.85","hazard ratio",.74,.65,.85),
    ("hazard ratio, 0.82; 95% confidence interval [CI], 0.73 to 0.92","hazard ratio",.82,.73,.92),
    ("adjusted odds ratio = 0.61 [95% CI, 0.31 to 1.21]","odds ratio",.61,.31,1.21),
    ("HR 0·75 [95% CI 0·65-0·86]","hazard ratio",.75,.65,.86)])
def test_reported_ratio_only(phrase,kind,ratio,lo,hi):
    from scimed_scout.discovery.structured_extraction_v2 import abstract_ratios
    r=report();r["payload"]["metadata"]["abstractText"]=phrase
    rows=abstract_ratios(r)
    assert len(rows)==1
    assert rows[0]["measure"]==kind and rows[0]["ratio"]==ratio and rows[0]["reported_ci"]==[lo,hi]
    assert not rows[0]["pooling_allowed"] and not rows[0]["wald_interval_verified"]
@pytest.mark.parametrize("phrase",["HR 0.7; p=0.01", "risk ratio 0.2; 95% CI 0.4-0.8", "hazard ratio 0; 95% CI 0-1", "odds ratio 1.1; 95% CI 0.8", "19 of 236 patients; 95% CI 2-10"])
def test_ratio_rejects_ambiguous_or_invalid(phrase):
    from scimed_scout.discovery.structured_extraction_v2 import abstract_ratios
    r=report();r["payload"]["metadata"]["abstractText"]=phrase
    assert not abstract_ratios(r)
def test_protocol_and_secondary_role_never_confirm_eligibility():
    from scimed_scout.discovery.structured_extraction_v2 import report_role_cues
    r=report();r["payload"]["metadata"]["pubtype"]=["Clinical Trial Protocol"]
    assert "PROTOCOL_CUE" in report_role_cues(r)["cues"]
    r["title"]="Post-hoc analysis of a randomized trial"
    assert "SECONDARY_ANALYSIS_CUE" in report_role_cues(r)["cues"]
    assert not report_role_cues(r)["eligibility_confirmed"]


def test_ratio_endpoint_qualifier_and_no_lowercase_conjunction():
    from scimed_scout.discovery.structured_extraction_v2 import abstract_ratios
    r=report();r["payload"]["metadata"]["abstractText"]="hazard ratio for cardiovascular death or hospitalization for heart failure, 0.75; 95% CI, 0.65 to 0.86"
    assert abstract_ratios(r)[0]["ratio"]==.75
    r["payload"]["metadata"]["abstractText"]="or 0.75; 95% CI, 0.65 to 0.86"
    assert not abstract_ratios(r)
def test_explicit_isrctn_registration_format_only():
    from scimed_scout.discovery.trial_family import registration_signals
    r=report();r["payload"]["metadata"]["abstractText"]="Trial registration: International Standard Randomised Controlled Trial Number (ISRCTN) registry, ID: ISRCTN80500123."
    assert set(registration_signals(r))=={"ISRCTN80500123"}
    r["payload"]["metadata"]["abstractText"]="Previous study cited ISRCTN80500123."
    assert not registration_signals(r)
def test_explicit_early_body_trial_registration_excludes_discussion_and_conflicts():
    from scimed_scout.discovery.registration_enrichment import extract_registration
    r=report();r["payload"]["metadata"]["abstractText"]=""
    x=b'<article><front><article-meta><article-id pub-id-type="pmid">29067426</article-id><article-id pub-id-type="pmc">5818805</article-id></article-meta></front><body><sec><title>Introduction</title><p>The trial is registered as ClinicalTrials.gov Identifier: NCT00000001.</p></sec></body></article>'
    v=extract_registration(r,x)
    assert v["registration_id"]=="NCT00000001" and not v["independence_confirmed"]
    assert extract_registration(r,x.replace(b"Introduction",b"Discussion")) is None
    assert extract_registration(r,x.replace(b"NCT00000001.",b"NCT00000001. Another study NCT00000002.")) is None

def test_bioc_early_registration_preserves_exact_document_identity():
    import json
    from scimed_scout.discovery.registration_enrichment import extract_bioc_registration
    r=report();r["payload"]["metadata"]["abstractText"]=""
    x=[{"documents":[{"id":"PMC5818805","passages":[{"infons":{"section_type":"INTRO","article-id_pmid":"29067426"},"text":"The trial is registered as ClinicalTrials.gov Identifier: NCT00000001."}]}]}]
    value=extract_bioc_registration(r,json.dumps(x).encode(),source_url="https://example.org/bioc")
    assert value["registration_id"]=="NCT00000001" and not value["independence_confirmed"]
    x[0]["documents"][0]["passages"][0]["infons"]["section_type"]="DISCUSS"
    assert extract_bioc_registration(r,json.dumps(x).encode(),source_url="https://example.org/bioc") is None
