"""Non-destructive, key-safe live health check of SciMed scholarly sources.

Run on GitHub Actions; never interpret a successful HTTP call as novelty
clearance, eligibility screening, or a comprehensive search.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from scimed_scout.sources import build_default_source_clients

QUERIES = {
    "PubMed": "left atrial appendage occlusion dialysis",
    "Europe PMC": "left atrial appendage occlusion dialysis",
    "OpenAlex": "left atrial appendage occlusion dialysis",
    "Crossref": "left atrial appendage occlusion dialysis",
    "Semantic Scholar": "left atrial appendage occlusion dialysis",
    "PROSPERO": '"left atrial appendage occlusion" AND "dialysis"',
    "OSF Registries": '"left atrial appendage occlusion" AND "dialysis"',
    "ClinicalTrials.gov": "left atrial appendage occlusion dialysis",
}

def main() -> None:
    sources = build_default_source_clients()
    report = {
        "schema": "SCIMED_SOURCE_HEALTH_V1",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "SOURCE_CONNECTIVITY_ONLY_NOT_COMPREHENSIVE_NOVELTY_OR_ELIGIBILITY",
        "openalex_personal_key_configured": bool(os.getenv("OPENALEX_API_KEY")),
        "semantic_scholar_personal_key_configured": bool(os.getenv("SEMANTIC_SCHOLAR_API_KEY")),
        "prospero_cli_configured": bool(os.getenv("PROSPERO_CLI_JS")),
        "sources": [],
    }
    secrets = [x for x in (
        os.getenv("OPENALEX_API_KEY"),
        os.getenv("SEMANTIC_SCHOLAR_API_KEY"),
    ) if x]
    for client in sources:
        name = client.name
        start = time.monotonic()
        try:
            result = client.search(QUERIES[name],limit=5)
            safe_message = str(result.message or "")[:350]
            for secret in secrets:
                safe_message = safe_message.replace(secret, "[SECRET_REDACTED]")
            item = {
                "name": name,
                "status": result.status.value,
                "reported_results": result.total_count,
                "retrieved_citations": len(result.records),
                "diagnostic": safe_message,
                "elapsed_seconds": round(time.monotonic() - start, 2),
            }
        except Exception as exc:
            item = {
                "name": name,
                "status": "ACCESS_FAILED",
                "reported_results": None,
                "retrieved_citations": 0,
                "diagnostic": f"Unexpected {type(exc).__name__} during source probe",
                "elapsed_seconds": round(time.monotonic() - start, 2),
            }
        print(f"{name}: {item['status']} ({item['elapsed_seconds']}s); {item['diagnostic']}")
        report["sources"].append(item)
    target = Path(os.getenv("SCIMED_SOURCE_HEALTH_OUTPUT","source-health.json"))
    target.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print(f"Wrote source diagnostics to {target}; scientific gates unchanged.")

if __name__ == "__main__":
    main()
