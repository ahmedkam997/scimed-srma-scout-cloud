"""Bounded multi-source published-review audit; reference IDs never query seeds."""
import json,argparse
from pathlib import Path
from .scientific_benchmark import _candidate,_pmid,safe_search
from .query_optimizer import optimized_queries
from .clinical_reranking import rank
from .evidence_classification import classify_review_search_hit,review_intervention_citation_signal
from .adaptive_retrieval import row
from scimed_scout.verification.queries import build_search_plan
from scimed_scout.sources import build_default_source_clients
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    fixture=json.loads(Path("benchmarks/ranking_v3.json").read_text())
    out={"schema":"REVIEW_DISCOVERY_AUDIT_V1","new_ai_requests":0,"scientific_accuracy_validated":False,"cases":[]}
    def save():args.output.write_text(json.dumps(out,indent=2)+"\n")
    clients={c.name:c for c in build_default_source_clients(allow_semantic_scholar_keyless_probe=True)}
    clients["PubMed"]=PubMedSource(sort="relevance")
    for case in fixture["cases"]:
        c=_candidate(case);plan=build_search_plan(c,max_queries=2)
        refs={r["pmid"] for r in case["reviews"]}
        entry={"case":case["id"],"reference_pmids":sorted(refs),"sources":[]}
        # Exact identifiers only in independent control lookup (not discovery).
        direct=safe_search(clients["Europe PMC"],"("+" OR ".join("EXT_ID:"+x for x in sorted(refs))+") AND SRC:MED",len(refs))
        entry["direct_controls"]=[{"pmid":_pmid(r),"title":r.title,"cue":classify_review_search_hit(r),"intervention":review_intervention_citation_signal(c,r),"doi":r.doi} for r in direct.records if _pmid(r) in refs]
        dois={r["doi"].casefold():r["pmid"] for r in entry["direct_controls"] if r["doi"]}
        def rid(r):
            m=r.metadata or {};ext=m.get("ids") or m.get("externalIds") or {}
            x=str(ext.get("pmid") or ext.get("PubMed") or "").rstrip("/").split("/")[-1] if isinstance(ext,dict) else ""
            return _pmid(r) or x or dois.get((r.doi or "").casefold(),"")
        for name in ("PubMed","Europe PMC","OpenAlex","Crossref","Semantic Scholar"):
            client=clients[name];q=optimized_queries(c,name,"REVIEW",plan.review_queries,max_queries=2)[0]
            r=safe_search(client,q,25)
            original=list(r.records);ranked=rank(c,[{**row(x),"source_record_id":str(i)} for i,x in enumerate(original)])
            ordered=[original[int(x["record"]["source_record_id"])] for x in ranked]
            cue=[x for x in original if classify_review_search_hit(x)=="CONFIRMED_REVIEW_CUE"]
            retained=[x for x in cue if review_intervention_citation_signal(c,x)!="NO_INTERVENTION_MENTION_IN_REVIEW_CITATION_MANUAL_CHECK"]
            obs=lambda rows:sorted(refs&{rid(x) for x in rows})
            entry["sources"].append({"source":name,"status":r.status.value,"total":r.total_count,"retrieved":len(original),"review_cues":len(cue),"retained_review_cues":len(retained),"reference_in_25":obs(original),"reference_in_raw12":obs(original[:12]),"reference_in_ranked12":obs(ordered[:12]),"reference_classified":obs(cue),"reference_retained":obs(retained),"query":q})
        out["cases"].append(entry);save();print(json.dumps(entry),flush=True)
    out["status"]="COMPLETE";save()
if __name__=="__main__":main()
