# SciMed topic memory and temporary recheck policy

Operational scope: **same browser/device token**, across completed SciMed
Review Scout jobs, including different dates and specialties. No paid service,
embedding subscription or new database table is required.

## Purpose

Prevent duplicated searching and repeated OpenRouter inference on the same
recently checked review question, without creating a permanent blacklist.
Reviews can become worthwhile when new evidence, practices or methods emerge.

## Current behavior

1. The researcher chooses the retrospective exclusion window in the web app:
   7, 14, 30 (default), 60, or 90 days; 0 means **recheck now**. The API accepts
   a validated range 0–180 days.
2. Before generating proposals, the cloud worker looks up **completed** jobs
   using the same device token hash. It does not retrieve another user's jobs.
3. Each completed job stores a structured history of its *actually verified*
   questions: specialty, question type, population, intervention/test,
   comparator, outcomes, study designs, status, and last check date.
   Older jobs without structured PICO are matched only by exactly equal
   normalized topic title. Failed or cancelled jobs do not suppress ideas.
4. Recently checked titles are supplied to the AI as exclusion context.
   A deterministic clinical PICO filter provides a second check independent
   of AI compliance: proposals matching the same specialty, question type,
   population, intervention, comparator and outcome are skipped **before**
   costly literature source searches.
5. When the previous question remained **PROVISIONAL_BACKUP** or
   **DEEP_VERIFYING** due to incomplete source coverage, the topic is eligible
   again after at most 7 days (or the chosen shorter interval).
   Completed reviews and rejected topics use the chosen period (default 30 days).
6. After expiry, an identical PICO becomes eligible for a fresh assessment.
   The check records the new date and qualification status. Setting 0 overrides
   the memory for a deliberate immediate recheck.
7. The results page shows the number of recently skipped questions, matched
   previous topics and the earliest revisit dates.

## Scientific boundaries

- Similarity heuristics are conservative to avoid excluding meaningful clinical
  changes. They do **not** guarantee discovery of all duplicates or all
  synonymous PICO questions. Changed comparator, outcome, study population
  or question type should remain eligible.
- The 7-day/30-day defaults are **local operational choices**, not validated
  evidence-based update intervals or Cochrane thresholds.
- Expiry permits a fresh search but does **not** establish that new evidence
  actually exists, or that novelty/information gain improved.
- A future upgrade should implement **lightweight evidence surveillance**
  (new PubMed/OpenAlex/ClinicalTrials.gov publication identifiers since the
  last check, newly registered relevant protocols, and changed guidelines)
  so relevant topics are rechecked early when meaningful new evidence appears.
  This is not currently implemented.
- The device token is stored in local browser storage. Different browsers
  or cleared storage do not share this history.
- At present the worker checks up to 80 recently completed jobs per user.
  For very high-volume multi-team use, introduce an indexed topic-history
  table and validated citation-based duplicate linkage.

## Evidence base

- Cochrane Handbook, Chapter IV, updating a review:
  https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-iv
- Garner et al., when and how to update systematic reviews, BMJ 2016:
  https://www.bmj.com/content/354/bmj.i3507

Both references argue for reassessment in the light of clinically meaningful
new evidence, rather than assuming an immutable negative result.
