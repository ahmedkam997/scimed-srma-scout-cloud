"""Source-specific bounded exploratory search optimization.

Curated clinical anchors are retrieval aids, NOT eligibility criteria.
No generated MeSH headings, automatic exclusions, or negative novelty claims.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
import unicodedata
from .focused_queries import focused_query

VERSION="CLINICAL_QUERY_OPTIMIZER_V1"

@dataclass(frozen=True)
class Concept:
    aliases: tuple[str,...]
    mesh: str=""
    mesh_id: str=""

# Verified NLM descriptors. More specific HF subtypes stay separate; broad
# Heart Failure heading is never substituted for a subtype in the focused plan.
CONCEPTS=(
    Concept(("heart failure with preserved ejection fraction","HFpEF"),),
    Concept(("heart failure with reduced ejection fraction","HFrEF"),),
    Concept(("heart failure","cardiac failure"),"Heart Failure","D006333"),
    Concept(("chronic coronary syndrome","chronic coronary syndromes","stable coronary artery disease"),),
    Concept(("coronary artery disease","coronary heart disease"),"Coronary Artery Disease","D003324"),
    Concept(("myocardial infarction","heart attack"),"Myocardial Infarction","D009203"),
    Concept(("body mass index","bmi"),"Body Mass Index","D015992"),
    Concept(("colchicine",),"Colchicine","D003078"),
    Concept(("sodium glucose transporter 2 inhibitors","sodium glucose cotransporter 2 inhibitors","sglt2 inhibitors","sglt 2 inhibitors","sglt2 inhibitor","sglt 2 inhibitor","gliflozins"),"Sodium-Glucose Transporter 2 Inhibitors","D000077203"),
    Concept(("empagliflozin",)),
    Concept(("dapagliflozin",)),
    Concept(("canagliflozin",)),
    Concept(("ertugliflozin",)),
    Concept(("high intensity interval training","hiit"),),
    Concept(("atrial fibrillation",)),
    Concept(("transcatheter aortic valve replacement","transcatheter aortic valve implantation","tavr","tavi")),
    Concept(("coronary artery bypass grafting","coronary artery bypass graft","cabg")),
    Concept(("fractional flow reserve","ffr")),
    Concept(("left atrial appendage occlusion","left atrial appendage closure")),
)
def normalize(value):
    return " ".join(re.findall(r"[a-z0-9]+",unicodedata.normalize("NFKC",str(value or "")).casefold()))

def _contains(value,phrase):
    return (" "+phrase+" ") in (" "+value+" ")

def _concept(value):
    text=normalize(value)
    if not text or re.search(r"\b(?:or|without|not|except|excluding)\b",text):
        return None
    # The longest explicit phrase wins only if all other matched phrases
    # are contained within it. Multiple distinct concepts remain ambiguous.
    hits=[]
    for c in CONCEPTS:
        for alias in c.aliases:
            if _contains(text,normalize(alias)):
                hits.append((normalize(alias),c))
    if not hits:return None
    hits.sort(key=lambda x:-len(x[0]))
    phrase,concept=hits[0]
    if any(c!=concept and not _contains(phrase,a) for a,c in hits[1:]):
        return None
    # Avoid claiming preserved/reduced EF equivalence for text that contains
    # a broad HF anchor plus a different subtype modifier.
    if concept.mesh=="Heart Failure" and re.search(r"\b(?:preserved|reduced|mildly|midrange|mid range)\b",text):
        return None
    return concept

def _expanded_group(value,source):
    c=_concept(value)
    if not c:return ""
    if source=="PubMed":
        terms=[f'"{x}"[Title/Abstract]' for x in c.aliases]
        if c.mesh:terms.append(f'"{c.mesh}"[MeSH Terms]')
    else:
        # Europe PMC title/abstract syntax, not PubMed field tags.
        terms=[f'TITLE_ABS:"{x}"' for x in c.aliases]
    return "("+" OR ".join(terms)+")"

def _review_suffix(source):
    if source=="PubMed":
        return ' AND ("Systematic Review"[Publication Type] OR "Meta-Analysis"[Publication Type] OR "systematic review"[Title/Abstract] OR "meta-analysis"[Title/Abstract])'
    return ' AND (PUB_TYPE:"systematic review" OR PUB_TYPE:"meta-analysis" OR TITLE_ABS:"systematic review" OR TITLE_ABS:"meta-analysis")'

def _dedup(items):
    return tuple(dict.fromkeys(x for x in items if x))

def optimized_queries(candidate,source,purpose,legacy,*,max_queries=4):
    """Keep the legacy budget; add precise P+I and controlled vocabulary variants.

    Preserve one broader legacy pair if possible, rather than require outcome
    or comparator terms in every search. Complex disjunctions stay on legacy
    queries until a proper semantic parser exists.
    """
    cap=max(1,min(4,int(max_queries)))
    old=_dedup(legacy)
    if source not in ("PubMed","Europe PMC") or purpose not in ("PRIMARY","REVIEW"):
        return old[:cap]
    text=normalize(candidate.population)+" "+normalize(candidate.intervention_exposure_index_test)
    if re.search(r"\b(?:or|without|not|except|excluding)\b",text):
        return old[:cap]
    precise=focused_query(candidate,source,purpose)
    p=_expanded_group(candidate.population,source)
    i=_expanded_group(candidate.intervention_exposure_index_test,source)
    expanded=p+" AND "+i if p and i else ""
    if expanded and purpose=="REVIEW":
        expanded+=_review_suffix(source)
    # Prioritize an actual P+I legacy pair (third primary variant in existing
    # planner) over isolated AI keywords if controlled expansion is unknown.
    legacy_pair=next((q for q in old if q.casefold().startswith(candidate.intervention_exposure_index_test.strip().casefold()+" ") and normalize(candidate.population) in normalize(q)),"")
    if not legacy_pair and purpose=="PRIMARY":
        # A plain-text pair retains automatic term mapping on PubMed.
        from scimed_scout.verification.queries import _compact,_join
        legacy_pair=_join(_compact(candidate.intervention_exposure_index_test,66),_compact(candidate.population,56))
        if not candidate.population.strip() or not candidate.intervention_exposure_index_test.strip():legacy_pair=""
    if purpose=="REVIEW":
        legacy_pair=old[0] if old else ""
    return _dedup((expanded,precise,legacy_pair,*old))[:cap]

def sample_quality(result):
    """Coverage of a bounded sample, not an estimate of clinical recall."""
    total=result.total_count
    records=list(result.records or [])
    usable=sum(bool(str(r.title or "").strip()) for r in records)
    abstracts=sum(bool((r.metadata or {}).get("abstract") or (r.metadata or {}).get("abstractText")) for r in records)
    return {"reported_count":total,"retrieved_count":len(records),"records_with_title":usable,
            "records_with_abstract":abstracts,
            "sample_status":"ACCESS_UNRESOLVED" if result.status.value not in ("SEARCHED_POSITIVE","SEARCHED_NEGATIVE") else
            "ZERO_QUERY_HITS_NOT_ZERO_EVIDENCE" if total==0 else "METADATA_INCOMPLETE" if usable==0 else
            "BROAD_BOUNDED_SAMPLE" if isinstance(total,int) and total>max(100,20*len(records)) else "BOUNDED_SAMPLE",
            "eligibility_verified":False,"novelty_verified":False}
