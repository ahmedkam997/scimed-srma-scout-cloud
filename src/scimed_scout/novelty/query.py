from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class QueryTerms:
    central_phrase: str = ""
    population: str = ""
    intervention: str = ""
    comparator: str = ""
    disease: str = ""
    intervention_class: str = ""
    strategy: str = ""
    principal_outcome: str = ""
    acronym: str = ""
    population_synonyms: list[str] = field(default_factory=list)
    intervention_synonyms: list[str] = field(default_factory=list)


def generate_registry_queries(terms: QueryTerms, *, max_queries: int = 10) -> list[str]:
    """Generate a high-sensitivity, deduplicated registry query set."""
    p_syn = terms.population_synonyms[0] if terms.population_synonyms else ""
    i_syn = terms.intervention_synonyms[0] if terms.intervention_synonyms else ""

    candidates = [
        terms.central_phrase,
        _and(terms.population, terms.intervention),
        _and(terms.intervention, terms.comparator),
        _and(terms.population, terms.intervention, terms.comparator),
        _and(terms.disease, terms.intervention_class or terms.intervention),
        _and(terms.disease, terms.strategy),
        terms.acronym,
        _and(terms.principal_outcome, terms.intervention),
        _and(p_syn or terms.population, i_syn or terms.intervention),
        _and(terms.disease or terms.population, terms.intervention_class or terms.intervention),
    ]

    out: list[str] = []
    seen: set[str] = set()
    for query in candidates:
        normalized = " ".join(query.split()).strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        out.append(normalized)
        if len(out) >= max_queries:
            break
    return out


def _and(*parts: str) -> str:
    clean = [f'"{part.strip()}"' if " " in part.strip() else part.strip() for part in parts if part and part.strip()]
    return " AND ".join(clean)
