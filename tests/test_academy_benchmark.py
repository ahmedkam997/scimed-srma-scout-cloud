from copy import deepcopy

from scimed_scout.discovery.scientific_verification_v2 import signature
from scripts.academy_benchmark import SCHEMA, audit_manifest, case_digest, model_observation

KEYS = {"reviewer-one": b"1" * 32, "reviewer-two": b"2" * 32}


def row(record_id, kind, day, pmid, *, family=None, doi=None):
    return {
        "record_id": record_id,
        "kind": kind,
        "available_on": day,
        "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "locator": "Methods",
        "identifiers": {
            "pmid": [pmid],
            "doi": [doi] if doi else [],
            "trial_family_ids": [family] if family else [],
        },
    }


def case(n=1, split="test", label="UPDATE"):
    value = {
        "case_id": f"case-{n}",
        "topic_family_id": f"topic-{n}",
        "split": split,
        "opportunity": label,
        "index_date": "2024-01-01",
        "evaluation_date": "2025-01-01",
        "question": {"population": "P", "intervention": "I", "comparator": "C", "outcome": "O"},
        "evidence": [row("new-study", "STUDY", "2023-03-10", f"1{n}", family=f"trial-{n}")],
    }
    if label == "UPDATE":
        value["evidence"].extend([
            row("baseline", "REVIEW", "2023-02-03", f"2{n}"),
            row("followup", "REVIEW", "2024-11-01", f"3{n}"),
        ])
        value["reverse_replay"] = {
            "baseline_review_id": "baseline",
            "followup_review_id": "followup",
            "baseline_search_through": "2023-01-02",
            "followup_search_through": "2024-06-04",
            "added_report_ids": ["new-study"],
        }
    return value


def signed(value, keys=KEYS):
    submission = {
        "schema": SCHEMA,
        "case_id": value["case_id"],
        "case_sha256": case_digest(value),
        "rationale": "Synthetic source-backed fixture",
        "rationale_record_ids": ["new-study"],
        "independent_extraction_and_screening_attested": True,
    }
    return {
        **value,
        "adjudication": {
            "submission": submission,
            "approvals": [
                {"reviewer": reviewer, "signature": signature(submission, reviewer, key)}
                for reviewer, key in keys.items()
            ],
        },
    }


def manifest(*cases):
    return {"schema": SCHEMA, "cases": list(cases)}


def test_empty_manifest_is_valid_but_benchmark_is_not_ready():
    result = audit_manifest(manifest())
    assert result["issues"] == []
    assert result["minimum_independent_test_cases"] == 30
    assert not result["benchmark_ready"] and not result["qualification_granted"]


def test_unsigned_or_unsigned_by_available_keys_is_pending():
    unsigned = case()
    first = audit_manifest(manifest(unsigned), KEYS)
    second = audit_manifest(manifest(signed(unsigned)))
    assert first["pending_adjudication"] == second["pending_adjudication"] == ["case-1"]
    assert first["signed_admitted_counts"]["test"] == 0


def test_signed_admission_requires_three_classes_and_thirty_test_cases():
    data = manifest(*(signed(case(n, label=("UPDATE", "NOVEL", "NEGATIVE")[n % 3])) for n in range(1, 31)))
    result = audit_manifest(data, KEYS)
    assert result["issues"] == []
    assert result["signed_test_class_counts"] == {"UPDATE": 10, "NOVEL": 10, "NEGATIVE": 10}
    assert result["benchmark_ready"] and not result["qualification_granted"]
    data["cases"].pop()
    assert not audit_manifest(data, KEYS)["benchmark_ready"]


def test_edited_signed_case_cannot_be_admitted():
    value = signed(case())
    value["question"]["outcome"] = "Different outcome"
    result = audit_manifest(manifest(value), KEYS)
    assert result["signed_admitted_counts"]["test"] == 0
    assert "exact benchmark case" in result["issues"][0]


def test_both_signers_require_distinct_trusted_keys():
    duplicates = {"reviewer-one": b"s" * 32, "reviewer-two": b"s" * 32}
    result = audit_manifest(manifest(signed(case(), duplicates)), duplicates)
    assert "distinct trusted reviewer keys" in result["issues"][0]


def test_future_review_and_label_never_in_observation():
    value = signed(case())
    result = model_observation(value)
    assert result.keys() == {"case_id", "index_date", "question", "available_records"}
    assert {r["record_id"] for r in result["available_records"]} == {"baseline", "new-study"}


def test_update_cannot_depend_on_studies_unavailable_at_index():
    value = case()
    value["evidence"][0]["available_on"] = "2024-02-02"
    result = audit_manifest(manifest(value), KEYS)
    assert "available at prediction time" in result["issues"][0]


def test_update_cannot_recount_an_earlier_trial_family():
    value = case()
    value["evidence"].append(row("old-study", "STUDY", "2022-09-01", "99", family="Trial-1"))
    result = audit_manifest(manifest(value), KEYS)
    assert "pre-baseline study" in result["issues"][0]


def test_shared_family_and_doi_aliased_between_splits_are_rejected():
    first = case(1, "train", "NOVEL")
    second = case(2, "test", "NEGATIVE")
    first["evidence"][0]["identifiers"]["doi"] = ["10.5555/EXAMPLE"]
    second["evidence"][0]["source_url"] = "https://doi.org/10.5555/example"
    second["evidence"][0]["identifiers"]["trial_family_ids"] = ["TRIAL-1"]
    second["index_date"] = second["evaluation_date"] = "2026-01-01"
    result = audit_manifest(manifest(first, second), KEYS)
    assert {"split leakage through 1 shared doi identities",
            "split leakage through 1 shared trial_family_ids identities"} <= set(result["issues"])


def test_training_data_must_exist_before_later_prediction():
    first = case(1, "train")
    second = deepcopy(case(2, "test"))
    result = audit_manifest(manifest(first, second), KEYS)
    assert "temporal leakage between train evaluation and test prediction" in result["issues"]



def test_nominated_public_report_is_ineligible_for_test_even_with_trusted_signatures():
    value = case(label="NOVEL")
    value["evidence"][0]["identifiers"]["pmid"] = ["30146931"]
    result = audit_manifest(manifest(signed(value)), KEYS)
    assert "known public nomination exposure through pmid" in result["issues"][0]
    assert result["signed_admitted_counts"]["test"] == 0


def test_nominated_public_topic_alias_is_ineligible_for_test():
    value = signed({**case(label="NEGATIVE"), "topic_family_id": "ASPIRIN-PRIMARY-CVD"})
    result = audit_manifest(manifest(value), KEYS)
    assert "known public nomination exposure through topic_family_id" in result["issues"][0]
