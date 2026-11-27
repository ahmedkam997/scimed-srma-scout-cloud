"""Audit Academy benchmark admission, historical chronology and split isolation."""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from scimed_scout.discovery.competitor_records import _doi
from scimed_scout.discovery.scientific_verification_v2 import authenticated, digest
from scimed_scout.discovery.trial_family import ID_PATTERN

SCHEMA = "SCIMED_ACADEMY_BENCHMARK_V1"
NOMINATIONS_PATH = Path(__file__).resolve().parents[1] / "benchmarks" / "academy" / "nominations.json"
NOMINATIONS_SCHEMA = "SCIMED_ACADEMY_NOMINATION_QUEUE_V1"
SPLITS = ("train", "development", "test")
OPPORTUNITIES = ("UPDATE", "NOVEL", "NEGATIVE")
RECORD_KINDS = ("STUDY", "REVIEW", "REGISTRATION", "OTHER")
MIN_TEST_CASES = 30
QUESTION_FIELDS = ("population", "intervention", "comparator", "outcome")


def require_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} requires nonempty text")
    return value.strip()


def exact_date(value, field):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ValueError(f"{field} requires ISO YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} is outside the calendar") from exc


def string_list(value, field):
    if not isinstance(value, list):
        raise ValueError(f"{field} requires a list")
    return [require_text(item, field) for item in value]


def source_identity(url):
    parsed = urlsplit(require_text(url, "source_url"))
    if (parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None):
        raise ValueError("source_url requires a public HTTPS source")
    return (parsed.hostname.casefold(), parsed.path.rstrip("/"), parsed.query)


def source_keys(url):
    host, path, query = source_identity(url)
    keys = {("source_url", (host, path, query))}
    if host == "pubmed.ncbi.nlm.nih.gov" and re.fullmatch(r"/[1-9][0-9]*", path):
        keys.add(("pmid", path[1:]))
    if host in ("doi.org", "dx.doi.org") and (value := _doi(path[1:])):
        keys.add(("doi", value))
    if host in ("clinicaltrials.gov", "www.clinicaltrials.gov"):
        registry_id = path.rsplit("/", 1)[-1].upper()
        if re.fullmatch(r"NCT[0-9]{8}", registry_id):
            keys.add(("registration_ids", registry_id))
    return keys


def nomination_exposures(nominations):
    if (not isinstance(nominations, dict) or nominations.get("schema") != NOMINATIONS_SCHEMA
        or nominations.get("independent_test_use") != "EXCLUDED_DEVELOPMENT_EXPOSURE"
        or not isinstance(nominations.get("cases"), list)):
        raise ValueError("invalid public development nominations queue")
    keys = set()
    for row in nominations["cases"]:
        if not isinstance(row, dict):
            raise ValueError("invalid public development nomination")
        topic = require_text(row.get("topic_family_hint"), "topic_family_hint").casefold()
        keys.add(("topic_family_id", topic))
        for url in string_list(row.get("source_urls"), "source_urls"):
            keys.update(source_keys(url))
    return keys


def identity_keys(record):
    keys = source_keys(record.get("source_url"))
    ids = record.get("identifiers")
    if not isinstance(ids, dict):
        raise ValueError("evidence requires an identifiers object")
    allowed = {"pmid", "doi", "registration_ids", "trial_family_ids"}
    if ids.keys() - allowed:
        raise ValueError("evidence identifiers require an approved identifier type")
    for field in sorted(allowed):
        for raw in string_list(ids.get(field, []), field):
            value = raw.casefold()
            if field == "pmid":
                if not re.fullmatch(r"[1-9][0-9]*", value):
                    raise ValueError("PMID requires canonical digits")
            elif field == "doi":
                value = _doi(value)
                if not value:
                    raise ValueError("invalid DOI")
            elif field == "registration_ids":
                value = re.sub(r"\s+", "", raw).upper()
                if not (ID_PATTERN.fullmatch(value) or re.fullmatch(r"CRD[0-9]{11,14}", value)):
                    raise ValueError("invalid registry identifier")
            keys.add((field, value))
    if record["kind"] == "STUDY" and not any(kind == "trial_family_ids" for kind, _ in keys):
        raise ValueError("study evidence requires a trial-family identifier")
    return keys


