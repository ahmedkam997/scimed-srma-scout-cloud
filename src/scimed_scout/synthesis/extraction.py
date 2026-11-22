from __future__ import annotations

import json
import math
import re
from typing import Any

from scimed_scout.ai import AIProvider, AIRequest
from scimed_scout.fulltext import evidence_text_for_record
from scimed_scout.storage import CandidateRecord

from .models import EvidenceScope, ExtractedOutcome, StudySynthesisExtraction


SYSTEM_PROMPT = """Extract synthesis-ready outcome data for a systematic review.
Use only the supplied source text. Never invent or infer missing numerical values.
For every populated numerical or categorical synthesis field, provide an exact supporting quote copied from the source text.
Return all potentially relevant outcomes reported in the supplied evidence.
If the source only signals graph/Kaplan-Meier/median-IQR/reconstructable data, record the signal with exact evidence and do not invent values.
Return strict JSON only. Do not decide whether the study is eligible, independent, or final-review worthy."""


class SynthesisDataExtractor:
    def __init__(self, provider: AIProvider):
        self.provider = provider

    def extract(
        self,
        candidate: CandidateRecord,
        study: dict[str, Any],
        source_record: dict[str, Any],
        *,
        evidence_scope: EvidenceScope = EvidenceScope.TITLE_ABSTRACT,
    ) -> StudySynthesisExtraction:
        text = evidence_text_for_record(\n            source_record, candidate, purpose="SYNTHESIS", max_chars=48000, max_chunks=8\n        )
        study_id = str(study.get("study_id") or "")
        source_record_id = str(source_record.get("source_record_id") or study_id)
        if not text:
            return StudySynthesisExtraction(
                study_id=study_id,
                source_record_id=source_record_id,
                evidence_scope=evidence_scope,
                outcomes=[],
                no_data_reason="No usable source text available for synthesis extraction",
            )

        response = self.provider.complete(
            AIRequest(
                system=SYSTEM_PROMPT,
                prompt=_prompt(candidate, study, source_record, text, evidence_scope),
                temperature=0.0,
                max_tokens=6000,
            )
        )
        raw = _json_object(response.text)
        outcomes: list[ExtractedOutcome] = []
        for item in raw.get("outcomes") or []:
            if not isinstance(item, dict):
                continue
            extraction = ExtractedOutcome(
                outcome_name=str(item.get("outcome_name") or "").strip(),
                outcome_type=str(item.get("outcome_type") or "OTHER").strip().upper(),
                follow_up=str(item.get("follow_up") or "").strip(),
                data=item.get("data") if isinstance(item.get("data"), dict) else {},
                signals=item.get("signals") if isinstance(item.get("signals"), dict) else {},
                overall_confidence=_confidence(item.get("overall_confidence")),
                unresolved_fields=[str(x) for x in (item.get("unresolved_fields") or []) if str(x).strip()],
                raw=item,
            )
            outcomes.append(_validate_outcome(extraction, text))

        return StudySynthesisExtraction(
            study_id=study_id,
            source_record_id=source_record_id,
            evidence_scope=evidence_scope,
            outcomes=outcomes,
            no_data_reason=str(raw.get("no_data_reason") or "").strip(),
            reviewer=f"{response.provider}:{response.model}",
        )


