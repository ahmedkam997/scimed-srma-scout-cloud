from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Iterable

from .models import FullTextChunk


_ELIGIBILITY_SECTIONS = {
    "methods", "method", "materials and methods", "patients and methods",
    "participants", "patients", "study design", "design", "population",
    "eligibility", "inclusion", "exclusion", "setting",
}
_SYNTHESIS_SECTIONS = {
    "results", "result", "outcomes", "outcome", "efficacy", "effectiveness",
    "diagnostic accuracy", "survival", "adverse events", "safety", "findings",
}
_QUANTITATIVE_TERMS = (
    "table", "events", "event", "mean", "standard deviation", " sd ",
    "confidence interval", "hazard ratio", "odds ratio", "risk ratio",
    "sensitivity", "specificity", "true positive", "false positive",
    "kaplan-meier", "person-years", "person time", "median", "interquartile",
)


@dataclass(frozen=True, slots=True)
class TextBlock:
    section: str
    text: str


def parse_jats_xml(xml_text: str, *, max_chunk_chars: int = 7000) -> tuple[str, list[FullTextChunk]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid JATS XML: {exc}") from exc

    blocks: list[TextBlock] = []
    for abstract in root.findall(".//abstract"):
        text = _clean_text(" ".join(abstract.itertext()))
        if text:
            blocks.append(TextBlock("Abstract", text))

    body = next((node for node in root.iter() if _tag(node) == "body"), None)
    if body is not None:
        _walk(body, "Body", blocks)

    if not blocks:
        text = _clean_text(" ".join(root.itertext()))
        if text:
            blocks.append(TextBlock("Full text", text))

    full_text = "\n\n".join(f"[{block.section}]\n{block.text}" for block in blocks)
    return full_text, chunk_blocks(blocks, max_chunk_chars=max_chunk_chars)


def chunk_plain_text(text: str, *, max_chunk_chars: int = 7000) -> list[FullTextChunk]:
    clean = _clean_text(text)
    if not clean:
        return []
    pieces = _split_long_text(clean, max_chunk_chars)
    return [
        FullTextChunk(f"FT-{index:04d}", index, "Full text", piece)
        for index, piece in enumerate(pieces, start=1)
    ]


def chunk_blocks(blocks: Iterable[TextBlock], *, max_chunk_chars: int = 7000) -> list[FullTextChunk]:
    max_chunk_chars = max(1000, int(max_chunk_chars))
    chunks: list[FullTextChunk] = []
    current_section = ""
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_section, current_parts
        if not current_parts:
            return
        text = "\n".join(current_parts).strip()
        chunks.append(FullTextChunk(f"FT-{len(chunks)+1:04d}", len(chunks)+1, current_section or "Full text", text))
        current_parts = []

    for block in blocks:
        section = block.section or "Full text"
        for piece in _split_long_text(block.text, max_chunk_chars):
            projected = len("\n".join(current_parts)) + len(piece) + 1
            if current_parts and (section != current_section or projected > max_chunk_chars):
                flush()
            current_section = section
            current_parts.append(piece)
    flush()
    return chunks


def evidence_text_for_record(
    record: dict[str, Any],
    candidate: Any | None = None,
    *,
    purpose: str = "SYNTHESIS",
    max_chars: int = 48000,
    max_chunks: int = 8,
) -> str:
    payload = record.get("payload") or {}
    metadata = payload.get("metadata") or {}
    base_parts = [
        record.get("title"),
        metadata.get("abstract"),
        metadata.get("summary"),
        metadata.get("description"),
        metadata.get("brief_summary"),
    ]
    base_text = "\n".join(str(x).strip() for x in base_parts if x and str(x).strip())

    raw_chunks = payload.get("full_text_chunks")
    chunks: list[FullTextChunk] = []
    if isinstance(raw_chunks, list):
        for item in raw_chunks:
            if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                continue
            chunks.append(
                FullTextChunk(
                    chunk_id=str(item.get("chunk_id") or f"FT-{len(chunks)+1:04d}"),
                    ordinal=int(item.get("ordinal") or len(chunks) + 1),
                    section=str(item.get("section") or "Full text"),
                    text=str(item.get("text") or "").strip(),
                )
            )
    elif str(payload.get("full_text") or "").strip():
        chunks = chunk_plain_text(str(payload.get("full_text")))

    if not chunks:
        return base_text[:max_chars]

    terms = _candidate_terms(candidate)
    selected = select_chunks(chunks, terms=terms, purpose=purpose, max_chunks=max_chunks, max_chars=max_chars)
    selected_text = "\n\n".join(
        f"[CHUNK {chunk.chunk_id} | SECTION {chunk.section}]\n{chunk.text}"
        for chunk in selected
    )
    combined = "\n\n".join(x for x in [base_text, selected_text] if x)
    return combined[:max_chars]


def select_chunks(
    chunks: list[FullTextChunk],
    *,
    terms: list[str] | None = None,
    purpose: str = "SYNTHESIS",
    max_chunks: int = 8,
    max_chars: int = 48000,
) -> list[FullTextChunk]:
    if not chunks:
        return []
    purpose = str(purpose or "SYNTHESIS").upper()
    terms = [x.casefold() for x in (terms or []) if len(x) >= 3]

    scored: list[tuple[float, int, FullTextChunk]] = []
    for chunk in chunks:
        section = chunk.section.casefold()
        text = f" {chunk.text.casefold()} "
        score = 0.0
        targets = _ELIGIBILITY_SECTIONS if purpose == "ELIGIBILITY" else _SYNTHESIS_SECTIONS
        if any(target in section for target in targets):
            score += 8.0
        if purpose == "SYNTHESIS":
            score += sum(1.5 for term in _QUANTITATIVE_TERMS if term in text)
            if re.search(r"\b\d+(?:\.\d+)?\s*(?:%|patients?|participants?|events?)\b", text):
                score += 3.0
        for term in terms:
            if term in text:
                score += min(4.0, 1.0 + text.count(term) * 0.25)
        scored.append((score, -chunk.ordinal, chunk))

    ranked = sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)
    selected: list[FullTextChunk] = []
    used = 0
    for score, _, chunk in ranked:
        if len(selected) >= max_chunks:
            break
        addition = len(chunk.text) + len(chunk.section) + 40
        if selected and used + addition > max_chars:
            continue
        if score <= 0 and selected:
            continue
        selected.append(chunk)
        used += addition

    if not selected:
        selected = chunks[: min(max_chunks, len(chunks))]

    return sorted(selected, key=lambda chunk: chunk.ordinal)


