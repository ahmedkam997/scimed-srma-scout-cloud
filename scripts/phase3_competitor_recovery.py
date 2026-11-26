"""Bounded public PubMed follow-up for Phase 3 opportunity leads."""

import argparse
import json
import re
from pathlib import Path
from xml.etree.ElementTree import ParseError

from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.pubmed_abstracts import _fetch, parse_efetch

QUESTIONS = {
    "tavr-savr": '("transcatheter aortic valve"[ti] OR TAVR[ti] OR TAVI[ti]) AND ("surgical aortic valve"[ti] OR SAVR[ti] OR (transcatheter[ti] AND surgical[ti] AND aortic[ti] AND valve[ti]))',
    "ticagrelor-clopidogrel": 'ticagrelor[ti] AND clopidogrel[ti] AND (coronary[tiab] OR PCI[tiab] OR myocardial[tiab])',
    "appendicitis-antibiotics": 'appendicitis[ti] AND (antibiotic*[ti] OR nonoperative[ti]) AND appendectom*[ti]',
}
ROUTES = {
    "competing_reviews": '(systematic review[pt] OR meta-analysis[pt] OR "systematic review"[tiab] OR meta-analysis[tiab])',
    "recent_randomized_reports": '(randomized controlled trial[pt] OR random*[tiab]) AND ("2023/01/01"[dp] : "3000/01/01"[dp])',
}


HEART_FAILURE_QUESTIONS = {
    "af-ablation-hfrhfmr": (
        '"atrial fibrillation"[tiab] AND "catheter ablation"[tiab] '
        'AND ("heart failure"[tiab] OR HFrEF[tiab] OR HFmrEF[tiab]) '
        'AND (medical[tiab] OR "drug therapy"[tiab] OR "rate control"[tiab] OR antiarrhythmic[tiab])'
    ),
    "sacubitril-enalapril-adult-hfref": (
        'sacubitril[tiab] AND enalapril[tiab] '
        'AND ("heart failure with reduced ejection fraction"[tiab] OR HFrEF[tiab])'
    ),
}
POST_FEBRUARY = (
    '(randomized controlled trial[pt] OR random*[tiab]) '
    'AND ("2026/02/01"[dp] : "3000/01/01"[dp])'
)


def run(client, *, questions=QUESTIONS, post_february=False):
    report = {}
    for question, pico in questions.items():
        routes = {}
        for name, filter_query in ROUTES.items():
            query = f"({pico}) AND ({filter_query})"
            if name == "recent_randomized_reports":
                if post_february and question == "af-ablation-hfrhfmr":
                    query = f"({pico}) AND ({POST_FEBRUARY})"
                query += ' NOT (systematic review[pt] OR meta-analysis[pt] OR "meta-analysis"[ti] OR "systematic review"[ti])'
            result = client.search(query, limit=8)
            records = [
                {"pmid": str(row.record_id), "title": row.title, "year": row.year}
                for row in result.records
            ]
            routes[name] = {
                "query": query,
                "status": result.status.value,
                "reported_total": result.total_count,
                "translation_warning_or_error": "query_warning_or_error=True" in result.message,
                "records": records,
            }
        report[question] = {
            "routes": routes,
            "actual_competitor_cutoffs_verified": False,
            "qualification_granted": False,
        }
    return report


REVIEW_CONTROLS = ("42985463", "42499063", "42201709", "43090943", "42251641", "42384223")
SEARCH_METHODS = re.compile(r"(?i)\b(?:searched|searches|search was|search date|search cutoff)\b")


def retrieve_cutoff_cues(client, reviews=REVIEW_CONTROLS):
    try:
        records, diagnostics = parse_efetch(_fetch(client, reviews), reviews)
    except (OSError, ValueError, ParseError):
        return {"status": "ACCESS_FAILED", "records": {}, "actual_cutoffs_verified": False}
    cues = {}
    for pmid, row in records.items():
        text = row.get("abstractText", "")
        sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
        matches = [sentence[:300] for sentence in sentences if SEARCH_METHODS.search(sentence)]
        cues[pmid] = {"search_methods_excerpt": matches[:2], "pmcid": row.get("pmcid")}
    return {
        "status": "SEARCHED_POSITIVE" if len(records) == len(reviews) else "PARTIAL",
        "records": cues,
        "diagnostics": diagnostics,
        "actual_cutoffs_verified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heart-failure", action="store_true")
    args = parser.parse_args()
    client = PubMedSource(sort="pub_date")
    if args.heart_failure:
        report = run(client, questions=HEART_FAILURE_QUESTIONS, post_february=True)
        cutoffs = retrieve_cutoff_cues(client, ("42769399", "42119914", "41773097"))
    else:
        report = run(client)
        cutoffs = retrieve_cutoff_cues(client)
    Path("phase3-competitor-recovery.json").write_text(
        json.dumps({**report, "cutoff_cues": cutoffs}, indent=2) + "\n"
    )
    for question, outcome in report.items():
        for name, route in outcome["routes"].items():
            safe = {key: value for key, value in route.items() if key != "query"}
            print(f"::notice title={question} {name}::{json.dumps(safe, ensure_ascii=True).replace('%', '%25')}")
    for pmid, cue in cutoffs["records"].items():
        print(f"::notice title=Search methods PMID {pmid}::{json.dumps(cue).replace('%', '%25')}")
    if cutoffs["status"] != "SEARCHED_POSITIVE" or any(
        route["status"] not in {"SEARCHED_POSITIVE", "SEARCHED_NEGATIVE"}
        for outcome in report.values()
        for route in outcome["routes"].values()
    ):
        raise SystemExit("One or more bounded competitor recovery routes are unresolved")


if __name__ == "__main__":
    main()