def _prompt(candidate: CandidateRecord, study: dict, record: dict, text: str, scope: EvidenceScope) -> str:
    return f"""Candidate review:
Question type: {candidate.question_type}
Review question: {candidate.review_question}
Target outcomes: {candidate.outcomes}
Explicit principal outcome, if any: {(candidate.metadata or {}).get('principal_outcome', '')}

Study:
Study ID: {study.get('study_id', '')}
Title: {study.get('title', '')}
Family ID: {study.get('family_id', '')}
Source: {record.get('source', '')}
Evidence scope: {scope.value}

Source text:
{text}

Return:
{{
  "outcomes": [
    {{
      "outcome_name": "",
      "outcome_type": "BINARY|CONTINUOUS|TIME_TO_EVENT|ORDINAL|DIAGNOSTIC_ACCURACY|PROPORTION|RATE|CORRELATION|GENERIC_EFFECT|PREDICTION_MODEL_PERFORMANCE|QUALITATIVE_FINDING|OTHER",
      "follow_up": "",
      "overall_confidence": 0.0,
      "unresolved_fields": [],
      "data": {{
        "treatment_binary": {{
          "n": {{"value": null, "evidence": "", "confidence": 0.0}},
          "events": {{"value": null, "evidence": "", "confidence": 0.0}},
          "proportion": {{"value": null, "evidence": "", "confidence": 0.0}}
        }},
        "control_binary": {{
          "n": {{"value": null, "evidence": "", "confidence": 0.0}},
          "events": {{"value": null, "evidence": "", "confidence": 0.0}},
          "proportion": {{"value": null, "evidence": "", "confidence": 0.0}}
        }},
        "single_binary": {{
          "n": {{"value": null, "evidence": "", "confidence": 0.0}},
          "events": {{"value": null, "evidence": "", "confidence": 0.0}},
          "proportion": {{"value": null, "evidence": "", "confidence": 0.0}}
        }},
        "treatment_continuous": {{
          "n": {{"value": null, "evidence": "", "confidence": 0.0}},
          "mean": {{"value": null, "evidence": "", "confidence": 0.0}},
          "sd": {{"value": null, "evidence": "", "confidence": 0.0}},
          "change_mean": {{"value": null, "evidence": "", "confidence": 0.0}},
          "change_sd": {{"value": null, "evidence": "", "confidence": 0.0}},
          "median": {{"value": null, "evidence": "", "confidence": 0.0}},
          "q1": {{"value": null, "evidence": "", "confidence": 0.0}},
          "q3": {{"value": null, "evidence": "", "confidence": 0.0}}
        }},
        "control_continuous": {{
          "n": {{"value": null, "evidence": "", "confidence": 0.0}},
          "mean": {{"value": null, "evidence": "", "confidence": 0.0}},
          "sd": {{"value": null, "evidence": "", "confidence": 0.0}},
          "change_mean": {{"value": null, "evidence": "", "confidence": 0.0}},
          "change_sd": {{"value": null, "evidence": "", "confidence": 0.0}},
          "median": {{"value": null, "evidence": "", "confidence": 0.0}},
          "q1": {{"value": null, "evidence": "", "confidence": 0.0}},
          "q3": {{"value": null, "evidence": "", "confidence": 0.0}}
        }},
        "diagnostic": {{
          "index_test": {{"value": "", "evidence": "", "confidence": 0.0}},
          "reference_standard": {{"value": "", "evidence": "", "confidence": 0.0}},
          "threshold": {{"value": "", "evidence": "", "confidence": 0.0}},
          "tp": {{"value": null, "evidence": "", "confidence": 0.0}},
          "fp": {{"value": null, "evidence": "", "confidence": 0.0}},
          "fn": {{"value": null, "evidence": "", "confidence": 0.0}},
          "tn": {{"value": null, "evidence": "", "confidence": 0.0}},
          "sensitivity": {{"value": null, "evidence": "", "confidence": 0.0}},
          "specificity": {{"value": null, "evidence": "", "confidence": 0.0}},
          "diseased_n": {{"value": null, "evidence": "", "confidence": 0.0}},
          "non_diseased_n": {{"value": null, "evidence": "", "confidence": 0.0}}
        }},
        "hr": {{"value": null, "evidence": "", "confidence": 0.0}},
        "hr_ci_lower": {{"value": null, "evidence": "", "confidence": 0.0}},
        "hr_ci_upper": {{"value": null, "evidence": "", "confidence": 0.0}},
        "log_hr": {{"value": null, "evidence": "", "confidence": 0.0}},
        "se_log_hr": {{"value": null, "evidence": "", "confidence": 0.0}},
        "o_minus_e": {{"value": null, "evidence": "", "confidence": 0.0}},
        "variance": {{"value": null, "evidence": "", "confidence": 0.0}},
        "common_or": {{"value": null, "evidence": "", "confidence": 0.0}},
        "common_or_ci_lower": {{"value": null, "evidence": "", "confidence": 0.0}},
        "common_or_ci_upper": {{"value": null, "evidence": "", "confidence": 0.0}},
        "person_time": {{"value": null, "evidence": "", "confidence": 0.0}},
        "rate_events": {{"value": null, "evidence": "", "confidence": 0.0}},
        "correlation": {{"value": null, "evidence": "", "confidence": 0.0}},
        "correlation_n": {{"value": null, "evidence": "", "confidence": 0.0}},
        "effect_estimate": {{"value": null, "evidence": "", "confidence": 0.0}},
        "effect_se": {{"value": null, "evidence": "", "confidence": 0.0}},
        "effect_ci_lower": {{"value": null, "evidence": "", "confidence": 0.0}},
        "effect_ci_upper": {{"value": null, "evidence": "", "confidence": 0.0}},
        "effect_measure": {{"value": "", "evidence": "", "confidence": 0.0}},
        "performance_estimate": {{"value": null, "evidence": "", "confidence": 0.0}},
        "performance_se": {{"value": null, "evidence": "", "confidence": 0.0}},
        "performance_ci_lower": {{"value": null, "evidence": "", "confidence": 0.0}},
        "performance_ci_upper": {{"value": null, "evidence": "", "confidence": 0.0}},
        "performance_metric": {{"value": "", "evidence": "", "confidence": 0.0}}
      }},
      "signals": {{
        "graph_only": {{"value": false, "evidence": ""}},
        "kaplan_meier": {{"value": false, "evidence": ""}},
        "median_iqr_only": {{"value": false, "evidence": ""}},
        "qualitative_findings_present": {{"value": false, "evidence": ""}}
      }}
    }}
  ],
  "no_data_reason": ""
}}"""


