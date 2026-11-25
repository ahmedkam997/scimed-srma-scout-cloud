"""Evidence-first RCT discovery. Bounded search samples, not verified eligibility.

Rotating P/I search anchors define the retrieval space, NOT novel questions.
A question is constructed only from observed own-trial comparison cues.
No model-generated topics, hard exclusions or fabricated trial counts.
"""
from __future__ import annotations
import hashlib,re
from collections import defaultdict
from datetime import datetime,timezone
from .pico_matching import _groups,_normalize,_passages,NONPRIMARY,PROTOCOL_TYPE,NEGATED_RCT,OBS
from .trial_family import audit_trial_families,registration_signals
from .evidence_first import _record
from .evidence_seed import _NONPRIMARY_SEED_TITLE
from .topic_memory import is_recently_checked
from scimed_scout.storage import CandidateRecord
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.europe_pmc import EuropePMCSource
from scimed_scout.domain import SourceStatus

VERSION="RCT_FIRST_V1"
MIN_FAMILIES=7
MAX_PAIRS=6
MAX_DEEP=3
MAX_SEED_RECORDS=60
MAX_EUROPE_SUPPLEMENTS=2
# Clinical search vocabulary; no claim that any pair is novel or eligible.
# Each tuple has a population phrase, intervention phrase and optional aliases.
ANCHORS={
 "cardiology":(
 ("hypertension","renal denervation",("resistant hypertension","high blood pressure"),("renal sympathetic denervation",)),
 ("heart failure","intravenous iron",("heart failure",),("ferric carboxymaltose","ferric derisomaltose")),
 ("atrial fibrillation","catheter ablation",(),("radiofrequency ablation",)),
 ("coronary artery disease","colchicine",("myocardial infarction","coronary disease"),()),
 ("heart failure","empagliflozin",(),()),("heart failure","dapagliflozin",(),()),
 ("dyslipidemia","bempedoic acid",("hypercholesterolemia","hyperlipidemia"),()),
 ("coronary artery disease","intravascular ultrasound",("percutaneous coronary intervention","PCI"),("IVUS",)),
 ("atrial fibrillation","left atrial appendage occlusion",(),("left atrial appendage closure",)),
 ("myocardial infarction","remote ischemic conditioning",("STEMI",),("remote ischaemic conditioning",)),
 ("heart failure","spironolactone",(),()),
 ("peripheral artery disease","rivaroxaban",(),()),
 ("cardiac rehabilitation","exercise training",(),("exercise rehabilitation",)),
 ("coronary artery bypass grafting","endoscopic vein harvesting",("CABG",),("endoscopic saphenous vein harvesting",)),
 ("aortic stenosis","transcatheter aortic valve replacement",(),("TAVR","TAVI")),
 ("coronary artery disease","ticagrelor",("percutaneous coronary intervention",),()),
 ("heart failure","sacubitril valsartan",(),("sacubitril/valsartan",)),
 ("atrial fibrillation","pulsed field ablation",(),()),
 ),
 "general surgery":(
 ("appendicitis","antibiotics",(),("antibiotic treatment",)),
 ("inguinal hernia","laparoscopic repair",(),("laparoscopic hernia repair",)),
 ("colorectal surgery","mechanical bowel preparation",(),("bowel preparation",)),
 ("cholecystectomy","indocyanine green",(),("fluorescence cholangiography",)),
 ("abdominal surgery","negative pressure wound therapy",(),("negative pressure wound dressing",)),
 ("hemorrhoids","stapled hemorrhoidopexy",("haemorrhoids",),("stapled haemorrhoidopexy",)),
 ("colorectal surgery","early oral feeding",(),("early feeding",)),
 ("appendectomy","laparoscopic appendectomy",("appendicectomy",),("laparoscopic appendicectomy",)),
 ),
 "orthopedics":(
 ("distal tibial fracture","fibular fixation",("distal tibia fracture",),()),
 ("total knee arthroplasty","tranexamic acid",("knee replacement",),()),
 ("hip fracture","hemiarthroplasty",(),()),
 ("rotator cuff tear","arthroscopic repair",(),()),
 ("distal radius fracture","volar locking plate",(),()),
 ("anterior cruciate ligament reconstruction","hamstring graft",("ACL reconstruction",),()),
 ),
 "neurology":(
 ("ischemic stroke","mechanical thrombectomy",("ischaemic stroke",),("endovascular thrombectomy",)),
 ("multiple sclerosis","ocrelizumab",(),()),
 ("migraine","erenumab",(),()),("epilepsy","levetiracetam",(),()),
 ("parkinson disease","deep brain stimulation",("parkinson's disease",),()),
 ("stroke","robot assisted rehabilitation",(),("robotic rehabilitation",)),
 ),
 "nephrology":(
 ("acute kidney injury","renal replacement therapy",("AKI","acute renal failure"),("kidney replacement therapy",)),
 ("chronic kidney disease","dapagliflozin",("CKD",),()),
 ("hemodialysis","intravenous iron",("haemodialysis",),()),
 ("chronic kidney disease","finerenone",("CKD",),()),
 ),
}
# Explicit comparator cues. Distinct active arms and usual/standard care
# remain separate; we never invent the comparator from a generic trial title.
CONTROLS=("placebo","sham","usual care","standard care","open surgery","open repair",
          "open vein harvesting","open saphenous vein harvesting","medical therapy",
          "aspirin","clopidogrel","warfarin","enalapril","metoprolol",
          "radiofrequency ablation","cryoballoon ablation","early treatment","delayed treatment",
          "appendectomy","appendicectomy","saline","no treatment")
