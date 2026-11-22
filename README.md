# SciMed Review Scout Cloud

Discovery-only engine for high-value systematic review and meta-analysis topics.

## Scope

The active product does one job: discover, verify and rank review topics.

It does:

- generate candidate systematic review and meta-analysis questions,
- search for competing published reviews,
- search PROSPERO and OSF registrations,
- search scholarly sources for primary-study candidates,
- search the future evidence pipeline when relevant,
- evaluate semantic overlap and fatal redundancy,
- estimate topic feasibility and publication potential,
- require at least 4 unique primary-study candidates in the discovery search,
- return several FIRST-CHOICE review-topic options,
- export those options for independent ChatGPT comparison.

It does not:

- download or analyze PDFs,
- perform title/abstract screening,
- perform full-text eligibility screening,
- extract outcome data,
- build study families,
- assess risk of bias,
- reconstruct Kaplan-Meier curves,
- run meta-analysis or TSA,
- write the final systematic review.

The minimum of 4 refers to 4 unique primary-study candidates discovered in the search. It is a discovery-feasibility threshold, not a claim that 4 studies are finally eligible or synthesis-ready.

## Supported review questions

The Scout is design-agnostic and supports review ideas involving randomized trials, non-randomized interventions, cohort studies, case-control studies, cross-sectional studies, diagnostic-accuracy studies, prevalence/incidence studies, prognostic studies, prediction models, registry/database studies, qualitative studies, mixed-methods studies, economic studies, implementation studies, genetic/association studies, and custom designs.

Diagnostic accuracy is supported as a review-question type, but the Scout only discovers the topic and candidate evidence. It does not perform DTA extraction or pooling.

## App scope selectors

The app supports an open scope at both levels:

- Specialty = All specialties means candidate generation is not restricted to one medical specialty.
- Question type = All question types means candidate generation is not restricted to one review-question type.
- A specific specialty can be combined with All question types.
- All specialties can be combined with a specific question type, such as Diagnostic Accuracy or Effectiveness.
- All + All performs broad review-topic discovery across medicine.

The backend treats ALL as an open scope. It is never passed to the AI as a literal specialty or question type.

## Discovery workflow

1. Generate candidate review topics.
2. Rank candidates for verification priority.
3. Search published reviews and meta-analyses.
4. Search PROSPERO and OSF review registrations.
5. Search primary-study candidates across scholarly sources.
6. Search ongoing/future evidence when relevant.
7. Deduplicate primary-study candidates by DOI and normalized title.
8. Assess overlap with competing reviews and registrations.
9. Apply discovery-only qualification gates.
10. Keep only FIRST-CHOICE review topics.
11. Export several qualified options to ChatGPT for final comparison.

## Discovery qualification

A final option must satisfy all discovery gates and have no unresolved Type-A issue.

The gates cover:

- a defined eligible study-design framework,
- at least 4 unique primary-study candidates,
- conclusive search coverage in at least 2 scholarly literature sources,
- a plausible meaningful synthesis question,
- clinical-question novelty of at least 3/5,
- overall novelty of at least 3/5,
- no fatal recent essentially identical review,
- a coherent review-question framework,
- HIGH or STRONG MODERATE feasibility,
- no fatal methodological flaw,
- clinical importance of at least 4/5,
- publication potential of at least 4/5,
- new information gain of at least 4/5,
- Publication-Oriented Score of at least 75/100,
- Editorial Stress-Test grade A, B, or corrected C.

A source failure never becomes a negative search result. ACCESS_FAILED and PARTIAL remain blocking or cautionary states according to the discovery policy.

## Sources

The current source layer includes:

- PubMed,
- Europe PMC,
- OpenAlex,
- Crossref,
- Semantic Scholar,
- PROSPERO through the read-only PROSPERO-MCP adapter,
- OSF Registries,
- ClinicalTrials.gov when future evidence matters.

The novelty layer compares the candidate question with competing reviews and registrations across population, intervention/exposure/index test, comparator/reference standard, outcomes, design scope, clinical decision, era, and likely study set/search cutoff.

## AI provider

