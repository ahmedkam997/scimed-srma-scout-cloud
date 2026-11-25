"""Post-hoc diagnosis on the frozen pilot, no new AI requests.

Compare PubMed date/relevance ordering at identical query/sample budgets.
Recheck DELIVER full-text linkage independently, without injecting IDs into
ordinary search. Never report scientific superiority from this diagnostic.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
from .scientific_benchmark import _candidate, sample_metrics, safe_search, _pmid, _record, _access
from .query_optimizer import optimized_queries
from .registration_enrichment import enrich_records
from .trial_family import audit_trial_families
from scimed_scout.verification.queries import build_search_plan
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--fixture",type=Path,default=Path("benchmarks/scientific_v1.json"))
    args=p.parse_args()
    fixture=json.loads(args.fixture.read_text())
    out={"version":"PILOT_DIAGNOSIS_V1","new_ai_requests":0,"scientific_accuracy_validated":False,"ordering_cases":[]}
    def save():args.output.write_text(json.dumps(out,indent=2)+"\n",encoding="utf-8")
    # One published-review query per case; exactly same query and eight hits
    # in each arm. This tests sampling order, not comprehensive retrieval.
    for case in fixture["cases"]:
        c=_candidate(case);base=build_search_plan(c,max_queries=2).review_queries
        q=optimized_queries(c,"PubMed","REVIEW",base,max_queries=2)[0]
        item={"case":case["id"],"query":q,"arms":{}}
        for sort in ("pub_date","relevance"):
            r=safe_search(PubMedSource(sort=sort),q,8)
            item["arms"][sort]={"status":r.status.value,"total_count":r.total_count,"retrieved":len(r.records),
                **sample_metrics([x["pmid"] for x in case["reviews"]],[_pmid(x) for x in r.records],_access(r))}
        out["ordering_cases"].append(item);save();print(json.dumps({"ordering":item}),flush=True)
    ids=fixture["family_controls"][0]["pmids"]
    ep=EuropePMCSource()
    r=safe_search(ep,"("+" OR ".join("EXT_ID:"+x for x in ids)+") AND SRC:MED",len(ids))
    rows=[_record(x,"PRIMARY_STUDY") for x in r.records if _pmid(x) in ids and x.title]
    before=audit_trial_families(rows)
    revised,enrichment=enrich_records(rows,max_lookups=3)
    after=audit_trial_families(revised)
    out["family_control"]={"retrieved":len(rows),"expected_reports":len(ids),
        "before_family_leads":before["conservative_family_lead_count"],"after_family_leads":after["conservative_family_lead_count"],
        "expected_family_leads":1,"registry_linked_families":after["registry_linked_families"],
        "passed":len(rows)==len(ids) and after["conservative_family_lead_count"]==1 and after["registry_linked_families"]==1,
        "enrichment":enrichment,"confirmed_independent_eligible_studies":None}
    out["status"]="DIAGNOSTIC_COMPLETE";save();print(json.dumps({"family_control":out["family_control"]}),flush=True)
if __name__=="__main__":main()
