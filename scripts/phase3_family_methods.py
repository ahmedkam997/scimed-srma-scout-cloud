"""Audit shortlisted public reports without granting scientific qualification."""

import json
from pathlib import Path

from scimed_scout.discovery.competitor_records import identifiers
from scimed_scout.discovery.open_access_dates import OpenAccessSearchDateResolver
from scimed_scout.discovery.structured_extraction_v2 import abstract_counts, abstract_ratios, report_role_cues
from scimed_scout.discovery.trial_family import audit_trial_families
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.pubmed_abstracts import _fetch, parse_efetch

TARGETS = {"RCT-15364278DD7EDB7B", "RCT-2E9103FF7C89F52D"}
RENAL = "RCT-8C63D3F7D7C752A7"
RENAL_REVIEW_QUERY = (
    '"renal denervation"[ti] AND sham[tiab] AND '
    '(systematic review[pt] OR meta-analysis[pt] OR "meta-analysis"[ti])'
)
REVIEWS = ("42985463", "42499063", "42201709", "43090943")


def comparison_identities(rows):
    identities = []
    for row in rows:
        ids = identifiers(row)
        identities.append({
            "source": row["source"],
            "source_record_id": str(row["source_record_id"]),
            "pmids": sorted(ids["pmid"]),
            "dois": sorted(ids["doi"]),
        })
    return identities


def pubmed_ids(identities):
    return list(dict.fromkeys(
        row["pmids"][0] for row in identities
        if len(row["pmids"]) == 1 and len(row["dois"]) <= 1 and row["pmids"][0].isascii()
    ))


def as_row(pmid, metadata):
    return {
        "source": "PubMed", "source_record_id": pmid,
        "title": metadata.get("pubmed_efetch_title", ""),
        "payload": {"url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "metadata": metadata},
    }


def audit(client, candidates, *, fetch=_fetch, resolver=None, targets=TARGETS, reviews=REVIEWS):
    resolver = resolver or OpenAccessSearchDateResolver(include_pmc_oai=True)
    identities = {
        row["candidate_id"]: comparison_identities(row["metadata"]["rct_first"]["comparison_records"])
        for row in candidates if row["candidate_id"] in targets
    }
    selected = {cid: pubmed_ids(records)[:30] for cid, records in identities.items()}
    ids = list(dict.fromkeys([*reviews, *(pmid for group in selected.values() for pmid in group)]))
    try:
        found, diagnostics = parse_efetch(fetch(client, ids), ids)
    except (OSError, ValueError, SyntaxError) as exc:
        found, diagnostics = {}, {"error_type": type(exc).__name__}
    rows = {pmid: as_row(pmid, metadata) for pmid, metadata in found.items()}
    return {
        "qualification_granted": False,
        "missing_pubmed_ids": sorted(set(ids) - set(rows)),
        "pubmed_diagnostics": diagnostics,
        "competitor_identities": {pmid: {
            "pmcid": found[pmid].get("pmcid"),
            "doi": found[pmid].get("doi"),
        } for pmid in reviews if pmid in found},
        "competitor_methods": {pmid: resolver.resolve(rows[pmid]) if pmid in rows else None
                               for pmid in reviews},
        "candidates": {
            cid: {
                "source_identities": identities[cid],
                "families": audit_trial_families([rows[pmid] for pmid in group if pmid in rows]),
                "role_cues": {pmid: report_role_cues(rows[pmid])["cues"] for pmid in group if pmid in rows},
                "outcome_cues": {
                    pmid: {
                        "title": rows[pmid]["title"],
                        "count_leads": abstract_counts(rows[pmid]),
                        "ratio_leads": abstract_ratios(rows[pmid]),
                    }
                    for pmid in group if pmid in rows
                },
                "usable_independent_trial_count": None,
            }
            for cid, group in selected.items()
        },
    }


def notice(title, value):
    print(f"::notice title={title}::{json.dumps(value, ensure_ascii=True).replace('%', '%25')}")


def main():
    source = Path("inputs/phase3-opportunities-cardiology/opportunity.json")
    candidates = json.loads(source.read_text())["candidates"]
    client = PubMedSource()
    renal = any(row["candidate_id"] == RENAL for row in candidates)
    targets, reviews = TARGETS, REVIEWS
    review_search = None
    if renal:
        targets = {RENAL}
        search = client.search(RENAL_REVIEW_QUERY, limit=6)
        reviews = tuple(str(row.record_id) for row in search.records)
        review_search = {
            "query": RENAL_REVIEW_QUERY, "status": search.status.value,
            "reported_total": search.total_count,
            "reports": [{"pmid": str(row.record_id), "title": row.title} for row in search.records],
        }
    result = audit(client, candidates, targets=targets, reviews=reviews)
    result["bounded_review_search"] = review_search
    Path("phase3-family-methods.json").write_text(json.dumps(result, indent=2) + "\n")
    if review_search is not None:
        notice("Renal competitor search", review_search)
    for pmid, methods in result["competitor_methods"].items():
        notice(f"Full Methods PMID {pmid}", {
            "identity": result["competitor_identities"].get(pmid), "methods": methods,
        })
    for cid, row in result["candidates"].items():
        families = row["families"]
        notice(f"Family ledger {cid}", {
            "linked": {group["registration_id"]: [report["report_id"] for report in group["reports"]]
                       for group in families["families"]},
            "unlinked": [report["report_id"] for report in families["unlinked_reports"]],
            "ambiguous": [report["report_id"] for report in families["ambiguous_reports"]],
            "role_cues": row["role_cues"],
            "non_pubmed_identities": [item for item in row["source_identities"] if item["source"] != "PubMed"],
        })
        notice(f"Outcome cue inventory {cid}", {
            pmid: {
                "title": evidence["title"],
                "count_leads": len(evidence["count_leads"]),
                "ratio_leads": len(evidence["ratio_leads"]),
            }
            for pmid, evidence in row["outcome_cues"].items()
        })
    if result["missing_pubmed_ids"] or set(result["candidates"]) != targets or not reviews or not all(result["competitor_methods"].values()):
        raise SystemExit("Family or full-text Methods audit remains incomplete")


if __name__ == "__main__":
    main()