def validate_reverse_replay(case, evidence, index):
    replay = case.get("reverse_replay")
    if not isinstance(replay, dict):
        raise ValueError("UPDATE requires a completed historical review pair")
    baseline = evidence.get(require_text(replay.get("baseline_review_id"), "baseline_review_id"))
    followup = evidence.get(require_text(replay.get("followup_review_id"), "followup_review_id"))
    if (baseline is None or followup is None
        or baseline[0]["kind"] != "REVIEW" or followup[0]["kind"] != "REVIEW"):
        raise ValueError("review pair must reference two evidence review rows")

    baseline_cutoff = exact_date(replay.get("baseline_search_through"), "baseline_search_through")
    followup_cutoff = exact_date(replay.get("followup_search_through"), "followup_search_through")
    if not baseline_cutoff <= baseline[1] <= index < followup[1]:
        raise ValueError("baseline and follow-up reviews straddle the index date")
    if not baseline_cutoff < followup_cutoff <= followup[1]:
        raise ValueError("follow-up search date must extend the baseline")
    if identity_keys(baseline[0]) & identity_keys(followup[0]):
        raise ValueError("review pair requires distinct publication identities")

    added = string_list(replay.get("added_report_ids"), "added_report_ids")
    if not added or len(added) != len(set(added)):
        raise ValueError("UPDATE requires distinct added study reports")
    pre_cutoff = set().union(*(
        identity_keys(row) for row, available in evidence.values()
        if row["kind"] == "STUDY" and available <= baseline_cutoff
    ))
    for rid in added:
        row = evidence.get(rid)
        if row is None or row[0]["kind"] != "STUDY":
            raise ValueError("added_report_ids must reference study evidence")
        if not baseline_cutoff < row[1] <= min(index, followup_cutoff):
            raise ValueError("added evidence must be post-baseline and available at prediction time")
        if identity_keys(row[0]) & pre_cutoff:
            raise ValueError("added evidence shares an identity with a pre-baseline study")


def validate_case(case):
    case_id = require_text(case.get("case_id"), "case_id")
    split = case.get("split")
    opportunity = case.get("opportunity")
    if split not in SPLITS or opportunity not in OPPORTUNITIES:
        raise ValueError("split or opportunity is outside the benchmark vocabulary")
    family = require_text(case.get("topic_family_id"), "topic_family_id").casefold()
    index = exact_date(case.get("index_date"), "index_date")
    evaluation = exact_date(case.get("evaluation_date"), "evaluation_date")
    if evaluation < index:
        raise ValueError("evaluation_date must be at or after index_date")
    question = case.get("question")
    if not isinstance(question, dict):
        raise ValueError("question requires a PICO object")
    for field in QUESTION_FIELDS:
        require_text(question.get(field), f"question.{field}")

    raw_evidence = case.get("evidence")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        raise ValueError("evidence requires a nonempty list")
    evidence = {}
    keys = {("topic_family_id", family)}
    for record in raw_evidence:
        if not isinstance(record, dict) or record.get("kind") not in RECORD_KINDS:
            raise ValueError("evidence record kind is outside the benchmark vocabulary")
        record_id = require_text(record.get("record_id"), "record_id")
        if record_id in evidence:
            raise ValueError("duplicate case-local evidence record ID")
        require_text(record.get("locator"), "evidence locator")
        available = exact_date(record.get("available_on"), "evidence.available_on")
        if available > evaluation:
            raise ValueError("evidence became available after evaluation_date")
        evidence[record_id] = (record, available)
        keys.update(identity_keys(record))

    if opportunity == "UPDATE":
        validate_reverse_replay(case, evidence, index)
    return case_id, split, opportunity, index, evaluation, evidence, keys


def case_digest(case):
    return digest({key: value for key, value in case.items() if key != "adjudication"})


