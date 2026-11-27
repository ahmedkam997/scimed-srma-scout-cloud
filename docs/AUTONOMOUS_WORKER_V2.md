# Autonomous Worker V2 — read-only research orchestration

## Methods and design
- Cochrane Handbook chapter 21, Living systematic reviews: https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-21
- TARCiS supplementary citation searching: https://doi.org/10.1136/bmj-2023-078384
- ASReview simulation and evaluation: https://asreview.nl/simulate/
- GitHub Actions concurrency: https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency

Reuse the existing RCT-first sampler, stratified retrieval, registration and
outcome-cue extraction, Methods resolver and Research Academy component
comparisons. Avoid a general-purpose coding agent with repository write
permissions in an unattended public research worker. Models may advise on
public lead prioritization only; no model text is executed. No paid keys
are required. No production or scientific gate changes.

## Schedule and checkpoints
An eight-cycle pattern reserves two discovery, two family recovery, two
competitor recovery, one learning comparison, one diagnostic slot. If no
due recovery job exists the slot returns to discovery. Each recovery
uses exact, broad and then date-stratified bounded source queries, then
rotates pending candidates. Bibliographic IDs accumulate rather than being
overwritten by partial responses. Compact source-linked registry and outcome
cues and Methods passages survive in the checkpoint; raw cycle reports are
separate artifacts. Queue and per-candidate inventory caps are explicit.
When both evidence and source access are unresolved, no eligibility or novelty
is inferred. The prior V1 checkpoint schema is retained with a V2 extension.

The empirical policy learns relative bibliographic yield to order untried
routes, not to remove routes. The Academy learning cycle compares original
and hybrid competitor ranking on known development references. Adopt a
ranking-only change if all sampled routes resolve, neither development
case loses reference hits and at least one improves. These are not held-out
tests or LLM weight training. The screening simulations already recorded in
benchmarks/academy/screening-development.json remain development evidence,
not an automated exclusion rule. No new model training or autonomous coding
is enabled in this version.

## Real validation
Run 45967670292: twelve tests passed; actual V1 checkpoint restored, then
family and competitor cycles for renal denervation vs sham. The family
search returned 40 PMIDs; 30 fetched without missing IDs, 11 distinct
registration links in that page, three report-level numeric outcome cues.
The competitor query returned 40 potential reviews; none of the first
three Methods attempts resolved a search-date passage. All 40 remain
unresolved as possible competitors. Nine reference reports fetched in
Academy comparison; 8/9 exact registration matches, four of six reference
same-family pairs linked, no false linked pair among 30 negative pairs.
Four of four known ratio leads matched; this does not verify outcome
direction or eligibility. Competitor ranking at five: cardiology baseline
1/2 vs hybrid 0/2; surgery 1/4 vs 1/4. Policy retains baseline. Both retrieval
inventories are bounded, not exhaustive. Core CI run 45967670173: 592 passed,
2 skipped. The later date-stratified route requires its own CI run.

## Scientific and operational boundaries
No first-choice qualification, no signed human adjudication, no completed
evidence synthesis. Do not replace required independent reviewers. All
qualification requirements unchanged. The scheduler must be pinned to a
tested commit. Retain V1 checkpoint continuity and use a verified bootstrap
if no prior scheduler success exists. State must fail closed on missing or
invalid checkpoints. Artifact retention is finite; long-term archival and
operator intervention after expiration remain necessary. In future integrate
larger independent training and test datasets, native Aviary/LDP and ASReview
training jobs, verified full-text extraction, registry and protocol competitor
searches and reviewer packet workflow. Do not auto-merge code.
