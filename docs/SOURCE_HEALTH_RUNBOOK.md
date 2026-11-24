# SciMed Research Scout: live source-availability runbook

This operational runbook documents public source connectivity and is separate from the scientific novelty decision. Research sources and analogous software consulted: OpenAlex official 2026 authentication/rate-limit docs; Semantic Scholar Academic Graph docs; the pinned read-only PROSPERO-MCP CLI v0.2.2; GitHub scheduled workflow documentation; Cochrane and PRISMA reporting principles.

## Verified root cause, 2026-11-24

- **OpenAlex** returned HTTP 429 in the Cardiology jobs. Its API requires free-key authentication for dependable full use in 2026. The worker now detects missing `OPENALEX_API_KEY` before any network request. The source is `ACCESS_FAILED` until configured, not a false negative. It remains optional for the two-source bibliographic connectivity requirement; PubMed, Europe PMC and Crossref remain available.
- **Semantic Scholar** returned HTTP 429 because repeated requests on the shared unauthenticated quota were exhausted. A live keyless worker makes no more than one exploratory query; subsequent query variants remain `PARTIAL`. With a personal key, the source is paced to 1 request per 1.1 seconds within the worker process. A 429 stops requests for the rest of that job.
- **OSF Registries**: the 24 November live health probe returned Trove zero and five records from the official OSF v2 title filter. The original code discarded those five citations, leaving an empty manual evidence queue. The revised source retains and labels the v2 citations, keeps the index discrepancy `PARTIAL`, and never claims exhaustive registration coverage. Compare [official OSF Trove API](https://share.osf.io/trove/docs) with [OSF APIv2](https://developer.osf.io/) for future revisions.
- **PROSPERO** broad and fragmented registry queries produced partial pagination and unstable result totals. The PICO plan now prioritizes a clinically coherent condition phrase (e.g. `"left main"`, `"atrial fibrillation"`, `"coronary artery disease"`) alongside the intervention instead of scattering generic population words over unrelated searches. PROSPERO-MCP remains pinned read-only. Partial pagination remains `PARTIAL` and still blocks research registration clearance.
- **GitHub Actions schedule**: GitHub officially warns that scheduled workflow runs may be delayed or dropped. On-demand dispatch from the mobile PWA remains the preferred worker wake-up. A new daily source-health workflow is supplemental, not proof the schedule is guaranteed.
- **LLM generation**: two older failed jobs were caused by invalid/truncated generation provider responses. Later jobs completed. A completed generation is not a scientifically qualified review, and no artificial `QUALIFIED` result is introduced by these fixes.

## Keys and free-plan configuration

The repo's GitHub Actions -> Secrets and variables -> Actions -> New repository secret page accepts:

- `OPENALEX_API_KEY`: free OpenAlex key, created at [OpenAlex API settings](https://openalex.org/settings/api). This is the correct current remedy for the previous 429, rather than relying on obsolete 2025 `mailto` advice.
- `SEMANTIC_SCHOLAR_API_KEY`: personal key requested from [Semantic Scholar](https://www.semanticscholar.org/product/api). Acceptance is at the provider's discretion and the introductory quota is 1 RPS.

Never put these keys in `web/config.js`, a JSON export, a public commit, or the browser. If the keys are unavailable, the program continues using other independent bibliographic databases, flags missing sources, and does **not** declare a fully completed literature search.

## Running the live diagnostic without generating an idea

1. Open the [source-health workflow](https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/workflows/source-health.yml) and choose **Run workflow**, or inspect the automatically run on merge of the health workflow.
2. Under the latest run, inspect **Check each scholarly source using one bounded PICO query**.
3. Download the `scimed-source-health` artifact containing `source-health.json`. It records per-source status, elapsed seconds, retrieved citations, reported total and sanitized error messages.
4. A successful GitHub test/deployment is not evidence that all external APIs worked. Read the source statuses.
5. Use the normal **Start discovery** button for a new actual experiment only after checking health. It queues a source-aware task and requests on-demand GitHub worker dispatch.

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
