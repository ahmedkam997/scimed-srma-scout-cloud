"""Investigate published replay misses after scoring, without modifying labels."""

import argparse
import json
import re
from pathlib import Path

from scimed_scout.sources.pubmed import PubMedSource
from scripts.phase3_family_methods import notice

SEARCHED = {"SEARCHED_POSITIVE", "SEARCHED_NEGATIVE"}


def diagnose_retrieval(client, replay):
    windows = replay["completed_public_review_pair"]["variants"]
    # Pinned inclusion-list reference from the completed CD000160 review pair.
    # PMID-guided probes are diagnostic only and never part of a scored run.
    pmid = "9510277"
    exact = client.search(f"{pmid}[uid]", limit=1)
    metadata = next(({
        "title": row.title, "publication_date": row.metadata.get("pubdate"),
        "electronic_publication_date": row.metadata.get("epubdate"),
    } for row in exact.records if str(row.record_id) == pmid), None)
    variants = {}
    for name, row in windows.items():
        route = client.search(f'({row["query"]}) AND {pmid}[uid]', limit=1)
        status = route.status.value
        matches = any(str(record.record_id) == pmid for record in route.records)
        membership = matches if status in SEARCHED else None
        variants[name] = {
            "status": status,
            "query_matches_reference": membership,
            "bounded_retrieval_recall_before_diagnosis": row["relative_added_report_recall"],
        }
    return {
        "pmid": pmid, "exact_metadata_status": exact.status.value,
        "metadata": metadata, "variant_diagnostics": variants,
        "scored_results_changed": False, "qualification_granted": False,
    }


def dataset_digests(dataset_audit):
    dataset = dataset_audit["datasets"]["trialreviewbench"]
    return {
        "status": dataset["status"],
        "artifacts": [
            {key: entry.get(key) for key in ("path", "sha256", "status")}
            for entry in dataset["artifacts"]
            if re.fullmatch("[0-9a-f]{64}", entry.get("sha256") or "")
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-audit", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    replay = json.loads(args.replay.read_text(encoding="utf-8"))
    audit = json.loads(args.data_audit.read_text(encoding="utf-8"))
    report = {
        "split": "development",
        "qualification_granted": False,
        "trialreviewbench_observed_digests": dataset_digests(audit),
        "replay_miss": diagnose_retrieval(PubMedSource(sort="relevance"), replay),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    notice("Academy diagnostics", report)
    if any(row["query_matches_reference"] is None
           for row in report["replay_miss"]["variant_diagnostics"].values()):
        raise SystemExit("Replay query membership unresolved")


if __name__ == "__main__":
    main()
