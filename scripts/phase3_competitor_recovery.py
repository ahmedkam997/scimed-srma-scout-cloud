"""Bounded public PubMed follow-up for Phase 3 opportunity leads."""

import json
from pathlib import Path

from scimed_scout.sources.pubmed import PubMedSource

QUESTIONS = {
    "tavr-savr": '("transcatheter aortic valve"[tiab] OR TAVR[tiab] OR TAVI[tiab]) AND ("surgical aortic valve"[tiab] OR SAVR[tiab])',
    "ticagrelor-clopidogrel": 'ticagrelor[tiab] AND clopidogrel[tiab] AND (coronary[tiab] OR PCI[tiab])',
    "appendicitis-antibiotics": 'appendicitis[tiab] AND (antibiotic*[tiab] OR nonoperative[tiab]) AND appendectom*[tiab]',
}
ROUTES = {
    "competing_reviews": '(systematic review[pt] OR meta-analysis[pt] OR "systematic review"[tiab] OR meta-analysis[tiab])',
    "recent_randomized_reports": '(randomized controlled trial[pt] OR random*[tiab]) AND ("2023/01/01"[dp] : "3000/01/01"[dp])',
}


def run(client):
    report = {}
    for question, pico in QUESTIONS.items():
        routes = {}
        for name, filter_query in ROUTES.items():
            query = f"({pico}) AND ({filter_query})"
            result = client.search(query, limit=8)
            records = [
                {"pmid": str(row.record_id), "title": row.title, "year": row.year}
                for row in result.records
            ]
            routes[name] = {
                "query": query,
                "status": result.status.value,
                "reported_total": result.total_count,
                "records": records,
            }
        report[question] = {
            "routes": routes,
            "actual_competitor_cutoffs_verified": False,
            "qualification_granted": False,
        }
    return report


def main():
    report = run(PubMedSource(sort="pub_date"))
    Path("phase3-competitor-recovery.json").write_text(json.dumps(report, indent=2) + "\n")
    for question, outcome in report.items():
        for name, route in outcome["routes"].items():
            safe = {key: value for key, value in route.items() if key != "query"}
            print(f"::notice title={question} {name}::{json.dumps(safe, ensure_ascii=True).replace('%', '%25')}")
    if any(
        route["status"] not in {"SEARCHED_POSITIVE", "SEARCHED_NEGATIVE"}
        for outcome in report.values()
        for route in outcome["routes"].values()
    ):
        raise SystemExit("One or more bounded competitor recovery routes are unresolved")


if __name__ == "__main__":
    main()
