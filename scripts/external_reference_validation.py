"""Frozen independent public corpora; no reference labels are passed to discovery.
External linkage proxy and review-level retrieval are distinct from RCT eligibility.
"""
from collections import defaultdict,Counter
from pathlib import Path
import argparse,csv,hashlib,io,json,re,urllib.request
from scimed_scout.discovery.trial_family import registration_signals
from scimed_scout.discovery.rct_first import query_pair,review_title_query,RCT_FILTER,REVIEW_FILTER
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.discovery.competitor_records import identifiers
from scimed_scout.discovery.evidence_first import _record

CLINI="https://raw.githubusercontent.com/ds4dh/CliniFact/77f8c19844fd4113aa051f867b4d7a8ce5c3a879/data/processed/primary_outcome_publication_dataset/"
SYNERGY="https://raw.githubusercontent.com/asreview/synergy-dataset/7efde4a37bed9e8d71f19421b90eae3485184c4d/datasets/"
def load_csv(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers={"User-Agent":"SciMed-validation/1.0"}),timeout=35) as response:
        raw=response.read(15_000_001)
    if len(raw)>15_000_000:raise ValueError("dataset size bound exceeded")
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))),hashlib.sha256(raw).hexdigest()

def metrics(tp,fp,fn,tn):
    def ratio(a,b):return a/b if b else None
    return {"tp":tp,"fp":fp,"fn":fn,"tn":tn,"sensitivity":ratio(tp,tp+fn),"precision":ratio(tp,tp+fp),"specificity":ratio(tn,tn+fp)}

def linkage(rows):
    # CliniFact uses results references for labels 0/1 and background
    # references for label 2. These are imperfect reference-role proxies,
    # not independent human adjudication of same-participant cohorts.
    pairs=defaultdict(set);abstracts=defaultdict(set)
    for row in rows:
        nct=str(row.get("nctId","")).upper();pmid=str(row.get("PMID","")).split(".")[0]
        label=str(row.get("label","")).split(".")[0]
        if not re.fullmatch(r"NCT[0-9]{8}",nct) or not pmid.isdigit() or label not in ("0","1","2"):continue
        pairs[nct,pmid].add(label!="2")
        abstracts[pmid].add((str(row.get("article_title","")),str(row.get("article_abstract",""))))
    counts=Counter();abstained=0;ambiguous=0;eligible=[]
    for (nct,pmid),labels in sorted(pairs.items()):
        if len(labels)!=1:ambiguous+=1;continue
        true=next(iter(labels))
        variants=abstracts[pmid]
        signals={k for title,abstract in variants for k in registration_signals({"title":title,"payload":{"metadata":{"abstractText":abstract}}})}
        # Match only a unique explicit observed registry identifier. A
        # different/multiple/missing identifier is not confirmed linkage.
        predicted=signals=={nct}
        abstained+=int(len(signals)!=1)
        counts[("t" if true==predicted else "f")+("p" if predicted else "n")]+=1
        eligible.append((nct,pmid,true,predicted))
    # Counter keys: true predicted positive=tp; false predicted positive=fp.
    return {"scope":"REGISTRY_REFERENCE_ROLE_PROXY_ABSTRACT_ONLY","reference_pairs":len(eligible),"distinct_pmids":len({x[1] for x in eligible}),"distinct_ncts":len({x[0] for x in eligible}),"ambiguous_labels_excluded":ambiguous,"missing_or_multi_id":abstained,**metrics(counts["tp"],counts["fp"],counts["fn"],counts["tn"]),"independent_rct_eligibility_validated":False}

def identity_set(row):
    doi=str(row.get("doi") or "").strip().lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    pmid=str(row.get("pmid") or "").split(".")[0]
    return ({("doi",doi)} if doi.startswith("10.") else set())|({("pmid",pmid)} if pmid.isdigit() else set())