OUTCOMES=("all cause mortality","mortality","cardiovascular death","hospitalization","heart failure hospitalization",
          "blood pressure","stroke","myocardial infarction","major adverse cardiovascular events",
          "bleeding","quality of life","exercise capacity","pain","infection","wound infection",
          "length of stay","functional outcome","fracture union","nonunion","reoperation",
          "recurrence","renal function","kidney function","adverse events","treatment failure")
# Sensitive RCT search *cue*, not a validated standalone search strategy.
RCT_FILTER='(randomized controlled trial[pt] OR controlled clinical trial[pt] OR randomized[tiab] OR randomised[tiab] OR randomly[tiab] OR placebo[tiab] OR trial[tiab]) NOT (animals[mh] NOT humans[mh])'
REVIEW_FILTER='(systematic[sb] OR meta-analysis[pt] OR systematic review[tiab])'
OWN_ASSIGN=re.compile(r"\b(?:randomi[sz]ed (?:controlled )?(?:trial|study)|randomi[sz]ed (?:to|into)|randomly (?:assigned|allocated)|placebo.controlled|sham.controlled)\b",re.I)
SECONDARY=re.compile(r"\b(?:secondary analysis|post.hoc|subgroup analysis|pooled analysis|individual patient data|rationale and design|trial protocol|study protocol|retracted publication)\b",re.I)
COMPARE=re.compile(r"\b(?:versus|vs\.?|compared (?:with|to)|randomi[sz]ed (?:to|into)|randomly (?:assigned|allocated)|placebo.controlled|sham.controlled)\b",re.I)
BACKGROUND=re.compile(r"^(?:background|introduction|rationale|objective|aim)\s*[:：]",re.I)

def supported(specialty):
    return str(specialty).strip().casefold() in ANCHORS
def should_route(specialty,question_type):
    return str(question_type).strip().upper() in ("ALL","EFFECTIVENESS") and (supported(specialty) or str(specialty).strip().upper()=="ALL")

def has(text,term):
    target=_normalize(term)
    return bool(target and re.search(r"(?<![a-z0-9])"+re.escape(target)+r"(?![a-z0-9])",_normalize(text)))
def phrases(anchor,aliases):
    return tuple(dict.fromkeys((anchor,*aliases)))
