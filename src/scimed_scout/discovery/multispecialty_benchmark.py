"""Paired exploratory PubMed ranking/query arms; no AI, no production changes."""
import argparse,json
from pathlib import Path
from .scientific_benchmark import _candidate,_pmid,safe_search,_access,sample_metrics,exact_reference_audit
from .query_optimizer import optimized_queries
from scimed_scout.verification.queries import build_search_plan
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource

# Candidate-independent vocabulary, documented NLM terms and common variants.
VOCAB={
"tranexamic acid":(("tranexamic acid","TXA"),"Tranexamic Acid"),
"postpartum bleeding":(("postpartum hemorrhage","postpartum haemorrhage","postpartum bleeding","childbirth","vaginal delivery","cesarean delivery","caesarean delivery"),"Postpartum Hemorrhage"),
"acute appendicitis":(("appendicitis","acute appendicitis"),"Appendicitis"),
"antibiotic therapy":(("antibiotics","antibiotic therapy","antibacterial agents","antibiotic treatment"),"Anti-Bacterial Agents"),
"bacterial meningitis":(("bacterial meningitis","pyogenic meningitis"),"Meningitis, Bacterial"),
"dexamethasone":(("dexamethasone",),"Dexamethasone"),
}
PAIRS={"TXA_PREVENT":("postpartum bleeding","tranexamic acid"),"APPENDICITIS":("acute appendicitis","antibiotic therapy"),"MENINGITIS":("bacterial meningitis","dexamethasone")}
RCT='(randomized controlled trial[pt] OR controlled clinical trial[pt] OR randomized[tiab] OR randomised[tiab] OR placebo[tiab] OR randomly[tiab] OR trial[tiab])'
REVIEW='(systematic review[pt] OR meta-analysis[pt] OR systematic review[tiab] OR meta-analysis[tiab])'
def group(key):
    aliases,mesh=VOCAB[key]
    return "("+" OR ".join([f'"{x}"[tiab]' for x in aliases]+[f'"{mesh}"[mh]'])+")"
def variant(case,purpose,base):
    p,i=PAIRS[case["id"]];pair=group(p)+" AND "+group(i)
    return (pair+" AND "+(RCT if purpose=="PRIMARY" else REVIEW),base[0])
def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    fixture=json.loads(Path("benchmarks/scientific_v2_development.json").read_text())
    report={"schema":fixture["version"],"scientific_accuracy_validated":False,"new_ai_requests":0,"cases":[]}
    def save():args.output.write_text(json.dumps(report,indent=2)+"\n")
    clients={s:PubMedSource(sort=s) for s in ("pub_date","relevance")}
    for case in fixture["cases"]:
        c=_candidate(case);plan=build_search_plan(c,max_queries=2)
        entry={"case":case["id"],"arms":{}}
        for purpose,base,key in (("PRIMARY",plan.primary_queries,"primary"),("REVIEW",plan.review_queries,"reviews")):
            original=optimized_queries(c,"PubMed",purpose,base,max_queries=2)
            proposed=variant(case,purpose,original)
            ref=[x["pmid"] for x in case[key]];controls=[x["pmid"] for x in case.get("controls",[])]
            cache={}
            for version,queries in (("V1",original),("EXPERIMENTAL",proposed)):
                for sort,client in clients.items():
                    rows=[];logs=[]
                    for q in queries:
                        k=(sort,q)
                        if k not in cache:cache[k]=safe_search(client,q,12)
                        r=cache[k];rows+=r.records;logs.append({"query":q,"status":r.status.value,"retrieved":len(r.records),"total":r.total_count,"access":_access(r)})
                    ids={_pmid(r) for r in rows};metrics=sample_metrics(ref,ids,all(x["access"] for x in logs))
                    name=version+"_"+sort;entry["arms"].setdefault(name,{})[purpose]={"metrics":metrics,"control_pmids_retrieved":sorted(ids.intersection(controls)),"query_count":len(logs),"logs":logs}
        entry["reference_audit"]=exact_reference_audit(c,case,EuropePMCSource())
        report["cases"].append(entry);save()
        print(json.dumps({"case":entry["case"],"arms":{a:{k:v["metrics"] for k,v in x.items()} for a,x in entry["arms"].items()},"exact":entry["reference_audit"]["retrieved_count"],"expected":entry["reference_audit"]["expected_reference_count"]}),flush=True)
    report["status"]="COMPLETE";save()
if __name__=="__main__":main()
