# SciMed SRMA Scout Cloud

Mobile-first, AI-assisted discovery and verification of publication-oriented RCT-only systematic review and meta-analysis topics.

## Design principles

- The application is a structured research system, not an autonomous truth source.
- AI helps discover, classify, compare, and interpret evidence.
- Deterministic code owns counts, locked thresholds, source states, and final gate logic.
- `ACCESS_FAILED` or `PARTIAL` never means `SEARCHED_NEGATIVE`.
- Trial publications are counted by independent randomized population, not paper count.
- Final first-choice candidates require all 15 locked gates and no unresolved Type-A issue.
- ChatGPT Plus is planned as the independent final-review layer after export.

## Current v0.1 scope

This bootstrap contains:

1. Core source-status model.
2. Checkpointable pipeline stages.
3. Deterministic implementation of the 15 locked RCT-only gates.
4. Tests protecting fail-closed registry logic and the seven-RCT thresholds.
5. A mobile-first PWA prototype.
6. GitHub Actions test workflow.

## Next milestones

- PubMed, Europe PMC, OpenAlex, Crossref and ClinicalTrials.gov adapters.
- PROSPERO and OSF novelty firewall.
- Trial-family resolver.
- Numerical-usability audit.
- Supabase project state and authentication.
- Pluggable free-model AI provider layer.
- Background discovery workflow and Final Review Package export.

## Local check

```bash
python -m pip install -e '.[dev]'
pytest -q
scimed-scout health
```

## Safety rule

A failed or incomplete source query must be stored as `ACCESS_FAILED` or `PARTIAL`. The system must never silently turn a source failure into zero competing records.
