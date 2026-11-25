"""Bounded P+I search for paired discovery diagnostics, not a systematic search."""
from __future__ import annotations
import re
import unicodedata

# Preserve clinically meaningful modifiers, with limited explicit aliases.
# Do not interpret arbitrary model text as search syntax.
ALIASES = {
    "heart failure with preserved ejection fraction": ("heart failure with preserved ejection fraction","HFpEF"),
    "heart failure preserved ejection fraction": ("heart failure with preserved ejection fraction","HFpEF"),
    "heart failure reduced ejection fraction": ("heart failure with reduced ejection fraction","HFrEF"),
    "heart failure": ("heart failure","cardiac failure"),
    "chronic coronary syndrome": ("chronic coronary syndrome","chronic coronary syndromes","stable coronary artery disease"),
    "coronary artery disease": ("coronary artery disease","coronary heart disease"),
    "myocardial infarction": ("myocardial infarction","heart attack"),
    "body mass index": ("body mass index","BMI"),
    "high intensity interval training": ("high intensity interval training","high-intensity interval training","HIIT"),
    "ischemic stroke": ("ischemic stroke","ischaemic stroke"),
    "ischaemic stroke": ("ischemic stroke","ischaemic stroke"),
    "large vessel occlusion": ("large vessel occlusion","large-vessel occlusion","LVO"),
    "endovascular thrombectomy": ("endovascular thrombectomy","mechanical thrombectomy","endovascular treatment","intraarterial treatment","intra-arterial treatment"),
    "mechanical thrombectomy": ("endovascular thrombectomy","mechanical thrombectomy","endovascular treatment","intraarterial treatment","intra-arterial treatment"),
    "acute kidney injury": ("acute kidney injury","acute renal failure","AKI"),
    "renal replacement therapy": ("renal replacement therapy","kidney replacement therapy"),
    "kidney replacement therapy": ("renal replacement therapy","kidney replacement therapy"),
    "type 1 diabetes": ("type 1 diabetes","type 1 diabetes mellitus","T1DM"),
    "continuous glucose monitoring": ("continuous glucose monitoring","CGM"),
    "multiple daily insulin injections": ("multiple daily insulin injections","multiple daily injections","insulin injections"),
    "hypertensive": ("hypertensive","hypertension"),
}
NOISE={"categories","category","diagnosed"}
# Grammatical connectors only; preserve clinical temporal/negative modifiers.
CONNECTORS={"adult","adults","patient","patients","with","of","in","the","a","an","and","for","individuals","people","due","to","by","from","using","receiving","undergoing","among","as","at","on","who","which","that","were","are","is","was","been","being"}
# 'chronic' is retained within known multiword clinical aliases.
def _units(value):
    raw=unicodedata.normalize("NFKC",str(value or ""))
    raw=re.sub(r"[\u2010-\u2015/]", " ",raw)
    raw=re.sub(r"[^a-zA-Z0-9 ]"," ",raw)
    terms=[t for t in raw.casefold().split() if t not in CONNECTORS]
    units=[]
    i=0
    while i<len(terms) and len(units)<6:
        match=None
        for size in range(min(7,len(terms)-i),0,-1):
            key=" ".join(terms[i:i+size])
            if key in ALIASES:
                match=(size,ALIASES[key])
                break
        if match:
            units.append(match[1])
            i+=match[0]
        else:
            token=terms[i]
            if token not in NOISE:
                units.append((token,))
            i+=1
    return units

def focused_query(candidate,source,purpose):
    if source not in ("PubMed","Europe PMC") or purpose not in ("PRIMARY","REVIEW"):
        raise ValueError("unsupported source or purpose")
    def term(text):
        return f'"{text}"[Title/Abstract]' if source=="PubMed" else f'TITLE_ABS:"{text}"'
    def group(value):
        return " AND ".join("("+" OR ".join(term(v) for v in unit)+")" for unit in _units(value))
    population=group(candidate.population)
    intervention=group(candidate.intervention_exposure_index_test)
    if not population or not intervention:
        return ""
    query=f"({population}) AND ({intervention})"
    if purpose=="REVIEW":
        query+=" AND ("+" OR ".join([term("systematic review"),term("meta-analysis"),
            'systematic[sb]' if source=="PubMed" else 'PUB_TYPE:"systematic review"',
            '"Meta-Analysis"[Publication Type]' if source=="PubMed" else 'PUB_TYPE:"meta-analysis"'])+")"
    return query