Candidate generation, semantic competitor assessment and topic scoring use a vendor-neutral OpenAI-compatible chat-completions endpoint.

Environment variables:

    SCIMED_AI_ENDPOINT=
    SCIMED_AI_MODEL=
    SCIMED_AI_API_KEY=

Optional:

    SEMANTIC_SCHOLAR_API_KEY=

AI does not control source status, deterministic study-candidate counts, fatal source failures, or the final inclusion of a topic into the qualified list.

## Persistent ledger

SQLite stores only discovery information used by the active product:

- projects,
- review-topic candidates,
- published-review records,
- primary-study candidate records,
- registrations,
- ongoing-study records,
- source-search logs,
- query history,
- decision history.

Earlier experimental analysis tables from old databases are ignored by version 0.2. New databases do not create outcome, study-family, or extraction tables.

## Cloud PWA and background jobs

The mobile-first PWA now uses Supabase as a persistent job queue and GitHub Actions as the Python background worker.

The browser workflow is:

1. Open the PWA.
2. The app creates or restores a private random device token stored only in that browser profile.
3. Choose Specialty and Question type, including All + All.
4. Press Start discovery.
5. A QUEUED job is stored in Supabase.
6. GitHub Actions polls the queue every five minutes and claims one job.
7. The Python engine generates candidates, runs discovery verification, novelty checks and gates.
8. Progress is written back to Supabase.
9. Closing Chrome does not stop the background job.
10. When complete, the PWA shows only qualified FIRST-CHOICE topics and provides Copy for ChatGPT and Download JSON.

The browser never receives the Supabase service-role key, worker token, or AI credentials. The production worker does not use the service-role key at all.

### One-time cloud setup

The production Supabase project and queue schema are already configured. Anonymous Auth is not required.

Set these GitHub repository Secrets:

    SCIMED_WORKER_TOKEN
    SCIMED_AI_API_KEY

The background worker defaults to:

    SCIMED_AI_ENDPOINT=https://openrouter.ai/api/v1/chat/completions
    SCIMED_AI_MODEL=openrouter/free

Optional secret:

    SEMANTIC_SCHOLAR_API_KEY

Then set GitHub Pages deployment source to GitHub Actions and run the `pages` workflow once. The public Supabase URL and anon key are already configured in the PWA. The `discovery-worker` workflow is both manually runnable and scheduled.

The worker installs the pinned read-only PROSPERO CLI and keeps PROSPERO failures fail-closed.

For detailed setup, see `supabase/README.md`.

## CLI

Initialize:

    scimed-scout init-db data/scout.sqlite3

Create a focused discovery project:

    scimed-scout create-project data/scout.sqlite3 RAD-DTA Radiology --question-type DIAGNOSTIC_ACCURACY

Create a broad All + All discovery project:

    scimed-scout create-project data/scout.sqlite3 MED-ALL ALL --question-type ALL

Generate topic candidates:

    scimed-scout generate-candidates data/scout.sqlite3 RAD-DTA --count 10 --question-type DIAGNOSTIC_ACCURACY --design "diagnostic accuracy studies"

Rank them:

    scimed-scout rank-candidates data/scout.sqlite3 RAD-DTA --top 10

Run the complete discovery workflow and seek 3 qualified options:

    scimed-scout discover-reviews data/scout.sqlite3 RAD-DTA --min-verify 3 --max-verify 10 --final-options 3

The command writes:

    data/RAD-DTA_review_topics.json

That JSON file is the handoff package for ChatGPT.

Recheck one candidate:

    scimed-scout verify-candidate data/scout.sqlite3 CANDIDATE_ID

Inspect candidates:

    scimed-scout list-candidates data/scout.sqlite3 RAD-DTA

## Final ChatGPT handoff

The engine does not choose the winner.

Only qualified FIRST-CHOICE review topics enter the final package. ChatGPT receives side-by-side information on novelty, source coverage, primary-study candidate count, competing reviews, registrations, scores, gates and unresolved issues, then ranks the included options and selects the strongest topic to take forward into a real systematic review.

## Local check

    python -m pip install -e '.[dev]'
    pytest -q
    scimed-scout health
