"""Temporal development exercises for Research Academy, separate from qualification."""

import argparse
import hashlib
import json
import re
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from scimed_scout.discovery.review_opportunity import date_bounds
from scimed_scout.discovery.stratified_retrieval import collect, date_query
from scimed_scout.sources.pubmed import PubMedSource
from scripts.academy_benchmark import audit_manifest, validate_case
from scripts.v2_historical_replay_dev import (
    BROAD, DRUG, NARROW, RCT, REFERENCE, evaluate,
)

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks" / "discovery_v1.json"
SEARCHED = {"SEARCHED_POSITIVE", "SEARCHED_NEGATIVE"}
REGROUP = "REGROUP_FOLLOW_UP"
RECOVERY = "RECOVERY_POST_CUTOFF"
BUDGET = 60
UPDATE_REPO = "https://github.com/Amal-Alharbi/Systematic_Reviews_Update"
UPDATE_REVISION = "35a78b615d9c9dbdd889c55a61e5032b3cc309c6"
UPDATE_PAIR = "CD000160"
UPDATE_DATES = "Reviews-Information/Publication_Date"
UPDATE_ORIGINAL = f"Included-PMIDs/content_level/{UPDATE_PAIR}.include.content.original.txt"
UPDATE_FOLLOWUP = f"Included-PMIDs/content_level/{UPDATE_PAIR}.include.content.update.txt"
UPDATE_SHA256 = {
    UPDATE_DATES: "4cc462ccb070afe6ccd893edae8318db3be1e9157fe67f35cc009c955a2aa764",
    UPDATE_ORIGINAL: "63b6e96681aa1e82c482dbcdfac2e6c07b3faf95c79d70626258133a0f39f509",
    UPDATE_FOLLOWUP: "f2488c55dc23ce1cbd26c8e4663b859c3256b14d35903138ccdc8ad4b5e96087",
}


def observe(reports, as_of):
    """Only expose complete publication intervals available by the replay date."""
    visible = []
    for report in reports:
        bounds = date_bounds(report["date"])
        if bounds and bounds[1] <= as_of:
            visible.append({
                "id": report["id"],
                "through": bounds[1],
                "from": bounds[0],
                "families": frozenset(report.get("families") or []),
                "comparison": report.get("comparison"),
            })
    return visible


def rank_signals(observed, cutoff):
    """Compare publication recency with an explicit trial-family cue."""
    earlier = {}
    uncertain = set()
    for row in observed:
        if row["through"] <= cutoff and len(row["families"]) == 1:
            family = next(iter(row["families"]))
            earlier.setdefault(family, set()).add(row["comparison"])
        elif row["from"] <= cutoff:
            uncertain.update(row["families"])

    post_cutoff, leads, unresolved = [], [], {}
    for row in observed:
        if row["from"] <= cutoff:
            continue
        ident = row["id"]
        post_cutoff.append(ident)
        if len(row["families"]) != 1:
            unresolved[ident] = "MISSING_OR_MULTIPLE_FAMILY_IDENTITIES"
            continue
        family = next(iter(row["families"]))
        if family in uncertain:
            unresolved[ident] = "PRIOR_FAMILY_CHRONOLOGY_OR_LINKAGE_UNRESOLVED"
        elif family in earlier:
            comparisons = earlier[family]
            if row["comparison"] and any(comparisons - {None, row["comparison"]}):
                unresolved[ident] = "PRIOR_REGISTRATION_DIFFERENT_COMPARISON"
            else:
                unresolved[ident] = "PREVIOUSLY_OBSERVED_FAMILY"
        else:
            leads.append(ident)
    return {
        "publication_recency": sorted(post_cutoff),
        "new_family_cues": sorted(leads),
        "post_cutoff_flags": unresolved,
    }


def reference_recall(ranked_ids, expected_ids):
    """Score only named positive references; other records remain unlabelled."""
    if not expected_ids:
        return None
    return len(set(ranked_ids) & set(expected_ids)) / len(set(expected_ids))


