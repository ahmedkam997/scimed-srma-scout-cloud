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
- Final first-choice candidates require all 15 locked publication gates and no unresolved decision-changing Type-A issue.
- ChatGPT Plus is planned as the independent final-review layer after export.

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

## Appraisal routing

The design profile suggests a validated tool where a clear default exists:

- DTA: QUADAS-3.
- Prediction models: PROBAST+AI.
- Randomized intervention studies: RoB 2.
- Non-randomized intervention studies: ROBINS-I or another design-appropriate validated tool.
- Other designs: design-appropriate validated risk-of-bias or critical-appraisal tool selected for the actual review question and design.

## Next milestones

- Persistent candidate, study-family, outcome and search ledgers.
- Pluggable free-model AI provider layer.
- Candidate discovery and ranking orchestration.
- Specialty and review-question configuration modules.
- Background cloud execution.
- Final Review Package export for ChatGPT Plus.
- Optional Supabase state and authentication if needed.

## Local check

```bash
python -m pip install -e '.[dev]'
pytest -q
scimed-scout health
```

## Safety rule

A failed or incomplete source query must be stored as `ACCESS_FAILED` or `PARTIAL`. The system must never silently turn a source failure into zero competing records. Study counts and synthesis feasibility must come from audited study-family and outcome ledgers rather than free-form AI claims.
