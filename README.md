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

Recheck one candidate after overlap or study-family verification:

    scimed-scout verify-candidate data/scout.sqlite3 CANDIDATE_ID

Deep verification writes every source query, source status, discovered review/registration/study record, checkpoint and decision back to the SQLite ledger. Raw search hits remain DISCOVERED_UNVERIFIED and do not count toward the four-study threshold. If only one or two candidates meet the full standard, the final package contains only those qualified candidates and reports the shortfall. No weaker candidate is added to fill the requested number.

## Next milestones

- Verification bridge that reviews AUTO_EXTRACTED study records and promotes only supported records into verified study families.
- Automated study-family construction and duplicate-population resolution from verified study records.
- Automated synthesis-usability extraction from verified study evidence, including DTA 2x2 data and other design-specific quantitative structures.
- Specialty and review-question configuration modules.
- Automated connection between source searches, novelty firewall and the persistent ledger.
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