def _validate_outcome(outcome: ExtractedOutcome, source_text: str) -> ExtractedOutcome:
    unresolved = list(outcome.unresolved_fields)
    validated, invalid = _validate_node(outcome.data, source_text, prefix="")
    outcome.data = validated

    validated_signals: dict[str, Any] = {}
    for name, raw in outcome.signals.items():
        if not isinstance(raw, dict):
            continue
        value = bool(raw.get("value"))
        evidence = str(raw.get("evidence") or "").strip()
        if value and (not evidence or _norm(evidence) not in _norm(source_text)):
            unresolved.append(f"signals.{name}")
            validated_signals[name] = {"value": False, "evidence": evidence}
            invalid = True
        else:
            validated_signals[name] = {"value": value, "evidence": evidence}
    outcome.signals = validated_signals

    if invalid:
        outcome.overall_confidence = min(outcome.overall_confidence, 0.79)
    outcome.unresolved_fields = list(dict.fromkeys(unresolved))
    return outcome


def _validate_node(node: Any, source_text: str, *, prefix: str) -> tuple[Any, bool]:
    if not isinstance(node, dict):
        return node, False

    if "value" in node:
        value = node.get("value")
        evidence = str(node.get("evidence") or "").strip()
        confidence = _confidence(node.get("confidence"))
        if value in (None, "", []):
            return {"value": value, "evidence": evidence, "confidence": confidence}, False

        supported = bool(evidence) and _norm(evidence) in _norm(source_text)
        if supported and isinstance(value, (int, float)) and not isinstance(value, bool):
            supported = _numeric_supported(float(value), evidence)
        if not supported or confidence < 0.85:
            return {"value": None, "evidence": evidence, "confidence": 0.0}, True
        return {"value": value, "evidence": evidence, "confidence": confidence}, False

    out: dict[str, Any] = {}
    invalid = False
    for key, value in node.items():
        child, child_invalid = _validate_node(value, source_text, prefix=f"{prefix}.{key}" if prefix else key)
        out[key] = child
        invalid = invalid or child_invalid
    return out, invalid


def _numeric_supported(value: float, evidence: str) -> bool:
    cleaned = evidence.replace(",", "")
    numbers = []
    for token in re.findall(r"[-+]?\d+(?:\.\d+)?", cleaned):
        try:
            numbers.append(float(token))
        except ValueError:
            pass
    if any(math.isclose(value, number, rel_tol=1e-6, abs_tol=1e-9) for number in numbers):
        return True

    if 0 <= value <= 1 and "%" in cleaned:
        valid_percentages: list[float] = []
        for match in re.finditer(r"(\d+(?:\.\d+)?)\s*%", cleaned):
            tail = cleaned[match.end():match.end() + 20].casefold()
            if re.match(r"\s*(?:ci|confidence\s+interval)", tail):
                continue
            try:
                valid_percentages.append(float(match.group(1)))
            except ValueError:
                pass
        return any(
            math.isclose(value * 100.0, number, rel_tol=1e-4, abs_tol=1e-4)
            for number in valid_percentages
        )
    return False


def _evidence_text(record: dict[str, Any]) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") or {}
    pieces = [
        record.get("title"),
        metadata.get("abstract"),
        metadata.get("summary"),
        metadata.get("description"),
        metadata.get("brief_summary"),
        payload.get("full_text"),
        payload.get("supplement_text"),
    ]
    return "\n".join(str(x).strip() for x in pieces if x and str(x).strip())[:50000]


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = chr(96) * 3
    if cleaned.startswith(fence):
        cleaned = re.sub("^" + re.escape(fence) + r"(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*" + re.escape(fence) + "$", "", cleaned)
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Synthesis extraction response did not contain JSON")
        value = json.loads(cleaned[start:end + 1])
    if not isinstance(value, dict):
        raise ValueError("Synthesis extraction root must be an object")
    return value


def _confidence(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _norm(text: str) -> str:
    return " ".join(str(text or "").casefold().split())
