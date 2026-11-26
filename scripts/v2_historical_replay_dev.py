"""Development-only historical relative-recall pilot; never grants qualification.
Search inputs are separated from published reference labels. No LLM calls.
"""
import json
from pathlib import Path
from scimed_scout.sources.pubmed import PubMedSource

CUTOFF = '2017/10/31'
DATE = f'("1800/01/01"[dp] : "{CUTOFF}"[dp])'
DRUG = '(statin*[tiab] OR "Hydroxymethylglutaryl-CoA Reductase Inhibitors"[Mesh] OR atorvastatin[tiab] OR pravastatin[tiab] OR rosuvastatin[tiab] OR simvastatin[tiab] OR lovastatin[tiab] OR fluvastatin[tiab] OR pitavastatin[tiab])'
RCT = '(randomized controlled trial[pt] OR random*[tiab] OR placebo[tiab])'
NARROW = '(primary prevention[tiab] OR "Primary Prevention"[Mesh])'
BROAD = '(cardiovascular[tiab] OR coronary[tiab] OR atherosclero*[tiab] OR stroke[tiab] OR hypertens*[tiab] OR hypercholesterolemia[tiab])'
STRATEGIES = {
    "narrow": [(f"{DRUG} AND {NARROW} AND {RCT} AND {DATE}", 100)],
    "dual_route": [(f"{DRUG} AND {NARROW} AND {RCT} AND {DATE}", 50),
                   (f"{DRUG} AND {BROAD} AND {RCT} AND {DATE}", 50)],
}
# Labels are report-level, not independently adjudicated RCTs. Table 1 and refs 25-40.
REFERENCE = {
    "review_pmid": "30834266", "review_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC6374814/",
    "reported_studies": 16, "cutoff": CUTOFF, "split": "development",
    "linked_reports": {
        "16899775":"Amarenco 2006", "20048204":"Chan 2010", "15325833":"Colhoun 2004",
        "9613910":"Downs 1998", "19764857":"Fonseca 2009 (secondary review, not a primary RCT report)",
        "7734010":"Furberg 1994", "28531241":"Han 2017 (secondary analysis)",
        "9003110":"Mercuri 1996", "19420918":"Mok 2009", "12114036":"HPS 2002",
        "17011942":"Nakamura 2006", "12686036":"Sever 2003", "7566020":"Shepherd 1995"
    },
    "unresolved_pmids": ["Huang 2012", "Zhai 2009", "Zhang 2016"],
    "excluded_from_rct_oriented_report_metric": ["19764857"]
}

def retrieve(client, routes):
    # Only search inputs reach retrieval. Labels are not sent to the search engine.
    ids = set()
    audit = []
    for query, slots in routes:
        result = client.search(query, limit=slots)
        ids.update(str(r.record_id) for r in result.records)
        audit.append({"query": query, "slots": slots, "status": result.status.value,
                      "reported_total": result.total_count, "retrieved": len(result.records)})
    return ids, audit

def evaluate(ids, audit, reference):
    linked = set(reference["linked_reports"])
    target = linked - set(reference["excluded_from_rct_oriented_report_metric"])
    complete_sample = all(x["status"] in {"SEARCHED_POSITIVE", "SEARCHED_NEGATIVE"} for x in audit)
    return {"retrieved_unique": len(ids), "reference_reports": len(target),
            "matched": sorted(ids & target), "missing": sorted(target - ids),
            "relative_recall": len(ids & target) / len(target) if target and complete_sample else None,
            "all_routes_definitive_bounded": complete_sample, "routes": audit,
            "all_cited_report_matches": sorted(ids & linked),
            "unlabelled_retrieved": len(ids - linked),
            "qualification_granted": False}

def main():
    client = PubMedSource(sort="relevance")
    retrieved = {name: retrieve(client, routes) for name, routes in STRATEGIES.items()}
    # Reveal reference labels only after retrieval has completed.
    results = {name: evaluate(ids, audit, REFERENCE) for name, (ids, audit) in retrieved.items()}
    report = {"version": "V2_PHASE3_REPLAY_DEV_V1", "reference": REFERENCE,
              "results": results, "historical_index_snapshot": False,
              "held_out": False, "training_weights_changed": False,
              "qualification_granted": False,
              "limitations": ["Report-level reference subset, not study-level gold standard",
                              "Publication-date filter on current PubMed index, not historical availability",
                              "Unlabelled records cannot be counted as false positives",
                              "No automatic production query changes or human adjudication"]}
    Path("v2-replay-dev.json").write_text(json.dumps(report, indent=2) + "\n")
    print("V2_REPLAY_DEV " + json.dumps(report), flush=True)

if __name__ == "__main__":
    main()
