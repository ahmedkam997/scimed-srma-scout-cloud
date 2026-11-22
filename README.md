# SciMed SRMA Scout Cloud

Mobile-first, AI-assisted discovery and verification of publication-oriented systematic review and meta-analysis topics across study designs.

## Design principles

- The application is a structured research system, not an autonomous truth source.
- AI helps discover, classify, compare, and interpret evidence.
- Deterministic code owns counts, locked thresholds, source states, study-family resolution, synthesis-usability status, and final gate logic.
- `ACCESS_FAILED` or `PARTIAL` never means `SEARCHED_NEGATIVE`.
- Multiple publications from the same underlying population are counted as one study family.
- Weak study-family similarities never trigger automatic merging.
- The default locked minimum is 4 verified independent eligible studies and 4 verified synthesis-usable study families.
- Every option in the final review list must be fully FIRST-CHOICE eligible. Pending, provisional, partially verified, or gate-failing candidates are never allowed into the final list.
- The engine does not choose the final winner. It exports several options for independent ChatGPT comparison.

## Study-design scope

The engine is design-agnostic. It supports broad design families and preserves the original design label from each paper. An `OTHER` / custom design route prevents unlisted or newer designs from being rejected merely because they are absent from a hard-coded taxonomy.

Supported families include:

- Randomized experimental designs, including parallel, cluster, crossover, factorial, stepped-wedge, platform and related randomized designs.
- Non-randomized and quasi-experimental intervention studies.
- Prospective, retrospective and ambidirectional cohort studies.
- Case-control, nested case-control and case-cohort studies.
- Cross-sectional studies.
- Prevalence and incidence studies.
- Registry and database studies.
- Ecological studies.
- Prognostic factor and prognostic outcome studies.
- Prediction-model development and validation studies.
- Genetic and association studies.
- Case series and case reports where appropriate to the review question.
- Economic and implementation studies.
- Qualitative and mixed-methods studies.
- Custom / other designs.

### Diagnostic accuracy

Diagnostic accuracy has a dedicated design and synthesis pathway. The design profile can represent combinations of:

- single-gate or two-gate/case-control sampling,
- cohort-based or cross-sectional sampling,
- prospective or retrospective data collection,
- paired or unpaired comparative accuracy,
- randomized test comparison,
- multiple index tests,
- multiple thresholds,
- partial or differential verification,
- custom diagnostic designs.

DTA synthesis usability supports complete TP/FP/FN/TN 2x2 data and verified reconstruction from sensitivity, specificity and diseased/non-diseased denominators. QUADAS-3 is the default suggested appraisal tool for DTA studies.

## Synthesis-data scope

The synthesis-usability engine supports:

- binary effects,
- continuous outcomes,
- time-to-event outcomes,
- ordinal outcomes,
- diagnostic accuracy 2x2 data,
- proportions and prevalence,
- incidence rates and person-time,
- correlations,
- generic adjusted or unadjusted effect estimates with SE/CI,
- prediction-model performance estimates,
- qualitative findings with a defined synthesis method,
- graph-derived, median/IQR and Kaplan-Meier reconstruction pathways.

Potentially recoverable data are kept separate from VERIFIED_USABLE data until the required extraction or reconstruction has been completed.

## Implemented

