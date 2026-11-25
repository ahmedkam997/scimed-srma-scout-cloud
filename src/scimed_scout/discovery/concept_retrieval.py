"""Experimental, evidence-linked concept retrieval; no eligibility decisions.

Curated descriptors verified against 2026 NLM MeSH. Broad anchors are discovery
terms, not replacements for the clinical population or intervention.
"""
from dataclasses import dataclass
from .query_optimizer import normalize, _contains, _dedup, _review_suffix, optimized_queries

@dataclass(frozen=True)
class Anchor:
    aliases: tuple[str,...]
    terms: tuple[str,...]
    mesh: str
    ui: str

ANCHORS=(
    Anchor(("ischemic stroke","ischaemic stroke","acute ischemic stroke","acute ischaemic stroke"),
           ("ischemic stroke","ischaemic stroke","cerebral infarction","stroke"),"Ischemic Stroke","D000083242"),
    Anchor(("endovascular thrombectomy","mechanical thrombectomy"),
           ("thrombectomy","endovascular therapy","endovascular treatment","endovascular intervention","endovascular thrombectomy","mechanical thrombectomy"),"Thrombectomy","D017131"),
    Anchor(("acute kidney injury","acute renal failure"),
           ("acute kidney injury","acute renal failure","AKI"),"Acute Kidney Injury","D058186"),
    Anchor(("renal replacement therapy","kidney replacement therapy"),
           ("renal replacement therapy","kidney replacement therapy","renal dialysis","RRT","KRT"),"Renal Replacement Therapy","D017582"),
    Anchor(("type 1 diabetes","type 1 diabetes mellitus","diabetes mellitus type 1"),
           ("type 1 diabetes","type 1 diabetes mellitus","T1D","T1DM","insulin dependent diabetes"),"Diabetes Mellitus, Type 1","D003922"),
    Anchor(("continuous glucose monitoring","continuous glucose monitor"),
           ("continuous glucose monitoring","continuous glucose monitor","CGM","glucose sensor"),"Continuous Glucose Monitoring","D000095583"),
)
# An inclusive experimental design cue, not a validated RCT filter. A second
# unfiltered P+I search is preserved to avoid losing unindexed publications.
RCT='(randomized controlled trial[pt] OR controlled clinical trial[pt] OR randomized[tiab] OR randomised[tiab] OR randomly[tiab] OR placebo[tiab] OR trial[tiab])'

def match(value):
    import re
    text=normalize(value)
    if re.search(r"\b(?:or|without|not|except|excluding)\b",text):return None
    matches=[a for a in ANCHORS if any(_contains(text,normalize(x)) for x in a.aliases)]
    return matches[0] if len(matches)==1 else None

def group(a):
    return "("+" OR ".join([f'"{x}"[Title/Abstract]' for x in a.terms]+[f'"{a.mesh}"[MeSH Terms]'])+")"

def experimental_queries(candidate,purpose,legacy,*,max_queries=2):
    old=optimized_queries(candidate,"PubMed",purpose,legacy,max_queries=max_queries)
    p=match(candidate.population);i=match(candidate.intervention_exposure_index_test)
    if not p or not i or p==i or purpose not in ("PRIMARY","REVIEW") or max_queries<2:return old
    pair=group(p)+" AND "+group(i)
    if purpose=="PRIMARY":
        proposed=(pair+" AND "+RCT,pair)
    else:
        # Do not drop the original focused review query; broader review cues
        # are discovery leads for subsequent PICO adjudication.
        proposed=(pair+_review_suffix("PubMed"),old[0] if old else "")
    return _dedup((*proposed,*old))[:max_queries]
