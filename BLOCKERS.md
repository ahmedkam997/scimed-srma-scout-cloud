# Mission blockers

- Local live source requests to PubMed, Europe PMC, ClinicalTrials.gov and
  Crossref returned proxy 403. Use the development-branch GitHub Actions
  workflow. The GitHub API is also denied locally; the public Actions pages
  and authorized Git ref transport work.
- No GPU device or local Hugging Face access. Continue CPU-compatible ASReview
  and deterministic retrieval/extraction checks. LEADS still needs authorized
  model access and an independently adjudicated task set.
- Two qualified human reviewers must independently verify complete candidate
  evidence and sign a reconciled packet. Automation cannot furnish or simulate
  this approval. Keep reviewer identities, keys and signatures in the
  protected operator channel.

- Both hosted discovery samples were partial. TAVR/SAVR and ticagrelor/
  clopidogrel have bibliographic shortlist cues, with actual trial identity,
  extractable outcomes and competitor cutoffs still unresolved.
