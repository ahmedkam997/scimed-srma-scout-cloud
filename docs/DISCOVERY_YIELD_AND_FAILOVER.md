# Higher-yield review-topic discovery and independent free AI fallback

Implementation: 2026-11-23. Repository: SciMed Review Scout Cloud.

## Findings from real Cardiology discovery jobs

Two completed Cardiology discoveries generated 12 candidates each and verified
10 candidates each. Both yielded 0 fully-qualified topics. In the later run,
all 10 were PROVISIONAL_BACKUP. Some broad bibliographic searches returned
200+ *candidate records* per topic, which are NOT independently eligible studies.
Every examined topic had PROSPERO=ACCESS_FAILED and OSF Registries=PARTIAL.
Semantic-competitor comparisons also failed with truncated JSON, empty
reasoning-model answers, or HTTP 429 (account quota). These technical coverage
gaps must not be treated as proof of lack of novelty.

The next request failed at initial candidate generation after OpenRouter
returned no usable JSON across bounded retries. Tests of the underlying
Python logic succeeded; no live Groq fallback has been verified.

## Changes implemented

1. **Two independent AI providers** in the same workflow:
   - Primary: `openrouter/free` using `SCIMED_AI_API_KEY`
   - Optional fallback: Groq free-plan `openai/gpt-oss-20b` using `GROQ_API_KEY`
   - Fallback only on HTTP 429/402, transient 5xx/timeouts, empty output or
     malformed JSON. No parallel duplicate provider calls.
   - Do not route to a priced OpenRouter model. The fallback uses a **separate**
     account, so it does not share OpenRouter's account-level quota.
   - Backend does not expose Groq or OpenRouter API keys in the browser.
   - The backup runs **only after** the repository owner adds `GROQ_API_KEY`
     as a GitHub Actions repository secret. No key has been created here.

2. **Source-anchored topic suggestions**: use a small free PubMed query for
   recent clinical records in the selected specialty. Give the language model
   traceable paper titles and PubMed identifiers solely as cues for generating
   focused PICO proposals. This is NOT eligibility screening or proof of
   evidence gap/novelty.

3. **More diverse generation, less repetitive verification**:
   - Produce 20 candidate questions instead of 12 by default.
   - Deeply verify up to 6 focused candidates instead of 10, avoiding
     rate-limit exhaustion across 10 saturated questions.
   - Novelty verification compares up to 3 nearest relevant published reviews
     and 2 registrations using short, source-quoted, single-record prompts,
     rather than giant JSON arrays. Every unassessed record remains
     transparently marked as incomplete semantic coverage.
   - Search results are limited to 12 per query during preflight instead of
     20. These limits are operational and do not mean that all relevant studies
     have been searched.

4. **Always retain useful leads**. Alongside the qualified set, return up to
   six PROVISIONAL topics with clinical PICO, incomplete source checks,
   bibliographic candidate counts, and 5 published-review and primary-record
   examples for manual scrutiny. The interface now displays safe links to
   record evidence. No provisional topic is falsely marked QUALIFIED.

5. **Fail fast on account quotas**. Stop retries on repeated 429/402 rather
   than burning all the remaining requests. Record fallback usage and the
   actual responding provider in completed run summaries.

## Enabling independent Groq fallback

1. Create a GroqCloud account on the Free plan in a supported region. Do
   **not** enable a paid developer/production tier when zero spend is required.
2. Go to https://console.groq.com/keys and create a Groq API key.
3. Add it to the GitHub repository at:
   https://github.com/ahmedkam997/scimed-srma-scout-cloud/settings/secrets/actions
   Secret name: `GROQ_API_KEY`.
4. Do not place the secret in README, `web/config.js`, a screenshot or
   chat message. GitHub Actions injects the key into the cloud worker.
5. After the secret is saved, re-run a previously failed job or create a new
   discovery to test real fallback. No production Groq API call has been
   performed as part of repository edits.

The exact free quotas and availability vary by provider and region. The free
Groq project has limits and may itself reach 429. If both independent
providers are exhausted, the job should report a quota limitation, never
switch to paid inference without explicit user configuration.

## Outstanding limitations

- The ProSPERO CLI currently returns ACCESS_FAILED in the sampled jobs.
  OSF title-metadata queries return PARTIAL when no record is retrieved.
  Neither should be interpreted as a conclusive negative. Source integration
  needs a separate repair or a human-authenticated registry audit.
- Search results with 200+ candidate records are not eligible primary studies
  until title/abstract and full-text eligibility checking.
- A source-blocked lead is NOT a validated novel or publishable systematic
  review. The 15 eligibility gates are intentionally preserved for
  fully-qualified outputs. Partial leads are offered for research judgment.
- Limited semantic comparison is a *screening triage*, not exhaustive
  equivalence checking. All records omitted from AI assessment remain flagged.
- Improved prompts, recent titles and limited calls are engineering
  hypotheses for increased yield, not demonstrated recall gains until tested
  on reference topics and measured with expert review.

## External references

- OpenRouter free-tier limitations:
  https://openrouter.ai/pricing
- OpenRouter free model router:
  https://openrouter.ai/collections/free-models/
- Groq model IDs and rate limits:
  https://console.groq.com/docs/models
  https://console.groq.com/docs/rate-limits
- Groq Chat Completions API:
  https://console.groq.com/docs/api-reference
- Cochrane Handbook Ch. 4, searching:
  https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04
- Grames et al. litsearchr:
  https://github.com/elizagrames/litsearchr
- Haddaway et al. citationchaser:
  https://github.com/nealhaddaway/citationchaser
- Frameworks for identifying systematic-review research gaps, 2026:
  https://pubmed.ncbi.nlm.nih.gov/42203174/