def any_term(text,terms):
    return any(has(text,t) for t in terms)
def _query(terms,field="[tiab]"):
    return "("+" OR ".join('"'+s.replace('"','')+'"'+field for s in terms)+")"
def query_pair(pair,review=False):
    pop,inter,pa,ia=pair
    return _query(phrases(pop,pa))+" AND "+_query(phrases(inter,ia))+" AND "+(REVIEW_FILTER if review else RCT_FILTER)
def ep_query(pair):
    pop,inter,pa,ia=pair
    q=lambda ts:"("+" OR ".join('TITLE_ABS:"'+t.replace('"','')+'"' for t in ts)+")"
    return q(phrases(pop,pa))+" AND "+q(phrases(inter,ia))+' AND (PUB_TYPE:"randomized controlled trial" OR TITLE_ABS:"randomized trial" OR TITLE_ABS:"randomised trial" OR TITLE_ABS:"placebo controlled" OR TITLE_ABS:"sham controlled")'

def own_rct(variants):
    passages,types=_passages(variants)
    title=[p[3] for p in passages if p[0]=="title"]
    labels=[p[3] for p in types]
    if any(NONPRIMARY.search(t) or _NONPRIMARY_SEED_TITLE.search(t) or SECONDARY.search(t) or OBS.search(t) or NEGATED_RCT.search(t) for t in title):return False
    if any(PROTOCOL_TYPE.search(t) or "retract" in t.casefold() for t in labels):return False
    indexed=any(re.search(r"\brandomi[sz]ed controlled trial\b",t,re.I) for t in labels)
    explicit=any(OWN_ASSIGN.search(t) and not NEGATED_RCT.search(t) for t in title)
    methods=any(OWN_ASSIGN.search(p[3]) and not NEGATED_RCT.search(p[3]) and re.search(r"\b(?:we|patients|participants|subjects|individuals)\b",p[3],re.I) and not BACKGROUND.search(p[3]) for p in passages if p[0]!="title")
    return indexed or explicit or methods

def representative(variants):
    rep=max(variants,key=lambda x:(bool((x.get("payload") or {}).get("metadata",{}).get("abstractText")),bool((x.get("payload") or {}).get("url")),len(str(x.get("title") or ""))))
    payload=dict(rep.get("payload") or {});meta=dict(payload.get("metadata") or {})
    meta["trial_registration_ids"]=sorted({i for r in variants for i in registration_signals(r)})
    return {**rep,"payload":{**payload,"metadata":meta}}

def eligible_groups(pair,rows,year=None):
    year=year or datetime.now(timezone.utc).year
    pop,inter,pa,ia=pair
    for group in _groups(rows):
        variants=group["records"]
        if not own_rct(variants):continue
        passages,_=_passages(variants)
        valid_year=any(str((r.get("payload") or {}).get("year") or "").isdigit() and 1900<=int(r["payload"]["year"])<=year for r in variants)
        if not valid_year:continue
        # Both concepts must appear in the title or in own-study Methods/
        # allocation text, not merely in unrelated background sentences.
        eligible=[p[3] for p in passages if p[0]=="title" or (OWN_ASSIGN.search(p[3]) and not BACKGROUND.search(p[3]))]
        if not any(any_term(t,phrases(pop,pa)) and any_term(t,phrases(inter,ia)) for t in eligible):continue
        yield variants,eligible

def family_summary(rows):
    a=audit_trial_families(rows)
    return {"distinct_report_leads":len(rows),"family_leads":a["conservative_family_lead_count"]-len(a["ambiguous_reports"]),
            "registry_linked_families":a["registry_linked_families"],"unlinked_reports":len(a["unlinked_reports"]),
            "ambiguous_reports":len(a["ambiguous_reports"]),"confirmed_independent_eligible_trials":None}

