from .base import SearchRecord, SearchResult, SourceClient
from .clinicaltrials import ClinicalTrialsGovSource
from .crossref import CrossrefSource
from .europe_pmc import EuropePMCSource
from .factory import build_default_source_clients
from .openalex import OpenAlexSource
from .osf import OSFRegistrationsSource
from .prospero import ProsperoCliSource
from .pubmed import PubMedSource
from .semantic_scholar import SemanticScholarSource

__all__ = [
    "SearchRecord",
    "SearchResult",
    "SourceClient",
    "PubMedSource",
    "EuropePMCSource",
    "OpenAlexSource",
    "ClinicalTrialsGovSource",
    "CrossrefSource",
    "SemanticScholarSource",
    "OSFRegistrationsSource",
    "ProsperoCliSource",
    "build_default_source_clients",
]
