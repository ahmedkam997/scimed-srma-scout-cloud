"""MeSH-assisted discovery of title-corroborated search anchors, not verified PICO."""
from collections import defaultdict
import re
VERSION="MESH_DYNAMIC_ANCHORS_V1"
SCOPES={
 "cardiology":'("Cardiovascular Diseases"[mh] OR cardiovascular[tiab] OR cardiology[tiab])',
 "general surgery":'("Surgical Procedures, Operative"[mh] OR surgery[tiab]) AND (abdominal[tiab] OR colorectal[tiab] OR hernia[tiab] OR biliary[tiab])',
 "orthopedics":'("Musculoskeletal Diseases"[mh] OR fractures[tiab] OR arthroplasty[tiab])',
 "neurology":'("Nervous System Diseases"[mh] OR neurology[tiab])',
 "neurosurgery":'("Neurosurgical Procedures"[mh] OR neurosurgery[tiab])',
 "radiology":'("Diagnostic Imaging"[mh] OR radiology[tiab])',
 "endocrinology":'("Endocrine System Diseases"[mh] OR diabetes[tiab])',
 "anesthesiology":'("Anesthesia"[mh] OR anesthesia[tiab] OR anaesthesia[tiab])',
 "obstetrics and gynecology":'("Pregnancy Complications"[mh] OR "Genital Diseases, Female"[mh] OR obstetric[tiab])',
 "nephrology":'("Kidney Diseases"[mh] OR dialysis[tiab])',
}
def query(specialty,year):
    if specialty not in SCOPES:return None
    return SCOPES[specialty]+' AND ("Randomized Controlled Trial"[pt] OR randomized[tiab] OR randomised[tiab]) AND ("%d/01/01"[dp] : "%d/12/31"[dp]) NOT (animals[mh] NOT humans[mh])'%(year-2,year)
def terms(value):
    return value if isinstance(value,list) else []
def clean(value):
    s=str(value or "").strip()
    return s if 3<=len(s)<=85 and re.fullmatch(r"[\w ,/()'’+-]+",s) else ""
def derive(rows,existing,*,year,limit=2):
    from .rct_first import own_rct,has,family_summary
    from .pico_matching import _groups,_normalize
    known={(_normalize(p),_normalize(i)) for p,i,*_ in existing}
    pool=defaultdict(list);canonical={}
    for group in _groups(rows):
        variants=group["records"]
        if not own_rct(variants):continue
        for row in variants:
            p=row.get("payload") or {};m=p.get("metadata") or {};title=str(row.get("title") or "")
            if m.get("pubmed_efetch_identity")!="EXACT_PMID" or not isinstance(p.get("year"),int) or not year-2<=p["year"]<=year:continue
            populations=[];interventions=[]
            for heading in terms(m.get("mesh_headings")):
                if not isinstance(heading,dict):continue
                term=clean(heading.get("descriptor"))
                q=set(terms(heading.get("qualifiers")))
                if not term or not has(title,term):continue
                if q & {"drug therapy","therapy","surgery","prevention & control","rehabilitation"}:populations.append(term)
                if q & {"therapeutic use","administration & dosage","methods"}:interventions.append(term)
            interventions.extend(t for raw in terms(m.get("chemical_names")) if (t:=clean(raw)) and has(title,t))
            for pop in sorted(set(populations)):
                for inter in sorted(set(interventions)):
                    key=(_normalize(pop),_normalize(inter))
                    if not all(key) or key[0]==key[1] or key in known:continue
                    if has(pop,inter) or has(inter,pop):continue
                    if key[1] in {"placebo","saline","water","oxygen","drug therapy","therapy","surgery","treatment"}:continue
                    canonical[key]=(pop,inter,(),())
                    if not any(x.get("source_record_id")==row.get("source_record_id") for x in pool[key]):pool[key].append(row)
    ranked=[]
    for key,records in pool.items():
        families=family_summary(records)
        if families["family_leads"]>=2:ranked.append((key,families,records))
    ranked.sort(key=lambda x:(-x[1]["registry_linked_families"],-min(x[1]["family_leads"],10),x[0]))
    out=[];seen=set()
    for key,families,records in ranked:
        if key[0] in seen:continue
        seen.add(key[0]);out.append({"pair":canonical[key],"family_cues":families["family_leads"],
            "source_reports":[{"title":r["title"],"record_id":r["source_record_id"],"url":r["payload"].get("url")} for r in records[:8]],
            "scope":"TITLE_CORROBORATED_MESH_ANCHOR_NOT_VERIFIED_PICO"})
        if len(out)>=limit:break
    return out
