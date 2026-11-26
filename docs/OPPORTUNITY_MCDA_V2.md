# SciMed opportunity assessment V2

RCT-first path only; other explicitly selected designs retain the legacy score. Local weights are not validated. No new AI calls; at most one extra PubMed review preflight and bounded abstract enrichment. The evidence-first seed remains a bounded sample, not comprehensive coverage. Review-abstract uncertainty triggers, actual abstract search-date cues, report chronology, methods cues and outcome-specific hypotheses prioritize checking; none establish novelty, independent trial eligibility or new-trial status.

Eight domains: clinical importance 15, route-specific gap 20, information gain 20, evidence readiness 15, methodological feasibility 15, timeliness 5, operational feasibility 5, editorial relevance 5. Unknowns retain their weights as score intervals; model opinions and family cues only contribute to separate exploratory bounds. An adjudicated-input score requires ratings, rationale and source URLs, but the software does not authenticate manual adjudication. Interval dominance across four prespecified weighting scenarios is reported; incomplete rankings are indeterminate rather than imputed.

The RCT worker never marks a topic scientifically qualified based on bibliography. Seven confirmed independent eligible RCTs, meaningful synthesis, material overlap/registry adjudication, source coverage, route-specific novelty and all original thresholds require independent assessment. The legacy score remains for audit only; the exported topic prompt instructs reviewers to resolve route-specific novelty rather than requiring an artificial PICO difference. No automatic update/corrective GO; actual inclusion lists and consequential flaws must be verified.

Methods consulted:
- Evidence synthesis prioritization systematic review: https://pubmed.ncbi.nlm.nih.gov/31846688/
- AHRQ research gap framework: https://www.ncbi.nlm.nih.gov/books/NBK62478/
- ISPOR MCDA good practices: https://www.ispor.org/heor-resources/good-practices/article/multiple-criteria-decision-analysis-for-health-care-decision-making---emerging-good-practices
- Garner et al., when and how to update systematic reviews: https://doi.org/10.1136/bmj.i3507
- 3ie Evidence Gap Maps: https://3ieimpact.org/evidence-hub/evidence-gap-maps

Limits: no validated independent study or gap classifier; no automated clinical guideline, stakeholder preference, patient-priority or journal acceptance model; no automatic change to eligibility for outcome-specific hypotheses. No automated full-text extraction or proof of registration readiness. Local researcher-rating editor and JSON export are available, with source/rationale/counterevidence/uncertainty fields. They do not authenticate inputs or update cloud qualification. Cloud synchronization of manual ratings and completed-job continuation remain future work. The manual input interface in Python is a validation/calculation contract, not an independent adjudication service.

Local manual assessment supports candidate interval comparisons across four prespecified weighting scenarios and report/topic exports. Each unresolved domain gets a concrete proposed recovery action (not a claim of execution).

A bounded exact-comparison review search (up to two additional searches plus abstract enrichment) recovers direct review cues missed by the broad population/intervention sample. Failure or absence remains uncertainty. No extra AI requests.

## Production comparator audit (2026-11-26)
Job 8e9ea8e7-21c0-4b76-85a6-c9ab25c10820 exposed treatment-context false matches: PMIDs 40659682, 41870899 (drug trials in TAVR), 38599220 and 41671005 (shared/concomitant antiplatelet arms). Added conservative arm composition guards and clinically relevant SAVR/OVH synonyms; evidence cues remain unverified. Methods: Cochrane Handbook chapter 3 https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-03 and CONSORT 2025 https://doi.org/10.1136/bmj-2024-081124. Regression replay includes rotation 2 as well as rotation 0. This does not constitute a validated arm classifier.

## Dynamic exploration
MeSH and substance names from exact PMID EFetch, title corroboration in two distinct family cues, at most two additional focused cells per run. Broad specialty query spans current year and two preceding years; no assumption of completeness, no additional AI calls. Missing indexing is a limitation, especially recent articles. Sources: https://www.nlm.nih.gov/mesh/intro_trees.html ; https://pubmed.ncbi.nlm.nih.gov/help/ ; https://www.ncbi.nlm.nih.gov/books/NBK62478/ . The comparison-recovery budget is increased to three bounded searches; no change to seven-family shortlist threshold. Independent evidence confirmation remains manual.

Report aggregation now reuses conflict-aware bibliographic grouping; exact DOI/PMID identity is required for metadata transfer. Search-date source evidence stays atomic, and conflicting semantic judgments are unresolved. Counts are still report/family cues, not verified independent RCTs.

Initial live dynamic replay returned zero anchors in each 60-record sample. V1 recovery allows a single title-corroborated direct comparison cue to seed a focused search, not pass eligibility. Also reuse broader pre-existing cardiovascular vocabulary for observed direct-arm combinations and audit indexing/candidate attrition. Seven-family shortlist threshold unchanged. No scientific success inferred from fixtures.

## Scientific validation V2: structured registry arms
Trialstreamer (https://pmc.ncbi.nlm.nih.gov/articles/PMC7727361/) and EBM-NLP (https://pmc.ncbi.nlm.nih.gov/articles/PMC6174533/) distinguish entity extraction from relation validation; scispaCy is a biomedical NER toolkit, not an arm adjudicator. Use at most eight exact NCT lookups from retrieved RCT reports and two dynamic cells in total. Require registered randomized parallel two-arm design, distinct single intervention names and corroboration from the report. Withhold complex/shared treatment arms rather than invent a contrast. Registry alone cannot establish published eligibility. The broad source sample uses existing mixed ranking to reduce relevance-only bias. Sources: https://clinicaltrials.gov/policy/protocol-definitions ; https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04 . No new AI calls. Limitations: naming differences, nonparallel designs and complex interventions may be missed; registry hints are not validated PICO labels. Clinical validation still needed.
