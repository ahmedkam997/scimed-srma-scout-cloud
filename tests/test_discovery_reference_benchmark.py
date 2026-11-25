import json
from pathlib import Path
from scimed_scout.discovery.benchmark import run_benchmark

def test_reference_benchmark_is_offline_and_does_not_claim_clinical_validation():
    fixture = json.loads(Path("benchmarks/discovery_v1.json").read_text())
    result = run_benchmark(fixture)
    assert result["cases"] == 15
    assert result["policy_checks_total"] == 12
    assert result["checks_passed"] == result["cases"]
    assert not result["clinical_accuracy_validated"]
    assert not result["live_ai_used"]
    assert result["known_scientific_gaps"] == 3
    assert {x["id"] for x in result["results"] if x.get("scientific_gap")} == {"R01", "R02", "R03"}