def _walk(node: ET.Element, section: str, blocks: list[TextBlock]) -> None:
    tag = _tag(node)
    if tag == "sec":
        title = next((child for child in node if _tag(child) == "title"), None)
        current_section = _clean_text(" ".join(title.itertext())) if title is not None else section
        current_section = current_section or section
        for child in node:
            if _tag(child) != "title":
                _walk(child, current_section, blocks)
        return

    if tag in {"p", "table-wrap", "fig", "disp-quote", "boxed-text"}:
        text = _clean_text(" ".join(node.itertext()))
        if text:
            blocks.append(TextBlock(section, text))
        return

    for child in node:
        _walk(child, section, blocks)


def _split_long_text(text: str, max_chars: int) -> list[str]:
    text = _clean_text(text)
    if len(text) <= max_chars:
        return [text] if text else []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            for start in range(0, len(sentence), max_chars):
                pieces.append(sentence[start:start + max_chars].strip())
            continue
        if current and len(current) + len(sentence) + 1 > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def _candidate_terms(candidate: Any | None) -> list[str]:
    if candidate is None:
        return []
    raw: list[str] = []
    for attr in (
        "population", "intervention_exposure_index_test", "comparator_reference",
        "review_question", "title",
    ):
        value = getattr(candidate, attr, "")
        if value:
            raw.append(str(value))
    outcomes = getattr(candidate, "outcomes", []) or []
    raw.extend(str(x) for x in outcomes)
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", " ".join(raw).casefold())
    stop = {"the", "and", "for", "with", "from", "what", "does", "among", "study", "studies", "patients", "adults"}
    return list(dict.fromkeys(token for token in tokens if token not in stop and len(token) >= 4))[:40]


def _tag(node: ET.Element) -> str:
    return str(node.tag).split("}")[-1].casefold()


def _clean_text(text: str) -> str:
    return " ".join(str(text or "").split())