def comparison_rows(pair,rows,comparator=None,year=None):
    buckets=defaultdict(list);all_rows=[]
    pop,inter,pa,ia=pair
    for variants,eligible in eligible_groups(pair,rows,year):
        r=representative(variants);all_rows.append(r)
        # Require observed intervention + comparator in same comparison title/
        # allocation passage. This is an explicit cue, not proof of exact arms.
        for control in ((comparator,) if comparator else CONTROLS):
            if any_term(control,phrases(inter,ia)):continue
            matches=[t for t in eligible if any_term(t,phrases(inter,ia)) and has(t,control) and COMPARE.search(t)]
            if matches:
                buckets[control].append({**r,"comparison_excerpt":matches[0][:500]})
    return all_rows,buckets

def strict_candidate_audit(candidate,rows):
    info=(candidate.metadata or {}).get("rct_first") or {}
    raw=info.get("pair")
    if not isinstance(raw,(tuple,list)) or len(raw)!=4:return {"family_leads":0,"confirmed_independent_eligible_trials":None}
    all_rows,buckets=comparison_rows(raw,rows,candidate.comparator_reference)
    exact=buckets.get(candidate.comparator_reference,[])
    return {**family_summary(exact),"population_intervention_family_leads":family_summary(all_rows)["family_leads"],
            "comparison_cues":[{"title":r["title"],"source":r["source"],"record_id":r["source_record_id"],
            "excerpt":r["comparison_excerpt"],"url":r["payload"].get("url"),"registration_ids":sorted(registration_signals(r))} for r in exact],
            "minimum":MIN_FAMILIES,"scope":"BIBLIOGRAPHIC_COMPARISON_CUES_ONLY"}

def _search(client,query,cap,stage,audits,check):
    if check:check()
    try:r=client.search(query,limit=cap)
    except Exception as e:
        audits.append({"source":client.name,"query":query,"stage":stage,"status":"ACCESS_FAILED","error_type":type(e).__name__,"retrieved":0});return []
    audits.append({"source":client.name,"query":query,"stage":stage,"status":r.status.value,"total":r.total_count,"retrieved":len(r.records),"message":str(r.message or "")[:240]})
    return [_record(x) for x in r.records if x.title.strip()]

