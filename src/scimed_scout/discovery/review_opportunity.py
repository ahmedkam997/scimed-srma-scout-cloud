"""Source-linked update/correction triage, never an automatic scientific GO.

Adapted from Garner et al. BMJ 2016 i3507, Cochrane Handbook IV,
AHRQ surveillance methods, and AMSTAR 2 / ROBIS appraisal domains.
No model calls, fixed-age rejection, or artificial novelty bonus.
"""
from __future__ import annotations
import calendar
import re
from datetime import date
from urllib.parse import urlsplit

from .pico_matching import _groups
from .trial_family import registration_signals

VERSION = "UPDATE_CORRECTIVE_V1"
CUTOFF_FIELDS = ("last_search_date", "date_last_searched", "search_end_date", "date_of_last_search", "search_cutoff")
MATERIAL = {"HIGH", "ESSENTIALLY_IDENTICAL"}
MONTHS = {name.casefold(): i for i, name in enumerate(calendar.month_name) if i}
MONTHS.update({name.casefold(): i for i, name in enumerate(calendar.month_abbr) if i})
CORRECTION_CUES = (
    ("SEARCH_COVERAGE", re.compile(r"\b(?:we searched only|only searched|search was limited to)\s+(?:pubmed|medline|embase|scopus|web of science|one database)\b", re.I),
     "Check whether the restricted search omitted eligible studies and whether a broader search would change conclusions."),
    ("SELECTION_OR_EXTRACTION", re.compile(r"\b(?:a single reviewer|one reviewer|one author)\s+(?:independently\s+)?(?:screened|selected|extracted)\b", re.I),
     "Check whether independent checking was absent, identify consequential selection/extraction errors, and document a corrective plan."),
    ("SYNTHESIS", re.compile(r"\b(?:we (?:pooled|combined)|were pooled|were combined)\b[^.!?]{0,100}\b(?:randomized and nonrandomized|randomised and non-randomised)\b", re.I),
     "Check design eligibility, whether designs were analyzed separately, confounding and whether separate synthesis changes findings."),
)


def _payload(record):
    return record.get("payload") or {}


def _meta(record):
    meta = _payload(record).get("metadata")
    return meta if isinstance(meta, dict) else {}


def _ref(record):
    return {"source": str(record.get("source") or ""), "record_id": str(record.get("source_record_id") or ""),
            "title": str(record.get("title") or ""), "url": str(_payload(record).get("url") or ""),
            "doi": str(_payload(record).get("doi") or "")}


def date_bounds(value):
    """Return inclusive interval for explicitly reported year/month/day.

    Ambiguous slash dates are not guessed. A later interval must start
    strictly after the cutoff interval ends to count as definitely later.
    """
    text = str(value or "").strip().rstrip(".")
    m = re.fullmatch(r"((?:19|20)\d{2})(?:-(\d{2})(?:-(\d{2}))?)?", text)
    if not m:
        named = re.fullmatch(r"(?:(\d{1,2})\s+)?([A-Za-z]+)\s+((?:19|20)\d{2})", text)
        rev = re.fullmatch(r"((?:19|20)\d{2})\s+([A-Za-z]+)(?:\s+(\d{1,2}))?", text)
        if named and named[2].casefold() in MONTHS:
            y, mo, day = int(named[3]), MONTHS[named[2].casefold()], int(named[1]) if named[1] else None
        elif rev and rev[2].casefold() in MONTHS:
            y, mo, day = int(rev[1]), MONTHS[rev[2].casefold()], int(rev[3]) if rev[3] else None
        else:
            return None
    else:
        y, mo, day = int(m[1]), int(m[2]) if m[2] else None, int(m[3]) if m[3] else None
    try:
        if y > date.today().year:
            return None
        if mo is None:
            return date(y, 1, 1), date(y, 12, 31)
        if day is None:
            return date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1])
        exact = date(y, mo, day)
        return exact, exact
    except ValueError:
        return None


def _http(url):
    try:
        parsed = urlsplit(str(url or ""))
        return parsed.scheme in ("https", "http") and bool(parsed.hostname)
    except ValueError:
        return False