def published_controls():
    """Reuse source-linked pilot rows, with a separate reviewer-adjudication boundary."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in fixture["cases"]}
    regroup, recovery, chronology = (cases[key] for key in ("R01", "R02", "R03"))
    controls = []
    for name, source, cutoff, frames in (
        (REGROUP, regroup, date(2019, 12, 31), (date(2021, 12, 31), date(2026, 12, 31))),
        (
            RECOVERY,
            recovery,
            date.fromisoformat(chronology["last_search_date"]),
            (date(2022, 12, 31), date(2023, 12, 31)),
        ),
    ):
        records = [{
            "id": row["pmid"],
            "date": chronology["new_report_date"] if row["url"] == chronology["new_report_url"] else str(row["year"]),
            "families": [row["registry_id"]],
            "comparison": row["comparison"],
            "source_url": row["url"],
        } for row in source["records"]]
        controls.append({
            "id": name,
            "scope": source["scope"],
            "split": "development",
            "cutoff": cutoff.isoformat(),
            "cutoff_basis": (
                {"kind": "reported_review_search_cutoff", "source_url": chronology["review_url"]}
                if name == RECOVERY else {"kind": "development_simulation_boundary"}
            ),
            "reference_basis": source["reference_basis"],
            "sources": [row["source_url"] for row in records],
            "frames": [{
                "as_of": index.isoformat(),
                **rank_signals(observed := observe(records, index), cutoff),
                "visible_pmids": sorted(row["id"] for row in observed),
            } for index in frames],
            "completed_review_update_pair": False,
            "independent_new_eligible_trial_count": None,
        })
    return controls


def paired_pubmed_retrieval(client):
    """Equal report budgets, fixed queries and disjoint date strata."""
    end = date(2017, 10, 31)
    start = date(1800, 1, 1)
    query = f"{DRUG} AND {NARROW} AND {RCT}"
    baseline_query = date_query(query, start, end)
    result = client.search(baseline_query, limit=BUDGET)
    baseline_routes = [{
        "query": baseline_query, "slots": BUDGET, "status": result.status.value,
        "reported_total": result.total_count, "retrieved": len(result.records),
    }]
    stratified_audit, stratified_records = collect(client, query, start=start, end=end, budget=BUDGET)
    broad_query = date_query(f"{DRUG} AND {BROAD} AND {RCT}", start, end)
    dual_routes = []
    dual_records = []
    for q in (baseline_query, broad_query):
        r = client.search(q, limit=BUDGET // 2)
        dual_records.extend(r.records)
        dual_routes.append({
            "query": q, "slots": BUDGET // 2, "status": r.status.value,
            "reported_total": r.total_count, "retrieved": len(r.records),
        })

    def score(records, routes):
        return evaluate({str(row.record_id) for row in records[:BUDGET]}, routes, REFERENCE)

    # Reference PMIDs are only used after retrieval.
    variants = {
        "single_query_relevance": score(result.records, baseline_routes),
        "date_stratified_relevance": score(stratified_records, stratified_audit["windows"]),
        "dual_route_relevance": score(dual_records, dual_routes),
    }
    # The existing stratifier can leave windows unqueried on rate limiting.
    if stratified_audit["status"] != "BOUNDED_SAMPLE":
        variants["date_stratified_relevance"].update(
            relative_recall=None, missing=None, all_routes_definitive_bounded=False)
    variants["date_stratified_relevance"]["stratum_audit"] = stratified_audit
    return {
        "split": "development",
        "reference_review_pmid": REFERENCE["review_pmid"],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "per_variant_report_budget": BUDGET,
        "variants": variants,
        "resolved": all(variant["all_routes_definitive_bounded"] for variant in variants.values()),
        "historical_index_snapshot": False,
        "interpretation": "Relative recall of linked reference reports. Unlabelled records are not false positives.",
    }


def fetch_update_text(name):
    base = "https://raw.githubusercontent.com/Amal-Alharbi/Systematic_Reviews_Update"
    request = urllib.request.Request(f"{base}/{UPDATE_REVISION}/{name}", headers={
        "User-Agent": "SciMed Research Academy evidence replay",
    })
    with urllib.request.urlopen(request, timeout=10) as response:
        return response.read(32769)


def load_external_review_pair(read=fetch_update_text):
    """Read only three pinned text files from the published review update corpus."""
    texts = {}
    for name, digest in UPDATE_SHA256.items():
        raw = read(name)
        if len(raw) > 32768 or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Review update source failed size or checksum verification")
        texts[name] = raw.decode("utf-8")
    header, *date_rows = texts[UPDATE_DATES].splitlines()
    if header.split() != ["Review", "original", "updated"]:
        raise ValueError("Review update publication table format changed")
    dates = {}
    for row in date_rows:
        case, original, updated = row.split()
        original, updated = date.fromisoformat(original), date.fromisoformat(updated)
        if case in dates or original >= updated:
            raise ValueError("Review publication table contains duplicate or non-temporal pairs")
        dates[case] = (original, updated)

    def pmids(path):
        rows = texts[path].split()
        if not rows or any(not re.fullmatch(r"[1-9][0-9]*", row) for row in rows):
            raise ValueError("Review inclusion labels require canonical PMIDs")
        return set(rows)

    original, updated = dates[UPDATE_PAIR]
    baseline_pmids = pmids(UPDATE_ORIGINAL)
    followup_pmids = pmids(UPDATE_FOLLOWUP)
    return {
        "available_pairs": len(dates),
        "original_publication": original,
        "updated_publication": updated,
        "baseline_pmids": baseline_pmids,
        "followup_pmids": followup_pmids,
    }


def replay_external_pair(client=None, read=fetch_update_text):
    """Compare two fixed query formulations against newly listed full-text reports."""
    provenance = {
        "case": UPDATE_PAIR,
        "topic": "Patch angioplasty versus primary closure for carotid endarterectomy",
        "dataset_url": UPDATE_REPO,
        "paper_doi": "10.1145/3331184.3331358",
        "revision": UPDATE_REVISION,
        "split": "development",
        "independent_new_eligible_trial_count": None,
        "qualification_granted": False,
    }
    try:
        pair = load_external_review_pair(read)
    except (OSError, ValueError, KeyError) as exc:
        return {**provenance, "source_resolved": False, "error_type": type(exc).__name__}
    start = pair["original_publication"] + timedelta(days=1)
    end = pair["updated_publication"] - timedelta(days=1)
    target = pair["followup_pmids"] - pair["baseline_pmids"]
    results = {
        **provenance,
        "source_resolved": True,
        "sha256": UPDATE_SHA256,
        "publication_dated_pairs_in_catalog": pair["available_pairs"],
        "original_review_publication": pair["original_publication"].isoformat(),
        "updated_review_publication": pair["updated_publication"].isoformat(),
        "source_labelled_original_reports": len(pair["baseline_pmids"]),
        "source_labelled_update_reports": len(pair["followup_pmids"]),
        "source_labelled_added_report_count": len(target),
        "original_and_update_overlap_count": len(pair["baseline_pmids"] & pair["followup_pmids"]),
        "observational_window_start": start.isoformat(),
        "observational_window_end": end.isoformat(),
        "window_basis": "Publication dates sandwich a retrospective proxy window; actual search cutoffs are unavailable.",
        "comparison_unit": "Published full-text included report labels, not trial families.",
        "variants": None,
    }
    if client is None:
        return results
    topic = '("Endarterectomy, Carotid"[Mesh] OR (carotid[tiab] AND endarterectom*[tiab]))'
    options = {
        "population_only": topic,
        "explicit_comparison": f"{topic} AND (patch*[tiab] OR angioplast*[tiab] OR closure[tiab])",
    }
    results["variants"] = {}
    for method, terms in options.items():
        query = date_query(terms, start, end)
        found = client.search(query, limit=BUDGET)
        observed = {str(record.record_id) for record in found.records[:BUDGET]}
        complete = found.status.value in SEARCHED
        results["variants"][method] = {
            "query": query,
            "slots": BUDGET,
            "status": found.status.value,
            "retrieved": len(observed),
            "relative_added_report_recall": reference_recall(observed, target) if complete else None,
        }
    return results


def replay_development_pairs(manifest):
    """Evaluate completed review pairs with labels held outside the replay observation."""
    if not isinstance(manifest, dict) or not isinstance(manifest.get("cases"), list):
        raise ValueError("Expected an Academy casebook")
    if any(not isinstance(case, dict) or case.get("split") not in {"train", "development"}
           for case in manifest["cases"]):
        raise ValueError("The development runner accepts only train and development cases")
    intake = audit_manifest(manifest)
    if intake["issues"]:
        raise ValueError("Casebook failed chronology or split-isolation checks")

    results = []
    for case in manifest["cases"]:
        case_id, split, opportunity, index, _, evidence, _ = validate_case(case)
        if opportunity != "UPDATE":
            continue
        pair = case["reverse_replay"]
        cutoff = date.fromisoformat(pair["baseline_search_through"])
        reports = [{
            "id": record_id,
            "date": availability.isoformat(),
            # Only observable registration cues are used for ranking. Adjudicated
            # family identities are reserved for validation and split isolation.
            "families": sorted({
                re.sub(r"\s+", "", token).upper()
                for token in record["identifiers"].get("registration_ids", [])
            }),
        } for record_id, (record, availability) in evidence.items()
            if record["kind"] == "STUDY" and availability <= index]
        signals = rank_signals(observe(reports, index), cutoff)
        # Follow-up review information is never included in the observation.
        expected = pair["added_report_ids"]
        results.append({
            "case_id": case_id,
            "split": split,
            "index_date": index.isoformat(),
            "baseline_search_through": cutoff.isoformat(),
            "observable_study_count": len(reports),
            "labelled_added_reports": len(expected),
            "baseline_relative_report_recall": reference_recall(signals["publication_recency"], expected),
            "family_cue_relative_report_recall": reference_recall(signals["new_family_cues"], expected),
            "retrospective_label_status": "STRUCTURAL_CHECKS_ONLY",
            "qualification_granted": False,
        })
    return results


def build_report(*, live_client=None, manifest=None, external_reader=None):
    return {
        "schema": "SCIMED_ACADEMY_REPLAY_V1",
        "scope": "DEVELOPMENT_ONLY",
        "qualification_granted": False,
        "scientific_accuracy_validated": False,
        "training_weights_changed": False,
        "controls": published_controls(),
        "review_pairs": replay_development_pairs(manifest) if manifest is not None else [],
        "retrieval": paired_pubmed_retrieval(live_client) if live_client else None,
        "completed_public_review_pair": (
            replay_external_pair(live_client, read=external_reader or fetch_update_text)
            if live_client is not None or external_reader is not None else None
        ),
        "limitations": [
            "Publication-date replay on a current index is not historical index availability.",
            "Registry and comparison cues do not establish independent eligible populations or usable outcomes.",
            "Source-linked chronology controls do not replace independently adjudicated review pairs.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true", help="Run bounded development-only paired PubMed retrieval.")
    parser.add_argument("--update-source", type=Path, help="Read pinned update dataset text locally instead of HTTPS.")
    parser.add_argument("--casebook", type=Path, help="Optional completed review pairs in train or development splits.")
    args = parser.parse_args()
    try:
        manifest = json.loads(args.casebook.read_text(encoding="utf-8")) if args.casebook else None
        report = build_report(
            live_client=PubMedSource(sort="relevance") if args.live else None,
            manifest=manifest,
            external_reader=(lambda name: (args.update_source / name).read_bytes()) if args.update_source else None,
        )
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    pair = report["completed_public_review_pair"]
    complete_pair_retrieval = pair and pair["source_resolved"] and (
        not args.live or all(variant["status"] in SEARCHED for variant in pair["variants"].values())
    )
    if ((args.live and (not report["retrieval"]["resolved"] or not complete_pair_retrieval))
        or (args.update_source and not complete_pair_retrieval)):
        raise SystemExit("Academy development replay incomplete; audit artifact preserved")


if __name__ == "__main__":
    main()
