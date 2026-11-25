"""Explainable, deliberately conservative bibliographic PICO triage.

This is an unvalidated prioritization aid, not an eligibility classifier.
Missing terms are UNKNOWN, not exclusion. Every report stays in the ledger.
Only positive population + intervention + compatible design signals support
the discovery feasibility gate; comparator/outcome cues are reported separately.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

from .trial_family import audit_trial_families, registration_signals

VERSION = "PICO_SIGNAL_V1"
STOP = set("a an and or the of in on for with without to by from patients patient adults adult people participants subjects women men individuals population clinical study studies trial trials treatment treatments therapy therapies intervention interventions effect effects efficacy effectiveness use using evaluation assessment suspected diagnosed versus vs comparison outcomes outcome standard care group groups".split())
ALIASES = (
    (r"\b(?:heart failure with preserved ejection fraction|hfpef)\b", "hfpef"),
    (r"\b(?:heart failure with reduced ejection fraction|hfref)\b", "hfref"),
    (r"\b(?:transcatheter aortic valve (?:replacement|implantation)|tavr|tavi)\b", "tavr"),
    (r"\b(?:coronary artery bypass graft(?:ing)?|cabg)\b", "cabg"),
    (r"\b(?:atrial fibrillation|afib)\b", "atrial fibrillation"),
    (r"\b(?:sodium glucose cotransporter 2|sglt 2|sglt2)\b", "sglt2"),
    (r"\b(?:dipeptidyl peptidase 4|dpp 4|dpp4)\b", "dpp4"),
    (r"\b(?:computed tomography fractional flow reserve|ct derived fractional flow reserve|ffr ct|ct ffr|ffrct|ctffr)\b", "ctffr"),
    (r"\b(?:chronic obstructive pulmonary disease|copd)\b", "copd"),
    (r"\b(?:acute kidney injury|aki)\b", "aki"),
    (r"\b(?:myocardial infarction|heart attack)\b", "myocardial infarction"),
    (r"\b(?:end stage renal disease|esrd|eskd|end stage kidney disease)\b", "eskd"),
)
RCT = re.compile(r"\b(?:randomi[sz]ed (?:controlled |clinical |parallel |crossover )?(?:trial|study)|randomi[sz]ed to|randomly (?:assigned|allocated)|random allocation|randomized controlled trial|rct)\b", re.I)
OBS = re.compile(r"\b(?:retrospective (?:cohort|observational|study)|observational (?:cohort|study)|nonrandomi[sz]ed|non randomi[sz]ed|case[ -]control|cross[ -]sectional|cohort study)\b", re.I)
DTA = re.compile(r"\b(?:diagnostic accuracy|diagnostic performance|sensitivity and specificity|reference standard|receiver operating characteristic)\b", re.I)
NONPRIMARY = re.compile(r"\b(?:systematic review|meta[ -]analysis|scoping review|narrative review|study protocol|trial protocol|protocol for|editorial|erratum|commentary|case report|in vitro|animal model)\b", re.I)
PROTOCOL_TYPE = re.compile(r"\b(?:review|meta-analysis|editorial|comment|letter|published erratum|study protocol|clinical trial protocol)\b", re.I)
NEGATED_RCT = re.compile(r"\b(?:non[ -]?randomi[sz]ed|not randomi[sz]ed|without randomi[sz]ation)\b", re.I)
BACKGROUND = re.compile(r"^(?:background|introduction|rationale)\s*[:：]", re.I)


def _normalize(text):
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    for pattern, replacement in ALIASES:
        text = re.sub(pattern, replacement, text)
    return text


def _terms(text):
    return {x for x in _normalize(text).split() if len(x) >= 2 and x not in STOP}


def _strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [s for item in value for s in _strings(item)]
    return []


def _metadata(record):
    payload = record.get("payload") or {}
    meta = payload.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _doi(record):
    payload = record.get("payload") or {}
    meta = _metadata(record)
    doi = payload.get("doi") or meta.get("doi") or ""
    external = meta.get("externalIds")
    if not doi and isinstance(external, dict):
        doi = external.get("DOI") or external.get("doi") or ""
    return str(doi).strip().casefold().removeprefix("https://doi.org/").removeprefix("http://doi.org/").removeprefix("doi:").rstrip(".")


def _pmid(record):
    meta = _metadata(record)
    payload = record.get("payload") or {}
    value = meta.get("pmid") or payload.get("pmid") or ""
    if not value and str(record.get("source")) == "PubMed":
        value = record.get("source_record_id") or ""
    if not value and isinstance(meta.get("externalIds"), dict):
        value = meta["externalIds"].get("PubMed") or ""
    return str(value) if str(value).isdigit() else ""


def _groups(records):
    """Merge only report-level identifiers, never clinical family aliases.
    Conflicting DOI/PMID prevents a title-only merge. Retain source variants.
    """
    groups = []
    for record in records:
        doi, pmid = _doi(record), _pmid(record)
        title = re.sub(r"[^a-z0-9]+", " ", str(record.get("title") or "").casefold()).strip()
        hits = []
        for group in groups:
            if (doi and group["dois"] and doi not in group["dois"]) or (pmid and group["pmids"] and pmid not in group["pmids"]):
                continue
            if (doi and doi in group["dois"]) or (pmid and pmid in group["pmids"]) or (title and title in group["titles"]):
                hits.append(group)
        # An ambiguous bridge must not join distinct records.
        group = hits[0] if len(hits) == 1 else None
        if group is None:
            group = {"dois": set(), "pmids": set(), "titles": set(), "records": []}
            groups.append(group)
        if doi:
            group["dois"].add(doi)
        if pmid:
            group["pmids"].add(pmid)
        if title:
            group["titles"].add(title)
        group["records"].append(record)
    return groups


def _passages(records):
    passages, types = [], []
    for record in records:
        meta = _metadata(record)
        source = str(record.get("source") or "")
        rid = str(record.get("source_record_id") or "")
        title = str(record.get("title") or "").strip()
        if title:
            passages.append(("title", source, rid, title))
        for key in ("abstractText", "abstract", "summary"):
            for abstract in _strings(meta.get(key)):
                # Use full retrieved abstract, splitting into bounded excerpts.
                for sentence in re.split(r"(?<=[.!?])\s+|\n+", abstract):
                    if sentence.strip():
                        passages.append((key, source, rid, sentence.strip()))
        for key in ("publicationTypes", "pubtype", "publication_types", "pubType", "type", "type_crossref"):
            value = meta.get(key)
            if isinstance(value, dict):
                value = value.get("pubType") or value.get("publicationType") or []
            for item in _strings(value):
                types.append((key, source, rid, item))
    return passages, types


def _cue(passage, matched):
    field, source, rid, quote = passage
    return {"field": field, "source": source, "record_id": rid,
            "excerpt": quote[:360], "matched_terms": sorted(matched)}


def _dimension(target, passages):
    terms = _terms(target)
    if not terms:
        return {"status": "NOT_SPECIFIED", "matched_terms": [], "evidence": []}
    seen = set()
    evidence = []
    for passage in passages:
        hit = _terms(passage[3]) & terms
        if hit:
            seen |= hit
            if len(evidence) < 3:
                evidence.append(_cue(passage, hit))
    # For brief concepts, require all discriminating terms; for long
    # concepts require a majority. Never equate a missing term with exclusion.
    required = len(terms) if len(terms) <= 3 else max(2, (len(terms)*2 + 2)//3)
    return {"status": "POSITIVE_CUE" if len(seen) >= required else "PARTIAL_CUE" if seen else "UNKNOWN",
            "matched_terms": sorted(seen), "target_terms": sorted(terms), "evidence": evidence}


def _design(candidate, passages, types):
    labels = " ".join(candidate.eligible_designs or []).casefold()
    # Only require RCT signals for an explicit RCT-only scope. Mixed RCT/
    # observational questions must not be silently narrowed.
    rct_requested = bool(re.search(r"\b(?:rcts?|randomi[sz]ed)\b", labels))
    obs_requested = bool(re.search(r"\b(?:observational|cohort|case.control|cross.sectional|nonrandomi[sz]ed|non.randomi[sz]ed|quasi.experimental)\b", labels))
    dta_requested = "diagnostic" in labels or str(candidate.question_type).upper() == "DIAGNOSTIC_ACCURACY"
    nonprimary = [p for p in passages if p[0] == "title" and NONPRIMARY.search(p[3])]
    nonprimary += [p for p in types if PROTOCOL_TYPE.search(p[3])]
    rct = [p for p in passages + types if not BACKGROUND.search(p[3]) and RCT.search(p[3]) and not NEGATED_RCT.search(p[3])]
    obs = [p for p in passages if p[0] == "title" and OBS.search(p[3])]
    obs += [p for p in types if OBS.search(p[3])]
    dta = [p for p in passages if not BACKGROUND.search(p[3]) and DTA.search(p[3])]
    if nonprimary:
        return {"status":"NONPRIMARY_OR_PROTOCOL_CUE","evidence":[_cue(p,[]) for p in nonprimary[:3]]}
    if rct_requested and not obs_requested:
        compatible = rct
        conflicting = obs
    elif dta_requested:
        compatible = dta
        conflicting = []
    elif rct_requested or obs_requested:
        compatible = (rct if rct_requested else []) + (obs if obs_requested else [])
        conflicting = []
    else:
        # Unsupported designs are left unknown; this is not a general-purpose
        # validated study-design classifier.
        compatible = []
        conflicting = []
    status = ("CONFLICTING_CUES" if conflicting and compatible else
              "DESIGN_MISMATCH_CUE" if conflicting else
              "COMPATIBLE_DESIGN_CUE" if compatible else "UNKNOWN")
    return {"status":status,"evidence":[_cue(p,[]) for p in (compatible + conflicting)[:3]]}


def assess_pico(candidate, records):
    rows, plausible_records = [], []
    for group in _groups(records):
        variants = group["records"]
        passages, types = _passages(variants)
        dims = {
            "population": _dimension(candidate.population, passages),
            "intervention_or_index": _dimension(candidate.intervention_exposure_index_test, passages),
            "comparator_or_reference": _dimension(candidate.comparator_reference, passages),
            "outcomes": _dimension(" ".join(candidate.outcomes or []), passages),
            "design": _design(candidate, passages, types),
        }
        design = dims["design"]["status"]
        if design in {"NONPRIMARY_OR_PROTOCOL_CUE", "DESIGN_MISMATCH_CUE", "CONFLICTING_CUES"}:
            status = "MANUAL_CONFLICT_CHECK"
        elif all(dims[k]["status"] == "POSITIVE_CUE" for k in ("population","intervention_or_index")) and design == "COMPATIBLE_DESIGN_CUE":
            status = "PICO_DESIGN_LEAD"
        else:
            status = "INSUFFICIENT_BIBLIOGRAPHIC_SIGNAL"
        rep = max(variants, key=lambda x: (bool(_metadata(x).get("abstractText") or _metadata(x).get("abstract")), len(str(x.get("title") or ""))))
        if status == "PICO_DESIGN_LEAD":
            # Preserve the registration signals from duplicate source versions,
            # including ambiguities. No cross-report linkage via generic text.
            ids = sorted({i for item in variants for i in registration_signals(item)})
            payload = dict(rep.get("payload") or {})
            meta = dict(_metadata(rep))
            meta["trial_registration_ids"] = ids
            payload["metadata"] = meta
            plausible_records.append({**rep, "payload":payload})
        rows.append({"title":str(rep.get("title") or ""), "source":str(rep.get("source") or ""),
                     "record_id":str(rep.get("source_record_id") or ""),
                     "url":str((rep.get("payload") or {}).get("url") or ""),
                     "doi":_doi(rep),"status":status,"dimensions":dims,
                     "source_variants":[{"source":str(v.get("source") or ""),"record_id":str(v.get("source_record_id") or "")} for v in variants],
                     "fulltext_eligibility":"NOT_CHECKED","independence":"NOT_CONFIRMED"})
    families = audit_trial_families(plausible_records)
    # Ambiguous multi-registry reports remain visible but cannot support
    # the minimum study-lead count.
    supported = families["conservative_family_lead_count"] - len(families["ambiguous_reports"])
    counts = Counter(row["status"] for row in rows)
    rows.sort(key=lambda row: (row["status"] != "PICO_DESIGN_LEAD",row["status"] != "MANUAL_CONFLICT_CHECK",row["title"].casefold()))
    return ({"method_version":VERSION,"validated_classifier":False,
             "distinct_reports_assessed":len(rows),"status_counts":dict(counts),
             "pico_design_report_leads":len(plausible_records),
             "pico_design_family_leads":supported,
             "ambiguous_registry_leads":len(families["ambiguous_reports"]),
             "confirmed_independent_eligible_studies":None,
             "rows":rows[:40],"rows_truncated":len(rows)>40,
             "limitations":"Positive citation cues do not establish PICO eligibility, comparison arms, extractable outcomes or independence. Missing cues never exclude a record; all raw records are retained. Unsupported designs and unknown synonyms require manual assessment."},
            plausible_records)