1. Core source-status model and fail-closed search logic.
2. Checkpointable pipeline stages.
3. Deterministic 15-gate publication decision system.
4. Four-study minimum for verified independent eligible studies and verified synthesis-usable studies.
5. PubMed, Europe PMC, OpenAlex, Crossref, Semantic Scholar and ClinicalTrials.gov source adapters.
6. PROSPERO-MCP read-only adapter with fail-closed behavior.
7. OSF Registries metadata adapter with conservative partial-coverage handling.
8. Registry query generator, novelty firewall, source-coverage audit and competitor matrix.
9. Design-agnostic study taxonomy with open custom design labels.
10. Study-family resolver for duplicate/overlapping publications and populations.
11. Dedicated diagnostic-accuracy design and data pathway.
12. Synthesis-usability audit across multiple outcome/effect structures.
13. Deterministic evidence counts for independent, usable and principal-outcome study families.
14. Threshold-aware family uncertainty, where unresolved links become Type-A only when they can change the four-study decision.
15. Final gate evaluation that overwrites AI-supplied study counts with audited ledger counts.
16. Mobile-first PWA prototype and GitHub Actions test workflow.
17. Persistent SQLite evidence ledger for projects, candidates, study families, studies, outcomes, search logs, query library and decision history.
18. Persistent external-evidence records for published reviews, registrations, protocols and ongoing studies.
19. Pluggable AI provider interface using vendor-neutral OpenAI-compatible endpoints.
20. Guarded AI candidate-generation schema that blocks AI from setting study counts, source status, gate results, publication score or final decisions.
21. Stable candidate IDs with persistent REJECTED / SHORTLISTED / PROVISIONAL / QUALIFIED status, including default protection against rediscovering rejected ideas.
22. CLI commands for database initialization, project creation, candidate generation, status changes and project/candidate listing.
23. Multi-option sequential verification with a configurable final shortlist, default 3 options.
24. Automatic SCIMED_FINAL_CHATGPT_REVIEW JSON package containing side-by-side evidence, coverage, gates, unresolved issues and option status.
25. Semantic competitor assessment for published reviews and registrations across population, intervention/exposure/index test, comparator/reference, outcomes, design scope, clinical decision, era and study-set/search-cutoff overlap.
26. Fail-closed competitor logic: low-confidence or unsupported semantic evidence remains UNRESOLVED, and essentially identical adequate recent reviews without meaningful new information trigger fatal redundancy.
27. Automated primary-study eligibility/design extraction from available title/abstract/metadata with field-level provenance and confidence.
28. Exact-source provenance validation: unsupported AI evidence quotes force fields or overlap assessments back to UNRESOLVED.
29. AUTO_EXTRACTED studies are persisted for verification but never count toward the four-study threshold until eligibility, design, independence and synthesis usability are verified.
30. Enriched literature metadata: Europe PMC core results, Semantic Scholar abstracts, reconstructed OpenAlex abstracts, and PubMed summary metadata.
31. Deterministic Verification Bridge that promotes only source-supported, high-confidence AUTO_EXTRACTED records to VERIFIED_ELIGIBLE or VERIFIED_INELIGIBLE.
32. Design classifier covering diagnostic accuracy, randomized, nonrandomized, quasi-experimental, cohort, case-control, cross-sectional, prediction, prognosis, prevalence/incidence, ecological, registry/database, qualitative, mixed-methods, economic, implementation, genetic and other designs.
33. Automated study-family construction with strong-identifier merging by DOI, registry ID or explicit manual same-family verification.
34. Stable study-family IDs across reruns and deterministic family-ledger rebuilds after verification changes.
35. Conservative independent-study counting across unresolved possible publication/population overlaps. A possible link can reduce the count used by the four-study gate even when raw family count is higher.
36. Threshold-aware family uncertainty: unresolved overlap blocks the candidate when it could reduce the conservative independent count below four.
37. Auditable manual overrides for study eligibility/design and SAME_FAMILY versus DISTINCT_FAMILIES decisions, stored in decision history.
38. Automated synthesis-data extraction from verified eligible studies with field-level exact-quote provenance and independent numeric validation.
39. Family-level synthesis-usability verification, so multiple publications from one population contribute at most one usable study family.
40. Automatic extraction pathways for binary events/denominators, continuous n/mean/SD, time-to-event HR/CI and related structures, ordinal effects, DTA 2x2 data, proportions, rates/person-time, correlations, generic effect estimates and prediction-model performance.
41. Diagnostic-accuracy reconstruction from sensitivity, specificity, diseased N and non-diseased N only when the reconstructed 2x2 counts are numerically exact within the deterministic tolerance.
42. Numeric hallucination protection: a populated number is discarded unless the supporting source quote contains the same numeric value or a valid corresponding percentage, and low-confidence fields are not used.
43. Abstract-level missing quantitative data are treated as POTENTIALLY_USABLE / needs-full-text rather than definitive non-usability.
44. Definitive NOT_USABLE status requires full-text evidence when no valid synthesis pathway exists.
45. Conservative usable-family counting across unresolved family links. Raw usable count of four does not pass if possible population overlap reduces the conservative count below four.
46. Decision-changing usable-family uncertainty is a Type-A blocker.
47. Repeated literature searches preserve previously attached full text, supplements and completed evidence assessments instead of overwriting enriched records.
48. Official Europe PMC open-access full-text acquisition through PMCID and the fullTextXML endpoint, with separate ACQUIRED, NOT_AVAILABLE, NO_PMCID, ACCESS_FAILED and INVALID_CONTENT states.
49. JATS XML parsing that preserves Methods, Results, tables, figure text and section provenance before chunking.
50. Deterministic full-text chunk selection tailored separately to eligibility review and synthesis-data extraction.
51. Eligibility extraction automatically upgrades from abstract evidence to selected full-text chunks when open full text is acquired.
52. Synthesis extraction automatically uses high-value Results/outcome chunks instead of truncating an entire long article.
53. Deep verification performs an eligibility full-text pass for uncertain studies, re-runs extraction when new evidence arrives, then performs a synthesis full-text pass for VERIFIED_ELIGIBLE studies.
54. Manual full-text attachment supports plain text and JATS XML for records unavailable through the open-access route.
55. Full-text changes invalidate cached eligibility extraction automatically, while repeated search still preserves enriched evidence.

