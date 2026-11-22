# SciMed SRMA Scout Cloud

Mobile-first, AI-assisted discovery and verification of publication-oriented RCT-only systematic review and meta-analysis topics.

## Design principles

- The application is a structured research system, not an autonomous truth source.
- AI helps discover, classify, compare, and interpret evidence.
- Deterministic code owns counts, locked thresholds, source states, trial-family resolution, quantitative-usability status, and final gate logic.
- `ACCESS_FAILED` or `PARTIAL` never means `SEARCHED_NEGATIVE`.
- Trial publications are counted by independent randomized population, not paper count.
- Weak trial-family similarities never trigger automatic merging.
- Final first-choice candidates require all 15 locked gates and no unresolved decision-changing Type-A issue.
- ChatGPT Plus is planned as the independent final-review layer after export.

## Implemented

1. Core source-status model and fail-closed search logic.
2. Checkpointable pipeline stages.
3. Deterministic implementation of the 15 locked RCT-only gates.
4. PubMed, Europe PMC, OpenAlex, Crossref, Semantic Scholar and ClinicalTrials.gov source adapters.
5. PROSPERO-MCP read-only adapter with fail-closed behavior.
6. OSF Registries metadata adapter with conservative partial-coverage handling.
7. Registry query generator, novelty firewall, source-coverage audit and competitor matrix.
8. Trial-family resolver using verified registration IDs, manual family IDs and duplicate DOI evidence.
9. Conservative POSSIBLE_SAME_FAMILY flagging for weaker bibliographic similarity.
10. Numerical-usability audit for binary, continuous, time-to-event and ordinal outcomes.
11. Verified, potential and unusable quantitative-data pathways, including median/IQR, graphs and Kaplan-Meier reconstruction states.
12. Deterministic evidence counts for independent RCT families, usable RCT families and principal-outcome RCTs.
13. Threshold-aware trial-family uncertainty, where unresolved links become Type-A only when they can change the locked decision.
14. Final gate evaluation that overwrites AI-supplied RCT counts with audited ledger counts.
15. Mobile-first PWA prototype and GitHub Actions test workflow.

## Next milestones

- Persistent candidate, trial-family, outcome and search ledgers.
- Pluggable free-model AI provider layer.
- Candidate discovery and ranking orchestration.
- Specialty configuration modules.
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

A failed or incomplete source query must be stored as `ACCESS_FAILED` or `PARTIAL`. The system must never silently turn a source failure into zero competing records. Quantitative feasibility and RCT counts must come from audited ledgers rather than free-form AI claims.
