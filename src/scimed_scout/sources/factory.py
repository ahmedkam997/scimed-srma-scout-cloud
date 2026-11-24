from __future__ import annotations

from .clinicaltrials import ClinicalTrialsGovSource
from .crossref import CrossrefSource
from .europe_pmc import EuropePMCSource
from .openalex import OpenAlexSource
from .osf import OSFRegistrationsSource
from .prospero import ProsperoCliSource
from .pubmed import PubMedSource
from .semantic_scholar import SemanticScholarSource


def build_default_source_clients(*, allow_semantic_scholar_keyless_probe: bool = False) -> list:
    return [
        PubMedSource(),
        EuropePMCSource(),
        OpenAlexSource(),
        CrossrefSource(),
        SemanticScholarSource(allow_keyless_probe=allow_semantic_scholar_keyless_probe),
        ProsperoCliSource(),
        OSFRegistrationsSource(),
        ClinicalTrialsGovSource(),
    ]