## Appraisal routing

The design profile suggests a validated tool where a clear default exists:

- DTA: QUADAS-3.
- Prediction models: PROBAST+AI.
- Randomized intervention studies: RoB 2.
- Non-randomized intervention studies: ROBINS-I or another design-appropriate validated tool.
- Other designs: design-appropriate validated risk-of-bias or critical-appraisal tool selected for the actual review question and design.

## AI provider configuration

The scientific workflow does not depend on one AI vendor. Candidate generation uses a generic OpenAI-compatible chat-completions interface configured only through environment variables:

- SCIMED_AI_ENDPOINT
- SCIMED_AI_MODEL
- SCIMED_AI_API_KEY

The repository includes .env.example and ignores real .env files. API credentials are never stored in the evidence ledger.

The AI layer is limited to candidate generation and descriptive proposal fields. Deterministic code and source audits retain authority over evidence counts, study-family decisions, source status, novelty clearance and locked-gate qualification. ChatGPT performs the final comparison among exported options.

## Persistent ledger

SQLite is the default zero-cost persistence layer. The ledger stores projects, candidate status, study families, studies, outcomes, source searches, query history, published reviews, registrations, protocols, ongoing studies and append-only decision history. The database survives process restarts and can later be synchronized or replaced by a cloud adapter without changing scientific logic.

## CLI workflow

Initialize a local database:

    scimed-scout init-db data/scout.sqlite3

Create a project:

    scimed-scout create-project data/scout.sqlite3 RAD-DTA Radiology --question-type DIAGNOSTIC_ACCURACY

After configuring SCIMED_AI_ENDPOINT and SCIMED_AI_MODEL, generate candidates:

    scimed-scout generate-candidates data/scout.sqlite3 RAD-DTA --count 10 --question-type DIAGNOSTIC_ACCURACY --design "diagnostic accuracy studies"

Inspect candidates:

    scimed-scout list-candidates data/scout.sqlite3 RAD-DTA

Rank candidates and shortlist the strongest three for verification priority:

    scimed-scout rank-candidates data/scout.sqlite3 RAD-DTA --top 3

Run sequential deep verification and seek 3 fully qualified final review options, checking up to 10 candidates if needed:

    scimed-scout deep-verify data/scout.sqlite3 RAD-DTA --min-verify 3 --max-verify 10 --final-options 3

