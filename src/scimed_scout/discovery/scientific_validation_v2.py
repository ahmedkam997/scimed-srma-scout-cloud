"""Reference retrieval pilot. IDs are only used for evaluation, not discovery."""
from pathlib import Path
import argparse,json
from .rct_first import query_pair,comparison_rows,family_summary,own_rct,_search,_query,control_terms
from .evidence_first import _record
from .evidence_classification import classify_review_search_hit
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.pubmed_abstracts import enrich_rows
from scimed_scout.sources.europe_pmc import EuropePMCSource
from .adaptive_search import citation_neighbors,_pmid

def evaluate(case,primary,reviews):
    def ids(rows):return {str(r["source_record_id"]) for r in rows}
    all_rows,buckets=comparison_rows(case["pair"],primary,comparator=case["comparator"])
    matched=buckets.get(case["comparator"],[])
    # Clinical reference set includes add-on designs; direct-arm classifier
    # may appropriately withhold a shared background contrast. Preserve it
    # separately instead of counting as a false direct-arm match.
    refs=set(case["primary"]);negative=set(case["nonprimary"]);followups=set(case.get("followups",[]))
    return {"reference_primary":sorted(refs),"retrieved_primary":sorted(refs&ids(primary)),
            "retained_primary_comparison_cue":sorted(refs&ids(matched)),
            "retrieved_nonprimary":sorted(negative&ids(primary)),"nonprimary_counted_as_comparison":sorted(negative&ids(matched)),
            "followups_retrieved":sorted(followups&ids(primary)),"followups_retained_as_report_cues":sorted(followups&ids(matched)),
            "family_audit":family_summary(matched),"reference_reviews":sorted(case["reviews"]),
            "retrieved_review_references":sorted(set(case["reviews"])&ids(reviews)),
            "known_add_on_reference_requires_separate_pico":sorted({"39602173"} & ids(primary)) if case["id"]=="TRICUSPID_TEER" else [],
            "independent_trial_eligibility_validated":False}

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    cases=json.loads(Path("benchmarks/scientific_validation_v2.json").read_text())["cases"]
    client=PubMedSource(sort="mixed");europe=EuropePMCSource()
    out={"schema":"SCIMED_REFERENCE_PILOT_V2","scientific_accuracy_validated":False,"new_ai_requests":0,"cases":[]}
    for case in cases:
        audits=[]
        primary=_search(client,query_pair(case["pair"]),60,"PRIMARY_REFERENCE_RETRIEVAL",audits,None)
        if primary:
            primary,diag=enrich_rows(client,primary);audits.append(diag)
        reviews=_search(client,query_pair(case["pair"],review=True),30,"REVIEW_REFERENCE_RETRIEVAL",audits,None)
        metrics=evaluate(case,primary,reviews)
        # Apply the same predetermined supplement to every case. Reference
        # IDs are used only after retrieval to score the result.
        supplemental=_search(client,query_pair(case["pair"],review=True)+" AND "+_query(control_terms(case["comparator"])),30,"REVIEW_COMPARISON_REFERENCE_RECOVERY",audits,None)
        metrics["review_references_after_supplement"]=sorted(set(case["reviews"])&{str(r["source_record_id"]) for r in [*reviews,*supplemental]})
        matched,buckets=comparison_rows(case["pair"],primary,comparator=case["comparator"])
        seeds=[_pmid(r) for r in [*buckets.get(case["comparator"],[]),*matched] if _pmid(r)]
        graph,linked=citation_neighbors(europe,seeds,[*primary,*reviews,*supplemental])
        graph_rows=[_record(x) for x in linked]
        expanded=evaluate(case,[*primary,*graph_rows],[*reviews,*supplemental,*graph_rows])
        metrics["citation_recovery_audit"]=graph
        metrics["review_references_after_citation"]=expanded["retrieved_review_references"]
        metrics["primary_references_after_citation"]=expanded["retrieved_primary"]
        metrics["retained_comparison_after_citation"]=expanded["retained_primary_comparison_cue"]
        metrics["nonprimary_counted_after_citation"]=expanded["nonprimary_counted_as_comparison"]
        row={"case":case["id"],"search_audit":audits,**metrics}
        out["cases"].append(row);print(json.dumps(row),flush=True)
        args.output.write_text(json.dumps(out,indent=2)+"\n")
    out["status"]="REFERENCE_PILOT_COMPLETE"
    out["primary_reference_retrieval"]=[sum(len(c["retrieved_primary"]) for c in out["cases"]),sum(len(c["reference_primary"]) for c in out["cases"])]
    out["primary_reference_comparison_retention"]=[sum(len(c["retained_primary_comparison_cue"]) for c in out["cases"]),sum(len(c["reference_primary"]) for c in out["cases"])]
    out["review_reference_retrieval"]=[sum(len(c["retrieved_review_references"]) for c in out["cases"]),sum(len(c["reference_reviews"]) for c in out["cases"])]
    out["review_reference_retrieval_after_supplement"]=[sum(len(c["review_references_after_supplement"]) for c in out["cases"]),sum(len(c["reference_reviews"]) for c in out["cases"])]
    out["review_reference_retrieval_after_citation"]=[sum(len(c["review_references_after_citation"]) for c in out["cases"]),sum(len(c["reference_reviews"]) for c in out["cases"])]
    out["primary_reference_retrieval_after_citation"]=[sum(len(c["primary_references_after_citation"]) for c in out["cases"]),sum(len(c["reference_primary"]) for c in out["cases"])]
    args.output.write_text(json.dumps(out,indent=2)+"\n");print(json.dumps({k:v for k,v in out.items() if k!="cases"}),flush=True)

if __name__=="__main__":main()
