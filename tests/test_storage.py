from scimed_scout.domain import CandidateStatus, SourceStatus
from scimed_scout.storage import (
    CandidateRecord,
    DecisionRecord,
    ProjectRecord,
    SearchLogRecord,
    SQLiteLedger,
    SCHEMA_VERSION,
)


def test_discovery_ledger_persists_only_active_discovery_entities(tmp_path):
    db = tmp_path / "scout.sqlite3"
    with SQLiteLedger(db) as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Radiology", question_type="DIAGNOSTIC_ACCURACY"))
        ledger.upsert_candidate(
            CandidateRecord(
                candidate_id="C1",
                project_id="P1",
                title="Index test versus reference standard",
                specialty="Radiology",
                question_type="DIAGNOSTIC_ACCURACY",
                review_question="What is the diagnostic accuracy of the index test?",
                search_terms=["index test", "reference standard"],
            )
        )
        ledger.upsert_external_evidence(
            "C1",
            "PRIMARY_STUDY",
            "PMID1",
            source="PubMed",
            title="Primary study",
            payload={"doi": "10.1000/study"},
        )
        ledger.upsert_external_evidence(
            "C1",
            "PUBLISHED_REVIEW",
            "10.1000/review",
            source="Crossref",
            title="Prior review",
        )
        ledger.upsert_external_evidence(
            "C1",
            "REGISTRATION",
            "CRD420260000001",
            source="PROSPERO",
            title="Protocol",
        )
        ledger.append_search_log(
            SearchLogRecord(
                "P1",
                "C1",
                "PubMed",
                "index test",
                SourceStatus.SEARCHED_POSITIVE,
                12,
            )
        )
        ledger.append_decision(
            DecisionRecord(
                "D1",
                "P1",
                "C1",
                "QUALIFIED — FIRST-CHOICE REVIEW TOPIC",
                "REVIEW_DISCOVERY",
            )
        )
        ledger.add_query("P1", "C1", "PubMed", "index test", "primary-study feasibility discovery")
        ledger.update_checkpoint("P1", stage="REVIEW_DISCOVERY", progress=60)

    with SQLiteLedger(db) as reopened:
        assert SCHEMA_VERSION == 4
        assert reopened.get_project("P1").stage == "REVIEW_DISCOVERY"
        assert reopened.get_candidate("C1").title.startswith("Index test")
        assert {x["evidence_type"] for x in reopened.list_external_evidence("C1")} == {
            "PRIMARY_STUDY",
            "PUBLISHED_REVIEW",
            "REGISTRATION",
        }
        assert reopened.list_search_log("C1")[0].status == SourceStatus.SEARCHED_POSITIVE
        assert reopened.list_decisions("C1")[0].stage == "REVIEW_DISCOVERY"
        assert reopened.list_queries("C1")[0]["purpose"] == "primary-study feasibility discovery"

        tables = {
            row[0]
            for row in reopened.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "studies" not in tables
        assert "study_families" not in tables
        assert "outcomes" not in tables


def test_candidate_status_is_persistent_and_filterable(tmp_path):
    with SQLiteLedger(tmp_path / "scout.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Neurology"))
        ledger.upsert_candidate(CandidateRecord("C1", "P1", "Topic", "Neurology"))
        ledger.set_candidate_status("C1", CandidateStatus.REJECTED)
        assert ledger.get_candidate("C1").status == CandidateStatus.REJECTED
        assert [x.candidate_id for x in ledger.list_candidates("P1", CandidateStatus.REJECTED)] == ["C1"]


def test_external_evidence_type_is_validated(tmp_path):
    with SQLiteLedger(tmp_path / "x.sqlite3") as ledger:
        ledger.upsert_project(ProjectRecord("P1", "Medicine"))
        ledger.upsert_candidate(CandidateRecord("C1", "P1", "Topic", "Medicine"))
        try:
            ledger.upsert_external_evidence("C1", "NOT_A_REAL_TYPE", "X")
        except ValueError as exc:
            assert "Unsupported evidence type" in str(exc)
        else:
            raise AssertionError("invalid evidence type should fail")

def test_source_native_id_collision_keeps_both_records_and_updates_only_same_source(tmp_path):
    with SQLiteLedger(tmp_path/"identity.sqlite") as l:
        l.upsert_project(ProjectRecord("p","Medicine"));l.upsert_candidate(CandidateRecord("c","p","Q","Medicine"))
        for src in ("PubMed","Other"):
            l.upsert_external_evidence("c","PRIMARY_STUDY","123",source=src,title=src,payload={"source":src})
        l.upsert_external_evidence("c","PRIMARY_STUDY","123",source="PubMed",title="new",payload={"source":"updated"})
        rows=l.list_external_evidence("c")
        assert len(rows)==2
        assert {r["source"]:r["title"] for r in rows}=={"PubMed":"new","Other":"Other"}
        assert not l.evidence_identity_legacy_risk("c")

def test_v3_identity_migration_preserves_rows_and_flags_unrecoverable_history(tmp_path):
    import sqlite3
    db=tmp_path/"old.sqlite"
    with SQLiteLedger(db) as l:
        l.upsert_project(ProjectRecord("p","Medicine"));l.upsert_candidate(CandidateRecord("c","p","Q","Medicine"))
        l.upsert_external_evidence("c","PRIMARY_STUDY","123",source="PubMed",title="original",payload={"x":1})
        before=l.list_external_evidence("c")
    with sqlite3.connect(db) as con:
        con.executescript("""ALTER TABLE external_evidence RENAME TO current_rows;
          CREATE TABLE external_evidence(candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,evidence_type TEXT NOT NULL,
            source_record_id TEXT NOT NULL,source TEXT NOT NULL DEFAULT '',title TEXT NOT NULL DEFAULT '',payload_json TEXT NOT NULL DEFAULT '{}',updated_at TEXT NOT NULL,
            PRIMARY KEY(candidate_id,evidence_type,source_record_id));
          INSERT INTO external_evidence SELECT * FROM current_rows; DROP TABLE current_rows;
          UPDATE schema_meta SET value='3' WHERE key='schema_version';""")
    with SQLiteLedger(db) as l:
        assert l.list_external_evidence("c")==before
        assert l.evidence_identity_legacy_risk("c")
        l.upsert_external_evidence("c","PRIMARY_STUDY","123",source="Other",title="different")
        assert len(l.list_external_evidence("c"))==2
        assert l.connection.execute("PRAGMA foreign_key_check").fetchall()==[]
    with SQLiteLedger(db) as l:assert len(l.list_external_evidence("c"))==2
