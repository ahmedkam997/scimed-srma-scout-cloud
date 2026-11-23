# SciMed Review Scout: discovery improvements and evidence basis

Updated 2026-11-23. Operational mode: **free public APIs and free-route LLM only**.

## Confirmed production failure

The Cardiology discovery job stopped during candidate-generation JSON parsing,
raising `json.decoder.JSONDecodeError: Unterminated string` (line 68).
This was an incomplete model response, not evidence that the research questions
were invalid.

## Implemented in source control

1. **Compact generation batches.** Generate up to four proposals per response,
   limit each proposal's verbosity, deduplicate titles, and make only a small
   number of short follow-up calls when malformed output reduces yield.
2. **Truncation-tolerant parsing.** Strict JSON remains the default. When a model
   produces incomplete JSON, accept only fully parsed complete candidate
   objects from a `candidates` array. Never fabricate missing strings,
   delimiters, PICO elements, or source evidence.
3. **PICO query variants.** Search using a bounded mix of population + intervention,
   intervention + comparator, intervention + outcome, concise title and
   candidate keywords. Use distinct query variants for reviews, primary studies,
   registries and prospective trials. Retain source statuses and raw query logs.
4. **Scientific integrity gate.** Any failed, incomplete, rate-limited or
   unverified source stays PARTIAL/ACCESS_FAILED. Never turn "not searched"
   into "no relevant review exists." Even highly scored ideas cannot
   bypass source coverage and other qualification gates.
5. **Provisional topic export.** The top five source-blocked review topics
   remain visible in a separate, clearly unqualified list, with PICO,
   unresolved checks, source statuses, and discovered study-candidate counts.
6. **Crash-resistant hypothesis checkpoint.** Persist generated titles and PICO
   questions before source validation, allowing an incomplete or failed
   verification run to retain unverified ideas rather than lose them all.
7. **Zero-cost scope.** No paid API model, hosted vector database, or subscription
   has been added by this change.

### Interpret outputs correctly

A "primary-study candidate" means a bibliographic match, not an eligible study.
Provisional choices are **not** qualified, original, synthesis-ready or cleared
of overlap. Scientific scores and source coverage are independent.

## Compared with published and open-source projects

| Reference | Relevant method | Status in SciMed Scout |
|---|---|---|
| Cochrane Handbook, ch. 2 and ch. 4 | Define focused questions, search for previous syntheses/registrations, use reproducible strategies | PICO variants and conservative coverage gates implemented; librarian peer-review of searches remains future work |
| litsearchr (Grames et al.) | Text mining and keyword co-occurrence for search-term selection | Search term variants implemented; co-occurrence network analysis **not yet implemented** |
| citationchaser (Haddaway et al.) | Forward/backward citation tracking from seed papers | Future optional enhancement; not currently implemented |
| OpenAlex | Connected bibliographic corpus, metadata, references and semantic retrieval | Existing keyword connector retained; structured citation/semantic graph expansion **not yet implemented** and may have API cost/rate restrictions |
| ASReview LAB v2 | Active-learning ranking for screening known bibliographic records | Not integrated into candidate topic generation; appropriate for a separate screening workflow |
| Garner et al. (BMJ 2016) | Reviews need updating when clinically important new evidence emerges | Existing tentative evidence gain proxy needs publication/search-date verification before any update claim |
| Epistemonikos | Specialized database of existing health syntheses | Manual cross-check recommended; no presumed free API access |

## Scientific upgrades for next iteration

1. Benchmark sensitivity of searching against 30 to 50 known-topic reference sets
   and report the proportion of known reviews and registrations retrieved.
2. Add optional forward/backward citation chasing, but preserve provenance
   and respect OpenAlex/Semantic Scholar provider rate limits and free quotas.
3. Add a manually verified protocol-search record workflow for PROSPERO and OSF.
   A registration API's empty/partial output must never imply a negative search.
4. Compare novelty and priority scores with two independent expert reviewers,
   inspect inter-rater reliability, and test weight sensitivity.
5. Capture included-study matrices before using Corrected Covered Area; do
   not estimate review overlap from simple hit counts.
6. Provide explicit "insufficient evidence" rather than fabricating numeric
   information-gain estimates from undated bibliographic records.

## Evidence and project references

- Cochrane, review-question scope:
  https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-02
- Cochrane, searching and selecting studies:
  https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04
- Garner et al., BMJ 2016, when and how to update:
  https://www.bmj.com/content/354/bmj.i3507
- litsearchr source:
  https://github.com/elizagrames/litsearchr
- litsearchr documentation:
  https://elizagrames.github.io/litsearchr/
- citationchaser source:
  https://github.com/nealhaddaway/citationchaser
- citationchaser methods publication:
  https://pubmed.ncbi.nlm.nih.gov/35472127/
- ASReview source:
  https://github.com/asreview/asreview
- ASReview LAB v2 published methods:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC12416088/
- OpenAlex API:
  https://help.openalex.org/api/
- OpenAlex semantic retrieval:
  https://help.openalex.org/api/semantic-search/
- OpenRouter structured outputs (provider dependent):
  https://github.com/OpenRouterTeam/docs/blob/main/guides/features/structured-outputs.mdx

Methods adapted conceptually, **not** copied wholesale. All new scoring
thresholds remain locally proposed and require prospective validation.
