# SciMed Review Scout Cloud Architecture

## Purpose

SciMed Review Scout Cloud is a discovery-only system for identifying strong systematic review and meta-analysis topics.

## Active workflow

1. Candidate topic generation.
2. Preliminary ranking.
3. Published-review search.
4. PROSPERO and OSF registration search.
5. Primary-study candidate discovery.
6. Ongoing/future evidence search when relevant.
7. Deterministic deduplication of primary-study candidates.
8. Semantic overlap and redundancy assessment.
9. Discovery-only qualification gates.
10. Export of several FIRST-CHOICE review topics for independent ChatGPT comparison.

## Out of scope

The active product does not perform screening, full-text eligibility assessment, PDF analysis, data extraction, study-family resolution, risk-of-bias assessment, synthesis-usability assessment, meta-analysis, TSA, or manuscript writing.

## Fail-closed source rule

Supported source states are:

- SEARCHED_NEGATIVE
- SEARCHED_POSITIVE
- PARTIAL
- ACCESS_FAILED
- NOT_SEARCHED
- MANUAL_VERIFIED

PARTIAL and ACCESS_FAILED never become SEARCHED_NEGATIVE.

## Discovery threshold

At least four unique primary-study candidates must be found in the discovery search. This is a feasibility signal only. It does not assert final eligibility or synthesis readiness.

## Final handoff

Only topics passing every discovery gate and carrying no unresolved Type-A issue enter the final JSON package. ChatGPT compares those topics and selects the strongest one for a real systematic review project.