def _cutoff(record):
    meta = _meta(record)
    raw = next((meta.get(key) for key in CUTOFF_FIELDS if meta.get(key)), None)
    bounds = date_bounds(raw)
    quote = str(meta.get("search_date_evidence_quote") or "").strip()
    url = str(meta.get("search_date_evidence_url") or "").strip()
    level = str(meta.get("search_date_evidence_level") or "")
    pub_year = date_bounds(_payload(record).get("year"))
    if not bounds or bounds[0] > date.today() or (pub_year and bounds[0] > pub_year[1]):
        return None
    # Do not substitute publication dates, bare metadata fields, or inferred
    # dates for a traceable original search statement.
    if not quote or not _http(url) or not level or not re.search(r"\b(?:search|searched|searches|searching)\b", quote, re.I):
        return None
    if str(raw).casefold() not in quote.casefold():
        return None
    return {"reported_date": str(raw), "start": bounds[0].isoformat(), "end": bounds[1].isoformat(),
            "evidence_quote": quote[:300], "evidence_url": url, "evidence_level": level}


def _material(record):
    assessment = _payload(record).get("discovery_semantic_assessment") or {}
    try:
        confidence = float(assessment.get("confidence") or 0)
    except (ValueError, TypeError):
        confidence = 0
    dims = {x.get("name") for x in assessment.get("dimensions", []) if isinstance(x, dict)
            and str(x.get("evidence") or "").strip()}
    return (assessment.get("overall_overlap") in MATERIAL and not assessment.get("unresolved")
            and confidence >= 0.8 and len(dims) >= 4)


def _publication_bounds(record):
    meta = _meta(record)
    # Earliest known publication date is conservative for online-first/print
    # duplicates. Do not use database indexing dates as publication dates.
    fields = ("firstPublicationDate", "electronicPublicationDate", "epubdate", "pubdate", "publication_date", "publicationDate")
    found = [date_bounds(meta.get(k)) for k in fields]
    found = [x for x in found if x]
    if found:
        return min(found, key=lambda x: (x[0], x[1]))
    return date_bounds(_payload(record).get("year"))


def _correction_cues(records):
    out, seen = [], set()
    for record in records:
        for field in ("abstractText", "abstract", "summary"):
            body = _meta(record).get(field)
            if not isinstance(body, str):
                continue
            for domain, pattern, action in CORRECTION_CUES:
                for m in pattern.finditer(body):
                    ref = _ref(record)
                    if not (_http(ref["url"]) or ref["doi"]):
                        continue
                    quote = body[max(0, m.start()-30):min(len(body), m.end()+60)]
                    key = (domain, quote.casefold())
                    if key not in seen:
                        seen.add(key)
                        out.append({**ref, "domain": domain, "source_field": field, "excerpt": quote,
                                    "status": "METHODS_CUE_NOT_VERIFIED_FLAW", "next_action": action})
    return out[:12]


