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

- Hosted open-access full-text recovery returned no Methods cutoff for all
  four direct review leads. Do not rerun the same resolver unchanged.
  Investigate DOI/publisher Methods, then preserve each source-specific
  date. Keep access and missing statements distinct.

- The alternate NCBI PMC OAI route also produced no exact Methods cutoff.
  EFetch recovered the four publisher DOIs, but the local proxy denied
  DOI resolution. Try the publisher pages on an authorized hosted runner
  before treating full-text access as exhausted. [OAI and DOI audit](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45892819750)

- The Academy's 30 nominations were exposed during development.
  A separate 30-case test panel needs fresh, nonoverlapping source
  families, verified historical cutoffs, and two genuine independent
  reviewer approvals per case. The private reviewer credentials and
  judgments have not been supplied. The initial admission report
  therefore remains unready.
- CSMeD inventory confirms reused literature collections and cannot
  be assumed independent. Two TrialReviewBench files passed a
  checksum-pinned hosted reacquisition, with 100 rows each. Study
  family independence, label suitability and RCT-only applicability
  are unresolved. LEADS corpus and model licensing and independent
  task labels require separate clearance.
