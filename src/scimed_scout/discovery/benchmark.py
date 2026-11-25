"""Offline benchmark: policy regression plus transparent published evidence checks."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from scimed_scout.discovery.evidence import discovery_evidence_snapshot
from scimed_scout.discovery.gates import final_discovery_decision
from scimed_scout.storage import CandidateRecord, ProjectRecord, SQLiteLedger

QUALIFIED = "QUALIFIED — FIRST-CHOICE REVIEW TOPIC"


def run_benchmark(fixture):
    rows = []
    for case in fixture["cases"]:
        kind = case["kind"]
        row = {"id": case["id"], "kind": kind, "description": case["description"]}
        if kind == "synthetic_policy":
            actual = final_discovery_decision({**fixture["policy_baseline"], **case["overrides"]})
            observed = actual["decision"] == QUALIFIED
            row.update(expected=case["expected_qualified"], observed=observed,
                       passed=observed == case["expected_qualified"],
                       failed_gates=[g["name"] for g in actual["gates"] if not g["passed"]])
        elif kind == "published_trial_family":
            # Test the real current bibliographic counter, not human eligibility.
            with TemporaryDirectory() as directory:
                with SQLiteLedger(Path(directory) / "bench.sqlite") as ledger:
                    ledger.upsert_project(ProjectRecord("P", "Cardiology"))
                    ledger.upsert_candidate(CandidateRecord("C", "P", case["scope"], "Cardiology"))
                    for item in case["records"]:
                        ledger.upsert_external_evidence("C", "PRIMARY_STUDY", item["pmid"],
                            source="PubMed", title=item["title"],
                            payload={"year": item["year"], "url": item["url"], "metadata": {"trial_registration_id": item["registry_id"], "comparison": item["comparison"]}})
                    snapshot = discovery_evidence_snapshot(ledger, "C")
                    observed = snapshot.unique_primary_study_candidates
                    family = snapshot.trial_family_audit
                    comparisons = sum(len(x["explicit_comparisons"]) for x in family["families"])
            row.update(expected=case["expected_reports"], observed=observed,
                       passed=(observed == case["expected_reports"] and family["registry_linked_families"] == case["reference_trial_families"]
                               and comparisons == case["reference_distinct_comparisons"]),
                       observed_trial_families=family["registry_linked_families"],
                       observed_explicit_comparisons=comparisons,
                       confirmed_independent_eligible_studies=None,
                       reference_trial_families=case["reference_trial_families"],
                       reference_distinct_comparisons=case["reference_distinct_comparisons"],
                       scientific_gap="Registry families and explicit comparisons are identified; full-text eligibility and population independence remain unverified",
                       reference_basis=case["reference_basis"])
        elif kind == "published_update_chronology":
            observed = date.fromisoformat(case["new_report_date"]) > date.fromisoformat(case["last_search_date"])
            row.update(expected=case["expected_after_cutoff"], observed=observed,
                       passed=observed == case["expected_after_cutoff"],
                       scientific_gap="Chronology alone cannot establish eligibility, novelty, or the need for an update",
                       reference_basis=case["reference_basis"])
        else:
            raise ValueError(f"Unknown benchmark case kind: {kind}")
        rows.append(row)
    policy = [r for r in rows if r["kind"] == "synthetic_policy"]
    return {"benchmark_version": fixture["version"], "cases": len(rows),
            "checks_passed": sum(r["passed"] for r in rows),
            "policy_checks_passed": sum(r["passed"] for r in policy),
            "policy_checks_total": len(policy),
            "known_scientific_gaps": sum("scientific_gap" in r for r in rows),
            "clinical_accuracy_validated": False, "live_ai_used": False,
            "results": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=Path("benchmarks/discovery_v1.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_benchmark(json.loads(args.fixture.read_text(encoding="utf-8")))
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["checks_passed"] == report["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
