# SciMed Research Scout: research-first development and evidence verification policy

Applies to every future feature, clinical PICO, discovery job, novelty audit, and scientific go/no-go decision.

## A. Research before modifying the program

1. Define the exact user goal, population, comparator, feasible data, resource limits and expected action.
2. Search current official documentation, peer-reviewed methodology, relevant domain studies and maintained existing projects before writing new algorithms. Use the original documentation and published software when suitable.
3. Record source name, link, source date/version, whether full text was accessible, and which claim or design decision it supports.
4. Compare adapting an existing solution with building new: evidence validity, maintainability, API limitations, full cost, reproducibility, errors, security and fit.
5. Explain tradeoffs and what remains uncertain. Do not treat a community report as verified technical or scientific truth.
6. Implement the smallest safe solution. Add regression tests that reproduce the observed failure and guard against misleading success indicators.
7. Validate first with deterministic fixtures, then live source data, then the deployed application. Distinguish successful deployment from proven scientific output quality.
8. Keep the original discovery job immutable and explain any unresolved source checks; never auto-qualify a question from bibliography alone.

## B. Methodological references to consult and adapt

- Cochrane Handbook, [Chapter 3: eligibility criteria](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-03), [Chapter 4: searching and selecting](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04), [Chapter IV: updating](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-iv), and [Chapter 24: NRSI](https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-24).
- [PRISMA 2020](https://pmc.ncbi.nlm.nih.gov/articles/PMC8008539/), including the distinction among records, reports and studies, source searches and study selection.
- [3ie Evidence Gap Maps](https://www.3ieimpact.org/evidence-hub/evidence-gap-maps): explicit population/intervention/outcome coverage and source links.
- [Methods for handling overlapping primary studies across systematic reviews](https://pmc.ncbi.nlm.nih.gov/articles/PMC8265144/).
- [ROBINS-I tool](https://methods.cochrane.org/bias/risk-bias-non-randomized-studies-interventions) for results of non-randomized intervention studies, used only after eligibility verification.
- Existing source-specific search tools and documentation (PubMed/NCBI, Europe PMC, OpenAlex, PROSPERO, OSF, Semantic Scholar), including current rate-limit and data-access rules.
- Comparable available products where relevant: EPPI-Reviewer evidence mapping, ASReview LAB screening, 3ie maps, OpenAlex-based literature discovery. Their capabilities are not automatically validated or interchangeable.

## C. Scientific source and status vocabulary

- `INDEXED_TITLE_ONLY`: title and identifier retrieved, full protocol/full text not independently read.
- `PUBLISHED_ABSTRACT_ONLY`: abstract available, methods/supplementary study list inaccessible.
- `FULL_TEXT_SCREENED`: full article inspected against eligibility criteria and an explicit dated decision recorded.
- `REPORT` versus `STUDY_FAMILY`: never increment independent study count for every published report. Overlapping databases or periods must be flagged until reconciled.
- `TECHNICAL_SEARCH_SUCCESS`: a query executed. Not a completed multi-database systematic search, clinical PICO overlap result, or publication-quality novelty clearance.
- `NOT_ESTIMABLE` or `UNRESOLVED`: missing evidence. Do not replace with numerical zero or a false statement that no studies exist.

## D. Registration recommendation rules

- `GO` requires source-based novelty, defensible clinical PICO, a reproducible comprehensive search, verified independent eligible populations, compatible outcome data and team confirmation. An automated tool cannot autonomously issue GO.
- `REFINE` suggests a narrower or clinically distinct PICO but does not claim feasibility until rechecked.
- `NO-GO NOW` is a conservative decision against immediate protocol registration because necessary evidence is unavailable or substantial competition exists; it is not proof that no studies exist.
- `UNRESOLVED` identifies any necessary sources or trial-family evaluations not completed.

Always keep the scientific assessment separate from automated job statuses (`QUEUED`, `RUNNING`, `COMPLETED`) and from the discovery `QUALIFIED` label.

## E. Evidence transfer and audit trail

- For each recommendation, preserve its source link, date, scope, limitations and next verification action.
- Keep competing published reviews distinct from registrations. Old registrations do not imply a completed published synthesis.
- Record last literature-search dates only when explicitly documented in a full text/protocol; months are not exact calendar days.
- Report article and conference duplicates using stable study-family keys. Do not claim independence because authors, years or titles differ.
- Retain reviewer notes and history; protect user-specific data with server authorization and device/account ownership checks.
- Use targeted source rechecks to repair access errors without regenerating questions. A targeted recheck does not retroactively clear original source coverage flags.
- Export a stand-alone source-linked brief, preserving unknown fields as null rather than invented numbers.

This SOP is a durable development rule for the SciMed project. Updates require a documented comparison to current evidence and regression tests.
