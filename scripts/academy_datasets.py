"""Stage approved public benchmark inputs and audit their provenance and coverage."""

import argparse
import csv
import hashlib
import itertools
import json
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from io import BytesIO, StringIO
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "benchmarks/academy/datasets.json"
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


def pmid(value):
    normalized = str(value or "").strip().removeprefix("https://pubmed.ncbi.nlm.nih.gov/").rstrip("/")
    return normalized if normalized.isascii() and normalized.isdigit() else ""


def audit_labeled_rows(rows, kind):
    id_field, pmid_field = (
        ("record_id", "pubmedID") if kind == "cohen_csv" else ("openalex_id", "pmid")
    )
    ids = [row[id_field].strip() for row in rows]
    labels = Counter(row["label_included"].strip() for row in rows)
    if not rows or "" in ids or len(set(ids)) != len(ids) or set(labels) != {"0", "1"}:
        raise ValueError("Expected unique nonempty source IDs and both binary labels")
    pubmed_ids = [pmid(row[pmid_field]) for row in rows]
    if any(row[pmid_field].strip() and not valid for row, valid in zip(rows, pubmed_ids)):
        raise ValueError("Invalid nonempty PubMed identifier")
    return {
        "rows": len(rows),
        "label_counts": dict(labels),
        "rows_without_pmid": pubmed_ids.count(""),
        "duplicate_pmid_rows": len([value for value in pubmed_ids if value]) - len(set(pubmed_ids) - {""}),
    }, set(pubmed_ids) - {""}


def audit_review_rows(rows, kind):
    required = {"PMID", "Title", "PICO", "Topic"}
    if kind == "review_jsonl":
        required.add("Involved_Citations")
    if not rows or any(not isinstance(row, dict) or not required <= row.keys() for row in rows):
        raise ValueError("Missing review, PICO or cited report fields")
    ids = [pmid(row["PMID"]) for row in rows]
    if "" in ids or len(set(ids)) != len(ids) or any(not row["Title"] or not row["PICO"] for row in rows):
        raise ValueError("Expected unique review PMIDs with titles and PICO")
    return {"rows": len(rows), "topic_counts": dict(Counter(str(row["Topic"]) for row in rows))}, set(ids)


def audit_content(data, kind):
    if kind == "zip":
        with zipfile.ZipFile(BytesIO(data)) as archive:
            files = [entry for entry in archive.infolist() if not entry.is_dir()]
            if not files or any(not entry.filename.endswith(".json") for entry in files):
                raise ValueError("Expected a nonempty archive of JSON work batches")
            # Manifest digest verifies the payload; enumeration needs no extraction.
            return {"archived_json_files": len(files)}, set()
    text = data.decode("utf-8-sig")
    if kind in {"cohen_csv", "synergy_csv"}:
        return audit_labeled_rows(list(csv.DictReader(StringIO(text))), kind)
    if kind in {"review_csv", "review_jsonl"}:
        rows = list(csv.DictReader(StringIO(text))) if kind == "review_csv" else [
            json.loads(line) for line in text.splitlines() if line.strip()
        ]
        return audit_review_rows(rows, kind)
    if kind == "object":
        if not isinstance(json.loads(text), dict):
            raise ValueError("Expected a JSON metadata object")
        return {}, set()
    if kind == "csmed_inventory":
        if "Cohen et al. (2006)" not in text:
            raise ValueError("The expected Cohen collection is missing from the CSMeD inventory")
        return {"cohen_collection_listed": True}, set()
    if kind == "text" and text.strip():
        return {}, set()
    raise ValueError("Unsupported artifact format or empty text")


def download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "SciMed-Research-Academy/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        if not response.geturl().startswith("https://"):
            raise ValueError("Expected HTTPS dataset acquisition")
        return response.read(MAX_ARTIFACT_BYTES + 1)


