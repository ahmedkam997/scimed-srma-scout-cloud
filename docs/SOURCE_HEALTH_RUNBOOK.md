# SciMed Research Scout: live source-availability runbook

This operational runbook documents public source connectivity and is separate from the scientific novelty decision. Research sources and analogous software consulted: OpenAlex official 2026 authentication/rate-limit docs; Semantic Scholar Academic Graph docs; the pinned read-only PROSPERO-MCP CLI v0.2.2; GitHub scheduled workflow documentation; Cochrane and PRISMA reporting principles.

## Verified root cause, 2026-11-24

- **OpenAlex** returned HTTP 429 in the Cardiology jobs. Current official documentation allows keyless basic API searches but recommends a free key for sustained use and requires a key for deeper cursor paging. The worker now permits **one anonymous probe per job** when no key is configured; subsequent search variants are flagged `PARTIAL`, never negative or complete. A 429 still stops all further requests in that job. `OPENALEX_API_KEY` is recommended for reliable search coverage, but missing it does not block PubMed, Europe PMC, Crossref, PROSPERO or OSF.
- **Semantic Scholar** returned HTTP 429 because repeated requests on the shared unauthenticated quota were exhausted. A live keyless worker makes no more than one exploratory query; subsequent query variants remain `PARTIAL`. With a personal key, the source is paced to 1 request per 1.1 seconds within the worker process. A 429 stops requests for the rest of that job.
- **PROSPERO** broad and fragmented registry queries produced partial pagination and unstable result totals. The PICO plan now prioritizes a clinically coherent condition phrase (e.g. `"left main"`, `"atrial fibrillation"`, `"coronary artery disease"`) alongside the intervention instead of scattering generic population words over unrelated searches. PROSPERO-MCP remains pinned read-only. Partial pagination remains `PARTIAL` and still blocks research registration clearance. The normal discovery plan issues at most three focused registry combinations per candidate, while saved targeted rechecks retain their original, separately documented strategy. This improves precision but is not an exhaustive registry search.
- **GitHub Actions schedule**: GitHub officially warns that scheduled workflow runs may be delayed or dropped. On-demand dispatch from the mobile PWA remains the preferred worker wake-up. A new daily source-health workflow is supplemental, not proof the schedule is guaranteed.
- **LLM generation**: two older failed jobs were caused by invalid/truncated generation provider responses. Later jobs completed. A completed generation is not a scientifically qualified review, and no artificial `QUALIFIED` result is introduced by these fixes.

## Keys and free-plan configuration

The repo's GitHub Actions -> Secrets and variables -> Actions -> New repository secret page accepts:

- `OPENALEX_API_KEY`: optional free OpenAlex key, created at [OpenAlex API settings](https://openalex.org/settings/api). Keyless first-page searches still work under public shared limits, but this key greatly improves reliability. No payment method is required to request the free key.
- `SEMANTIC_SCHOLAR_API_KEY`: personal key requested from [Semantic Scholar](https://www.semanticscholar.org/product/api). Acceptance is at the provider's discretion and the introductory quota is 1 RPS.

Never put these keys in `web/config.js`, a JSON export, a public commit, or the browser. If the keys are unavailable, the program continues using other independent bibliographic databases, flags missing sources, and does **not** declare a fully completed literature search.

## Running the live diagnostic without generating an idea

1. Open the [source-health workflow](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/workflows/source-health.yml) and choose **Run workflow**, or inspect the automatically run on merge of the health workflow.
2. Under the latest run, inspect **Check each scholarly source using one bounded PICO query**.
3. Download the `scimed-source-health` artifact containing `source-health.json`. It records per-source status, elapsed seconds, retrieved citations, reported total and sanitized error messages.
4. A successful GitHub test/deployment is not evidence that all external APIs worked. Read the source statuses.
5. Use the normal **Start discovery** button for a new actual experiment only after checking health. It queues a source-aware task and requests on-demand GitHub worker dispatch.

## 2026 verified provider limitations and comparable implementations

- [OpenAlex official authentication](https://help.openalex.org/api/authentication/) distinguishes free first-page anonymous calls from the larger personal-key usage budget. Do not label keyless searches universally unsupported.
- [Semantic Scholar official tutorial](https://www.semanticscholar.org/product/api/tutorial) confirms anonymous requests share capacity and personal API keys start at 1 request per second across endpoints; the runner prevents repeat calls immediately after 429.
- [GitHub official scheduling guide](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule) documents delayed or dropped scheduled events. [October 2026 GitHub community experiences](https://github.com/orgs/community/discussions/209885) corroborate this operational limitation; the mobile on-demand dispatch is the first line of defense.
- [PROSPERO-MCP v0.2.2](https://github.com/erichuang777777/PROSPERO-MCP) remains a source-built, read-only registry search integration; never treat fragmented page retrieval as full coverage.
- The [ASReview](https://github.com/asreview/asreview), [MetaDTA](https://github.com/CRSU-Apps/MetaDTA), and Cochrane DTA guidance are useful existing tools for screening and later syntheses. They do not prove an unverified topic has eligible independent studies.

## Safe operational acceptance test

1. Confirm the test workflow, live source-health workflow and latest GitHub Pages deployment all completed successfully. **These are three separate checks.**
2. Confirm whether the source-health artifact reports `openalex_personal_key_configured` and `semantic_scholar_personal_key_configured` without exposing actual tokens. Verify the provider responses and whether 429 remained.
3. Run exactly one new Discovery on a clinical PICO different from the recently checked ones. Check that source-level query status and skipped variants are visible and do not convert technical partial coverage into `QUALIFIED`.
4. Review candidate-specific PROSPERO/OSF overlap and primary-study family reports. A `COMPLETED` cloud job is operational success, NOT proof a publication-ready SRMA has been found.
5. If GitHub missed a scheduled run, use the existing on-demand dispatch button. Do not repeatedly queue jobs or re-run costly shared-quota searches to 'force' a positive result.

## Decision policy

- `SEARCHED_POSITIVE` or `SEARCHED_NEGATIVE` means a **bounded query** completed. It is not a full systematic literature search, and a zero result from one query is not proof of novelty.
- `PARTIAL`, `ACCESS_FAILED`, `NOT_SEARCHED`: clearly disclose missing query coverage and preserve original scientific blockers.
- The current clinical review discovery threshold of four bibliographic study candidates is an internal prioritization rule, not proof of four independent eligible trials.
- A **GO** decision still requires human verification of clinical PICO, published and registered review overlap, last actual search dates, full text, distinct study families and extractable outcomes.
- The `Final Evidence Audit` is an analyst workbench with documented source links, not an autonomous full text review.

## Source references

- [OpenAlex Authentication and API keys](https://help.openalex.org/api/authentication/)
- [OpenAlex deprecations](https://help.openalex.org/api/deprecations/)
- [Semantic Scholar API](https://www.semanticscholar.org/product/api)
- [PROSPERO-MCP read-only CLI](https://github.com/erichuang777777/PROSPERO-MCP)
- [GitHub Actions scheduling limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
