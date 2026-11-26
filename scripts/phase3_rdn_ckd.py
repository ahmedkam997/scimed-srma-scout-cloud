"""Trace the RDN-CKD report to a registry record and preserve endpoint cues."""

import json
import re
from pathlib import Path

from scimed_scout.discovery.trial_family import registration_signals
from scimed_scout.sources.http import JsonHttpClient
from scimed_scout.sources.pubmed import PubMedSource
from scimed_scout.sources.pubmed_abstracts import _fetch, parse_efetch
from scripts.phase3_family_methods import as_row, notice

PMID = "42937114"
PRIOR_REGISTRATIONS = {
    "NCT01418261", "NCT02392351", "NCT02439749", "NCT02439775",
    "NCT02649426", "NCT02918305", "NCT03614260",
}
CTG = "https://clinicaltrials.gov/api/v2/studies"


def describe_registry(study, expected):
    protocol = study.get("protocolSection") or {}
    identity = protocol.get("identificationModule") or {}
    if identity.get("nctId") != expected:
        return {"status": "IDENTITY_MISMATCH"}
    design = protocol.get("designModule") or {}
    arms = protocol.get("armsInterventionsModule") or {}
    outcomes = protocol.get("outcomesModule") or {}
    return {
        "status": "EXACT_IDENTIFIER",
        "registration": expected,
        "title": identity.get("briefTitle"),
        "design": design,
        "arms": [
            {"label": arm.get("label"), "type": arm.get("type"), "interventions": arm.get("interventionNames")}
            for arm in arms.get("armGroups", [])
        ],
        "primary_outcomes": outcomes.get("primaryOutcomes", []),
        "results_available": study.get("hasResults"),
        "identifier_seen_in_prior_sample": expected in PRIOR_REGISTRATIONS,
        "participant_independence_confirmed": False,
        "usable_outcome_confirmed": False,
    }


def audit(client, registry, *, fetch=_fetch):
    report = {"pmid": PMID, "qualification_granted": False}
    try:
        found, diagnostics = parse_efetch(fetch(client, [PMID]), [PMID])
    except (OSError, ValueError, SyntaxError) as exc:
        return {**report, "status": "ACCESS_FAILED", "error_type": type(exc).__name__}
    if PMID not in found:
        return {**report, "status": "UNRESOLVED", "diagnostics": diagnostics}
    metadata = found[PMID]
    signals = registration_signals(as_row(PMID, metadata))
    excerpts = [
        sentence.strip()[:420]
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", metadata["abstractText"])
        if re.search(r"ambulatory|mm\s*hg|randomi[sz]|sham|medication", sentence, re.I)
    ][:8]
    report.update(status="REPORT_RETRIEVED", title=metadata["pubmed_efetch_title"],
                  doi=metadata["doi"], pmcid=metadata["pmcid"],
                  registration_signals=signals, outcome_excerpts=excerpts)
    exact = list(signals)
    if len(exact) != 1 or not re.fullmatch(r"NCT[0-9]{8}", exact[0]):
        report["registry"] = {"status": "UNRESOLVED_REGISTRATION"}
        return report
    try:
        report["registry"] = describe_registry(registry.get_json(f"{CTG}/{exact[0]}"), exact[0])
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        report["registry"] = {"status": "ACCESS_OR_FORMAT_UNRESOLVED", "error_type": type(exc).__name__}
    return report


def main():
    report = audit(PubMedSource(), JsonHttpClient(timeout=12, retries=1))
    Path("phase3-rdn-ckd.json").write_text(json.dumps(report, indent=2) + "\n")
    notice("RDN-CKD registration and outcome cues", report)
    if report.get("registry", {}).get("status") != "EXACT_IDENTIFIER":
        raise SystemExit("RDN-CKD registry identity remains unresolved")


if __name__ == "__main__":
    main()