def collect(specialty,rotation=0,*,pubmed=None,europe=None,check=None,prior=(),year=None,max_pairs=MAX_PAIRS):
    key=str(specialty).strip().casefold()
    year=year or datetime.now(timezone.utc).year
    if key=="all":key=("cardiology","general surgery","orthopedics","neurology","nephrology")[rotation%5]
    report={"version":VERSION,"specialty":key,"queries":[],"cells":[],"candidates":[],"skipped_recent":[],"new_ai_requests":0,"minimum_family_leads":MIN_FAMILIES,"scientific_accuracy_validated":False}
    if key not in ANCHORS:return {**report,"status":"UNSUPPORTED_SPECIALTY"}
    pubmed=pubmed or PubMedSource(sort="relevance");europe=europe or EuropePMCSource()
    anchors=ANCHORS[key];start=(int(rotation)*MAX_PAIRS)%len(anchors)
    pairs=[anchors[(start+i)%len(anchors)] for i in range(min(max_pairs,len(anchors),MAX_PAIRS))]
    samples=[]
    for pair in pairs:
        rows=_search(pubmed,query_pair(pair),MAX_SEED_RECORDS,"RCT_SEED",report["queries"],check)
        all_rows,buckets=comparison_rows(pair,rows,year=year)
        samples.append((pair,rows,family_summary(all_rows)["family_leads"]))
    # Recover only the strongest sampled cells; don't spend all time on a slow
    # second provider. PubMed metadata remains preserved if Europe PMC fails.
    strongest=sorted(range(len(samples)),key=lambda i:(-samples[i][2],i))[:MAX_EUROPE_SUPPLEMENTS]
    for i in strongest:
        pair,rows,n=samples[i]
        if n<2:continue
        rows+=_search(europe,ep_query(pair),MAX_SEED_RECORDS,"ABSTRACT_SUPPLEMENT",report["queries"],check)
    for pair,rows,_ in samples:
        all_rows,buckets=comparison_rows(pair,rows,year=year)
        primary=family_summary(all_rows)
        report["cells"].append({"population":pair[0],"intervention":pair[1],**primary,
            "observed_comparators":{k:family_summary(v) for k,v in buckets.items()},
            "source_records":all_rows})
        for comp,exact in sorted(buckets.items(),key=lambda x:(-family_summary(x[1])["family_leads"],x[0])):
            if family_summary(exact)["family_leads"]<2:continue
            # Outcomes are observed citation terms, never invented results.
            text=" ".join(r["title"]+" "+str((r["payload"].get("metadata") or {}).get("abstractText") or "") for r in exact)
            outcomes=[o for o in OUTCOMES if has(text,o)][:5]
            if not outcomes:outcomes=["Clinical outcomes reported in eligible trials (verify before protocol)"]
            ident=hashlib.sha256(("|".join((key,pair[0],pair[1],comp))).encode()).hexdigest()[:16].upper()
            title=f"{pair[1].capitalize()} versus {comp} in {pair[0]}: systematic review of randomized trials"
            info={"version":VERSION,"pair":pair,**family_summary(exact),"population_intervention_family_leads":primary["family_leads"],
                  "observed_outcome_terms":outcomes,"comparison_records":exact,"minimum":MIN_FAMILIES,
                  "shortlist_eligible":primary["family_leads"]>=MIN_FAMILIES,
                  "novelty_confirmed":False,"confirmed_independent_eligible_trials":None}
            candidate=CandidateRecord("RCT-"+ident,"",title,key.title(),"EFFECTIVENESS",
                review_question=title,population=pair[0],intervention_exposure_index_test=pair[1],comparator_reference=comp,
                outcomes=outcomes,eligible_designs=["Randomized controlled trial"],
                rationale="Observed randomized-report comparison cues; independent eligibility and extractable outcomes remain unverified.",
                novelty_hypothesis="Check existing reviews and actual search dates; neither novelty nor update value is confirmed.",
                search_terms=[pair[0],pair[1],comp],metadata={"rct_first":info,"evidence_preflight":{"priority_signal":primary["family_leads"],"eligibility_confirmed":False,"novelty_confirmed":False}})
            if any(is_recently_checked(candidate,x) for x in prior):
                report["skipped_recent"].append({"candidate_id":candidate.candidate_id,"title":title,"reason":"RECENTLY_CHECKED_PICO"});continue
            from dataclasses import asdict
            report["candidates"].append(asdict(candidate))
    # Cap questions by evidence and clinical diversity, never by AI opinion.
    report["candidates"].sort(key=lambda c:(-c["metadata"]["rct_first"]["family_leads"],-c["metadata"]["rct_first"]["population_intervention_family_leads"],c["candidate_id"]))
    report["status"]="SAMPLED" if any(q["status"] in ("SEARCHED_POSITIVE","SEARCHED_NEGATIVE") for q in report["queries"]) else "ACCESS_UNRESOLVED"
    return report

def main():
    import argparse,json
    from pathlib import Path
    p=argparse.ArgumentParser();p.add_argument("--output",type=Path,required=True);p.add_argument("--rotation",type=int,default=0);p.add_argument("--specialty",default="Cardiology");args=p.parse_args()
    r=collect(args.specialty,args.rotation);args.output.write_text(json.dumps(r,indent=2,default=str)+"\n")
    print(json.dumps({"status":r["status"],"queries":r["queries"],"cells":[{k:v for k,v in c.items() if k!="source_records"} for c in r["cells"]],"candidates":[{"title":c["title"],"family_leads":c["metadata"]["rct_first"]["family_leads"],"pi_families":c["metadata"]["rct_first"]["population_intervention_family_leads"],"shortlist_eligible":c["metadata"]["rct_first"]["shortlist_eligible"]} for c in r["candidates"]],"new_ai_requests":0}),flush=True)
if __name__=="__main__":main()
