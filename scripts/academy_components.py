"""Run separate CPU development comparisons on published report controls."""

import argparse
import json
from collections import Counter
from itertools import combinations
from pathlib import Path
from xml.etree.ElementTree import ParseError

from scimed_scout.discovery.competitor_priority_v2 import hybrid
from scimed_scout.discovery.evidence_first import _record
from scimed_scout.discovery.novelty import _select_records
from scimed_scout.discovery.structured_extraction_v2 import abstract_ratios
from scimed_scout.discovery.trial_family import audit_trial_families
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.pubmed_abstracts import _fetch, parse_efetch
from scimed_scout.storage import CandidateRecord
from scripts.phase3_family_methods import as_row, notice
from scripts.v2_real_family_contrast import CASES


# The two clinical review pools and report-level reference positives were
# originally recorded in v2_phase2_live. These are reused development controls.
COMPETITORS = (
    (
        "cardiology", "heart failure", "dapagliflozin", "placebo",
        '(dapagliflozin[tiab] OR empagliflozin[tiab]) AND "heart failure"[tiab] '
        'AND (meta-analysis[pt] OR systematic review[pt] OR meta-analysis[tiab])',
        {"36030328", "42547169"},
    ),
    (
        "surgery", "rectal cancer", "robotic surgery", "laparoscopic surgery",
        '"rectal cancer"[tiab] AND (robotic[tiab] OR laparoscopic[tiab]) '
        'AND (meta-analysis[pt] OR systematic review[pt] OR meta-analysis[tiab])',
        {"42581199", "40022103", "40770525", "42223567"},
    ),
)


def family_pair_scores(reference, observed):
    labels = Counter()
    for a, b in combinations(sorted(reference), 2):
        expected = reference[a] == reference[b]
        linked = a in observed and b in observed and observed[a] == observed[b]
        labels[("t" if expected == linked else "f") + ("p" if linked else "n")] += 1
    return {key: labels[key] for key in ("tp", "fp", "fn", "tn")}


def evaluate_report_tasks(found):
    rows = [as_row(pmid, metadata) for pmid, metadata in found.items() if pmid in CASES]
    actual = {
        row["report_id"]: family["registration_id"]
        for family in audit_trial_families(rows)["families"]
        for row in family["reports"]
    }
    reference = {pmid: family for pmid, (family, _, _) in CASES.items()}
    retrieved = {row["source_record_id"] for row in rows}
    retrieved_reference = {pmid: family for pmid, family in reference.items() if pmid in retrieved}

    outcome_metrics = {}
    targets = {pmid: expected for pmid, (_, _, expected) in CASES.items() if expected is not None}
    leads = {row["source_record_id"]: abstract_ratios(row) for row in rows}
    for label, limit in (("first_explicit_ratio", 1), ("all_explicit_ratios", None)):
        matched = 0
        proposed = 0
        for pmid in targets:
            predictions = leads.get(pmid, [])[:limit]
            proposed += len(predictions)
            matched += any(
                (lead["ratio"], *lead["reported_ci"]) == targets[pmid]
                for lead in predictions
            )
        outcome_metrics[label] = {"matched_reference_reports": matched, "ratio_cues": proposed}

    return {
        "coverage": "RETRIEVED" if len(rows) == len(CASES) else "PARTIAL_OR_UNAVAILABLE",
        "report_references": len(CASES),
        "retrieved_reports": len(rows),
        "trial_family_linkage": {
            "singleton_baseline": family_pair_scores(reference, {}),
            "explicit_registration_linkage": family_pair_scores(reference, actual),
            "conditional_on_retrieved": {
                "report_count": len(retrieved_reference),
                "singleton_baseline": family_pair_scores(retrieved_reference, {}) if len(retrieved_reference) >= 2 else None,
                "explicit_registration_linkage": family_pair_scores(retrieved_reference, actual) if len(retrieved_reference) >= 2 else None,
            },
            "exact_registration_matches": sum(actual.get(pmid) == family for pmid, family in reference.items()),
            "registry_linkage_only": True,
        },
        "outcome_extraction": {
            "reference_primary_report_ratios": len(targets),
            "retrieved_primary_report_ratios": len(retrieved & targets.keys()),
            **outcome_metrics,
            "endpoint_direction_and_usable_outcomes_verified": False,
        },
    }


def evaluate_competitors(client):
    results = {}
    for name, population, intervention, comparator, query, references in COMPETITORS:
        response = client.search(query, limit=30)
        rows = [{**_record(record), "evidence_type": "PUBLISHED_REVIEW"} for record in response.records]
        candidate = CandidateRecord(
            name, "academy", name, name, population=population,
            intervention_exposure_index_test=intervention, comparator_reference=comparator,
        )
        baseline = _select_records(candidate, rows, len(rows))
        reranked = hybrid(candidate, baseline)
        available = {row["source_record_id"] for row in baseline}
        results[name] = {
            "status": response.status.value,
            "retrieved_inventory_size": len(available),
            "known_review_reference_count": len(references),
            "known_reviews_retrieved": len(available & references),
            "comparison_at_five": {
                key: (
                    len(references & {row["source_record_id"] for row in ranked[:5]})
                    if response.status.value in {"SEARCHED_POSITIVE", "SEARCHED_NEGATIVE"}
                    else None
                )
                for key, ranked in (("lexical_baseline", baseline), ("hybrid_bm25", reranked))
            },
        }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    client = PubMedSource(sort="relevance")
    ids = list(CASES)
    try:
        found, diagnostics = parse_efetch(_fetch(client, ids), ids)
    except (OSError, ValueError, ParseError) as exc:
        found, diagnostics = {}, {"error_type": type(exc).__name__}
    result = {
        "schema": "SCIMED_ACADEMY_COMPONENTS_V1",
        "split": "development",
        "weight_training": False,
        "qualification_granted": False,
        "metadata_diagnostics": diagnostics,
        **evaluate_report_tasks(found),
        "competitor_detection": evaluate_competitors(client),
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    notice("Academy development component comparisons", result)
    if result["coverage"] != "RETRIEVED" or any(
        row["status"] not in {"SEARCHED_POSITIVE", "SEARCHED_NEGATIVE"}
        for row in result["competitor_detection"].values()
    ):
        raise SystemExit("Academy component source coverage incomplete")


if __name__ == "__main__":
    main()
