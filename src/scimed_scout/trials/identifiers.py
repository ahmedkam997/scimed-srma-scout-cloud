from __future__ import annotations

import re


REGISTRY_PATTERN = re.compile(
    r"\b(?:NCT\d{8}|ISRCTN\d{8}|ACTRN\d{14}|ChiCTR[A-Za-z0-9-]+|"
    r"CTRI/\d{4}/\d{2}/\d{6}|IRCT[A-Za-z0-9]+|UMIN\d{9})\b",
    re.IGNORECASE,
)


def normalize_doi(value: str) -> str:
    text = (value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.strip().rstrip(".,;)")


def normalize_registry_id(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).upper()


def extract_registry_ids(text: str) -> list[str]:
    found = [normalize_registry_id(match.group(0)) for match in REGISTRY_PATTERN.finditer(text or "")]
    return list(dict.fromkeys(found))


def normalize_text(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", (value or "").lower())
    return " ".join(text.split())


def token_jaccard(a: str, b: str) -> float:
    left = set(normalize_text(a).split())
    right = set(normalize_text(b).split())
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
