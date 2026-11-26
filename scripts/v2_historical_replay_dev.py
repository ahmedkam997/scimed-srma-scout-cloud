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

def full_id_diagnostic(client, query, cap=10000):
    """Fetch only IDs, not full metadata, to distinguish matching from top-K ranking.
    A bounded or invalid response is unresolved, never used to infer nonmatching.
    """
    try:
        data = client.http.get_json(client.base + "esearch.fcgi", client._params({
            "db":"pubmed", "term":query, "retmode":"json", "retmax":cap,
            "sort":"relevance"}))
        block = data.get("esearchresult") or {}
        total = int(block["count"])
        ids = [str(x) for x in block.get("idlist", [])]
        warnings = block.get("warninglist") or {}
        valid = not (block.get("errorlist") or data.get("error") or data.get("ERROR")
                     or (isinstance(warnings,dict) and warnings.get("quotedphrasesnotfound")))
        complete = valid and 0 <= total <= cap and len(ids) == total and len(set(ids)) == total
        return set(ids), {"total":total,"retrieved_ids":len(ids),"complete":complete}
    except Exception as exc:
        return set(), {"complete":False,"error_type":type(exc).__name__}

def diagnose(top_ids, full_ids, full_audit, reference):
    target = set(reference["linked_reports"]) - set(reference["excluded_from_rct_oriented_report_metric"])
    complete = all(a["complete"] for a in full_audit)
    return {"all_matching_reference_reports": sorted(full_ids & target),
            "matched_but_outside_top_k": sorted((full_ids & target) - top_ids),
            "not_matching_any_query": sorted(target - full_ids) if complete else None,
            "full_id_diagnostic_complete": complete,
            "full_unique_ids":len(full_ids), "routes":full_audit,
            "full_relative_recall": len(full_ids & target)/len(target) if complete else None}

def main():
    client = PubMedSource(sort="relevance")
    retrieved = {name: retrieve(client, routes) for name, routes in STRATEGIES.items()}
    full_by_query = {q: full_id_diagnostic(client,q) for q in dict.fromkeys(q for routes in STRATEGIES.values() for q,_ in routes)}
    # Reveal reference labels only after retrieval has completed.
    results = {name: evaluate(ids, audit, REFERENCE) for name, (ids, audit) in retrieved.items()}
    for name, routes in STRATEGIES.items():
        ids = set().union(*(full_by_query[q][0] for q,_ in routes))
        results[name]["diagnostic"] = diagnose(retrieved[name][0],ids,[full_by_query[q][1] for q,_ in routes],REFERENCE)
    report = {"version": "V2_PHASE3_REPLAY_DEV_V2", "reference": REFERENCE,
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
