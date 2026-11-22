from __future__ import annotations
from dataclasses import asdict, dataclass
from enum import StrEnum
import json
from pathlib import Path

class Stage(StrEnum):
    NEW = "NEW"
    DISCOVERY = "DISCOVERY"
    RANKING = "RANKING"
    DEEP_VERIFY = "DEEP_VERIFY"
    STUDY_FAMILY_AUDIT = "STUDY_FAMILY_AUDIT"
    TRIAL_FAMILY_AUDIT = "TRIAL_FAMILY_AUDIT"
    SYNTHESIS_USABILITY = "SYNTHESIS_USABILITY"
    NUMERICAL_USABILITY = "NUMERICAL_USABILITY"
    REVIEW_OVERLAP = "REVIEW_OVERLAP"
    REGISTRY_OVERLAP = "REGISTRY_OVERLAP"
    ONGOING_TRIALS = "ONGOING_TRIALS"
    NOVELTY_AUDIT = "NOVELTY_AUDIT"
    LOCKED_GATES = "LOCKED_GATES"
    EDITORIAL_STRESS_TEST = "EDITORIAL_STRESS_TEST"
    EXPORT = "EXPORT"
    COMPLETE = "COMPLETE"
    PAUSED = "PAUSED"
    FAILED = "FAILED"

@dataclass(slots=True)
class ProjectCheckpoint:
    project_id: str
    specialty: str
    stage: Stage = Stage.NEW
    progress: int = 0
    message: str = ""
    last_completed_stage: str = ""

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ProjectCheckpoint":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        raw["stage"] = Stage(raw["stage"])
        return cls(**raw)