def retrieval(rows,hits):
    # One reference row is one labelled record, not one trial. Do not call
    # off-corpus results false positives or missing identifiers true negatives.
    found=set()
    for item in hits:
        ids=identifiers(_record(item))
        found.update((k,v) for k,vs in ids.items() for v in vs)
    labels=defaultdict(set)
    for row in rows:
        ids=identity_set(row)
        label=str(row.get("label_included") or "").split(".")[0]
        if ids and label in ("0","1"):labels[tuple(sorted(ids))].add(label)
    counts=Counter();matched_ids=set();conflicts=0
    for ids,values in labels.items():
        if len(values)!=1:conflicts+=1;continue
        truth=values=={"1"};pred=bool(set(ids)&found)
        if pred:matched_ids.update(set(ids)&found)
        counts[("t" if truth==pred else "f")+("p" if pred else "n")]+=1
    return {"reference_rows_with_identity":sum(counts.values()),"source_rows":len(rows),"conflicting_identity_labels":conflicts,"retrieved_distinct_records":len(hits),"retrieved_identifier_count":len(found),"matched_reference_identifiers":len(matched_ids),**metrics(counts["tp"],counts["fp"],counts["fn"],counts["tn"]),"precision_scope":"ONLY_MATCHED_LABELLED_CORPUS_NOT_ALL_RETRIEVED_RECORDS"}

def main():
    p=argparse.ArgumentParser();p.add_argument("--output",required=True,type=Path);a=p.parse_args()
    out={"schema":"SCIMED_EXTERNAL_REFERENCE_V1","scientific_accuracy_validated":False,"new_ai_requests":0,"corpora":{}}
    def save():
        a.output.write_text(json.dumps(out,indent=2)+"\n");print(json.dumps(out),flush=True)
    try:
        rows=[];hashes={}
        for part in ("train","validation","test"):
            batch,h=load_csv(CLINI+part+"_set.csv");rows+=batch;hashes[part]=h
        out["corpora"]["cliniFact"]={"sha256":hashes,**linkage(rows)}
    except Exception as exc:out["corpora"]["cliniFact"]={"status":"ACCESS_OR_SCHEMA_UNRESOLVED","error_type":type(exc).__name__}
    save()
    # Prespecified independent review scopes taken from public eligibility
    # descriptions, not from included IDs. Narrow search budget (60 hits).
    # Reference cohorts include excluded records; unmatched new articles
    # cannot be judged from historical labels.
    cases=[
      ("Oud_2018",'("borderline personality disorder"[tiab]) AND (psychotherapy[tiab] OR "dialectical behavior therapy"[tiab] OR "mentalization based"[tiab] OR "schema therapy"[tiab] OR "transference focused"[tiab]) AND '+RCT_FILTER),
      ("van_Dis_2019",'(anxiety[tiab] OR "anxiety disorder"[tiab] OR "post-traumatic stress"[tiab] OR obsessive-compulsive[tiab]) AND ("cognitive behavioral therapy"[tiab] OR "cognitive behavioural therapy"[tiab] OR CBT[tiab]) AND '+RCT_FILTER),
      ("Moseng_2024",'(osteoarthritis[tiab] OR "knee pain"[tiab]) AND (exercise[tiab] OR education[tiab] OR "weight loss"[tiab] OR nonpharmacological[tiab] OR "non-pharmacological"[tiab]) AND '+REVIEW_FILTER),
    ]
    client=PubMedSource(sort="mixed")
    for key,query in cases:
        try:
            rows,h=load_csv(SYNERGY+key+"/"+key+"_ids.csv")
            result=client.search(query,limit=60)
            out["corpora"][key]={"sha256":h,"search_status":result.status.value,"reported_hits":result.total_count,**retrieval(rows,result.records)}
        except Exception as exc:out["corpora"][key]={"status":"ACCESS_OR_SCHEMA_UNRESOLVED","error_type":type(exc).__name__}
        save()
if __name__=="__main__":main()
