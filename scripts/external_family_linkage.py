"""External article-to-registered-trial grouping benchmark.
Gold standard is published NCT linkage, not confirmed independent participants.
No registry identifiers from labels are supplied to prediction.
"""
import argparse,csv,hashlib,io,itertools,json,re,urllib.request
from collections import defaultdict,Counter
from pathlib import Path
from scimed_scout.discovery.trial_family import audit_trial_families
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.pubmed_abstracts import _fetch,parse_efetch,MAX_IDS
from external_reference_validation import metrics

URL="https://zenodo.org/records/5885692/files/TrialSample_2orMoreNCTlinked.csv?download=1"
MD5="e645797ad00acc521e4d89fcdfd3a3b3"
def positive(value):return str(value).strip().lower() in ("1","1.0","true")
def load_reference():
    with urllib.request.urlopen(urllib.request.Request(URL,headers={"User-Agent":"SciMed-validation/1.0"}),timeout=90) as response:
        raw=response.read(80_000_001)
    if len(raw)>80_000_000 or hashlib.md5(raw).hexdigest()!=MD5:raise ValueError("reference checksum mismatch")
    rows=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not {"NCT_num","PMID","NCTlinkreal","Reslinkreal"}.issubset(rows.fieldnames or []):raise ValueError("reference schema mismatch")
    gold=defaultdict(set);silver=defaultdict(set);count=0
    for row in rows:
        count+=1
        nct=str(row["NCT_num"]).upper();pmid=str(row["PMID"]).split(".")[0]
        if not re.fullmatch(r"NCT[0-9]{8}",nct) or not pmid.isdigit():continue
        if positive(row["NCTlinkreal"]):gold[pmid].add(nct)
        if positive(row["Reslinkreal"]):silver[pmid].add(nct)
    if count<1_000_000 or not gold:raise ValueError("reference incomplete")
    return gold,silver,count

def select(gold,trial_cap=100,report_cap=4):
    clusters=defaultdict(list)
    for pmid,labels in gold.items():
        if len(labels)==1:clusters[next(iter(labels))].append(pmid)
    key=lambda x:hashlib.sha256(("SCIMED_EXTERNAL_V1:"+x).encode()).hexdigest()
    selected={}
    for nct in sorted((x for x,v in clusters.items() if len(v)>=2),key=key)[:trial_cap]:
        for pmid in sorted(clusters[nct],key=key)[:report_cap]:selected[pmid]=nct
    return selected

def pair_score(truth,observed):
    audit=audit_trial_families(observed)
    prediction={}
    for family in audit["families"]:
        for row in family["reports"]:prediction[row["report_id"]]=family["registration_id"]
    ids=sorted(truth);c=Counter()
    for a,b in itertools.combinations(ids,2):
        same=truth[a]==truth[b]
        linked=a in prediction and b in prediction and prediction[a]==prediction[b]
        c[("t" if same==linked else "f")+("p" if linked else "n")]+=1
    return {**metrics(c["tp"],c["fp"],c["fn"],c["tn"]),"reference_reports":len(ids),"reference_trials":len(set(truth.values())),"observed_reports":len(observed),"predicted_registry_families":audit["registry_linked_families"],"predicted_linked_reports":audit["registry_linked_reports"],"unlinked_reports":len(audit["unlinked_reports"]),"ambiguous_reports":len(audit["ambiguous_reports"]),"exact_gold_registry_matches":sum(prediction.get(k)==v for k,v in truth.items()),"scope":"PUBLISHED_NCT_LINKAGE_PROXY_NOT_PATIENT_INDEPENDENCE"}

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    report={"schema":"SCIMED_EXTERNAL_FAMILY_LINKAGE_V1","scientific_accuracy_validated":False,"new_ai_requests":0,"source_md5":MD5,"status":"STARTED"}
    def save():
        a.output.write_text(json.dumps(report,indent=2)+"\n");print(json.dumps(report),flush=True)
    try:
        gold,silver,count=load_reference();truth=select(gold)
        if len(truth)<100:raise ValueError("insufficient reference reports")
        # Silver-only registered results references lacking gold-linked
        # evidence, restricted to the same sample of trials.
        selected_trials=set(truth.values())
        silver_truth={k:next(iter(v)) for k,v in silver.items() if k not in gold and len(v)==1 and next(iter(v)) in selected_trials}
        silver_truth=dict(sorted(silver_truth.items(),key=lambda x:hashlib.sha256(x[0].encode()).hexdigest())[:100])
        report.update(status="REFERENCE_LOADED",reference_rows=count,gold_reference_pmids=len(gold),silver_only_sample=len(silver_truth))
        save()
        ids=list(truth)+list(silver_truth);observed=[];batches=[];client=PubMedSource()
        for start in range(0,len(ids),MAX_IDS):
            batch=ids[start:start+MAX_IDS]
            try:
                raw=_fetch(client,batch);found,diag=parse_efetch(raw,batch)
                for pmid,metadata in found.items():
                    observed.append({"source":"PubMed","source_record_id":pmid,"title":metadata.get("pubmed_efetch_title",""),"payload":{"metadata":metadata}})
                batches.append({"requested":len(batch),"retrieved":len(found),**diag})
            except Exception as exc:batches.append({"requested":len(batch),"retrieved":0,"error_type":type(exc).__name__})
        gold_rows=[r for r in observed if r["source_record_id"] in truth]
        silver_rows=[r for r in observed if r["source_record_id"] in silver_truth]
        # Report both end-to-end (missing metadata is not a confirmed link)
        # and conditional-on-retrieved results. Do not inflate denominators.
        available={r["source_record_id"] for r in gold_rows}
        report.update(status="MEASURED" if len(available)==len(truth) else "PARTIAL_METADATA",batches=batches,
            end_to_end=pair_score(truth,gold_rows),conditional_on_retrieved=pair_score({k:v for k,v in truth.items() if k in available},gold_rows),
            silver_only=pair_score(silver_truth,silver_rows))
    except Exception as exc:report.update(status="REFERENCE_OR_METADATA_UNRESOLVED",error_type=type(exc).__name__)
    save()
if __name__=="__main__":main()
