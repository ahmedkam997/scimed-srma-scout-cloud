from __future__ import annotations

from .clinicaltrials import ClinicalTrialsGovSource
from .crossref import CrossrefSource
from .europe_pmc import EuropePMCSource
from .openalex import OpenAlexSource
from .osf import OSFRegistrationsSource
from .prospero import ProsperoCliSource
from .pubmed import PubMedSource
from .semantic_scholar import SemanticScholarSource


def build_default_source_clients() -> list:
    return [
        PubMedSource(),
        EuropePMCSource(),
        OpenAlexSource(),
        CrossrefSource(),
        SemanticScholarSource(),
        ProsperoCliSource(),
        OSFRegistrationsSource(),
        ClinicalTrialsGovSource(),
    ]
