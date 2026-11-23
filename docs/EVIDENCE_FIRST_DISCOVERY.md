# Evidence-first literature-gap discovery

## Purpose

SciMed Review Scout must generate useful systematic-review hypotheses without
mistaking bibliographic keyword hits for eligible, independent studies or
mistaking registered primary research for a review protocol.

The architecture follows an evidence-map approach: locate recent original
study records, find published review evidence with explicitly documented
uncertainties, and identify where intervention/condition/outcome combinations
seem under-synthesized. It does NOT claim to construct a formally validated
systematic evidence gap map or a final review.

## Existing methodologies and reusable open services

1. 3ie's [evidence gap maps](https://www.3ieimpact.org/evidence-hub/evidence-gap-maps):
   concentrations of primary studies with few up-to-date syntheses are useful
   signals for research priority. A map is not proof a focused SRMA is feasible.
2. [Campbell evidence and gap map guidance](https://pmc.ncbi.nlm.nih.gov/articles/PMC8356343/):
   classify interventions and outcomes in a traceable evidence matrix and
   separately represent original evaluations and systematic reviews.
3. [JBI evidence synthesis manual](https://jbi-global-wiki.refined.site/space/MANUAL):
   an existing review may warrant updating only after evaluating new evidence,
   study populations, clinical importance, and the scope of the original work.
4. [Review-gap frameworks scoping review (2026)](https://pubmed.ncbi.nlm.nih.gov/42203174/):
   frame research needs in the context of evidence certainty and
   evidence-to-decision factors, not merely publication counts.
5. [Europe PMC REST API](https://europepmc.org/RestfulWebService):
   query review publication types and return original titles, dates, DOI/PMID,
   abstracts and links as source-backed gap cues.
6. [NCBI E-utilities API](https://eutilities.github.io/site/API_Key/usageandkey/):
   retrieve recent original-study citations while respecting the rate limit
   for requests without a key.
7. [Official PROSPERO search guide](https://www.crd.york.ac.uk/prospero/documents/Guide%20to%20searching%20v1.pdf):
   quote phrases and combine concepts with Boolean AND for focused queries.
8. [OSF Trove search API](https://share.osf.io/trove/docs):
   a registration may represent a trial, not a systematic review. Search
   metadata and classify registration types before assessing overlap.

## Discovery algorithm

1. Retrieve recent PubMed study citations and a limited set of Europe PMC
   published systematic-review abstract-gap cues, retaining original
   bibliographic metadata and text excerpts. Never invent missing details.
2. Give Gemini or another independently configured free model those cues,
   plus an explicit instruction to generate distinct PICOs with potentially
   feasible clinical comparisons. Gap signals are hypotheses, not conclusions.
3. Search recent PICO-specific primary-study records across supported
   databases, and track failed searches independently from negative results.
4. Classify each review-search citation as a synthesis lead, a clearly
   nonreview citation, or an unresolved bibliographic type. Retain
   nonreview/ambiguous citations in the SQLite OTHER audit bucket.
5. Distinguish OSF primary-study preregistrations from review-protocol
   registrations. Preserve uncertain registrations for independent assessment.
6. Build PROSPERO/OSF searches by combining quoted intervention anchors
   with specific population or outcome concepts. Store each query and
   source coverage status. Do not convert incomplete pagination to negative.
7. Deduplicate clinical titles across sources and rank unverified studies
   by title/abstract intervention, population, comparator and outcome cues.
   A matching abstract does not establish eligibility, design or unique
   participants.
8. Produce a separate provisional research-question shortlist with source
   links, registry dates, uncertainty, a screening queue, and an
   independent ChatGPT verification prompt.
9. Only label a FIRST-CHOICE topic qualified if all mandatory source and
   methodological gates pass. Do not lower this bar because one source is
   slow or unavailable.

## Common failures and what they mean

- "Generated 10; qualified 0" may mean mandatory PROSPERO/OSF coverage was
  incomplete. It does not mean ten novel ideas were invalid.
- An OpenAlex hit about an RCT is not a competing published review even if
  returned for a search containing "systematic review".
- OSF "Registrations" includes primary research plans. Only actual
  systematic-review protocols should be counted as competing review
  registrations.
- A 2018 PROSPERO protocol is not necessarily published, and a 2026
  database metadata update is not necessarily a recent literature search.
- One newer PMID does not prove a new, eligible, independent randomized
  population; companion reports and published search dates must be checked.
- Title/abstract PICO signals and database result counts never establish
  extractable outcome counts.

## Independent validation required before GO

Check published systematic reviews and protocols (including their actual
last search dates), extractable eligible primary studies, independent trial
families, relevant comparator arms, outcome reporting, RoB framework and
the value of an update. If sources failed, label UNRESOLVED and provide
the exact pending verification tasks.

Tests cover each source classifier, source-gap extraction, PROSPERO focused
search planning, chronological registration cues, PICO title/abstract
triage, provider failover, and the final qualification boundary.
