"""Temporary, device-scoped memory of previously checked review questions.

This is a conservative reuse filter, not a clinical semantic-equivalence model.
In particular, a different comparator, patient population, outcome or study
design must not be suppressed merely because titles look alike.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

_STOPWORDS = {
    "a", "an", "and", "among", "as", "at", "by", "effect", "effects",
    "for", "from", "in", "is", "of", "on", "or", "the", "to", "using",
    "with", "study", "studies", "systematic", "review", "meta", "analysis",
}


def _tokens(value: Any) -> set[str]:
    if isinstance(value, (tuple, list)):
        value = " ".join(str(x) for x in value)
    words = re.findall(r"[a-z0-9\u0600-\u06ff]+", str(value or "").casefold())
    return {word for word in words if word not in _STOPWORDS}


def _overlap(left: Any, right: Any) -> float:
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _same_type(a: Any, b: Any) -> bool:
    for name in ("specialty", "question_type"):
        left, right = str(_field(a, name) or "").strip().casefold(), str(_field(b, name) or "").strip().casefold()
        if left and right and left != "all" and right != "all" and left != right:
            return False
    return True


def is_recently_checked(proposal: Any, historical: dict[str, Any]) -> bool:
    """Skip exact duplicates or unusually close PICO matches, not vague title similarity."""
    if not _same_type(proposal, historical):
        return False

    title_match = _overlap(_field(proposal, "title"), historical.get("title"))
    population = _overlap(_field(proposal, "population"), historical.get("population"))
    intervention = _overlap(
        _field(proposal, "intervention_exposure_index_test"),
        historical.get("intervention_exposure_index_test"),
    )
    comparator = _overlap(_field(proposal, "comparator_reference"), historical.get("comparator_reference"))
    outcome = _overlap(_field(proposal, "outcomes"), historical.get("outcomes"))
    designs = _overlap(_field(proposal, "eligible_designs"), historical.get("eligible_designs"))

    # Older reports stored a title without the PICO. Restrict them to an exact
    # normalized title match, rather than guessing that two topics are identical.
    if not historical.get("population") or not historical.get("intervention_exposure_index_test"):
        return bool(_tokens(_field(proposal, "title"))) and title_match == 1.0

    if population < 0.67 or intervention < 0.75:
        return False

    # A changed comparator or clinical outcome often changes the review question.
    for dim in ("comparator_reference", "outcomes", "eligible_designs"):
        old_value = historical.get(dim)
        new_value = _field(proposal, dim)
        old_present = bool(_tokens(old_value))
        new_present = bool(_tokens(new_value))
        # Unspecified is not equivalent to a specified clinical dimension.
        if old_present != new_present:
            return False
        if old_present and _overlap(old_value, new_value) < 0.70:
            return False

    return title_match >= 0.80 or (
        population >= 0.85
        and intervention >= 0.85
        and (not historical.get("comparator_reference") or comparator >= 0.85)
        and (not historical.get("outcomes") or outcome >= 0.85)
        and (not historical.get("eligible_designs") or designs >= 0.85)
    )


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def recent_topic_memory(
    completed_jobs: Iterable[dict[str, Any]],
    *,
    revisit_days: int = 30,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Collect only topics actually checked in completed jobs, never failed drafts.

    A provisional topic whose source verification failed receives a short
    7-day retry window. Other evaluated topics use the selected revisit period.
    This interval is a configurable operational heuristic, not a Cochrane rule.
    """
    days = max(0, min(180, int(revisit_days)))
    if days == 0:
        return []
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    out: list[dict[str, Any]] = []
    for row in completed_jobs:
        if str(row.get("status") or "").upper() != "COMPLETED":
            continue
        result = row.get("result_json") or {}
        if not isinstance(result, dict):
            continue
        summary = result.get("run_summary") or {}
        package = result.get("package") or {}
        if not isinstance(summary, dict) or not isinstance(package, dict):
            continue
        checked = summary.get("topic_history")
        if not isinstance(checked, list):
            # Historical runs have audits and a few qualified/provisional PICOs.
            full = {
                str(item.get("candidate_id")): item
                for item in (*package.get("options", []), *package.get("provisional_options", []))
                if isinstance(item, dict)
            }
            checked = [
                {**full.get(str(audit.get("candidate_id")), {}),
                 "candidate_id": audit.get("candidate_id"),
                 "title": audit.get("title") or full.get(str(audit.get("candidate_id")), {}).get("title"),
                 "status": audit.get("status")}
                for audit in summary.get("candidate_audits", []) if isinstance(audit, dict)
            ]
        for topic in checked:
            if not isinstance(topic, dict) or not topic.get("title"):
                continue
            checked_at = _parse_dt(topic.get("checked_at")) or _parse_dt(row.get("completed_at")) or _parse_dt(row.get("updated_at"))
            if checked_at is None:
                continue
            state = str(topic.get("status") or topic.get("qualification_status") or "").upper()
            duration = min(days, 7) if state in ("PROVISIONAL_BACKUP", "DEEP_VERIFYING") else days
            recheck_at = checked_at + timedelta(days=duration)
            if current >= recheck_at:
                continue
            out.append({
                **topic,
                "checked_at": checked_at.isoformat(),
                "recheck_at": recheck_at.isoformat(),
                "cooldown_days": duration,
            })
            if len(out) >= 500:
                return out
    return out


