# Adaptive Research Gym V2 — development experiment (2026-11-26)

Source: FutureHouse Aviary 0.37.0 and LDP 1.10.1 (Apache-2.0). See https://github.com/Future-House/ldp and https://pypi.org/project/ldp/1.10.1/. Search design follows Cochrane Handbook ch. 4 and TARCiS, but this is NOT a complete Cochrane search or scientific stopping rule.

## Verified first native LDP run
CI run 45885991636: 12 tests passed (7 original Aviary + 5 adaptive).
- Agent observes query counts, retrieves narrow top 100, chooses expansion based on broad:narrow count ratio, then ends episode.
- Four candidate thresholds evaluated on two previously used development cases. Labels are terminal scorer only. Threshold 5 selected on tie with 2; saved and reloaded before surgical transfer.
- Statins PMID 30834266: 12/12 reference reports, 6812 IDs.
- SGLT2 HF PMID 35112512: 4/4, 100 IDs vs 956 for always-expand.
- Surgery transfer PMID 28588886 (https://pmc.ncbi.nlm.nih.gov/articles/PMC5446136/), March 2016 cutoff approximated to month end, ten direct PubMed links from Table 1 (references 11–18 excluding Shirazi, plus 20–22). The review has 33 reported RCTs, but the pilot measures ten report-level reference links, not independent trials or the full eligible set.
- Transfer: narrow=276, broad=417, count ratio 1.51. The adaptive policy recovered 3/10 in 100 IDs; conservative expansion recovered 10/10 in 417 IDs. No generalization claim. All three source exercises resolved.
- Reject adaptive stopping on this evidence. Added explicit fail-closed comparison to conservative baseline and experimental experience JSON. Never grant production approval even if the pilot passes. No changes to scientific qualification code or production configuration.

## Curriculum
Report-role/contrast episode uses native LDP tools to inspect PubMed metadata then extract explicit contrast leads or defer to manual review, on the nine existing development controls across four trial families. This is NOT a learned screening classifier or verified endpoint selection. Need independently adjudicated labels, larger held-out datasets and actual LLM inference before any such claim.

ASReview closed-corpus simulation (run 45884974971): 3,465 input records, 85 reference positives; 1,744 screened at 95% observed recall, WSS@95=0.44668, 84/85 measured at exported default results-table level. Different raw log vs export counts require duplicate-group audit; never infer trial-level recall. Oracle-assisted labels are not autonomous decisions.

## Decisions and boundaries
- Prioritize retrieval coverage; use learned models to prioritize screening rather than drop search routes or stop on document counts.
- Training here is exhaustive selection among four scalar policy thresholds, NOT RL fine-tuning of LLM weights.
- No model API calls. No production access or deployment.
- Future work: larger cardiology/surgery benchmark, independent review-family split, compare ranking methods, citation routes, trial linkage and outcome verification; connect an authorized LLM endpoint for LDP agent experiments. The current transfer set is now development data and must not be reused as final held-out test.
- Experience and policy artifacts are persisted to CI artifacts, not automatically promoted or loaded across runs.
