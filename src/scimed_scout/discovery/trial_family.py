"""Conservative registry-linked report families, not eligibility adjudication.

Explicit identifiers are evidence of a registration relationship, not proof
of identical arms, randomization cohorts, or non-overlapping participants.
No fuzzy title/acronym-only merges or unrestricted abstract ID harvesting.
"""
from __future__ import annotations

import re
from typing import Any

ID_PATTERN = re.compile(r"\b(?:NCT\s*\d{8}|ISRCTN\s*\d{8}|ACTRN\s*\d{14}|ChiCTR(?:-[A-Z]+-)?\d{8,11}|DRKS\s*\d{8}|UMIN\s*\d{9})\b", re.I)
FIELDS = ("trial_registration_id", "trial_registration_ids", "registration_number",
          "registration_numbers", "clinicalTrialNumber", "clinicalTrialNumbers",
          "clinical_trial_number", "clinical_trial_numbers", "nct_id", "nctId",
          "isrctn", "secondarySourceId", "secondarySourceIds", "secondary_source_ids",
          "accessionNumberList", "clinicalTrialList")
REGISTRATION_CONTEXT = re.compile(
    r"(?:trial registration(?: number)?|clinicaltrials\.gov(?: identifier| number)?|"
    r"registered (?:at|with|in)|registration number|trial identifier|"
    r"this (?:study|trial) (?:is|was) registered)\s*[:;,()\s]*(?:https?://clinicaltrials\.gov/(?:study/|ct2/show/))?"
    r"((?:NCT\s*\d{8}|ISRCTN\s*\d{8}|ACTRN\s*\d{14}|DRKS\s*\d{8}|UMIN\s*\d{9}))", re.I)


def _ids(value):
    if isinstance(value, str):
        return {re.sub(r"\s+", "", m.group(0)).upper() for m in ID_PATTERN.finditer(value)}
    if isinstance(value, (list, tuple)):
        return set().union(*(_ids(x) for x in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(_ids(x) for x in value.values())) if value else set()
    return set()


def registration_signals(record):
    payload = record.get("payload") or {}
    meta = payload.get("metadata") or {}
    signals = {}
    for container in (payload, meta):
        if not isinstance(container, dict):
            continue
        for field in FIELDS:
            for identifier in _ids(container.get(field)):
                signals.setdefault(identifier, []).append("structured:" + field)
    if isinstance(meta, dict):
        for field in ("abstract", "abstractText", "summary"):
            text = meta.get(field)
            if isinstance(text, str):
                for m in REGISTRATION_CONTEXT.finditer(text):
                    for identifier in _ids(m.group(1)):
                        signals.setdefault(identifier, []).append("registration_context:" + field)
    return {k: sorted(set(v)) for k, v in sorted(signals.items())}


def audit_trial_families(records):
    """Pass DISTINCT publication leads (not raw duplicate database records).

    Multiple IDs are ambiguous and never bridge two registry clusters.
    Unlinked reports stay visible as unknown, not confirmed independent.
    Comparisons are preserved only if explicit, not guessed from wording.
    """
    groups = {}
    unlinked = []
    ambiguous = []
    for i, record in enumerate(records):
        payload = record.get("payload") or {}
        meta = payload.get("metadata") or {}
        signals = registration_signals(record)
        entry = {"report_id": str(record.get("source_record_id") or i),
                 "source": str(record.get("source") or ""),
                 "title": str(record.get("title") or ""),
                 "url": str(payload.get("url") or ""),
                 "registration_signals": signals,
                 "comparison": str(meta.get("comparison") or meta.get("comparison_label") or "") if isinstance(meta, dict) else ""}
        if len(signals) == 1:
            identifier = next(iter(signals))
            groups.setdefault(identifier, []).append(entry)
        elif len(signals) > 1:
            ambiguous.append(entry)
        else:
            unlinked.append(entry)
    families = []
    for identifier, reports in sorted(groups.items()):
        comparisons = sorted({r["comparison"].strip() for r in reports if r["comparison"].strip()})
        families.append({"registration_id": identifier, "reports": reports,
                         "explicit_comparisons": comparisons,
                         "comparison_resolution": "MULTIPLE_REPORTED_COMPARISONS_MANUAL_CHECK" if len(comparisons) > 1
                         else "COMPARISON_INDEPENDENCE_UNVERIFIED",
                         "population_independence_confirmed": False})
    collapsed = sum(max(0, len(x["reports"]) - 1) for x in families)
    return {"method_version": "REGISTRY_LINKAGE_V1", "distinct_report_leads": len(records),
            "registry_linked_families": len(families),
            "registry_linked_reports": sum(len(x["reports"]) for x in families),
            "unlinked_reports": unlinked, "ambiguous_reports": ambiguous,
            "families": families, "additional_linked_reports": collapsed,
            "conservative_family_lead_count": len(families) + len(unlinked) + len(ambiguous),
            "confirmed_independent_eligible_studies": None,
            "limitation": "Conservative registry-family prioritization count; unlinked/ambiguous leads are not confirmed independent, and multiple comparisons within a registry require manual population and arm adjudication."}