# Generation diversity is deliberately separate from the strict PICO recheck
# policy above. A draft is NOT a scientifically screened topic; repeated draft
# themes only change what a subsequent brainstorming run prioritizes.
_EXPLORATION_THEME_STOP = {
    "exercise", "prior", "following", "post", "acute", "daily", "weekly",
    "intervention", "investigation", "comparison", "efficacy", "extract",
    "standardized", "drug", "drugs", "care", "use", "in", "of",
    "high", "low", "mg", "dose", "doses", "participants",
    "oral", "ingestion", "supplementation", "supplement", "supplements",
    "treatment", "treatments", "therapy", "therapies", "and", "for",
    "versus", "standard", "patients", "patient", "adult", "adults",
}


def intervention_theme_tokens(value: Any) -> frozenset[str]:
    """Non-generic keywords used only for rotating brainstorming subjects."""
    return frozenset(
        term for term in _tokens(value)
        if term not in _EXPLORATION_THEME_STOP
        and len(term) >= 3
        and not term.isdigit()
    )


def same_intervention_theme(a: Any, b: Any) -> bool:
    """Comparable intervention identity, not clinical PICO equivalence."""
    left = intervention_theme_tokens(_field(a, "intervention_exposure_index_test"))
    right = intervention_theme_tokens(_field(b, "intervention_exposure_index_test"))
    return bool(left and right) and len(left & right) / min(len(left), len(right)) >= 0.8


def recent_generated_topic_memory(
    completed_jobs: Iterable[dict[str, Any]],
    *,
    revisit_days: int = 30,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Source-authentic generated drafts from this browser's completed jobs.

    Include verified and unverified generated PICOs, unlike the strict
    recent_topic_memory() filter. Use only for exploration diversity within
    at most seven days. Never label these topics screened or non-novel.
    """
    days = min(7, max(0, min(180, int(revisit_days))))
    if days == 0:
        return []
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    output: list[dict[str, Any]] = []
    for row in completed_jobs:
        if str(row.get("status") or "").upper() != "COMPLETED":
            continue
        completed_at = _parse_dt(row.get("completed_at")) or _parse_dt(row.get("updated_at"))
        if completed_at is None or completed_at + timedelta(days=days) <= current:
            continue
        result = row.get("result_json") or {}
        if not isinstance(result, dict):
            continue
        package = result.get("package") or {}
        summary = result.get("run_summary") or {}
        if not isinstance(package, dict) or not isinstance(summary, dict):
            continue
        topics = [
            *(package.get("options") or []),
            *(package.get("provisional_options") or []),
            *(package.get("unverified_generated_options") or []),
            *(summary.get("topic_history") or []),
        ]
        seen: set[str] = set()
        for topic in topics:
            if not isinstance(topic, dict):
                continue
            if not topic.get("intervention_exposure_index_test") or not topic.get("title"):
                continue
            key = str(topic.get("candidate_id") or topic["title"]).casefold()
            if key in seen:
                continue
            seen.add(key)
            output.append({
                "job_id": str(row.get("id") or ""),
                "title": str(topic["title"]),
                "specialty": str(topic.get("specialty") or ""),
                "question_type": str(topic.get("question_type") or ""),
                "population": str(topic.get("population") or ""),
                "intervention_exposure_index_test": str(topic["intervention_exposure_index_test"]),
                "comparator_reference": str(topic.get("comparator_reference") or ""),
                "outcomes": list(topic.get("outcomes") or []),
                "eligible_designs": list(topic.get("eligible_designs") or []),
                "checked_at": completed_at.isoformat(),
                "recheck_at": (completed_at + timedelta(days=days)).isoformat(),
                "role": "PRIOR_GENERATED_TOPIC_EXPLORATION_ONLY",
            })
            if len(output) >= 600:
                return output
    return output


def saturated_intervention_themes(
    generated_history: Iterable[dict[str, Any]],
    *,
    minimum_distinct_jobs: int = 2,
) -> list[dict[str, Any]]:
    """Group themes recurring across runs; do not count variants in one job."""
    themes: list[dict[str, Any]] = []
    for row in generated_history:
        if not intervention_theme_tokens(row.get("intervention_exposure_index_test")):
            continue
        matching = next(
            (item for item in themes if same_intervention_theme(row, item)),
            None,
        )
        if matching is None:
            matching = {
                "intervention_exposure_index_test": str(
                    row.get("intervention_exposure_index_test") or ""
                ),
                "example_title": str(row.get("title") or ""),
                "job_ids": set(),
            }
            themes.append(matching)
        matching["job_ids"].add(str(row.get("job_id") or ""))
    output = [
        {
            "intervention_exposure_index_test": item["intervention_exposure_index_test"],
            "example_title": item["example_title"],
            "distinct_prior_jobs": len(item["job_ids"]),
        }
        for item in themes
        if len(item["job_ids"]) >= minimum_distinct_jobs
        and "" not in item["job_ids"]
    ]
    return sorted(output, key=lambda item: (
        -item["distinct_prior_jobs"], item["intervention_exposure_index_test"].casefold()
    ))


def filter_saturated_evidence_cues(
    cues: list[dict[str, Any]],
    themes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Avoid repeatedly priming the LLM with the same source study titles.

    Every excluded cue is a preserved bibliographic item, not an excluded
    clinical study. This filter affects the brainstorm prompt only.
    """
    kept: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for cue in cues:
        title_tokens = _tokens(cue.get("title"))
        matched = next((
            item for item in themes
            if (
                anchor := intervention_theme_tokens(
                    item["intervention_exposure_index_test"]
                )
            )
            and len(anchor & title_tokens) / len(anchor) >= 0.8
        ), None)
        (deferred if matched else kept).append(cue)
    return kept, deferred