def approve(case, bundle, reviewer_keys, evidence):
    submission, _ = authenticated(bundle, reviewer_keys)
    if (submission.get("schema") != SCHEMA or submission.get("case_id") != case["case_id"]
        or submission.get("case_sha256") != case_digest(case)):
        raise ValueError("signed submission must bind the exact benchmark case")
    require_text(submission.get("rationale"), "adjudication rationale")
    records = string_list(submission.get("rationale_record_ids"), "rationale_record_ids")
    if not records or not set(records) <= evidence.keys():
        raise ValueError("adjudication rationale must link to indexed evidence")


def model_observation(case):
    """Project the prespecified PICO and identifiers available at the index."""
    _, _, _, index, _, evidence, _ = validate_case(case)
    return {
        "case_id": case["case_id"],
        "index_date": case["index_date"],
        "question": {key: case["question"][key] for key in QUESTION_FIELDS},
        "available_records": [
            {key: row[key] for key in ("record_id", "kind", "available_on", "source_url")}
            for row, available in evidence.values() if available <= index
        ],
    }


def audit_manifest(manifest, reviewer_keys=None):
    if (not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA
        or not isinstance(manifest.get("cases"), list)):
        raise ValueError("manifest requires the benchmark schema and a cases list")

    exposed = nomination_exposures(json.loads(NOMINATIONS_PATH.read_text()))
    issues = []
    structurally_valid = []
    pending = []
    admitted = Counter()
    test_labels = Counter()
    seen_ids = set()
    identities = defaultdict(set)
    positions = defaultdict(list)
    for position, case in enumerate(manifest["cases"], start=1):
        if not isinstance(case, dict):
            issues.append(f"case {position}: expected an object")
            continue
        try:
            case_id, split, label, index, evaluation, evidence, keys = validate_case(case)
            if case_id.casefold() in seen_ids:
                raise ValueError("case_id already used")
            seen_ids.add(case_id.casefold())
        except (ValueError, TypeError) as exc:
            issues.append(f"case {position}: {exc}")
            continue

        structurally_valid.append(case_id)
        positions[split].append((index, evaluation))
        for key in keys:
            identities[key].add(split)

        if split == "test" and (shared := keys & exposed):
            kinds = ", ".join(sorted({kind for kind, _ in shared}))
            issues.append(f"case {position}: known public nomination exposure through {kinds}")
            continue

        bundle = case.get("adjudication")
        if bundle is None or reviewer_keys is None:
            pending.append(case_id)
            continue
        try:
            approve(case, bundle, reviewer_keys, evidence)
        except (ValueError, TypeError) as exc:
            issues.append(f"case {position}: {exc}")
            continue
        admitted[split] += 1
        if split == "test":
            test_labels[label] += 1

    cross_split = Counter(kind for (kind, _), splits in identities.items() if len(splits) > 1)
    for kind, count in sorted(cross_split.items()):
        issues.append(f"split leakage through {count} shared {kind} identities")

    populated = [split for split in SPLITS if positions[split]]
    for earlier, later in zip(populated, populated[1:]):
        if max(row[1] for row in positions[earlier]) >= min(row[0] for row in positions[later]):
            issues.append(f"temporal leakage between {earlier} evaluation and {later} prediction")

    ready = (
        not issues and not pending and admitted["test"] >= MIN_TEST_CASES
        and all(test_labels[label] for label in OPPORTUNITIES)
    )
    return {
        "schema": SCHEMA,
        "benchmark_ready": ready,
        "minimum_independent_test_cases": MIN_TEST_CASES,
        "structurally_valid_case_count": len(structurally_valid),
        "signed_admitted_counts": {split: admitted[split] for split in SPLITS},
        "signed_test_class_counts": {label: test_labels[label] for label in OPPORTUNITIES},
        "pending_adjudication": pending,
        "issues": issues,
        "qualification_granted": False,
    }


def read_keys(path):
    if path is None:
        return None
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value.values()):
        raise ValueError("reviewer keys require an object of reviewer IDs and hex keys")
    try:
        return {reviewer: bytes.fromhex(key) for reviewer, key in value.items()}
    except ValueError as exc:
        raise ValueError("reviewer keys require valid hexadecimal values") from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--reviewer-keys", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    try:
        data = json.loads(args.manifest.read_text())
        report = audit_manifest(data, read_keys(args.reviewer_keys))
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    encoded = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")
    if report["issues"] or (args.require_ready and not report["benchmark_ready"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
