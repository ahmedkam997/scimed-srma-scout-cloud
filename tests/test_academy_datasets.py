import hashlib
import json

from scripts import academy_datasets


def source(path, content, kind, *, pinned=True):
    return {
        "path": path,
        "url": "https://example.test/pinned/" + path,
        "kind": kind,
        "sha256": hashlib.sha256(content).hexdigest() if pinned else None,
    }


def test_acquisition_rejects_modified_cache_before_auditing_bytes(tmp_path):
    fixture = b"record_id,pubmedID,label_included\n1,124,1\n2,125,0\n"
    artifact = source("data.csv", fixture, "cohen_csv")
    (tmp_path / "data.csv").write_bytes(fixture.replace(b"124", b"126"))
    audit, ids = academy_datasets.audit_artifact(tmp_path, artifact)
    assert audit["status"] == "CHECKSUM_MISMATCH"
    assert not ids
    assert "label_counts" not in audit


def test_reports_overlap_without_promoting_task_data(tmp_path):
    first = b"record_id,pubmedID,label_included\n1,124,1\n2,,0\n"
    second = b"record_id,pubmedID,label_included\n1,124,0\n2,125,1\n"
    artifacts = [source("first.csv", first, "cohen_csv"), source("second.csv", second, "cohen_csv")]
    for artifact, fixture in zip(artifacts, (first, second)):
        (tmp_path / artifact["path"]).write_bytes(fixture)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "datasets": [
            {"id": name, "source_families": ["shared"], "artifacts": [artifact]}
            for name, artifact in zip(("first", "second"), artifacts)
        ],
    }))
    audited = academy_datasets.audit_manifest(tmp_path, manifest_path=manifest)
    assert audited["observed_article_overlap"] == [{"datasets": ["first", "second"], "shared_article_pmids": 1}]
    assert audited["datasets"]["first"]["artifacts"][0]["rows_without_pmid"] == 1
    assert not audited["study_family_leakage_cleared"]
    assert not audited["datasets"]["first"]["training_approved"]
    assert not audited["datasets"]["second"]["independent_test_approved"]
    assert not audited["qualification_granted"]


def test_cross_file_review_mismatch_remains_incomplete(tmp_path):
    data = {
        "reviews.csv": b"PMID,Title,PICO,Topic\n100,Review,PICO,Topic\n",
        "screening.jsonl": b'{"PMID": 101, "Title": "Review", "PICO": "PICO", "Topic": "Topic", "Involved_Citations": []}\n',
    }
    artifacts = []
    for (name, content), kind in zip(data.items(), ("review_csv", "review_jsonl")):
        (tmp_path / name).write_bytes(content)
        artifacts.append(source(name, content, kind, pinned=False))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": 1, "datasets": [{"id": "review", "artifacts": artifacts}]}))
    report = academy_datasets.audit_manifest(tmp_path, manifest_path=manifest)["datasets"]["review"]
    assert report["status"] == "INCOMPLETE"
    assert report["cross_file_review_id_mismatch"]
    assert all(row["status"] == "DIGEST_NOT_PINNED" for row in report["artifacts"])