This command also writes:

    data/RAD-DTA_chatgpt_review.json

Upload that JSON file to ChatGPT for the final comparison and selection.

Analyze the discovered competitors and primary studies again after source updates:

    scimed-scout analyze-evidence data/scout.sqlite3 CANDIDATE_ID --force

Promote source-supported extracted studies and rebuild study families:

    scimed-scout verify-studies data/scout.sqlite3 CANDIDATE_ID

When a study still needs human verification:

    scimed-scout manual-verify-study data/scout.sqlite3 CANDIDATE_ID STUDY_ID ELIGIBLE --design "prospective diagnostic accuracy study" --reason "verified against full text"

Or mark a study ineligible:

    scimed-scout manual-verify-study data/scout.sqlite3 CANDIDATE_ID STUDY_ID INELIGIBLE --reason "population outside protocol"

Resolve an ambiguous publication/population link:

    scimed-scout resolve-family-link data/scout.sqlite3 CANDIDATE_ID STUDY_A STUDY_B DISTINCT_FAMILIES --reason "different sites and recruitment periods"

Use SAME_FAMILY instead when the two publications come from the same underlying population.

Extract and verify synthesis usability for a candidate:

    scimed-scout verify-synthesis data/scout.sqlite3 CANDIDATE_ID

Force re-extraction after updating source text or full text:

    scimed-scout verify-synthesis data/scout.sqlite3 CANDIDATE_ID --force

Acquire official open-access full text for records that need eligibility clarification:

    scimed-scout acquire-full-text data/scout.sqlite3 CANDIDATE_ID --purpose ELIGIBILITY

Acquire full text for verified eligible studies before synthesis-usability verification:

    scimed-scout acquire-full-text data/scout.sqlite3 CANDIDATE_ID --purpose SYNTHESIS

Attempt acquisition for all discovered primary-study records:

    scimed-scout acquire-full-text data/scout.sqlite3 CANDIDATE_ID --purpose ALL

Attach a locally supplied UTF-8 text or JATS XML file when automated open-access retrieval is unavailable:

    scimed-scout attach-full-text data/scout.sqlite3 CANDIDATE_ID STUDY_ID article.xml --source-label USER_JATS

Recheck one candidate after overlap, study-family or synthesis verification:

    scimed-scout verify-candidate data/scout.sqlite3 CANDIDATE_ID

Deep verification writes every source query, source status, discovered review/registration/study record, checkpoint and decision back to the SQLite ledger. Raw search hits remain DISCOVERED_UNVERIFIED. AUTO_EXTRACTED records also do not count until the verification bridge promotes them. The independent-study gate uses the conservative family count after duplicate merging and possible-overlap analysis. The synthesis gate separately requires at least four conservative VERIFIED_USABLE study families. Missing quantitative data in title/abstract evidence triggers a full-text requirement rather than automatic rejection. If full text has been reviewed and no valid synthesis pathway exists, the family can be marked definitively NOT_USABLE. If only one or two candidates meet the full standard, the final package contains only those qualified candidates and reports the shortfall. No weaker candidate is added to fill the requested number.

## Next milestones

- PDF full-text ingestion for legally supplied local PDFs, including page-aware provenance and table extraction.
- Manual and assisted reconstruction workflows for graph-only data, Kaplan-Meier curves and justified median/IQR conversion.
- Outcome harmonization across study families, including synonym mapping, follow-up windows and clinically defensible pooling groups.
- Specialty and review-question configuration modules.
- Background GitHub Actions research jobs with resumable checkpoints.
- Optional Supabase state/authentication adapter if cloud multi-device synchronization is needed.

## Local check

```bash
python -m pip install -e '.[dev]'
pytest -q
scimed-scout health
```

## Safety rule

A failed or incomplete source query must be stored as `ACCESS_FAILED` or `PARTIAL`. The system must never silently turn a source failure into zero competing records. Study counts and synthesis feasibility must come from audited study-family and outcome ledgers rather than free-form AI claims.
