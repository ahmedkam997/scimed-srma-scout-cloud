# Bounded citation recovery and outstanding validation — 2026-11-26

Decision: reuse the existing Europe PMC citation-link adapter, not a second
network stack or a key-dependent provider. TARCiS (https://doi.org/10.1136/bmj-2023-078384),
Cochrane chapter 4 (https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04),
and Citationchaser (https://doi.org/10.1002/jrsm.1563) support supplementary
forward/backward search, not replacement of independent database searches.
OpenAlex is a useful independent index but has a separate access budget and
unmatched references; not added to this bounded path.

Changes: one-hop exact PMID hydration, interleaved directions, explicit partial
sampling, rate-limit stop, cancellation checks, citation recovery in at most
two seed cells, priority for dynamically derived and near-threshold cells,
and shared broad review preflight for all qualifying comparators in a cell.
Deep supplementary discovery no longer stops solely because the family cue
floor is met. Citation hits are unverified leads; all existing trial, novelty,
coverage, semantic and human eligibility gates remain unchanged.
The development replay now applies exact-comparison supplement to every case,
not conditionally on reference IDs missed, and measures graph yield separately.
The same small set is not an independent accuracy test.

Outstanding: OpenAlex/other citation index coverage, larger expert-adjudicated
held-out corpus, actual full-text trial-family and outcome extraction,
live provider/registry failure diagnosis, and production resume replay.
The previous failed tests workflow was superseded by successful run
45770275165 and Pages 45770275177. Historical competitor backlog and quota
pressure remain open until measured with new production evidence.
No new AI requests in this citation recovery layer; logical network call
budget is at most six at seed stage (two cells, each two directions plus
one hydration) and four per deep supplement including optional refinement.
No claim of completeness or automatic qualification.
