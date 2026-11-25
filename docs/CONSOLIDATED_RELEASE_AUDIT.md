# Consolidated release audit — 2026-11-25

## Evidence and acceptance
- Historical issue #24: 27/27 provisional, 13 unassessed review, 11 registration, 10 coverage blockers; overlapping reasons, not current-version performance.
- Latest review audit: four of six distinct reference reviews seen in 25-record samples, one missed by PubMed's lexical intervention gate despite an exact Europe PMC match. BM25 did not consistently beat raw ranking; do not enable by default.
- PROSPERO 449/449 scoped results verified; DELIVER secondary report linkage verified. These are limited controls.
- Adaptive replay improved observed leads from 3/13 to 7/13 in development; not independent sensitivity.
- Changes: recovery-only bounded adaptive PubMed route; review-count stopping bug; biomedical review preservation despite no lexical overlap; fulltext identity and BioC fallback; date validation; registry partial retention; empty-positive bibliography integrity; audit export.
- Acceptance: all unit/integration tests pass; new live controls capture source statuses and expected IDs; a known review is never declared novel merely because absent from bounded samples. No forced qualified topic. No extra paid service.
- Remaining scientific/external limitations: review inclusion-list/full-text PICO and independent trial adjudication; OSF index scope; ClinicalTrials.gov broad query caps; provider quotas; Crossref broad ranking; lack of independently double-adjudicated holdout; no verified new production discovery result. Do not close issues #24/#25 merely because CI passes.
- Use existing E2E workflow for verification of a fixed question; use the single consolidated workflow for no-AI source and review audit. Review issue #25 for current evidence.
- Methods: Cochrane Handbook ch4 and IV, NLM systematic review subset, TARCiS BMJ 2024 e078384, Garner BMJ 2016 i3507, official PMC BioC.
