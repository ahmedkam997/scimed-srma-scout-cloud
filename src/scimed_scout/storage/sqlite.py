from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from scimed_scout.domain import CandidateStatus, SourceStatus
from .models import CandidateRecord, DecisionRecord, ProjectRecord, SearchLogRecord, utc_now


SCHEMA_VERSION = 1


class SQLiteLedger:
    """Persistent evidence ledger using only Python's standard library."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLiteLedger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                specialty TEXT NOT NULL,
                question_type TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT 'NEW',
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS candidates (
                candidate_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                specialty TEXT NOT NULL,
                question_type TEXT NOT NULL DEFAULT '',
                review_question TEXT NOT NULL DEFAULT '',
                population TEXT NOT NULL DEFAULT '',
                intervention_exposure_index_test TEXT NOT NULL DEFAULT '',
                comparator_reference TEXT NOT NULL DEFAULT '',
                outcomes_json TEXT NOT NULL DEFAULT '[]',
                eligible_designs_json TEXT NOT NULL DEFAULT '[]',
                rationale TEXT NOT NULL DEFAULT '',
                novelty_hypothesis TEXT NOT NULL DEFAULT '',
                search_terms_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'DISCOVERED',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS study_families (
                family_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (candidate_id, family_id)
            );

            CREATE TABLE IF NOT EXISTS studies (
                study_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
                family_id TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (candidate_id, study_id)
            );

            CREATE TABLE IF NOT EXISTS outcomes (
                outcome_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
                family_id TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (candidate_id, outcome_id)
            );

            CREATE TABLE IF NOT EXISTS search_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                query TEXT NOT NULL,
                status TEXT NOT NULL,
                result_count INTEGER,
                searched_at TEXT NOT NULL,
                fallback_used TEXT NOT NULL DEFAULT '',
                message TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS decision_history (
                decision_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
                decision TEXT NOT NULL,
                stage TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS query_library (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                query TEXT NOT NULL,
                purpose TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(candidate_id, source, query, purpose)
            );

            CREATE INDEX IF NOT EXISTS idx_candidates_project ON candidates(project_id);
            CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
            CREATE INDEX IF NOT EXISTS idx_search_candidate ON search_log(candidate_id);
            CREATE INDEX IF NOT EXISTS idx_decision_candidate ON decision_history(candidate_id);
            """
        )
        self.connection.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.connection.commit()

    def upsert_project(self, record: ProjectRecord) -> None:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO projects(project_id,specialty,question_type,stage,status,progress,message,metadata_json,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(project_id) DO UPDATE SET
                specialty=excluded.specialty,
                question_type=excluded.question_type,
                stage=excluded.stage,
                status=excluded.status,
                progress=excluded.progress,
                message=excluded.message,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at
            """,
            (
                record.project_id, record.specialty, record.question_type, record.stage,
                record.status, int(record.progress), record.message, _dump(record.metadata),
                record.created_at, now,
            ),
        )
        self.connection.commit()

    def get_project(self, project_id: str) -> ProjectRecord | None:
        row = self.connection.execute("SELECT * FROM projects WHERE project_id=?", (project_id,)).fetchone()
        return _project(row) if row else None

    def list_projects(self) -> list[ProjectRecord]:
        rows = self.connection.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [_project(row) for row in rows]

    def update_checkpoint(self, project_id: str, *, stage: str, progress: int, message: str = "") -> None:
        self.connection.execute(
            "UPDATE projects SET stage=?, progress=?, message=?, updated_at=? WHERE project_id=?",
            (stage, int(progress), message, utc_now(), project_id),
        )
        self.connection.commit()

    def upsert_candidate(self, record: CandidateRecord) -> None:
        now = utc_now()
        self.connection.execute(
            """
            INSERT INTO candidates(
                candidate_id,project_id,title,specialty,question_type,review_question,population,
                intervention_exposure_index_test,comparator_reference,outcomes_json,eligible_designs_json,
                rationale,novelty_hypothesis,search_terms_json,status,metadata_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(candidate_id) DO UPDATE SET
                title=excluded.title,
                specialty=excluded.specialty,
                question_type=excluded.question_type,
                review_question=excluded.review_question,
                population=excluded.population,
                intervention_exposure_index_test=excluded.intervention_exposure_index_test,
                comparator_reference=excluded.comparator_reference,
                outcomes_json=excluded.outcomes_json,
                eligible_designs_json=excluded.eligible_designs_json,
                rationale=excluded.rationale,
                novelty_hypothesis=excluded.novelty_hypothesis,
                search_terms_json=excluded.search_terms_json,
                status=excluded.status,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at
            """,
            (
                record.candidate_id, record.project_id, record.title, record.specialty,
                record.question_type, record.review_question, record.population,
                record.intervention_exposure_index_test, record.comparator_reference,
                _dump(record.outcomes), _dump(record.eligible_designs), record.rationale,
                record.novelty_hypothesis, _dump(record.search_terms), record.status.value,
                _dump(record.metadata), record.created_at, now,
            ),
        )
        self.connection.commit()

    def get_candidate(self, candidate_id: str) -> CandidateRecord | None:
        row = self.connection.execute("SELECT * FROM candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        return _candidate(row) if row else None

    def list_candidates(self, project_id: str, status: CandidateStatus | None = None) -> list[CandidateRecord]:
        if status is None:
            rows = self.connection.execute(
                "SELECT * FROM candidates WHERE project_id=? ORDER BY created_at",
                (project_id,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT * FROM candidates WHERE project_id=? AND status=? ORDER BY created_at",
                (project_id, status.value),
            ).fetchall()
        return [_candidate(row) for row in rows]

    def set_candidate_status(self, candidate_id: str, status: CandidateStatus) -> None:
        self.connection.execute(
            "UPDATE candidates SET status=?, updated_at=? WHERE candidate_id=?",
            (status.value, utc_now(), candidate_id),
        )
        self.connection.commit()

    def upsert_payload(self, table: str, candidate_id: str, item_id: str, payload: dict[str, Any], *, family_id: str = "") -> None:
        allowed = {"study_families", "studies", "outcomes"}
        if table not in allowed:
            raise ValueError(f"Unsupported ledger table: {table}")
        id_column = {"study_families": "family_id", "studies": "study_id", "outcomes": "outcome_id"}[table]
        if table == "study_families":
            sql = f"""
                INSERT INTO {table}({id_column},candidate_id,payload_json,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(candidate_id,{id_column}) DO UPDATE SET
                    payload_json=excluded.payload_json,updated_at=excluded.updated_at
            """
            values = (item_id, candidate_id, _dump(payload), utc_now())
        else:
            sql = f"""
                INSERT INTO {table}({id_column},candidate_id,family_id,payload_json,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(candidate_id,{id_column}) DO UPDATE SET
                    family_id=excluded.family_id,payload_json=excluded.payload_json,updated_at=excluded.updated_at
            """
            values = (item_id, candidate_id, family_id, _dump(payload), utc_now())
        self.connection.execute(sql, values)
        self.connection.commit()

    def list_payloads(self, table: str, candidate_id: str) -> list[dict[str, Any]]:
        if table not in {"study_families", "studies", "outcomes"}:
            raise ValueError(f"Unsupported ledger table: {table}")
        rows = self.connection.execute(
            f"SELECT payload_json FROM {table} WHERE candidate_id=? ORDER BY rowid",
            (candidate_id,),
        ).fetchall()
        return [_load(row["payload_json"], {}) for row in rows]

    def append_search_log(self, record: SearchLogRecord) -> int:
        cursor = self.connection.execute(
            """
            INSERT INTO search_log(project_id,candidate_id,source,query,status,result_count,searched_at,fallback_used,message)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                record.project_id, record.candidate_id, record.source, record.query,
                record.status.value, record.result_count, record.searched_at,
                record.fallback_used, record.message,
            ),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def list_search_log(self, candidate_id: str) -> list[SearchLogRecord]:
        rows = self.connection.execute(
            "SELECT * FROM search_log WHERE candidate_id=? ORDER BY id",
            (candidate_id,),
        ).fetchall()
        return [
            SearchLogRecord(
                project_id=row["project_id"], candidate_id=row["candidate_id"],
                source=row["source"], query=row["query"], status=SourceStatus(row["status"]),
                result_count=row["result_count"], searched_at=row["searched_at"],
                fallback_used=row["fallback_used"], message=row["message"],
            )
            for row in rows
        ]

    def append_decision(self, record: DecisionRecord) -> None:
        self.connection.execute(
            """
            INSERT INTO decision_history(decision_id,project_id,candidate_id,decision,stage,reason,payload_json,created_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                record.decision_id, record.project_id, record.candidate_id, record.decision,
                record.stage, record.reason, _dump(record.payload), record.created_at,
            ),
        )
        self.connection.commit()

    def list_decisions(self, candidate_id: str) -> list[DecisionRecord]:
        rows = self.connection.execute(
            "SELECT * FROM decision_history WHERE candidate_id=? ORDER BY created_at, rowid",
            (candidate_id,),
        ).fetchall()
        return [
            DecisionRecord(
                decision_id=row["decision_id"], project_id=row["project_id"],
                candidate_id=row["candidate_id"], decision=row["decision"],
                stage=row["stage"], reason=row["reason"],
                payload=_load(row["payload_json"], {}), created_at=row["created_at"],
            )
            for row in rows
        ]

    def add_query(self, project_id: str, candidate_id: str, source: str, query: str, purpose: str = "") -> None:
        self.connection.execute(
            """
            INSERT OR IGNORE INTO query_library(project_id,candidate_id,source,query,purpose,created_at)
            VALUES(?,?,?,?,?,?)
            """,
            (project_id, candidate_id, source, query, purpose, utc_now()),
        )
        self.connection.commit()

    def list_queries(self, candidate_id: str) -> list[dict[str, str]]:
        rows = self.connection.execute(
            "SELECT source,query,purpose,created_at FROM query_library WHERE candidate_id=? ORDER BY id",
            (candidate_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _load(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except Exception:
        return default


def _project(row: sqlite3.Row) -> ProjectRecord:
    return ProjectRecord(
        project_id=row["project_id"], specialty=row["specialty"],
        question_type=row["question_type"], stage=row["stage"], status=row["status"],
        progress=row["progress"], message=row["message"],
        metadata=_load(row["metadata_json"], {}), created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _candidate(row: sqlite3.Row) -> CandidateRecord:
    return CandidateRecord(
        candidate_id=row["candidate_id"], project_id=row["project_id"], title=row["title"],
        specialty=row["specialty"], question_type=row["question_type"],
        review_question=row["review_question"], population=row["population"],
        intervention_exposure_index_test=row["intervention_exposure_index_test"],
        comparator_reference=row["comparator_reference"], outcomes=_load(row["outcomes_json"], []),
        eligible_designs=_load(row["eligible_designs_json"], []), rationale=row["rationale"],
        novelty_hypothesis=row["novelty_hypothesis"], search_terms=_load(row["search_terms_json"], []),
        status=CandidateStatus(row["status"]), metadata=_load(row["metadata_json"], {}),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )
