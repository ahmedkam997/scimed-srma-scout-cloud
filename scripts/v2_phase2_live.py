"""Known-source extraction and ranking challenge, not end-to-end scientific GO.
Published count pairs are reference labels only, never fed to extractors.
"""
import json
from pathlib import Path
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.pubmed_abstracts import parse_efetch,_fetch,enrich_rows
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.discovery.evidence_first import _record
from scimed_scout.discovery.structured_extraction_v2 import collect,registry_leads
from scimed_scout.discovery.novelty import _select_records
from scimed_scout.discovery.competitor_priority_v2 import hybrid
from scimed_scout.storage import CandidateRecord

CASES=[
 ("DAPA-HF","31535829","NCT03036124",[(386,2373),(502,2371)]),
 ("DELIVER","36027570","NCT03619213",[(512,3131),(610,3132)]),
 ("EMPEROR-Reduced","32865377","NCT03057977",[(361,1863),(462,1867)]),
 ("ROLARR","29067426","NCT01736072",[(19,236),(28,230)])]
def main():
    ep=EuropePMCSource(JsonHttpClient(timeout=12,retries=0,service="europe_pmc",min_interval=.5))
    ct=JsonHttpClient(timeout=12,retries=0,service="ctgov",min_interval=.3)
    pub=PubMedSource(JsonHttpClient(timeout=18,retries=1,service="ncbi",min_interval=.5),sort="relevance")
    try:abstracts,abstract_diag=parse_efetch(_fetch(pub,[x[1] for x in CASES]),[x[1] for x in CASES]);batch_status="SEARCHED_POSITIVE" if len(abstracts)==len(CASES) else "PARTIAL"
    except Exception as ex:abstracts={};abstract_diag={"error_type":type(ex).__name__};batch_status="ACCESS_FAILED"
    report={"version":"V2_PHASE2_REAL_SOURCE_CHALLENGE","new_ai_requests":0,"scientific_qualification_validated":False,"trials":[],"ranking":[]}
    report["pubmed_efetch_batch"]={"status":batch_status,"retrieved":len(abstracts),**abstract_diag}
    for name,pmid,nct,gold in CASES:
        item={"trial":name,"pmid":pmid,"registry":nct,"reference_count_pairs":gold}
        if pmid in abstracts:
            m=abstracts[pmid]
            exact=[{"source":"PubMed","source_record_id":pmid,"title":m["pubmed_efetch_title"],"payload":{"url":f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/","metadata":m}}]
            item["article_source_status"]="SEARCHED_POSITIVE";item["article_source"]="PubMed EFetch"
        else:
            found=ep.search(f"EXT_ID:{pmid} AND SRC:MED",limit=3)
            exact=[_record(r) for r in found.records if r.record_id==pmid and r.metadata.get("source")=="MED"]
            item["article_source_status"]=found.status.value;item["article_source"]="Europe PMC";item["article_diagnostic"]=found.message[:240]
        if len(exact)==1:
            a=collect(exact,max_fulltexts=1)
            if a["reports"][0].get("fulltext",{}).get("status")!="JATS_SOURCE_LINKED_LEADS" and a["reports"][0].get("pmcid"):
                a=collect(exact,previous=a,max_fulltexts=1)
            r=a["reports"][0]
            pairs={(x["events"],x["denominator"]) for x in r["abstract_count_leads"]}
            item.update(abstract_pairs=sorted(pairs),abstract_matches=sum(p in pairs for p in gold),fulltext_status=r.get("fulltext",{}).get("status","NO_PMCID"),table_count=len(r.get("fulltext",{}).get("tables",[])),methods_count=len(r.get("fulltext",{}).get("methods",[])),fulltext_routes=r.get("fulltext_attempts",[]),observed_registry_ids=r["registration_ids"])
        try:
            study=ct.get_json("https://clinicaltrials.gov/api/v2/studies/"+nct)
            r=registry_leads(study,nct)
            item["registry_result_layouts"]=[{"title":o.get("title"),"type":o.get("paramType"),"units":o.get("unitOfMeasure"),"denominator_units":[d.get("units") for d in o.get("denoms",[])],"groups":len(o.get("groups",[]))} for o in (study.get("resultsSection",{}).get("outcomeMeasuresModule",{}).get("outcomeMeasures",[]))[:12]]
            outcomes=r.get("numeric_outcome_leads",[])
            item["registry_status"]=r["status"];item["allocation"]=r.get("allocation");item["enrollment"]=r.get("enrollment");item["numeric_outcome_leads"]=len(outcomes)
            item["same_outcome_exact_pairs"]=[{"title":o["title"],"groups":o["groups"],"time_frame":o["time_frame"]} for o in outcomes if sorted((g["events"],g["denominator"]) for g in o["groups"])==sorted(gold)]
        except Exception as ex:item["registry_status"]="ACCESS_UNRESOLVED";item["error_type"]=type(ex).__name__
        report["trials"].append(item)
        print(json.dumps(item),flush=True)
    for name,pop,inter,control,query,positive in [
        ("cardiology","heart failure","dapagliflozin","placebo",'(TITLE_ABS:dapagliflozin OR TITLE_ABS:empagliflozin) AND TITLE_ABS:"heart failure" AND (TITLE_ABS:"meta-analysis" OR TITLE_ABS:"systematic review")',{"36030328","42547169"}),
        ("surgery","rectal cancer","robotic surgery","laparoscopic surgery",'TITLE_ABS:"rectal cancer" AND (TITLE_ABS:robotic OR TITLE_ABS:laparoscopic) AND (TITLE_ABS:"meta-analysis" OR TITLE_ABS:"systematic review")',{"42581199","40022103","40770525","42223567"})]:
        res=ep.search(query,limit=60);ep_status=res.status.value
        if not res.records:
            # equivalent concepts in PubMed syntax; different source/query,
            # never treat a fallback as complete Europe PMC coverage.
            query=('(dapagliflozin[tiab] OR empagliflozin[tiab]) AND "heart failure"[tiab] AND (meta-analysis[pt] OR systematic review[pt] OR meta-analysis[tiab])' if name=="cardiology" else '"rectal cancer"[tiab] AND (robotic[tiab] OR laparoscopic[tiab]) AND (meta-analysis[pt] OR systematic review[pt] OR meta-analysis[tiab])')
            res=pub.search(query,limit=60)
        rows=[{**_record(r),"evidence_type":"PUBLISHED_REVIEW"} for r in res.records]
        if res.source=="PubMed":rows,enrichment=enrich_rows(pub,rows)
        else:enrichment={}
        c=CandidateRecord(name,"challenge","Q",name,population=pop,intervention_exposure_index_test=inter,comparator_reference=control)
        prior=_select_records(c,rows,len(rows));new=hybrid(c,prior)
        def pos(rs):return {r["source_record_id"]:i+1 for i,r in enumerate(rs) if r["source_record_id"] in positive}
        result={"topic":name,"query":query,"source":res.source,"ep_status":ep_status,"enrichment":enrichment,"source_status":res.status.value,"total":res.total_count,"raw":len(rows),"unique":len(prior),"baseline_known_ranks":pos(prior),"hybrid_known_ranks":pos(new),"inventory_retained":{(r["source"],r["source_record_id"]) for r in prior}=={(r["source"],r["source_record_id"]) for r in new},"known_positive_pmids":sorted(positive),"qualification_granted":False}
        report["ranking"].append(result);print(json.dumps(result),flush=True)
    Path("v2-phase2-live.json").write_text(json.dumps(report,indent=2)+"\n")
    print("V2_PHASE2_SUMMARY "+json.dumps(report),flush=True)
if __name__=="__main__":main()
