from scimed_scout.discovery.adjudication import build,validate
from scimed_scout.storage import CandidateRecord
from scimed_scout.discovery.registration_enrichment import enrich_fair
from scimed_scout.sources.prospero import ProsperoCliSource
from scimed_scout.sources.clinicaltrials import ClinicalTrialsGovSource
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.domain import SourceStatus
import json,subprocess
from urllib.parse import urlparse,parse_qs

def record(i,kind="PRIMARY_STUDY"):
    return {"source":"PubMed","source_record_id":str(i),"title":"Trial report "+str(i),"evidence_type":kind,"payload":{"url":f"https://pubmed.ncbi.nlm.nih.gov/{i}/","metadata":{"pmid":str(i),"pmcid":"PMC"+str(1234500+i)}}}

def test_all_competitors_visible_and_no_qualification():
    c=CandidateRecord("c","p","Q","Cardiology")
    packet=build(c,[record(i) for i in range(1,9)],[record(i,"PUBLISHED_REVIEW") for i in range(10,100)],[])
    assert packet["competitor_count"]==90 and len(packet["primary_report_index"])==8
    a=validate(packet,packet["submission_template"])
    assert a["valid_study_rows"]==0 and a["competitors_pending"]==90 and not a["qualification_granted"]

def test_outcome_validation_rejects_double_count_invalid_events_and_wrong_scope():
    import pytest
    c=CandidateRecord("c","p","Q","Cardiology");packet=build(c,[record(i) for i in range(1,9)],[],[])
    e={"url":"https://pubmed.ncbi.nlm.nih.gov/1/","locator":"Table 2","excerpt":"Source evidence"}
    s={"study_id":"s","report_ids":["PubMed:1"],"registry_ids":[],"design":"RCT","population":"P","intervention_arm":"I","comparator_arm":"C","independence_basis":"distinct cohort","eligibility_evidence":e,"reviewers":["A","B"]}
    o={"study_id":"s","report_id":"PubMed:1","outcome":"death","definition":"all-cause","timepoint":"1 year","measure":"RR","intervention_n":20,"comparator_n":20,"intervention_events":1,"comparator_events":2,"evidence":e,"reviewers":["A","B"]}
    a=validate(packet,{"candidate_id":"c","studies":[s,{**s,"study_id":"duplicate"}],"outcomes":[o,o,{**o,"intervention_events":21}]})
    assert a["valid_study_rows"]==1 and a["studies_with_valid_outcome_rows"]==1 and len(a["errors"])==3 and not a["qualification_granted"]
    with pytest.raises(ValueError):validate(packet,{"candidate_id":"different"})

def test_fair_enrichment_rotates_and_keeps_budget():
    calls=[]
    def fail(url):calls.append(url);raise TimeoutError()
    rows=[record(i) for i in range(1,5)]
    _,a=enrich_fair(rows,fetcher=fail,max_lookups=3)
    assert a["source_calls"]==3 and len({x["pmid"] for x in a["new_attempts"]})==3
    _,b=enrich_fair(rows,fetcher=fail,max_lookups=3,previous=a)
    assert b["source_calls"]==3 and b["new_attempts"][0]["pmid"] not in {x["pmid"] for x in a["new_attempts"]}
    assert len(b["attempts"])==4 and not b["independence_confirmed"]

def test_prospero_same_scope_recovery_completes_350():
    pages=[]
    def run(cmd):
        page=int(cmd[cmd.index("--page")+1]);pages.append(page)
        hits=[{"record_id":str(i),"title":"Review"} for i in range((page-1)*50,min(350,page*50))]
        return subprocess.CompletedProcess(cmd,0,stdout=json.dumps({"ok":True,"data":{"page":page,"page_size":50,"total_hits":350,"hits":hits}}),stderr="")
    src=ProsperoCliSource(runner=run)
    assert src.search("q").status==SourceStatus.PARTIAL
    pages.clear()
    r=src.search_recovery("q")
    assert r.status==SourceStatus.SEARCHED_POSITIVE and len(r.records)==350 and pages==list(range(1,8))

def test_ctgov_same_scope_recovery_completes_784():
    calls=[]
    def load(url):
        params=parse_qs(urlparse(url).query);calls.append(params)
        size=int(params["pageSize"][0]);start=int(params.get("pageToken",["0"])[0]);end=min(start+size,784)
        return {"totalCount":784,"studies":[{"protocolSection":{"identificationModule":{"nctId":f"NCT{i+1:08d}","briefTitle":"Trial"}}} for i in range(start,end)],**({"nextPageToken":str(end)} if end<784 else {})}
    src=ClinicalTrialsGovSource(JsonHttpClient(loader=load))
    assert src.search("catheter ablation").status==SourceStatus.PARTIAL
    calls.clear()
    r=src.search_recovery("catheter ablation")
    assert len(r.records)==784 and r.status==SourceStatus.SEARCHED_POSITIVE and len(calls)==2
    assert all(x["query.term"]==["catheter ablation"] for x in calls)


def test_registry_reference_recovery_rotates_without_new_merges():
    from scimed_scout.discovery.registry_reference_suggestions import suggest
    rows=[record(i) for i in range(1,6)]
    for i in range(4):rows[i]["payload"]["metadata"]["trial_registration_id"]=f"NCT{i+1:08d}"
    calls=[]
    def lookup(n):
        calls.append(n)
        return {"protocolSection":{"identificationModule":{"nctId":n},"referencesModule":{"references":[{"type":"RESULT","pmid":"5"}] if n=="NCT00000004" else []}}}
    first=suggest(rows,lookup=lookup,max_lookups=3)
    assert not first["suggestions"] and first["remaining_registry_ids"]==1
    second=suggest(rows,lookup=lookup,max_lookups=3,previous=first)
    assert second["source_calls"]==1 and second["remaining_registry_ids"]==0
    assert second["suggestions"][0]["pmid"]=="5" and not second["automatic_merge"]
    assert len(set(calls))==4

def test_documented_mcda_unchanged_exploratory_exposed():
    from scimed_scout.discovery.opportunity_mcda import weighted_assessment,compare_assessments
    a=weighted_assessment({"clinical_importance":{"rating":5,"status":"PRELIMINARY"}})
    r=compare_assessments([("a",a)])
    row=r["scenarios"]["balanced"]["intervals"][0]
    assert row["lower"]==0 and row["upper"]==100 and row["exploratory_lower"]==15
    assert r["robust_winner"] is None and not r["qualification_granted"]


def test_registry_results_are_source_linked_without_automatic_arm_mapping():
    from scimed_scout.discovery.registry_outcomes import extract
    study={"protocolSection":{"identificationModule":{"nctId":"NCT00000001"}},"resultsSection":{"outcomeMeasuresModule":{"outcomeMeasures":[{"title":"All-cause death","timeFrame":"12 months","paramType":"COUNT_OF_PARTICIPANTS","unitOfMeasure":"participants","groups":[{"id":"OG000","title":"Group A"},{"id":"OG001","title":"Group B"}],"denoms":[{"units":"participants","counts":[{"groupId":"OG000","value":"50"},{"groupId":"OG001","value":"49"}]}],"classes":[{"categories":[{"measurements":[{"groupId":"OG000","value":"2"},{"groupId":"OG001","value":"3"},{"groupId":"UNKNOWN","value":"100"}]}]}]}]}}}
    rows=extract(study,"NCT00000001")
    assert rows[0]["measurements"][0]["value"]=="2" and len(rows[0]["measurements"])==2
    assert rows[0]["denominators"][1]["value"]=="49" and not rows[0]["pooling_allowed"]
    assert not extract(study,"NCT00000002")
