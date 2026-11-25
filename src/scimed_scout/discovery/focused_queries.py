"""Bounded P+I search for paired discovery diagnostics, not a systematic search."""
from __future__ import annotations
import re
import unicodedata
from scimed_scout.verification.queries import _registry_focus

# Reuse existing clinical token normalization, with limited explicit aliases.
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
    "hypertensive": ("hypertensive","hypertension"),
}
NOISE={"categories","category","post","pre","chronic","diagnosed","inpatients","outpatients"}
# 'chronic' is retained within known multiword clinical aliases.
def _units(value):
    raw=unicodedata.normalize("NFKC",str(value or ""))
    raw=re.sub(r"[\u2010-\u2015/]", " ",raw)
    raw=re.sub(r"[^a-zA-Z0-9 ]"," ",raw)
    terms=_registry_focus(raw)
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
            '"Systematic Review"[Publication Type]' if source=="PubMed" else 'PUB_TYPE:"systematic review"',
            '"Meta-Analysis"[Publication Type]' if source=="PubMed" else 'PUB_TYPE:"meta-analysis"'])+")"
    return query