def assess_review_opportunity(reviews, pico_records, primary_records, *, coverage_complete, registrations_unresolved=False, competitor_scope_unresolved=False):
    """Return separately labeled opportunities; no changes to novelty scores.

    A newer report on an older registered family is a follow-up signal, not
    a new trial. Even apparently newer families need full-text and review
    inclusion-list checks. Unknown dates/IDs never prove study independence.
    """
    groups = _groups(reviews)
    material = [g["records"] for g in groups if any(_material(r) for r in g["records"])]
    related = []
    for group in material:
        candidates = [x for r in group if (x := _cutoff(r))]
        # Use the latest source-backed cutoff across versions and databases.
        chosen = max(candidates, key=lambda x: x["end"]) if candidates else None
        related.append({**_ref(next(r for r in group if _material(r))), "cutoff": chosen,
                        "cutoff_versions": candidates})
    missing = sum(row["cutoff"] is None for row in related)
    baseline = max((row["cutoff"]["end"] for row in related if row["cutoff"]), default=None)
    baseline = baseline if not missing else None
    newer, followup, unknown, unlinked = [], [], [], []
    if baseline:
        cutoff = date.fromisoformat(baseline)
        # Use all primary records, not only PICO hits, to detect known earlier
        # family publications. They are not included or eligible studies.
        earlier_ids, uncertain_ids = set(), set()
        # Combine the PICO-prioritized representatives with ALL raw source
        # variants before comparing dates. A later print date must not
        # transform an already-published online-first report into new evidence.
        pico_object_ids = {id(r) for r in pico_records}
        report_groups = _groups([*primary_records, *pico_records])
        def group_bounds(rows):
            dates = [_publication_bounds(r) for r in rows]
            dates = [d for d in dates if d and d[0] <= date.today()]
            return min(dates, key=lambda x: (x[0], x[1])) if dates else None
        for group in report_groups:
            rows = group["records"]
            bounds = group_bounds(rows)
            ids = {i for r in rows for i in registration_signals(r)}
            if len(ids) != 1 or not bounds or bounds[0] <= cutoff < bounds[1]:
                uncertain_ids |= ids
            elif bounds[1] <= cutoff:
                earlier_ids |= ids
        for group in report_groups:
            rows = group["records"]
            matched = [r for r in rows if id(r) in pico_object_ids]
            if not matched:
                continue
            bounds = group_bounds(rows)
            dates = [bounds] if bounds else []
            ids = sorted({i for r in rows for i in registration_signals(r)})
            row = {**_ref(matched[0]), "registration_ids": ids}
            if not dates:
                unknown.append({**row, "reason": "PUBLICATION_DATE_UNKNOWN"})
                continue
            bounds = min(dates, key=lambda x: (x[0], x[1]))
            row["publication_date_interval"] = [d.isoformat() for d in bounds]
            if bounds[0] <= cutoff:
                if bounds[1] > cutoff:
                    unknown.append({**row, "reason": "DATE_INTERVAL_OVERLAPS_CUTOFF"})
                continue
            if len(ids) > 1:
                unknown.append({**row, "reason": "MULTIPLE_REGISTRATION_IDS"})
            elif not ids:
                unlinked.append({**row, "reason": "POST_CUTOFF_REPORT_NO_FAMILY_ID"})
            elif ids[0] in earlier_ids:
                followup.append({**row, "reason": "REGISTERED_FAMILY_HAS_EARLIER_REPORT"})
            elif ids[0] in uncertain_ids:
                unknown.append({**row, "reason": "EARLIER_FAMILY_CHRONOLOGY_UNRESOLVED"})
            else:
                newer.append({**row, "reason": "POST_CUTOFF_FAMILY_LEAD_NOT_CONFIRMED_NEW_TRIAL"})
    family_ids = sorted({r["registration_ids"][0] for r in newer})
    correction = _correction_cues([r for group in material for r in group])
    update_signal = bool(baseline and (newer or followup or unlinked))
    if not related:
        route = "OVERLAP_NEEDS_ADJUDICATION" if competitor_scope_unresolved else "NOVEL_REVIEW_ASSESSMENT"
    elif update_signal and correction:
        route = "UPDATE_AND_CORRECTIVE_SIGNAL"
    elif update_signal:
        route = "UPDATE_SIGNAL"
    elif correction:
        route = "CORRECTIVE_SIGNAL"
    elif not baseline or unknown or competitor_scope_unresolved:
        route = "OVERLAP_NEEDS_ADJUDICATION"
    else:
        route = "OVERLAP_NO_POST_CUTOFF_SIGNAL"
    return {"method_version": VERSION, "route": route, "material_review_count": len(related),
            "material_reviews": related[:30], "latest_source_linked_cutoff_end": baseline,
            "missing_material_review_cutoffs": missing, "source_coverage_complete": bool(coverage_complete),
            "registration_overlap_unresolved": bool(registrations_unresolved),
            "competitor_scope_unresolved": bool(competitor_scope_unresolved),
            "post_cutoff_registered_family_leads": len(family_ids), "family_ids": family_ids,
            "post_cutoff_family_report_examples": newer[:12],
            "post_cutoff_known_family_followup_count": len(followup), "followup_examples": followup[:12],
            "post_cutoff_unlinked_report_count": len(unlinked), "unlinked_examples": unlinked[:12],
            "uncertain_chronology_or_linkage_count": len(unknown), "uncertain_examples": unknown[:12],
            "correction_method_cues": correction,
            "corrective_review_checklist": ["Eligibility and clinical scope", "Search and study selection",
                "Data extraction and risk of bias", "Synthesis, dependency and interpretation"] if related else [],
            "confirmed_new_independent_eligible_studies": None, "verified_material_methodological_flaws": None,
            "clinical_impact_confirmed": False, "qualified": False,
            "next_action": "Check latest competing reviews and registrations; verify original search methods and included studies; assess eligibility, comparison-level independence, outcomes and potential change in conclusions. For correction, verify a consequential flaw in full text and specify a reproducible repair. Consider author correction versus a new review.",
            "limitations": "A source-linked cutoff is an extraction cue, not independent adjudication. Publication after cutoff does not establish novelty, new independent trials or sufficient evidence. No age rule or novelty bonus."}