def audit_artifact(stage, artifact, *, fetch=False):
    path = stage / artifact["path"]
    result = {"path": artifact["path"], "kind": artifact["kind"]}
    try:
        if path.is_file():
            with path.open("rb") as source:
                data = source.read(MAX_ARTIFACT_BYTES + 1)
        elif fetch:
            data = download(artifact["url"])
        else:
            return {**result, "status": "UNAVAILABLE"}, set()
    except urllib.error.HTTPError as exc:
        return {**result, "status": "UNAVAILABLE", "http_status": exc.code}, set()
    except (OSError, ValueError) as exc:
        return {**result, "status": "UNAVAILABLE", "error_type": type(exc).__name__}, set()
    if len(data) > MAX_ARTIFACT_BYTES:
        return {**result, "status": "SIZE_LIMIT_EXCEEDED"}, set()
    digest = hashlib.sha256(data).hexdigest()
    expected = artifact["sha256"]
    result.update(bytes=len(data), sha256=digest, expected_sha256=expected)
    if expected is not None and digest != expected:
        return {**result, "status": "CHECKSUM_MISMATCH"}, set()
    try:
        summary, ids = audit_content(data, artifact["kind"])
    except (ValueError, KeyError, TypeError, AttributeError, csv.Error, zipfile.BadZipFile) as exc:
        return {**result, "status": "SCHEMA_INVALID", "error": str(exc)}, set()
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return {**result, **summary, "status": "VERIFIED" if expected else "DIGEST_NOT_PINNED"}, ids


def audit_manifest(stage, *, dataset_ids=None, fetch=False, manifest_path=MANIFEST):
    manifest = json.loads(manifest_path.read_text())
    selected = set(dataset_ids or (row["id"] for row in manifest["datasets"]))
    unknown = selected - {row["id"] for row in manifest["datasets"]}
    if unknown:
        raise ValueError(f"Unknown dataset IDs: {', '.join(sorted(unknown))}")
    datasets = {}
    article_sets = {}
    for row in manifest["datasets"]:
        if row["id"] not in selected:
            continue
        artifacts = []
        articles = set()
        review_sets = []
        for artifact in row["artifacts"]:
            result, ids = audit_artifact(stage, artifact, fetch=fetch)
            artifacts.append(result)
            if artifact["kind"] in {"cohen_csv", "synergy_csv"}:
                articles.update(ids)
            if artifact["kind"] in {"review_csv", "review_jsonl"}:
                review_sets.append(ids)
        valid = {"VERIFIED", "DIGEST_NOT_PINNED"}
        review_id_mismatch = len(review_sets) > 1 and any(ids != review_sets[0] for ids in review_sets)
        status = "SOURCE_REVIEW_REQUIRED"
        if artifacts:
            status = "VERIFIED"
            if any(artifact["status"] not in valid for artifact in artifacts) or review_id_mismatch:
                status = "INCOMPLETE"
            elif any(artifact["status"] == "DIGEST_NOT_PINNED" for artifact in artifacts):
                status = "DIGEST_NOT_PINNED"
        datasets[row["id"]] = {
            **{key: value for key, value in row.items() if key != "artifacts"},
            "status": status,
            "cross_file_review_id_mismatch": review_id_mismatch,
            "artifacts": artifacts,
            "training_approved": False,
            "independent_test_approved": False,
        }
        if articles:
            article_sets[row["id"]] = articles
    overlap = [
        {"datasets": [left, right], "shared_article_pmids": len(article_sets[left] & article_sets[right])}
        for left, right in itertools.combinations(sorted(article_sets), 2)
    ]
    return {
        "schema_version": manifest["schema_version"],
        "datasets": datasets,
        "observed_article_overlap": overlap,
        "study_family_leakage_cleared": False,
        "qualification_granted": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True, help="Directory for local source files")
    parser.add_argument("--output", type=Path, required=True, help="Write audit JSON without raw text or labels")
    parser.add_argument("--dataset", action="append", help="Select one dataset ID; repeat as needed")
    parser.add_argument("--fetch", action="store_true", help="Acquire missing public inputs from pinned sources")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero on incomplete or unpinned acquisitions")
    args = parser.parse_args()
    audit = audit_manifest(args.stage, dataset_ids=args.dataset, fetch=args.fetch)
    args.output.write_text(json.dumps(audit, indent=2) + "\n")
    if args.strict and any(
        row["status"] not in {"VERIFIED", "SOURCE_REVIEW_REQUIRED"} for row in audit["datasets"].values()
    ):
        raise SystemExit("One or more selected dataset acquisitions remain unverified")


if __name__ == "__main__":
    main()
